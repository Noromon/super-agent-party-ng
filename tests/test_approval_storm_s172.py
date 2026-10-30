# S172: 审批编排断链修复 + 自动重放风暴掐灭。
# 事故（2026-10-30）：asyncTools 管道把审批哨兵吞进后台结果表（pending_abort 永不
# 触发、Web 审批卡与 IM /y /n 全部失联），DiaryChat 总结每 60s 失败无限自调用，
# 待批复期间模型被 nudge 催动反复重放。本测钉桩修复的三层闸：
#   1) 审批预检在 async spawn 之前同步执行；
#   2) 尾部未批复哨兵 → 路由静止态回执 + 不附 nudge；
#   3) 总结失败退避 + 引擎单飞 + 前端 resume 限流/审批刹车。
import ast
import json
import os
import sys
import time
from pathlib import Path

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
TOOLDISP = (ROOT / "py" / "tool_dispatch.py").read_text(encoding="utf-8")
INTEG = (ROOT / "py" / "diary_chat_integration.py").read_text(encoding="utf-8")
ENGINE = (ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
STORE = (ROOT / "py" / "approval_store.py").read_text(encoding="utf-8")
RESUME_JS = (ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")

_SENT = json.dumps({"__sap_approval_v1__": 1, "type": "approval_required",
                    "tool_name": "shell_tool_local", "tool_params": {"command": "ls"},
                    "permission_mode": "default", "cwd": ""},
                   ensure_ascii=False, separators=(",", ":"))


class TestPendingApprovalAtTailBehavior:
    def test_tail_sentinel_returns_dict(self):
        from py.tool_dispatch import pending_approval_at_tail
        ap = pending_approval_at_tail([
            {"role": "user", "content": "run it"},
            {"role": "assistant", "content": "", "tool_calls": [1]},
            {"role": "tool", "tool_call_id": "c1", "name": "shell_tool_local", "content": _SENT},
        ])
        assert ap is not None and ap["tool_name"] == "shell_tool_local"

    def test_tail_plain_tool_result_returns_none(self):
        from py.tool_dispatch import pending_approval_at_tail
        assert pending_approval_at_tail([{"role": "tool", "content": "ok done"}]) is None

    def test_tail_user_message_returns_none(self):
        from py.tool_dispatch import pending_approval_at_tail
        msgs = [{"role": "tool", "content": _SENT}, {"role": "user", "content": "继续"}]
        assert pending_approval_at_tail(msgs) is None

    def test_multi_tool_tail_with_sentinel(self):
        from py.tool_dispatch import pending_approval_at_tail
        msgs = [{"role": "tool", "content": "r1"}, {"role": "tool", "content": _SENT}]
        assert pending_approval_at_tail(msgs) is not None

    def test_truncated_sentinel_not_matched(self):
        from py.tool_dispatch import pending_approval_at_tail
        broken = _SENT[:40] + "...(truncated)..." + _SENT[-20:]
        assert pending_approval_at_tail([{"role": "tool", "content": broken}]) is None

    def test_empty_messages(self):
        from py.tool_dispatch import pending_approval_at_tail
        assert pending_approval_at_tail([]) is None
        assert pending_approval_at_tail(None) is None


def _exec_server_func(name):
    tree = ast.parse(SERVER)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(SERVER, node)
            ns = {"json": json, "time": time}
            exec(compile(seg, "<s172>", "exec"), ns)  # noqa: S102
            return ns[name]
    pytest.fail(f"{name} not found in server.py")


class TestPendingApprovalReplyDict:
    def test_reply_shape_and_content(self):
        fn = _exec_server_func("_pending_approval_reply_dict")
        d = fn({"tool_name": "shell_tool_local"}, "super-model")
        assert d["object"] == "chat.completion"
        assert d["choices"][0]["finish_reason"] == "stop"
        assert "等待审批" in d["choices"][0]["message"]["content"]
        assert "shell_tool_local" in d["choices"][0]["message"]["content"]


class TestAsyncApprovalPrecheck:
    def test_helpers_defined(self):
        assert "def _approval_precheck(" in SERVER
        assert "_sensitive_approval(tool_name, tool_params, settings)" in SERVER
        assert "path_scope.evaluate(" in SERVER

    def test_precheck_runs_before_async_spawn(self):
        i = SERVER.index("if settings['tools']['asyncTools']['enabled']:")
        j = SERVER.index("else:\n            if _st_cancelled(_st):", i)
        window = SERVER[i:j]
        assert "_pre_ap = _approval_precheck(response_content.name, args_dict, settings)" in window
        assert window.index("_pre_ap = _approval_precheck(") < window.index("asyncio.create_task(")

    def test_tail_function_is_imported_not_redefined(self):
        i = SERVER.index("from py.tool_dispatch import (_APPROVAL_PREFIX")
        assert "pending_approval_at_tail" in SERVER[i:i + 300]
        assert "def pending_approval_at_tail" not in SERVER
        assert "def pending_approval_at_tail" in TOOLDISP


class TestNudgeAndRouteGate:
    def test_nudge_gated_both_paths(self):
        gate = "if pending_approval_at_tail(request.messages) is None: append_resume_nudge(request.messages)"
        assert SERVER.count(gate) == 2

    def test_route_short_circuit_present(self):
        assert "_ap_tail = pending_approval_at_tail(request.messages)" in SERVER
        assert "_pending_approval_reply_dict(_ap_tail" in SERVER
        assert "_ap_hold_stream" in SERVER

    def test_endpoint_fingerprint(self):
        assert "ua=" in SERVER and "plat=" in SERVER and "bot=" in SERVER

    def test_pending_notifications_are_warn_level(self):
        assert '等待审批（Web 会话）", level="warn"' in SERVER
        assert '等待审批（{platform} · {peer_id}）", level="warn"' in STORE

    def test_pathscope_log_honest(self):
        assert "已产生审批哨兵" in SERVER
        assert "等待用户路径授权" not in SERVER


class TestDiarySummaryStorm:
    def test_failure_backoff(self):
        assert "_RETRY_AFTER: dict = {}" in INTEG
        assert "_RETRY_COOLDOWN = 300.0" in INTEG
        assert "_RETRY_AFTER[key] = time.time() + _RETRY_COOLDOWN" in INTEG
        assert "_RETRY_AFTER.pop(key, None)" in INTEG
        assert "_now < _RETRY_AFTER.get(key, 0.0)" in INTEG

    def test_error_repr_not_empty_str(self):
        assert "{e!r}" in INTEG
        assert "总结对话失败 [{key}]: {e}\"" not in INTEG

    def test_engine_single_flight(self):
        assert "self._chat_summary_task = None" in ENGINE
        assert "self._chat_summary_task is None or self._chat_summary_task.done()" in ENGINE

    def test_diary_platform_skips_memory_search(self):
        n = (SERVER.count('!= "diary":  # S172: 日记总结自调用跳过记忆检索')
             + SERVER.count('!= "diary":  # S172: 日记自调用跳过记忆检索'))
        assert n == 3
        assert "if m0 and not request.is_sub_agent:" not in SERVER
        assert "if m0 and not request.is_sub_agent and not request.is_quarantined:" not in SERVER

    def test_ns_abort_registers_im_approval(self):
        assert "await _im_approval_hangup(request, request.messages, _tail_m.get(\"content\"))" in SERVER


class TestFrontendBrakes:
    def test_resume_rate_limit(self):
        assert "this._resumeAttempts" in RESUME_JS
        assert "300000" in RESUME_JS and ">= 3" in RESUME_JS

    def test_approval_brake_flag(self):
        assert "this._resumeSawApproval = true;" in RESUME_JS
        assert "this._resumeSawApproval = false;" in CHAT_JS
        assert "!this._resumeSawApproval" in CHAT_JS
