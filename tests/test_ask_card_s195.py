# -*- coding: utf-8 -*-
"""S195 web 提问卡（page_chat_main ask 卡 + 双路嗅探 + 活卡宣告事件）。

覆盖：哨兵载荷携带问题、_ask_pending_event_chunk 单测、_ask_tool_handle
哨兵带问题、server/前端 source 钉（嗅探建卡、折叠、提交回写、冻结跳过、
模板与 locales/css 键）。前端为纯 source 钉（无浏览器测试设施）。
"""
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")
JS_RESUME = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
JS_BLOCKS = (_ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")
JS_CHAT = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
TPL = (_ROOT / "static" / "templates" / "page_chat_main.html").read_text(encoding="utf-8")
ZH = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")
CSS = (_ROOT / "static" / "css" / "ask_card.css").read_text(encoding="utf-8")


def _payload_of(sentinel):
    return json.loads(sentinel)


class TestSentinelCarriesQuestions:
    def test_with_questions(self):
        from py import ask_flow
        qs = [{"question": "场景?", "options": ["A", "B"]}]
        p = _payload_of(ask_flow.make_sentinel("p1", qs))
        assert p["type"] == "ask_pending" and p["ask_id"] == "p1" and p["questions"] == qs
        assert ask_flow.is_ask_result(ask_flow.make_sentinel("p1", qs)) is not None

    def test_without_questions_backward(self):
        from py import ask_flow
        p = _payload_of(ask_flow.make_sentinel("p2"))
        assert "questions" not in p

    def test_ask_tool_handle_embeds_merged(self):
        import server
        st = {}
        sent = asyncio.run(server._ask_tool_handle(
            None, {"questions": [{"question": "q1", "options": ["a"]}]}, [], "t1", st))
        p = _payload_of(sent)
        assert p["questions"] == st["ask_qs"] == [{"question": "q1", "options": ["a"]}]


class TestAskPendingEventChunk:
    def test_names_sentinel(self):
        import server
        from py import ask_flow

        class R:
            messages = [
                {"role": "tool", "tool_call_id": "call_a", "content": "无关"},
                {"role": "tool", "tool_call_id": "call_ask",
                 "content": ask_flow.make_sentinel("pending", [{"question": "q", "options": []}])},
            ]
        chunk = server._ask_pending_event_chunk(R())
        assert chunk and chunk.startswith("data: ")
        d = json.loads(chunk[len("data: "):])["choices"][0]["delta"]["ask_pending"]
        assert d["tool_call_id"] == "call_ask"

    def test_none_without_sentinel(self):
        import server

        class R:
            messages = [{"role": "user", "content": "hi"}]
        assert server._ask_pending_event_chunk(R()) is None


class TestServerWiringPins:
    def test_handle_passes_questions(self):
        assert 'ask_flow.make_sentinel("pending", all_q)' in SERVER

    def test_web_only_yield(self):
        assert 'if _st.get("ask_hit") and _ask_channel(request)[0] == "web":' in SERVER
        assert "_ask_ev_chunk = _ask_pending_event_chunk(request)" in SERVER

    def test_event_chunk_source(self):
        body = SERVER[SERVER.index("def _ask_pending_event_chunk"):]
        body = body[: body.index("GATE_MAX")]
        assert "ask_flow_is_ask_result" in body and '"ask_pending"' in body


class TestFrontendIngestPins:
    def test_sniff_and_card(self):
        body = JS_RESUME[JS_RESUME.index("_ingestToolFrame(tool, delta"):]
        assert 'tool.content.startsWith(\'{"__sap_ask_v1__":1,\')' in body
        assert "tempAsk.type === 'ask_pending'" in body
        assert "getBlock('ask', toolCallId, toolName)" in body
        assert "this._resumeSawAsk = true" in body
        assert "this._pendingAskToolCallId = toolCallId || null" in body
        assert "this._collapseStaleAskCards(currentMsg, toolCallId)" in body
        # 哨兵原文入 backend_content（服务端替换定位所需）
        assert "name: toolName, content: tool.content });" in body

    def test_delta_and_finish_collapse(self):
        assert JS_CHAT.count("if (delta.ask_pending)") == 1
        assert JS_RESUME.count("if (delta.ask_pending)") == 1
        assert JS_CHAT.count("this._collapseStaleAskCards(currentMsg);") == 2
        assert JS_RESUME.count("this._collapseStaleAskCards(currentMsg);") == 1
        assert "this._pendingAskToolCallId = null;" in JS_CHAT
        assert "this._resumeSawAsk = false;" in JS_CHAT

    def test_freeze_skip_and_brake(self):
        assert "if (_raw.type === 'approval' || _raw.type === 'ask') return;" in JS_CHAT
        assert "if (this._resumeSawApproval || this._resumeSawAsk)" in JS_CHAT


class TestCardMethodsPins:
    def test_collapse_defined(self):
        body = JS_BLOCKS[JS_BLOCKS.index("_collapseStaleAskCards(msg, keepOverride)"):]
        body = body[: body.index("pickAskOption")]
        assert "b && b.type === 'ask' && b.id !== keep" in body
        assert "type: 'tool_result'" in body and "expired: true" in body

    def test_submit_bookkeeping(self):
        body = JS_BLOCKS[JS_BLOCKS.index("submitAskAnswer(msg, block)"):]
        assert "showNotification('正在生成中，暂无法提交答复', 'warning')" in body
        assert "${i + 1}. ${other}" in body and "${i + 1}. ${q.options[s]}" in body
        assert "type: 'tool_result', name: '已提交答复'" in body
        # S198：审批模式——服务端结算回写格式化结果，无 user 消息重放续跑；
        # 失效时降级 userInput+sendMessage（fallback 保留）
        assert "it.content = resultText" in body
        assert "await this.generateAIResponse(this.mainAgent" in body
        assert "'/ask_card_answer'" in body
        assert "this.userInput = answerText" in body  # 降级路径仍在
        assert "this._askInFlight" in body

    def test_pick_and_ready(self):
        assert "block.sel[qIdx] = optIdx;" in JS_BLOCKS
        assert "block.other[qIdx] = '';" in JS_BLOCKS
        assert "askCardReady(block)" in JS_BLOCKS and ":disabled=\"!askCardReady(block)\"" in TPL


class TestTemplateLocaleCssPins:
    def test_template(self):
        assert "v-else-if=\"block.type === 'ask'\"" in TPL
        assert "pickAskOption(block, qi, oi)" in TPL
        assert "submitAskAnswer(message, block)" in TPL
        assert ":disabled=\"!askCardReady(block)\"" in TPL
        assert "v-model=\"block.other[qi]\"" in TPL

    def test_locales(self):
        for blob in (ZH, EN):
            for key in ("'askCardTitle'", "'askCardOtherPlaceholder'", "'askCardSubmit'"):
                assert key in blob

    def test_css(self):
        assert ".type-ask .sp-header i" in CSS
        assert ".sp-ask-opt.active" in CSS
        assert ".sp-btn:disabled" in CSS
        # CSS 防恶化裁决：新样式入独立文件并由 chat.html 引用
        assert 'href="css/ask_card.css"' in (_ROOT / "static" / "chat.html").read_text(encoding="utf-8")


class TestAskCardHostInvariant:
    """S197 教训：桌面主对话= index.html + page_home 模板，chat.html 只是另一宿主。
    凡渲染审批卡的模板必须同样渲染提问卡；两个宿主页都必须引用 ask_card.css。"""

    def test_every_approval_template_has_ask_branch(self):
        tpl_dir = _ROOT / "static" / "templates"
        hosts = [p for p in tpl_dir.glob("*.html")
                 if "processToolApproval(block.id" in p.read_text(encoding="utf-8")]
        assert len(hosts) >= 3, "模板宿主枚举异常（page_chat_main/page_home/page_ai-browser）"
        for p in hosts:
            txt = p.read_text(encoding="utf-8")
            assert "block.type === 'ask'" in txt, f"{p.name} 缺提问卡分支（S197 漏渲染事故）"
            assert "submitAskAnswer(message, block)" in txt, f"{p.name} 缺提问提交接线"

    def test_both_hosts_link_ask_css(self):
        for host in ("index.html", "chat.html"):
            assert 'href="css/ask_card.css"' in \
                (_ROOT / "static" / host).read_text(encoding="utf-8"), host
