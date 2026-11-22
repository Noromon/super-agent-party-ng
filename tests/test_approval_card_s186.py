# S186：孤儿审批卡与批复点击语义修复（2026-10-31 二次实测事故）。
# 事故：asyncTools 模式哨兵回注本轮不掐停（设计使然），前端对任何流经哨兵
# 无条件建卡 → 模型越过后的孤儿卡仍可点击；S185 的 isSending 全局拒入使
# 生成期首点被拦=卡零反馈；幂等吞掉的 "[已处理]" 被当正常结果照样唤醒模型。
# 钉桩：①后端唯一 approval_pending SSE（真-pending 活卡宣告）；②前端孤儿卡
# 折叠（新卡出现即折叠 + 收尾折叠未点名卡，右侧详情复用 openToolBlockDetail）；
# ③点击语义：仅 per-toolCallId 锁、[已处理]/[Cancelled] 不唤醒模型、catch 恢复原态。
import os
import sys
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

ROOT = Path(__file__).resolve().parent.parent
SERVER = ((ROOT / "server.py").read_text(encoding="utf-8") + (ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8") + (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8"))  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
CHAT_JS = (ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
RESUME_JS = (ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
BLOCKS_JS = (ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")


def _approval_body():
    i = CHAT_JS.index("async processToolApproval")
    return CHAT_JS[i:CHAT_JS.index("    updateUIBlock(msg, blockId, newHtml)")]


class TestBackendApprovalPendingEvent:
    def test_helper_defined(self):
        assert "def _approval_pending_event_chunk(request):" in SERVER
        assert '"approval_pending"' in SERVER

    def test_yield_after_web_notify(self):
        assert "_notify_web_approval_pending(_st)\n        _ap_ev_chunk = _approval_pending_event_chunk(request)" in SERVER
        assert "if _ap_ev_chunk:\n            yield _ap_ev_chunk" in SERVER

    def test_helper_declares_tool_call_id(self):
        i = SERVER.index("def _approval_pending_event_chunk")
        seg = SERVER[i:i + 1200]
        assert '"tool_call_id": _tid' in seg
        assert "_is_approval_result(" in seg


class TestOrphanCardCollapse:
    def test_collapse_method_defined(self):
        assert "_collapseStaleApprovalCards(msg, keepOverride)" in BLOCKS_JS
        assert "已失效：流程已继续" in BLOCKS_JS
        assert "type: 'tool_result'," in BLOCKS_JS  # S187 起为替换式生成

    def test_supersede_on_new_card(self):
        assert "this._collapseStaleApprovalCards(currentMsg, toolCallId);" in RESUME_JS

    def test_collapse_at_stream_ends(self):
        assert CHAT_JS.count("_collapseStaleApprovalCards(currentMsg)") >= 2
        assert "_collapseStaleApprovalCards(currentMsg); // S186" in RESUME_JS

    def test_ingest_and_reset(self):
        assert CHAT_JS.count("delta.approval_pending") >= 1
        assert RESUME_JS.count("delta.approval_pending") >= 1
        assert "this._pendingApprovalToolCallId = delta.approval_pending.tool_call_id || null;" in CHAT_JS
        assert "this._pendingApprovalToolCallId = delta.approval_pending.tool_call_id || null;" in RESUME_JS
        assert "this._pendingApprovalToolCallId = null;" in CHAT_JS


class TestClickSemantics:
    def test_global_sending_guard_removed(self):
        body = _approval_body()
        assert "|| this.isSending || this.isTyping" not in body
        assert "if (this._approvalInFlight[toolCallId]) {" in body

    def test_final_note_no_model_wake(self):
        body = _approval_body()
        assert "startsWith('[已处理]')" in body
        assert "startsWith('[Cancelled]')" in body
        dup = body.index("startsWith('[已处理]')")
        wake = body.index("await this.generateAIResponse")
        assert body.index("return;\n                }", dup) < wake

    def test_catch_keeps_result_block_with_detail(self):
        # S187 语义修正：失败不再恢复回卡，错误文本写进结果块
        body = _approval_body()
        assert "targetBlock.type = 'approval';" not in body
        assert "执行失败: ${_cm}" in body
        assert "Tool execution failed: ${_em}" in body
