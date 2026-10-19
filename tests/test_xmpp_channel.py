# -*- coding: utf-8 -*-
"""M5-XMPP channel pins (no real XMPP server): config model, service-url
parsing (ws rejection), segment flushing, outbound path fence, command
routing, wake word gating, incoming image extraction.
"""
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# Must precede any py.get_setting import: keep paths out of the production dir.
os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_xmpp_test_")

# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest
from pydantic import ValidationError

from py.xmpp_bot_manager import XmppBotConfig
from py.xmpp_client import XmppClient


def make_client():
    c = XmppClient.__new__(XmppClient)  # skip __init__ (no behavior-engine register)
    c.XmppAgent = "super-model"
    c.memoryList = {}
    c.asyncToolsID = {}
    c.fileLinks = {}
    c.separators = ["。", "\n", "？", "！"]
    c.reasoningVisible = False
    c.quickRestart = True
    c.wakeWord = None
    c.bot_username = "sap_bot"
    c.bot_password = "x"
    c.domain = "localhost"
    c.service_url = "tcp://localhost:5222"
    c.xmpp = None
    c.sent = []

    async def fake_send(jid, text):
        c.sent.append((jid, text))
    c._send_text = fake_send
    return c


class FakeJid:
    def __init__(self, full):
        self.bare = full.split("/")[0]  # slixmpp JID.bare strips the resource


class FakeMsg(dict):
    def get_from(self):
        return FakeJid(self.get("_from"))


def msg(frm="kerobros@localhost/res", body="", oob=None, mtype="chat"):
    m = FakeMsg({"type": mtype, "body": body, "_from": frm})
    if oob is not None:
        m["oob"] = oob
    return m


class TestConfigModel:
    def test_required_fields(self):
        with pytest.raises(ValidationError):
            XmppBotConfig(XmppAgent="m", bot_username="bot")  # password missing
        cfg = XmppBotConfig(XmppAgent="m", bot_username="bot",
                            bot_password="pw", domain="xmpp.local")
        assert cfg.service_url == "tcp://localhost:5222"
        assert cfg.memoryLimit == 10

    def test_secret_fields_encrypted_by_name_rule(self):
        # bot_password ends in "password" -> DPAPI rule applies on save
        from py.secret_box import encrypt_settings
        enc = encrypt_settings({"xmppBotConfig": {"bot_password": "s3cr3t"}})
        assert str(enc["xmppBotConfig"]["bot_password"]).startswith("dpapi:")


class TestServiceUrl:
    def test_tcp(self):
        assert XmppClient._parse_service("tcp://xmpp.local:5222") == ("xmpp.local", 5222, False)

    def test_tls(self):
        assert XmppClient._parse_service("xmpps://xmpp.local") == ("xmpp.local", 5223, True)

    def test_bare_host_defaults_tcp_5222(self):
        assert XmppClient._parse_service("xmpp.local") == ("xmpp.local", 5222, False)

    def test_websocket_rejected_with_guidance(self):
        with pytest.raises(RuntimeError, match="5222"):
            XmppClient._parse_service("ws://localhost:7071/ws")


class TestFlushSegments:
    def test_splits_completed_sentences(self):
        c = make_client()
        rest, ready = c._flush_segments("你好。今天天气")
        assert ready == ["你好。"] and rest == "今天天气"

    def test_code_block_holds_splitting(self):
        c = make_client()
        buf = "看代码```py\nprint(1)。"
        rest, ready = c._flush_segments(buf)
        assert ready == [] and rest == buf

    def test_force_split_on_long_text(self):
        c = make_client()
        text = ("句子。" * 2000)
        rest, ready = c._flush_segments(text)
        assert ready and sum(len(r) for r in ready) <= len(text)
        assert ("".join(ready) + rest) == text


class TestFence:
    def test_outside_fence_rejected(self):
        from py.get_setting import UPLOAD_FILES_DIR
        c = make_client()
        assert c._fence_ok(r"C:\Windows\System32\secret.png") is False
        assert c._fence_ok(os.path.join(UPLOAD_FILES_DIR, "ok.png")) is True


class TestCommandRouting:
    def _run(self, m, client):
        asyncio.run(client._handle_message(m))
        return client.sent

    def test_new_clears_memory(self):
        c = make_client()
        c.memoryList["kerobros@localhost"] = [{"role": "user", "content": "x"}]
        out = self._run(msg(body="/new"), c)
        assert c.memoryList["kerobros@localhost"] == []
        assert out and "重置" in out[0][1]

    def test_id_and_help(self):
        c = make_client()
        out = self._run(msg(body="/id"), c)
        assert "kerobros@localhost" in out[0][1]

    def test_self_messages_ignored(self):
        c = make_client()
        out = self._run(msg(frm="sap_bot@localhost/x", body="hi"), c)
        assert out == []

    def test_groupchat_ignored(self):
        c = make_client()
        out = self._run(msg(body="hi", mtype="groupchat"), c)
        assert out == []

    def test_wake_word_gates_normal_chat(self):
        c = make_client()
        c.wakeWord = "西瓜"
        c._process_llm = lambda *a, **k: asyncio.sleep(0)
        out = self._run(msg(body="普通消息"), c)
        assert out == []  # gated, no LLM, no reply


class TestIncomingImages:
    def test_oob_urls_and_inline_base64(self):
        c = make_client()
        m = msg(body="看这个", oob={"urls": ["https://x/y.png", "ftp://skip"]})
        uris = c._extract_incoming_images(m, "看这个")
        assert uris == ["https://x/y.png"]
        b64 = "data:image/png;base64," + ("A" * 300)
        m2 = msg(body=f"图 {b64} 结束")
        uris2 = c._extract_incoming_images(m2, m2["body"])
        assert uris2 == [b64]
