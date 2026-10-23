# -*- coding: utf-8 -*-
"""S68：IM 家族空回复防线（观测/兜底/防污染）行为测 + 结构 pins。"""
import asyncio
import io
import os
import sys
import tempfile
import types
from pathlib import Path

# Must precede any py.get_setting import: keep paths out of the production dir.
os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_empty_test_")

# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest

from py.im_empty_guard import EMPTY_REPLY_MSG

_ROOT = str(REPO_ROOT)


def _read(rel):
    with io.open(os.path.join(_ROOT, rel), encoding="utf-8-sig") as f:
        return f.read()


# ---------------------------------------------------------------- 行为测（xmpp）

def _fake_chunk(content="", reasoning="", finish=None):
    delta = types.SimpleNamespace(content=content, reasoning_content=reasoning,
                                  tool_link="", async_tool_id="")
    return types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta,
                                                                finish_reason=finish)])


def _patch_xmpp_env(monkeypatch, chunks):
    from py import xmpp_client as xc

    class _FakeStream:
        def __init__(self, chunks):
            self._chunks = chunks

        def __aiter__(self):
            async def _gen():
                for c in self._chunks:
                    yield c
            return _gen()

    class _FakeCompletions:
        async def create(self, **kwargs):
            return _FakeStream(chunks)

    class _FakeClient:
        chat = types.SimpleNamespace(completions=_FakeCompletions())

    monkeypatch.setattr(xc, "AsyncOpenAI", lambda **kw: _FakeClient())

    async def _fake_load_settings():
        return {"tools": {"toolMemorandum": {"enabled": False}}}

    monkeypatch.setattr(xc, "load_settings", _fake_load_settings)
    monkeypatch.setattr(xc, "get_port", lambda: 1)

    client = xc.XmppClient()
    client.reasoningVisible = False

    sent, persisted = [], []

    async def _rec_send(chat_jid, text):
        sent.append(text)

    async def _rec_persist(chat_jid):
        persisted.append(chat_jid)

    async def _fake_restore(chat_jid):
        return []

    client._send_text = _rec_send
    client._persist_conv = _rec_persist
    client._restore_conv = _fake_restore
    return client, sent, persisted


def test_reasoning_only_triggers_fallback_and_no_history_pollution(monkeypatch):
    from py.im_empty_guard import EMPTY_REPLY_MSG
    chunks = [_fake_chunk(reasoning="让我好好思考一下这个问题……"),
              _fake_chunk(reasoning="结论是……", finish="stop")]
    client, sent, persisted = _patch_xmpp_env(monkeypatch, chunks)

    asyncio.run(client._process_llm("u@x", "hello", []))

    assert sent == [EMPTY_REPLY_MSG]
    # 空 assistant 不得写入历史；仅保留本轮 user
    hist = client.memoryList["u@x"]
    assert [m["role"] for m in hist] == ["user"]
    assert persisted == []


def test_normal_content_unaffected(monkeypatch):
    chunks = [_fake_chunk(content="你好呀，"), _fake_chunk(content="主人～", finish="stop")]
    client, sent, persisted = _patch_xmpp_env(monkeypatch, chunks)

    asyncio.run(client._process_llm("u@x", "hi", []))

    assert any("主人" in s for s in sent)
    assert EMPTY_REPLY_MSG not in sent
    hist = client.memoryList["u@x"]
    assert hist[-1]["role"] == "assistant" and hist[-1]["content"] == "你好呀，主人～"
    assert persisted == ["u@x"]


# ---------------------------------------------------------------- 结构 pins

GUARD_FILES = {
    "py/xmpp_client.py": 'if not assistant_text.strip():',
    "py/telegram_client.py": 'if not assistant_text.strip():',
    "py/dingtalk_bot_manager.py": 'if not state["full_response"].strip():',
    "py/discord_bot_manager.py": 'if not full_content.strip():',
    "py/feishu_bot_manager.py": 'if not full_content.strip():',
    "py/qq_bot_manager.py": 'if not full_content.strip():',
    "py/slack_bot_manager.py": 'if not full_content.strip():',
    "py/wechat_bot_manager.py": 'if not full_content.strip():',
    "py/wecom_bot_manager.py": 'if not full_response_text.strip():',
}


@pytest.mark.parametrize("rel,marker", sorted(GUARD_FILES.items()))
def test_guard_present_in_each_collector(rel, marker):
    src = _read(rel)
    # S89-B：xmpp 换用错误帧感知的 empty_reply_msg，import 口径随之更新
    imp = ("from py.im_empty_guard import empty_reply_msg, error_from_delta, log_empty_reply"
           if rel == "py/xmpp_client.py"
           else "from py.im_empty_guard import EMPTY_REPLY_MSG, log_empty_reply")
    assert imp in src
    assert marker in src


def test_qq_has_two_guard_sites():
    src = _read("py/qq_bot_manager.py")
    assert src.count("if not full_content.strip():") == 2
    assert src.count("log_empty_reply(") >= 2


def test_guard_module_contract():
    from py.im_empty_guard import EMPTY_REPLY_MSG
    assert "模型" in EMPTY_REPLY_MSG and "重试" in EMPTY_REPLY_MSG
    src = _read("py/im_empty_guard.py")
    assert "[IM-empty]" in src


def test_server_no_empty_assistant_append():
    src = _read("server.py")
    assert ("if not tool_calls and full_content:\n"
            "                # 将响应添加到消息列表（S68：空生成不写历史，防 assistant 空串污染上下文）\n"
            "                content_append(request.messages, 'assistant', full_content)") in src
