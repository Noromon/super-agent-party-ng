# -*- coding: utf-8 -*-
"""S221: plan 模式对齐 opencode——声明层隐藏 + 拦截集再平衡 + 结构化计划契约。

三决策：①键鼠执行类隐藏+拦截（截图只读保留）②todo_write 移出拦截（plan 允许
计划可视化）③MCP/扩展不过滤靠提示软引导。本测试覆盖：拦截集成员、三引擎 plan
工具集=只读+todo、声明尾滤纯函数语义（非 plan 同引用零漂移）、build_llm_tools
接线与 _plan_mode_block 兜底 source-pin、契约关键句。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # S59 shim 坑：库 py 抢占时清掉再导包

from py.cli_tool import (  # noqa: E402
    get_local_tools_for_permission,
    get_tools_for_permission,
    get_wsl_tools_for_permission,
)
from py.tool_assembly import _plan_hide_blocked_tools  # noqa: E402
from py.tool_registry import COMPUTER_USE_EXEC_TOOLS, PLAN_BLOCKED_TOOLS  # noqa: E402

_SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8-sig")
_ASSEMBLY_SRC = (ROOT / "py" / "tool_assembly.py").read_text(encoding="utf-8-sig")


def _names(tools):
    return {t.get("function", {}).get("name") for t in tools}


def _fake(name):
    return {"type": "function", "function": {"name": name, "description": "x"}}


class TestBlockedSet:
    def test_computer_use_exec_blocked(self):
        assert len(COMPUTER_USE_EXEC_TOOLS) == 11
        for n in ("mouse_move", "mouse_click", "mouse_double_click", "mouse_drag",
                  "mouse_hold", "mouse_scroll", "copy_to_input_box", "keyboard_press",
                  "keyboard_sequence", "keyboard_hotkey", "keyboard_hold"):
            assert n in PLAN_BLOCKED_TOOLS, n

    def test_readonly_kept_and_old_entries_survive(self):
        assert "screenshot" not in PLAN_BLOCKED_TOOLS
        assert "wait" not in PLAN_BLOCKED_TOOLS
        # 既有成员不因再平衡丢失
        assert "edit_file_tool" in PLAN_BLOCKED_TOOLS
        assert "shell_tool_local" in PLAN_BLOCKED_TOOLS
        assert "acpx_agent" in PLAN_BLOCKED_TOOLS
        assert "update_workspace_settings" in PLAN_BLOCKED_TOOLS

    def test_todo_allowed_in_plan(self):
        assert "todo_write_tool" not in PLAN_BLOCKED_TOOLS
        assert "todo_write_tool_local" not in PLAN_BLOCKED_TOOLS


class TestEnginePlanSets:
    def test_plan_sets_include_todo_only_from_edit(self):
        # registry 键≠声明名：todo_write→todo_write_tool；wsl 声明同用 _local 后缀名
        plan_ds = _names(get_tools_for_permission("plan"))
        plan_local = _names(get_local_tools_for_permission("plan"))
        plan_wsl = _names(get_wsl_tools_for_permission("plan"))
        assert "todo_write_tool" in plan_ds
        assert "edit_file_tool" not in plan_ds and "docker_sandbox" not in plan_ds
        assert "todo_write_tool_local" in plan_local
        assert "edit_file_tool_local" not in plan_local and "shell_tool_local" not in plan_local
        assert "todo_write_tool_local" in plan_wsl
        assert "edit_file_tool_local" not in plan_wsl

    def test_non_plan_untouched(self):
        # default 全量 / auto-approve 编辑组：既有语义零变化
        full = _names(get_tools_for_permission("default"))
        aa = _names(get_tools_for_permission("auto-approve"))
        assert {"edit_file_tool", "edit_file_patch_tool", "todo_write_tool",
                "docker_sandbox"} <= full
        assert "docker_sandbox" not in aa and "edit_file_tool" in aa


class TestPlanHidePure:
    def test_non_plan_same_reference_zero_drift(self):
        tools = [_fake("edit_file_tool"), _fake("read_file")]
        assert _plan_hide_blocked_tools(tools, False) is tools

    def test_plan_hides_blocked_keeps_rest(self):
        tools = [_fake("edit_file_tool"), _fake("mouse_click"), _fake("read_file"),
                 _fake("todo_write"), _fake("screenshot"), _fake("custom_http_x")]
        kept = _names(_plan_hide_blocked_tools(tools, True))
        assert kept == {"read_file", "todo_write", "screenshot", "custom_http_x"}

    def test_original_list_not_mutated(self):
        tools = [_fake("edit_file_tool"), _fake("read_file")]
        _plan_hide_blocked_tools(tools, True)
        assert len(tools) == 2  # 调用方（request.tools 引用）不被就地改写


class TestWiringPins:
    def test_assembly_calls_tail_filter(self):
        assert 'tk["cli_permission_mode_for"](settings) == "plan"' in _ASSEMBLY_SRC
        assert "_plan_hide_blocked_tools(tools, _is_plan)" in _ASSEMBLY_SRC

    def test_dispatch_backstop_still_blocks_full_set(self):
        # 兜底不变：dispatch 仍按同一单源集合拦截（声明隐藏为前置，拦截为双保险）
        assert "if tool_name in PLAN_BLOCKED_TOOLS:" in _SERVER_SRC
        assert "请把拟执行的改动写进计划正文" in _SERVER_SRC


class TestPlanContract:
    def test_plan_section_guides_prose_plan(self):
        from py.agent_prompt import build_agent_core_prompt
        sec = build_agent_core_prompt("plan")
        assert "NOT in your tool list" in sec
        assert "DETAILED plan" in sec
        assert "do not probe for them" in sec
        assert "WAIT for the user" in sec
        assert "Never pretend to have executed" in sec
        assert "hidden side effects" in sec  # MCP 软引导（决策③）

    def test_other_modes_unaffected(self):
        from py.agent_prompt import build_agent_core_prompt
        assert "PLAN mode is ACTIVE" not in build_agent_core_prompt("default")
        assert "PLAN mode is ACTIVE" not in build_agent_core_prompt("yolo")
        assert "File-edit tools execute directly" in build_agent_core_prompt("auto-approve")
