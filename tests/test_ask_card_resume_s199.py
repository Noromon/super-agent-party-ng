# -*- coding: utf-8 -*-
"""S199 提问卡续跑自备 AbortController（修复 null.signal 崩溃）。

事故：submitAskAnswer 裸调 generateAIResponse，其 fetch 读
this.abortController.signal——该字段仅由 sendMessage 创建并在 finally 置 null，
独立入口调用必为 null → 「Cannot read properties of null (reading 'signal')」。
审批路径不崩是因为 processToolApproval 调用前自备三件套（10_chat_stream.js:830-832）。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

JS_BLOCKS = (_ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")


class TestAskResumeAbortController:
    def setup_method(self):
        self.body = JS_BLOCKS[JS_BLOCKS.index("submitAskAnswer(msg, block)"):]
        self.i_replay = self.body.index("await this.generateAIResponse(this.mainAgent")

    def test_controller_created_before_replay(self):
        body = self.body
        assert body.count("this.abortController = new AbortController();") == 1
        i_ctl = body.index("this.abortController = new AbortController();")
        assert i_ctl < self.i_replay
        assert body.index("this.isSending = true;") < self.i_replay
        assert body.index("this.isTyping = true;") < self.i_replay

    def test_failure_resets_busy_flags(self):
        seg = self.body[self.i_replay:self.i_replay + 400]
        assert "this.isSending = false;" in seg and "this.isTyping = false;" in seg

    def test_approval_reference_intact(self):
        src = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
        i_ap = src.index("await this.generateAIResponse(this.mainAgent, currentMsg.agentName, true)")
        i_ctl = src.rindex("this.abortController = new AbortController();", 0, i_ap)
        assert i_ctl > src.index("async processToolApproval(")
