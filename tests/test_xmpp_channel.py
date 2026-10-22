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

import py.xmpp_client as xc
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
    c._manager_ref = None
    c._ready_callback = None
    c.session = None
    c.ignore_cert_hosts = []
    c.extra_outbound_dirs = []
    c.tools_mode = "inherit"
    c.tools_list = []
    c.image_resize_mode = "downscale_only"
    c.image_max_side = 1024
    c.image_oversize_action = "reject"
    c.image_max_mb = 20
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


class _ChunkStream:
    def __init__(self, chunks):
        self.chunks = chunks
        self.served = 0
        self.total = len(chunks)

    async def iter_chunked(self, _n):
        for c in self.chunks:
            self.served += 1
            yield c


class _FakeResp:
    def __init__(self, stream, status=200, ctype="image/png"):
        self.content = stream
        self.status = status
        self.headers = {"Content-Type": ctype + "; charset=binary"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _fake_session(body, pieces=1, status=200, ctype="image/png"):
    size = max(1, (len(body) + pieces - 1) // pieces)
    stream = _ChunkStream([body[i:i + size] for i in range(0, len(body), size)] or [b""])

    class FakeSession:
        def get(self, url, ssl=None):
            return _FakeResp(stream, status=status, ctype=ctype)
    FakeSession.stream = stream
    return FakeSession()


class TestOversizeAndIntegrity:
    @staticmethod
    def _png(w, h, rgba=False):
        import io as _io
        from PIL import Image
        img = Image.new("RGBA" if rgba else "RGB", (w, h), (9, 99, 199, 128) if rgba else (9, 99, 199))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    @staticmethod
    def _noise_png(w, h):
        import io as _io
        import os as _os
        from PIL import Image
        img = Image.frombytes("RGB", (w, h), _os.urandom(w * h * 3))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def test_validate_image_pure(self):
        good = self._png(32, 32)
        assert XmppClient._validate_image(good) is True
        assert XmppClient._validate_image(good[:-10]) is False   # truncated
        assert XmppClient._validate_image(b"not-an-image") is False

    def test_truncated_stream_rejected_by_gate(self):
        # the exact field bug: last bytes "missing" -> fail-closed, never to model
        c = make_client()
        body = self._png(200, 150)
        c.session = _fake_session(body[:-16], pieces=5)
        assert asyncio.run(c._download_as_data_uri("http://files.local/x.png")) == (None, None)

    def test_reject_stops_stream_early(self):
        c = make_client()
        c.image_oversize_action, c.image_max_mb = "reject", 1
        body = self._noise_png(600, 600)          # ~1.08MB incompressible PNG
        assert len(body) > 1024 * 1024
        sess = _fake_session(body, pieces=40)
        c.session = sess
        assert asyncio.run(c._download_as_data_uri("http://files.local/big.png")) == (None, None)
        assert sess.stream.served < sess.stream.total   # 掐断，未传完

    def test_shrink_oversize_becomes_new_original(self):
        import base64 as b64m
        import io as _io
        from PIL import Image
        c = make_client()
        c.image_oversize_action, c.image_max_mb = "shrink", 1
        c.image_resize_mode = "off"               # isolate the shrink layer
        body = self._noise_png(700, 700)
        assert len(body) > 1024 * 1024
        sess = _fake_session(body, pieces=40)
        c.session = sess
        uri, fname = asyncio.run(c._download_as_data_uri("http://files.local/big.png"))
        assert sess.stream.served == sess.stream.total     # 完整传完
        assert uri and uri.startswith("data:image/png;base64,")
        raw = b64m.b64decode(uri.split(",", 1)[1])
        assert len(raw) <= 1024 * 1024
        assert max(Image.open(_io.BytesIO(raw)).size) < 700
        assert fname is None or fname.endswith(".png")     # 落盘"原图"=缩小版

    def test_off_mode_no_limit(self):
        c = make_client()
        c.image_oversize_action = "off"
        body = self._png(80, 60)
        c.session = _fake_session(body, pieces=3)
        uri, _f = asyncio.run(c._download_as_data_uri("http://files.local/x.png"))
        assert uri and uri.startswith("data:image/png;base64,")

    def test_shrink_floor_gives_up_cleanly(self):
        # threshold below the 256px floor output -> clean None, no crash
        assert XmppClient._shrink_to_bytes(self._noise_png(260, 260), 512) is None


class TestMobileLayer:
    """WP1 inline / tools override / persistence helpers."""

    def test_inline_remote_images_replaces_and_notifies(self, monkeypatch):
        c = make_client()

        async def fake_dl(url):
            return ("data:image/png;base64,QUJD", "saved.png") if "good" in url else (None, None)
        monkeypatch.setattr(c, "_download_as_data_uri", fake_dl)
        content = [
            {"type": "image_url", "image_url": {"url": "https://good/x.png"}},
            {"type": "image_url", "image_url": {"url": "https://bad/y.png"}},
            {"type": "text", "text": "附言"},
        ]
        out = asyncio.run(c._inline_remote_images(content))
        assert out[0]["image_url"]["url"].startswith("data:image/png")
        assert out[1]["type"] == "text" and "原始URL" in out[1]["text"]
        assert out[2]["text"] == "附言"

    def test_download_streams_chunks_to_completion(self):
        # aiohttp content.read(n) is a PARTIAL read — the pipeline must
        # consume iter_chunked to EOF; fake delivers bytes in pieces
        c = make_client()
        body = TestOversizeAndIntegrity._png(60, 40)
        c.session = _fake_session(body, pieces=7)
        import base64 as b64m
        uri, _f = asyncio.run(c._download_as_data_uri("http://files.local/x.png"))
        assert uri.startswith("data:image/png;base64,")
        assert b64m.b64decode(uri.split(",", 1)[1]) == body

    def test_download_bad_status(self):
        c = make_client()
        c.session = _fake_session(b"x", status=404)
        assert asyncio.run(c._download_as_data_uri("http://files.local/x.png")) == (None, None)

    def test_tools_override_modes(self):
        c = make_client()
        c.tools_mode, c.tools_list = "inherit", ["a"]
        assert c._tools_override() == {}
        c.tools_mode = "whitelist"
        assert c._tools_override() == {"enable_tools": ["a"]}
        c.tools_mode = "blacklist"
        assert c._tools_override() == {"disable_tools": ["a"]}
        c.tools_mode, c.tools_list = "whitelist", []
        assert c._tools_override() == {}

    def test_restore_persist_and_new(self, monkeypatch):
        from py import get_setting as gs_mod
        c = make_client()
        saved = []

        async def fake_load(cid):
            assert cid == "bot:xmpp:jid@x"
            return [{"role": "user", "content": "history"}]

        async def fake_save(cid, msgs):
            saved.append((cid, list(msgs)))
        monkeypatch.setattr(gs_mod, "load_bot_conv", fake_load)
        monkeypatch.setattr(gs_mod, "save_bot_conv", fake_save)
        restored = asyncio.run(c._restore_conv("jid@x"))
        assert restored[0]["content"] == "history"
        c.memoryList["jid@x"] = [{"role": "user", "content": "new"}]
        asyncio.run(c._persist_conv("jid@x"))
        assert saved[-1][0] == "bot:xmpp:jid@x" and len(saved[-1][1]) == 1
        # /new must persist the cleared history too
        asyncio.run(c._handle_message(msg(body="/new", frm="jid@x/res")))
        assert saved[-1][1] == []

    def test_fence_roots_include_workspace_and_extra(self, monkeypatch):
        c = make_client()
        c.extra_outbound_dirs = [r"Z:\artifacts", "  "]

        async def fake_settings():
            return {"CLISettings": {"cc_path": r"D:\project-x"}}
        monkeypatch.setattr("py.xmpp_client.load_settings", fake_settings)
        roots = asyncio.run(c._fence_roots())
        assert r"Z:\artifacts" in roots and r"D:\project-x" in roots
        assert __import__("os").getcwd() in roots
        assert "" not in roots


class TestIncomingImages:
    def test_oob_urls_and_inline_base64(self):
        c = make_client()
        m = msg(body="看这个", oob={"urls": ["https://x/y.png", "ftp://skip"]})
        uris, _kept = c._extract_incoming_images(m, "看这个")
        assert uris == ["https://x/y.png"]
        b64 = "data:image/png;base64," + ("A" * 300)
        m2 = msg(body=f"图 {b64} 结束")
        uris2, _kept2 = c._extract_incoming_images(m2, m2["body"])
        assert uris2 == [b64]


class TestResizeIfNeeded:
    @staticmethod
    def _png(w, h, rgba=False):
        import io as _io
        from PIL import Image
        img = Image.new("RGBA" if rgba else "RGB", (w, h), (200, 30, 30, 120) if rgba else (200, 30, 30))
        buf = _io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()

    def test_off_passthrough(self):
        data = self._png(300, 200)
        out, ct = XmppClient._resize_if_needed(data, "image/png", "off", 100)
        assert out is data and ct == "image/png"

    def test_downscale_shrinks_small_untouched(self):
        big, small = self._png(300, 200), self._png(50, 40)
        out, ct = XmppClient._resize_if_needed(big, "image/png", "downscale_only", 100)
        assert out is not big
        from PIL import Image
        import io as _io
        assert max(Image.open(_io.BytesIO(out)).size) == 100
        out2, _ = XmppClient._resize_if_needed(small, "image/png", "downscale_only", 100)
        assert out2 is small   # 只缩小不放大

    def test_fit_enlarges_to_side(self):
        from PIL import Image
        import io as _io
        out, ct = XmppClient._resize_if_needed(self._png(50, 40), "image/png", "fit", 100)
        assert max(Image.open(_io.BytesIO(out)).size) == 100

    def test_alpha_survives(self):
        from PIL import Image
        import io as _io
        out, ct = XmppClient._resize_if_needed(
            self._png(400, 300, rgba=True), "image/png", "downscale_only", 128)
        img = Image.open(_io.BytesIO(out))
        assert ct == "image/png" and img.mode == "RGBA"

    def test_corrupt_bytes_passthrough(self):
        out, ct = XmppClient._resize_if_needed(b"not-an-image", "image/jpeg", "fit", 512)
        assert out == b"not-an-image"

    def test_download_wires_resize(self, monkeypatch):
        # download pipeline must resize the request copy, keep original on disk
        c = make_client()
        c.image_resize_mode, c.image_max_side = "downscale_only", 64
        body = TestResizeIfNeeded._png(500, 400)
        c.session = _fake_session(body, pieces=4)
        import base64 as b64m
        import io as _io
        from PIL import Image
        uri, _f = asyncio.run(c._download_as_data_uri("http://files.local/x.png"))
        raw = b64m.b64decode(uri.split(",", 1)[1])
        assert max(Image.open(_io.BytesIO(raw)).size) == 64   # 请求副本已缩放


class TestBodyUrlExtraction:
    def test_body_links_extracted_and_stripped(self):
        c = make_client()
        text = ("看图 https://upload.example.invalid:7443/httpfileupload/ABC/zb2rh.jpg "
                "还有 https://x.example/y.png?v=2 普通 https://example.com/page 链接")
        uris, cleaned = c._extract_incoming_images(FakeMsg(body=""), text)
        assert uris == ["https://upload.example.invalid:7443/httpfileupload/ABC/zb2rh.jpg",
                        "https://x.example/y.png?v=2"]
        assert "httpfileupload" not in cleaned and "y.png" not in cleaned
        assert "example.com/page" in cleaned and "看图" in cleaned

    def test_oob_and_body_dedupe(self):
        c = make_client()
        url = "https://u.local/a.jpg"
        msg = FakeMsg(body=url)
        msg["oob"] = {"urls": [url]}
        uris, cleaned = c._extract_incoming_images(msg, url)
        assert uris == [url] and cleaned == ""

    def test_data_uri_extracted_and_stripped(self):
        c = make_client()
        b64 = "data:image/png;base64," + "A" * 300
        uris, cleaned = c._extract_incoming_images(FakeMsg(body=""), f"前 {b64} 后")
        assert len(uris) == 1 and uris[0].startswith("data:image/png")
        assert "base64" not in cleaned and "前" in cleaned and "后" in cleaned


class TestTlsGate:
    @pytest.fixture(autouse=True)
    def _isolated_store(self, tmp_path, monkeypatch):
        # S72: 全局 STORE 一律换 tmp（防 env 泄漏写进生产 xmpp_trust.json），
        # 并禁用系统信任链真实联网。
        from py import xmpp_trust as xt
        monkeypatch.setattr(xt, "STORE", xt.TrustStore(tmp_path / "x.json"))
        monkeypatch.setattr(xc, "system_tls_ok", lambda h, p: False)

    def _fake_conn(self, monkeypatch, der=b"FAKE-DER", fail=False):
        import hashlib

        class _SslObj:
            def getpeercert(self, _binary):
                return der

        class _Writer:
            def get_extra_info(self, name):
                return _SslObj() if name == "ssl_object" else None

            def close(self):
                pass

        async def fake_open(*a, **kw):
            if fail:
                raise OSError("connection refused")
            return None, _Writer()
        monkeypatch.setattr(xc.asyncio, "open_connection", fake_open)
        return "sha256:" + hashlib.sha256(der).hexdigest()

    def test_plain_http_passes(self):
        c = make_client()
        assert asyncio.run(c._gate_https("http://whatever/x.png")) is True

    def test_whitelist_and_host_trust_short_circuit(self, monkeypatch):
        c = make_client()

        async def boom(*a, **kw):
            raise AssertionError("must not probe")
        monkeypatch.setattr(xc.asyncio, "open_connection", boom)
        c.ignore_cert_hosts = ["files.local"]
        assert asyncio.run(c._gate_https("https://files.local:7443/a.jpg")) is True
        from py import xmpp_trust as xt
        xt.get_store().trust("upload.local:443", "sha256:whatever")
        assert asyncio.run(c._gate_https("https://upload.local/a.jpg")) is True

    def test_probe_failure_refuses(self, monkeypatch):
        c = make_client()
        self._fake_conn(monkeypatch, fail=True)
        assert asyncio.run(c._gate_https("https://newhost.local:7443/a.jpg")) is False

    def test_unknown_cert_queued_for_review(self, monkeypatch):
        from py import xmpp_trust as xt
        c = make_client()
        xt.PENDING.clear()
        self._fake_conn(monkeypatch)
        assert asyncio.run(c._gate_https("https://stranger.local:7443/a.jpg")) is False
        keys = [it["key"] for it in xt.PENDING.list()]
        assert "stranger.local:7443" in keys

    def test_matching_fingerprint_passes(self, monkeypatch):
        from py import xmpp_trust as xt
        c = make_client()
        fp = self._fake_conn(monkeypatch)
        xt.get_store().trust("known2.local:7443", fp)
        assert asyncio.run(c._gate_https("https://known2.local:7443/a.jpg")) is True

    def test_system_trusted_cert_passes(self, monkeypatch):
        # S72: CA 证书系统链可验 → 直放，不探测不排队
        c = make_client()
        monkeypatch.setattr(xc, "system_tls_ok", lambda h, p: True)

        async def boom(*a, **kw):
            raise AssertionError("must not probe")
        monkeypatch.setattr(xc.asyncio, "open_connection", boom)
        assert asyncio.run(c._gate_https("https://ca.good/a.jpg")) is True

    def test_same_cert_other_host_passes(self, monkeypatch):
        # S72: 已审阅证书的同指纹主机（Openfire slot 回机器名:7443）免复审
        from py import xmpp_trust as xt
        c = make_client()
        fp = self._fake_conn(monkeypatch)
        xt.get_store().trust("localhost:5222", fp)
        assert asyncio.run(c._gate_https("https://DESKTOP-XYZ:7443/a.jpg")) is True


class TestRedactMediaForStore:
    def test_image_replaced_with_filename_marker(self):
        c = make_client()
        content = [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 400},
             "_saved": "xmpp_in_1.png"},
            {"type": "text", "text": "原话在此"},
        ]
        m = c._redact_media_for_store(content)
        assert m["role"] == "user"
        assert m["content"].startswith("[用户发送了图片，已存文件: xmpp_in_1.png]")
        assert "原话在此" in m["content"] and "base64" not in m["content"]

    def test_image_without_saved_name_and_pure_text(self):
        c = make_client()
        m = c._redact_media_for_store(
            [{"type": "image_url", "image_url": {"url": "data:x"}, "_saved": ""}])
        assert m["content"] == "[用户发送了图片]"
        m2 = c._redact_media_for_store([{"type": "text", "text": "hi"}])
        assert m2["content"] == "hi"
        assert c._redact_media_for_store("plain") == {"role": "user", "content": "plain"}


