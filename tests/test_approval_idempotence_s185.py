# S185：审批未决期间重复推理/拥塞事故四层修复钉桩（2026-10-31 实锤事故）。
# 事故链：授权卡可重复点击 → 每次点击均触 /execute_tool_manually 与模型唤醒；
# 重复/残留流无法被单条停止掐灭；PathScope 拦截与"工具失败"提示与授权卡同瞬并现。
# 本测钉桩：F1 前端幂等防重入+安全降级；F2 审批执行一次性消费+complete 入口
# 审批尾卫兵；F3 会话级全停 cancel_all（与单条取消同围栏语义）。
import ast
import json
import os
import sys
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
TASKS = (ROOT / "py" / "routers" / "tasks.py").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
RESUME_JS = (ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")


def _func_src(source, name):
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(source, node)
            if seg:
                return seg
    pytest.fail(f"{name} not found")


class TestExecOnceConsumption:
    def test_dedup_defined_and_used(self):
        body = _func_src(SERVER, "execute_approved_tool")
        assert "_approval_exec_dedup(" in body
        assert "def _approval_prune_locked" in SERVER
        helper = _func_src(SERVER, "_approval_exec_dedup")
        assert "_approval_exec_once_lock" in helper
        assert "该批复的执行请求已消费完毕" in helper

    def test_cancel_fence_preserved(self):
        body = _func_src(SERVER, "execute_approved_tool")
        assert 'entry.get("cancelled")' in body or '_appr_entry.get("cancelled")' in body

    def test_exec_once_prune_behavior(self):
        ns = {"_approval_exec_once": set(range(600))}
        seg = ast.get_source_segment(SERVER, next(
            n for n in ast.walk(ast.parse(SERVER))
            if isinstance(n, ast.FunctionDef) and n.name == "_approval_prune_locked"))
        exec(compile(seg, "<s185>", "exec"), ns)  # noqa: S102
        ns["_approval_prune_locked"]()
        assert len(ns["_approval_exec_once"]) <= 400


class TestCompleteEntryApprovalGuard:
    def test_guard_before_entry_registration(self):
        body = _func_src(SERVER, "generate_complete_response")
        assert "pending_approval_at_tail(_msgs)" in body
        assert "_pending_approval_reply_dict" in body
        assert body.index("pending_approval_at_tail(_msgs)") < body.index("complete_stream_id = str(uuid.uuid4())")
        assert "[S185] complete 入口检出未批复审批尾部" in body

    def test_stream_guard_intact(self):
        assert "_ap_tail = pending_approval_at_tail(request.messages)" in SERVER
        assert "_ap_hold_stream" in SERVER


class TestCancelAllEndpoint:
    def test_endpoint_defined(self):
        assert '"/v1/streams/cancel_all"' in TASKS

    def test_per_entry_fence_semantics(self):
        body = _func_src(TASKS, "cancel_all_streams_endpoint")
        assert "_active_streams_lock" in body
        assert '_entry["cancelled"] = True' in body
        assert "_task.cancel()" in body
        assert "asyncio.shield" in body
        assert "_cleanup_stream(_sid, delay=5.0)" in body
        assert "[S185] cancel_all" in body

    def test_single_cancel_intact(self):
        assert '"/v1/streams/cancel/{stream_id}"' in TASKS


class TestFrontendIdempotence:
    def test_inflight_guard_and_release(self):
        assert "_approvalInFlight[toolCallId]" in CHAT_JS
        assert "delete this._approvalInFlight[toolCallId];" in CHAT_JS

    def test_guard_precedes_backend_call(self):
        body = CHAT_JS[CHAT_JS.index("async processToolApproval"):
                       CHAT_JS.index("    updateUIBlock(msg, blockId, newHtml)")]
        guard = body.index("if (this._approvalInFlight[toolCallId]) {")
        stale = body.index("if (!this.approvalMap[toolCallId])")
        backend = body.index("executeToolBackend")
        wake = body.index("await this.generateAIResponse")
        assert guard < backend and stale < backend and guard < wake

    def test_missing_block_downgrade(self):
        body = CHAT_JS[CHAT_JS.index("async processToolApproval"):
                       CHAT_JS.index("    updateUIBlock(msg, blockId, newHtml)")]
        assert "if (!targetBlock) {" in body
        assert body.index("if (!targetBlock) {") < body.index("this.isSending = true;")
        assert CHAT_JS.count("该审批已处理或已失效，未触发新的请求") >= 2

    def test_single_model_wake_per_call(self):
        assert CHAT_JS.count("await this.generateAIResponse(this.mainAgent, currentMsg.agentName, true)") == 1

    def test_stop_all_wired_into_stop(self):
        assert "/v1/streams/cancel_all" in RESUME_JS
        i = RESUME_JS.index("stopGenerate()")
        assert "/v1/streams/cancel_all" in RESUME_JS[i:i + 900]


class TestSkippedNotApproval:
    def test_skipped_message_not_matched(self):
        from py.tool_dispatch import pending_approval_at_tail
        msgs = [{"role": "tool", "content": "[Skipped] 未执行：同一轮中前面的工具调用正在等待用户审批，或流程被中断。"}]
        assert pending_approval_at_tail(msgs) is None

    def test_real_sentinel_still_matched(self):
        from py.tool_dispatch import pending_approval_at_tail
        sent = json.dumps({"__sap_approval_v1__": 1, "type": "approval_required",
                           "tool_name": "list_files_tool_local", "tool_params": {},
                           "permission_mode": "default", "cwd": ""},
                          ensure_ascii=False, separators=(",", ":"))
        assert pending_approval_at_tail([{"role": "tool", "content": sent}]) is not None
