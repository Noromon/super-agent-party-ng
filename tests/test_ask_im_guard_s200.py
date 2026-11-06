# -*- coding: utf-8 -*-
"""S200 IM 提问卡挂起轮不得触发空回复误报。

事故：模型纯工具轮调 ask 工具被服务端掐流（无正文是合规形态），
_process_llm 挂起检查只查 kind=approval → ask 轮掉进空回复兜底，
提问卡消息后秒发「⚠️ 模型本轮未返回正文」。修复=has_pending(kind=None)。
"""
import asyncio
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

XMPP = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")

_QUESTIONS = [{"question": "随便问点什么？", "options": ["A", "B"]}]


def _mk_fake(sents, calls):
    async def fake_stream(chat_jid, history):
        return {"out_buffer": "好嘞！那我来问问～", "assistant_text": "",
                "reasoning_chars": 12, "finish_reason": "stop", "err_text": "",
                "chain": [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]}]}

    async def fake_send(jid, text):
        sents.append(text)

    async def _noop_async(*a, **k):
        calls.append(a[0] if a else "")
        return None

    async def _restore(jid):
        return []

    return types.SimpleNamespace(
        asyncToolsID={}, fileLinks={}, memoryList={}, _approval_queue={},
        memoryLimit=0, _restore_conv=_restore, _merge_inflight=_noop_async,
        _inline_remote_images=lambda ec: asyncio.sleep(0, ec),
        _agent_stream_to_peer=fake_stream, _send_text=fake_send,
        _persist_conv=_noop_async, _clear_inflight=_noop_async,
        _send_local_images=_noop_async)


async def _mk_pending(jid, kind):
    from py import approval_store
    return await approval_store.create(
        platform="xmpp", peer_id=jid, tool_name="ask_user_question_tool",
        tool_params={"questions": _QUESTIONS}, messages=[],
        kind=kind, questions=_QUESTIONS, ttl=300)


class TestAskHangNoWarning:
    def test_ask_pending_round_skips_empty_guard(self):
        from py.xmpp_client import XmppClient
        from py import approval_store
        sents, calls = [], []
        jid = "askhang@sap.test"

        async def run():
            await _mk_pending(jid, "ask")
            fake = _mk_fake(sents, calls)
            await XmppClient._process_llm.__wrapped__(fake, jid, "随便问我点什么", [])
            await approval_store.resolve("xmpp", jid, "answers", "", "done", kind="ask")
            return fake
        fake = asyncio.run(run())
        assert any("好嘞" in s for s in sents)
        assert not any("未返回正文" in s for s in sents), f"误报警告: {sents}"
        assert fake.__dict__.get("_empty_reply_flags", {}).get(jid) is not True
        assert "_clear_inflight" not in str(calls)
        mem = fake.memoryList[jid]
        assert mem[-1]["role"] == "assistant" and mem[-1].get("backend_content")
        assert approval_store.latest_pending_ask("xmpp", jid) is None

    def test_approval_hang_still_early_returns(self):
        from py.xmpp_client import XmppClient
        from py import approval_store
        sents, calls = [], []
        jid = "apprhang@sap.test"

        async def run():
            await _mk_pending(jid, "approval")
            fake = _mk_fake(sents, calls)
            await XmppClient._process_llm.__wrapped__(fake, jid, "删掉那个文件", [])
            await approval_store.resolve("xmpp", jid, "approve", "", "ok")
        asyncio.run(run())
        assert any("好嘞" in s for s in sents)
        assert not any("未返回正文" in s for s in sents)

    def test_normal_empty_round_still_warns(self):
        from py.xmpp_client import XmppClient
        sents, calls = [], []
        jid = "plainempty@sap.test"

        async def run():
            fake = _mk_fake(sents, calls)
            await XmppClient._process_llm.__wrapped__(fake, jid, "hi", [])
        asyncio.run(run())
        assert any("未返回正文" in s for s in sents), "正常空回复兜底不得被削弱"


class TestSourcePin:
    def test_kind_none_before_guard(self):
        body = XMPP[XMPP.index("async def _process_llm"):]
        i_pend = body.index('has_pending("xmpp", chat_jid, kind=None)')
        i_warn = body.index("empty_reply_msg")
        assert i_pend < i_warn

    def test_has_pending_kind_none_semantics(self):
        from py import approval_store

        async def run():
            await approval_store.create(
                platform="xmpp", peer_id="sem@x", tool_name="t", messages=[],
                kind="ask", questions=_QUESTIONS, ttl=60)
            assert approval_store.has_pending("xmpp", "sem@x", kind=None) is True
            assert approval_store.has_pending("xmpp", "sem@x") is False      # 默认仍只认审批
            assert approval_store.has_pending("xmpp", "sem@x", kind="ask") is True
            await approval_store.resolve("xmpp", "sem@x", "answers", "", "x", kind="ask")
            assert approval_store.has_pending("xmpp", "sem@x", kind=None) is False
        asyncio.run(run())