class TestRunConstruction:
    """Pin the slixmpp construction lines (past bugs: slixmpp.Client does not
    exist in 1.17; connect() takes host/port kwargs, not an address tuple,
    and must NOT be awaited — readiness comes from session_start)."""

    def test_run_constructs_clientxmpp_and_connects_tcp(self, monkeypatch):
        from py import xmpp_client as mod
        calls, handlers = {}, {}

        class FakeXmpp:
            def __init__(self, jid, password, **kw):
                calls["jid"] = jid
                calls["password"] = password
                calls["registered"] = []

            def register_plugin(self, name):
                calls["registered"].append(name)

            def add_event_handler(self, ev, fn):
                handlers[ev] = fn

            def send_presence(self):
                pass

            def disconnect(self):
                calls["disconnected"] = True

            def connect(self, host=None, port=None):  # sync, returns a future IRL
                calls["connect"] = (host, port)
                calls["tls"] = (self.enable_direct_tls, self.enable_starttls,
                                self.enable_plaintext)

                async def _fire():
                    await handlers["session_start"](None)
                    c._shutdown_requested = True
                asyncio.ensure_future(_fire())
                return None

        monkeypatch.setattr(mod.slixmpp, "ClientXMPP", FakeXmpp)
        c = make_client()
        asyncio.run(c.run())  # bounded: session_start sets shutdown
        assert calls["jid"] == "sap_bot@localhost"
        assert calls["connect"] == ("localhost", 5222)
        assert calls["tls"] == (False, True, False)  # tcp => starttls only
        assert set(calls["registered"]) == set(mod.XmppClient.PLUGINS)
        assert calls.get("disconnected") is True

    def test_xmpps_forces_direct_tls(self, monkeypatch):
        from py import xmpp_client as mod
        calls, handlers = {}, {}

        class FakeXmpp:
            def __init__(self, jid, password, **kw):
                pass

            def register_plugin(self, name):
                pass

            def add_event_handler(self, ev, fn):
                handlers[ev] = fn

            def send_presence(self):
                pass

            def disconnect(self):
                pass

            def connect(self, host=None, port=None):
                calls["connect"] = (host, port)
                calls["tls"] = (self.enable_direct_tls, self.enable_starttls,
                                self.enable_plaintext)

                async def _fire():
                    await handlers["session_start"](None)
                    c._shutdown_requested = True
                asyncio.ensure_future(_fire())
                return None

        monkeypatch.setattr(mod.slixmpp, "ClientXMPP", FakeXmpp)
        c = make_client()
        c.service_url = "xmpps://xmpp.local:5223"
        asyncio.run(c.run())
        assert calls["connect"] == ("xmpp.local", 5223)
        assert calls["tls"] == (True, False, False)

    def test_ws_url_rejected_before_any_construction(self, monkeypatch):
        from py import xmpp_client as mod
        built = []

        class NoBuild:
            def __init__(self, *a, **k):
                built.append(a)

        monkeypatch.setattr(mod.slixmpp, "ClientXMPP", NoBuild)
        c = make_client()
        c.service_url = "ws://localhost:7071/ws"
        with pytest.raises(RuntimeError, match="5222"):
            asyncio.run(c.run())
        assert built == []  # rejected before touching slixmpp at all


