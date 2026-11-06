# -*- coding: utf-8 -*-
"""S196 IM 提问续流修复回归（11-06 卡手事故）。

根因：xmpp _resume_llm 复用审批替换器 replace_sentinel_content（只认
__sap_approval_v1__），ask 哨兵不被替换 → 答案 result_text 静默丢失。
覆盖：双前缀替换组合语义、_resume_llm 函数级注入（假 peer 流）、
ask 拦截先于 wakeWord、[Ask] 观测日志、questions 非法 JSON 串报错细化。
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


def _snapshot_with_ask():
    from py import ask_flow
    return [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "c1", "type": "function",
         "function": {"name": "ask_user_question_tool", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "name": "ask_user_question_tool",
         "content": ask_flow.make_sentinel("pending",
                                           [{"question": "q?", "options": ["a", "b"]}])}]


class TestDualReplacerSemantics:
    def test_ask_snapshot_only_ask_replacer_hits(self):
        from py import approval_im, ask_flow
        msgs = _snapshot_with_ask()
        assert approval_im.replace_sentinel_content(msgs, "X") is False
        assert ask_flow.replace_ask_sentinel(msgs, "【提问卡答复】ok") is True
        assert msgs[-1]["content"] == "【提问卡答复】ok"

    def test_approval_snapshot_not_clobbered_by_ask(self):
        from py import approval_im, ask_flow
        msgs = [{"role": "tool", "tool_call_id": "t",
                 "content": '{"__sap_approval_v1__":1,"type":"approval_required"}'}]
        assert approval_im.replace_sentinel_content(msgs, "APPROVED") is True
        assert ask_flow.replace_ask_sentinel(msgs, "X") is False


class TestResumeLlmFunctional:
    def test_ask_resume_injects_answer(self):
        from py.xmpp_client import XmppClient

        captured = {}

        async def fake_stream(chat_jid, messages):
            captured["messages"] = messages
            return {"out_buffer": "", "assistant_text": "done", "chain": []}

        async def fake_send(jid, text):
            return None

        async def _noop_async(*a, **k):
            return None

        fake = types.SimpleNamespace(asyncToolsID={}, fileLinks={}, memoryList={},
                                     _approval_queue={}, memoryLimit=0,
                                     _agent_stream_to_peer=fake_stream,
                                     _send_text=fake_send,
                                     _persist_conv=_noop_async,
                                     _clear_inflight=_noop_async,
                                     _send_local_images=_noop_async)
        snap = _snapshot_with_ask()
        asyncio.run(XmppClient._resume_llm(fake, "peer@x", snap, "【提问卡答复】1. b"))
        msgs = captured.get("messages") or []
        joined = repr(msgs)
        assert "【提问卡答复】1. b" in joined          # 答案注入请求
        assert "__sap_ask_v1__" not in joined          # 哨兵被替换掉

    def test_resume_llm_source_pins(self):
        body = XMPP[XMPP.index("async def _resume_llm"):]
        assert "approval_im.replace_sentinel_content(messages, result_text)" in body
        assert "ask_flow.replace_ask_sentinel(messages, result_text)" in body
        assert "未找到任何哨兵" in body


class TestInterceptOrderAndLogs:
    def test_ask_before_wakeword(self):
        i_ask = XMPP.index('latest_pending_ask("xmpp", frm)')
        i_wake = XMPP.index("if self.wakeWord and self.wakeWord not in text:")
        assert i_ask < i_wake, "提问作答拦截必须先于 wakeWord 门禁"

    def test_ask_observability_logs(self):
        assert "[Ask] IM 收到作答" in XMPP
        assert "[Ask] IM 续流触发" in XMPP


class TestBadJsonQuestionsError:
    def test_invalid_json_string_error(self):
        from py.ask_flow import normalize_questions
        _q, err = normalize_questions({"questions": '[{"question": "a"'})
        assert "not valid JSON" in err

    def test_valid_json_string_still_ok(self):
        from py.ask_flow import normalize_questions
        qs, err = normalize_questions(
            {"questions": '[{"question": "选哪个", "options": ["A", "B"]}]'})
        assert not err and qs[0]["question"] == "选哪个"
