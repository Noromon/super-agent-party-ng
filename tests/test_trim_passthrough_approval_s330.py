# -*- coding: utf-8 -*-
"""S330: MsgTrim 预算直通（对齐 opencode）+ 审批执行主表回退 + one-shot 放行。

事故双链：①9fc4387f 起群聊盲切12坐落 context_manager 上游，980→12 失忆级
裁剪；②start_extension_node_tool_local 不在 approval_exec S150 副本表，
approve 后执行报 not found → 模型当轮误判"没拉起"+双弹窗（17:21 日志实锤）。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # 驱逐 site-packages 的 py 单体库（s323 同法）

import pytest  # noqa: E402

from py import approval_exec as AE  # noqa: E402
from py import approval_store as ST  # noqa: E402
from py import tool_hooks as TH  # noqa: E402
from py.group_memory import _trim_request_messages  # noqa: E402

CM_ON = {"contextManagement": {"enabled": True, "contextWindow": 262144,
                               "compactRatio": 0.8, "keepRecentDialog": 12}}


@pytest.fixture(autouse=True)
def _clean_grants():
    yield
    ST._GRANTS.clear()  # 防 grant/上下文跨测试泄漏（同 session 其他审批测试误放）
    ST.set_current_im_ctx(None, None)


def _dialog(n, chars=8):
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"m{i} " + "x" * chars})
    return out


class TestTrimBudget:
    def test_passthrough_within_budget(self):
        msgs = [{"role": "system", "content": "s"}] + _dialog(150)
        out = _trim_request_messages(msgs, settings=CM_ON)
        assert len(out) == len(msgs)  # est 远小于 262144*0.8 → 全量直通

    def test_over_budget_falls_back_to_window(self):
        st = {"contextManagement": {"enabled": True, "contextWindow": 200,
                                    "compactRatio": 0.8, "keepRecentDialog": 12}}
        msgs = _dialog(60, chars=3000)
        out = _trim_request_messages(msgs, settings=st)
        assert len(out) <= 13  # 窗口 12 +（若有）保 user 回捞 1
        assert out is not msgs

    def test_explicit_recent_count_wins_over_budget(self):
        msgs = _dialog(40)
        out = _trim_request_messages(msgs, recent_count=5, settings=CM_ON)
        assert len(out) == 5  # 显式定窗优先，S320 既有钉不受影响

    def test_disabled_skips_budget(self):
        st = {"contextManagement": {"enabled": False, "contextWindow": 262144,
                                    "compactRatio": 0.8, "keepRecentDialog": 12}}
        out = _trim_request_messages(_dialog(40), settings=st)
        assert len(out) <= 13  # 关闭预算直通 → 固定 keepRecentDialog 窗


class TestMainRegistryFallback:
    """B1：审批执行路径副本表 miss → 主注册表单一事实源回退。"""

    def test_copy_table_missing_tool_runs_via_main_registry(self, monkeypatch):
        called = {}

        async def _fake(ext_id=""):
            called["ext_id"] = ext_id
            return "FAKE-OK running on port 9"

        async def _dd(*a, **k):
            return None

        fake = SimpleNamespace(_active_streams={}, _approval_exec_dedup=_dd,
                               _TOOL_HOOKS={"s330_main_only_tool": _fake})
        monkeypatch.setattr(AE, "_srv", lambda: fake)
        out = asyncio.run(AE.execute_approved_tool(
            "s330_main_only_tool", {"ext_id": "zz"}, "once"))
        assert "FAKE-OK" in out["result"]
        assert called.get("ext_id") == "zz"

    def test_unknown_tool_still_reports_not_found(self, monkeypatch):
        async def _dd(*a, **k):
            return None

        fake = SimpleNamespace(_active_streams={}, _approval_exec_dedup=_dd,
                               _TOOL_HOOKS={})
        monkeypatch.setattr(AE, "_srv", lambda: fake)
        out = asyncio.run(AE.execute_approved_tool("no_such_tool_s330", {}, "once"))
        assert "not found in backend registry" in out["result"]


class TestOneShotGrant:
    def test_grant_ttl_window_and_peer_isolation(self):
        ST.set_current_im_ctx("xmpp", "peerA")
        assert not ST.grant_active("t_s330")
        ST.grant_oneshot("xmpp", "peerA", "t_s330")
        assert ST.grant_active("t_s330")   # 批复后可行
        assert ST.grant_active("t_s330")   # peek 语义：同轮双门不互吃
        ST.set_current_im_ctx("xmpp", "peerB")
        assert not ST.grant_active("t_s330")  # 不串对端
        ST.grant_oneshot("xmpp", "peerA", "t_s330_exp", ttl=-1)
        ST.set_current_im_ctx("xmpp", "peerA")
        assert not ST.grant_active("t_s330_exp")  # 过期作废

    def test_hook_allows_granted_tool_without_second_approval(self, monkeypatch):
        class _Srv:
            def cli_permission_mode_for(self, settings):
                return "default"

        monkeypatch.setattr(TH, "_srv", lambda: _Srv())
        st = {"CLISettings": {"engine": "local", "cc_path": ""},
              "localEnvSettings": {"permissionMode": "default"}}
        tool = "start_extension_node_tool_local"
        ST.set_current_im_ctx("xmpp", "peerS330")
        assert TH._sensitive_approval(tool, {"ext_id": "x"}, st) is not None
        ST.grant_oneshot("xmpp", "peerS330", tool)
        assert TH._sensitive_approval(tool, {"ext_id": "x"}, st) is None
        # grant 只覆盖该工具：同 peer 其他敏感工具照拦
        assert TH._sensitive_approval("shell_tool_local", {"command": "ls"}, st) is not None


class TestB3Guidance:
    def test_start_success_string_anti_retry_guidance(self):
        src = (_ROOT / "py" / "agent_ext_tools.py").read_text(encoding="utf-8")
        assert "do not retry the start" in src
        assert "NOT a failure" in src or "NOT added to your index" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