class TestS72UploadFlow:
    """_upload_and_share 候选顺序重试 + 纯 helper 行为测（探针实测语义回归）。"""

    def _tmp_png(self):
        import os as _os
        fd, path = tempfile.mkstemp(suffix=".png")
        _os.write(fd, b"x" * 64)
        _os.close(fd)
        self._path = path
        return path

    def _client(self):
        c = make_client()
        c._upload_service_jid = None
        c._xep0363_supported = True
        c.sent = []

        async def fake_send(chat_jid, text):
            c.sent.append(text)
        c._send_text = fake_send
        c.sims = []
        c._send_sims = lambda jid, url, name, size, mime: c.sims.append((url, name))
        return c

    def test_pick_upload_services_order(self):
        got = xc.pick_upload_services(
            [("proxy.a", "File Proxy"), ("fileupload.localhost", "HTTP File Upload")],
            "localhost")
        assert got == ["fileupload.localhost",
                       "httpfileupload.localhost", "upload.localhost"]

    def test_slot_request_size_dual_form(self):
        # Openfire 读 <size> 文本；XEP 严格实现读 size 属性。缺任一都是回归。
        # （<request> 子元素按惯例不带命名空间，序列化时由父级继承）
        req = xc.build_slot_request("a.png", 1234)
        sz = req.find("size")
        assert sz is not None and sz.get("size") == "1234" and sz.text == "1234"
        fn = req.find("filename")
        assert fn is not None and fn.get("name") == "a.png" and fn.text == "a.png"

    def test_slot_error_kind(self):
        from slixmpp.xmlstream import ET as XET
        nosrv = XET.fromstring(
            "<iq type='error'><error type='cancel'>"
            "<remote-server-not-found xmlns='urn:ietf:params:xml:ns:xmpp-stanzas'/>"
            "</error></iq>")
        bad = XET.fromstring(
            "<iq type='error'><error type='modify'>"
            "<bad-request xmlns='urn:ietf:params:xml:ns:xmpp-stanzas'/>"
            "</error></iq>")
        assert xc.slot_error_kind(nosrv) == "noservice"
        assert xc.slot_error_kind(bad) == "error"

    def test_all_noservice_disables_and_informs(self, monkeypatch):
        c = self._client()
        path = self._tmp_png()

        async def services():
            return ["a.localhost", "b.localhost"]

        async def slot(service, name, size):
            return None, None, "noservice"
        monkeypatch.setattr(c, "_discover_upload_services", services)
        monkeypatch.setattr(c, "_request_slot", slot)
        out = asyncio.run(c._upload_and_share("j@x", path))
        os.unlink(path)
        assert out is None
        assert c._xep0363_supported is False
        assert any("XEP-0363" in s for s in c.sent)

    def test_partial_failure_keeps_capability(self, monkeypatch):
        c = self._client()
        path = self._tmp_png()

        async def services():
            return ["a.localhost", "b.localhost"]

        seq = iter([("noservice"), ("error")])

        async def slot(service, name, size):
            return None, None, next(seq)
        monkeypatch.setattr(c, "_discover_upload_services", services)
        monkeypatch.setattr(c, "_request_slot", slot)
        out = asyncio.run(c._upload_and_share("j@x", path))
        os.unlink(path)
        assert out is None
        assert c._xep0363_supported is True
        assert any("暂不可用" in s for s in c.sent)

    def test_first_dead_second_success(self, monkeypatch):
        c = self._client()
        path = self._tmp_png()

        async def services():
            return ["dead.localhost", "good.localhost"]

        async def slot(service, name, size):
            if service.startswith("dead"):
                return None, None, "noservice"
            return "https://good.local/p/a.png", "https://good.local/get/a.png", None

        async def gate(url):
            return True

        class _Resp:
            status = 201

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        class _Sess:
            def put(self, url, **kw):
                return _Resp()
        c.session = _Sess()
        c._aio_ssl = lambda url: False
        monkeypatch.setattr(c, "_discover_upload_services", services)
        monkeypatch.setattr(c, "_request_slot", slot)
        monkeypatch.setattr(c, "_gate_https", gate)
        out = asyncio.run(c._upload_and_share("j@x", path))
        os.unlink(path)
        assert out == "https://good.local/get/a.png"
        assert c._upload_service_jid == "good.localhost"
        assert c.sims and c._xep0363_supported is True

    def test_discover_prefers_sticky_cache(self, monkeypatch):
        c = make_client()
        c._upload_service_jid = "sticky.local"

        async def services():
            return [c._upload_service_jid]
        assert asyncio.run(c._discover_upload_services()) == ["sticky.local"]
