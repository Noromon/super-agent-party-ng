# -*- coding: utf-8 -*-
"""S198 web 提问卡审批化（答案单一表征 + 回合文本归位）。

事故（20:03 请求 dump 实锤）：提问回合开场白被 _syncAssistantBody 尾挂到
工具结果之后 + 卡片答案同时以 tool 结果与 user 消息双份出现——模型对畸形
历史自我解释出「用户说这是幻觉」的 confabulation。
覆盖：/ask_card_answer 端点（成功/部分作答按未答复结算/无挂起卡）、
_syncAssistantBody 合并逻辑 source 钉、卡片提交链 source 钉。
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

JS_SYNC = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
JS_BLOCKS = (_ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")
SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")

_QUESTIONS = [{"question": "今晚干嘛？", "options": ["折腾框架", "闲聊摸鱼"]},
              {"question": "coding agent 有着落没？", "options": ["有", "没有"]}]


class _FakeReq:
    def __init__(self, d):
        self._d = d

    async def json(self):
        return self._d


async def _mk_pending(conv):
    from py import approval_store
    return await approval_store.create(
        platform="web", peer_id=conv, tool_name="ask_user_question_tool",
        tool_params={"questions": _QUESTIONS}, messages=[],
        kind="ask", questions=_QUESTIONS, ttl=600)


class TestAskCardAnswerEndpoint:
    def test_full_answer_resolves_and_formats(self):
        import server
        from py import approval_store

        async def run():
            conv = "s198-full"
            await _mk_pending(conv)
            r = await server.ask_card_answer(_FakeReq(
                {"conversation_id": conv, "answer_text": "1. 闲聊摸鱼\n2. 那还是opencode牛逼"}))
            assert r["ok"] and "提问卡答复" in r["result_text"]
            assert "闲聊摸鱼" in r["result_text"] and "opencode" in r["result_text"]
            assert "（未答复）" not in r["result_text"]
            assert approval_store.latest_pending_ask("web", conv) is None
        asyncio.run(run())

    def test_partial_settles_missing_as_unanswered(self):
        import server

        async def run():
            conv = "s198-partial"
            await _mk_pending(conv)
            r = await server.ask_card_answer(_FakeReq(
                {"conversation_id": conv, "answer_text": "1. 闲聊摸鱼"}))
            assert r["ok"] and "（未答复）" in r["result_text"]
        asyncio.run(run())

    def test_no_pending_degrades(self):
        import server

        async def run():
            r = await server.ask_card_answer(_FakeReq(
                {"conversation_id": "s198-none", "answer_text": "1. x"}))
            assert r["ok"] is False and r["reason"] == "no_pending"
        asyncio.run(run())


class TestSyncAssistantMerge:
    def test_merge_into_tool_calls_entry(self):
        body = JS_SYNC[JS_SYNC.index("_syncAssistantBody(msg)"):]
        assert "it.role === 'assistant' && it.tool_calls && it.tool_calls.length" in body
        assert "if (it.role === 'user') break;" in body
        assert "tcEntry.content = body;" in body
        # 尾挂仅剩两处：空 backend 起手 + 无 tool_calls 条目兜底（合并优先于兜底）
        assert body.count(
            "msg.backend_content.push({ role: 'assistant', content: body });") == 2
        assert body.index("tcEntry && !String(tcEntry.content") < body.rindex(
            "msg.backend_content.push({ role: 'assistant', content: body });")

    def test_endpoint_source_pins(self):
        assert '@app.post("/ask_card_answer")' in SERVER
        assert 'latest_pending_ask("web", conv)' in SERVER
        assert "ask_flow.format_result_text(rec, ans)" in SERVER
        assert '[Ask] web 卡片提交' in SERVER


class TestSubmitFlowPins:
    def test_card_answer_no_user_message_on_success(self):
        body = JS_BLOCKS[JS_BLOCKS.index("submitAskAnswer(msg, block)"):]
        assert body.count("this.userInput = answerText") == 1   # 仅失效降级一处
        assert "await this.generateAIResponse(this.mainAgent" in body
        assert "提问卡已失效" in body
