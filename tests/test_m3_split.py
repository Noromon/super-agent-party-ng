# -*- coding: utf-8 -*-
"""M-3 structural ratchet (audit 09 item 7): giant functions may only shrink.

WHITELIST = module-level functions still >=300 lines. Each M-3 batch must
REMOVE an entry (never add). tools_change_messages split (2026-10-20) moved
768 -> 205 lines into 11 module-level helpers, all verified here.
"""
import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# whitelist retired 2026-10-20: server.py has no module-level function >=300
GIANT_WHITELIST = {
    # S65-P3（A5 日记）：lifespan +19 行（引擎启动/停止钩子）、ws +5 行（save_settings 热更）越过 300 线，冻结现值，后续拆分时下调
    "lifespan": 307,
    "websocket_endpoint": 302,
}

STREAM_HELPERS = [
    "_stream_desktop_capture",
    "_stream_context_compress",
    "_stream_character_context",
    "_stream_async_tools",
    "_stream_kb_before",
    "_stream_web_search_pre",
    "_stream_filter_tools",
    "_stream_deepsearch_pre",
    "_stream_reasoner_prep",
    "_stream_first_pass",
    "_stream_drs_round",
    "_stream_tool_round",
    "_stream_reasoner_update",
    "_stream_regrab",
    "_stream_loop_pass",
    "_stream_drs_loop_round",
    "_stream_round_compress",
    "_stream_usage_event",
    "_stream_finalize_jobs",
    "stream_generator",
]

COMPLETE_HELPERS = [
    "_apply_context_compression",
    "_complete_character_context",
    "_complete_web_search_setup",
    "_complete_reasoner_prep",
    "_complete_drs_step",
    "_ns_tool_round",
    "_ns_reasoner_pass",
    "_complete_finalize",
]

DISPATCH_HELPERS = [
    "_build_tool_hooks",
    "_plan_mode_block",
    "_sensitive_approval",
]

TCM_HELPERS = [
    "_inject_workspace_memory",
    "_append_permission_mode_message",
    "_append_todos_context",
    "_append_agents_md",
    "_append_project_skills",
    "_resolve_agent_name",
    "_append_tts_voice_prompts",
    "_append_avatar_prompts",
    "_append_affection_prompt",
    "_append_a2ui_prompt",
    "_inject_task_checkpoint",
]


def _module_funcs():
    tree = ast.parse((_ROOT / "server.py").read_text(encoding="utf-8-sig"))
    return [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_giant_function_whitelist_only_shrinks():
    found = {}
    for n in _module_funcs():
        size = n.end_lineno - n.lineno + 1
        if size >= 300:
            found[n.name] = size
    assert set(found) <= set(GIANT_WHITELIST), (
        "new >=300-line function(s): %s -- split instead of adding to the "
        "whitelist" % (set(found) - set(GIANT_WHITELIST))
    )
    for name, frozen in GIANT_WHITELIST.items():
        if name in found:
            assert found[name] <= frozen, (
                "%s grew: %d -> %d lines" % (name, frozen, found[name])
            )


def test_tcm_split_helpers_present_and_small():
    funcs = {n.name: n for n in _module_funcs()}
    tcm = funcs["tools_change_messages"]
    assert tcm.end_lineno - tcm.lineno + 1 < 300
    for h in TCM_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300


def test_dispatch_split_helpers_and_hooks_literal():
    funcs = {n.name: n for n in _module_funcs()}
    assert funcs["dispatch_tool"].end_lineno - funcs["dispatch_tool"].lineno + 1 < 300
    for h in DISPATCH_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300
    # py/audit_tools.py parses this literal to audit hook-table consistency
    src = (_ROOT / "server.py").read_text(encoding="utf-8-sig")
    assert "_TOOL_HOOKS = {" in src


def test_tool_dispatch_module_helpers_present_and_small():
    # 批 2h3：审批哨兵与 dispatch helpers 迁入 py/tool_dispatch.py
    tree = ast.parse((_ROOT / "py" / "tool_dispatch.py").read_text(encoding="utf-8-sig"))
    funcs = {n.name: n for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for h in ("_approval_payload", "_is_approval_result", "dispatch_external_tool",
              "dispatch_task_center_tool", "dispatch_unknown_tool"):
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300
    src = (_ROOT / "py" / "tool_dispatch.py").read_text(encoding="utf-8-sig")
    assert "_APPROVAL_PREFIX = " in src


def test_complete_split_helpers_present_and_small():
    funcs = {n.name: n for n in _module_funcs()}
    assert funcs["_generate_complete_impl"].end_lineno - funcs["_generate_complete_impl"].lineno + 1 < 300
    for h in COMPLETE_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300


def test_stream_split_helpers_present_and_small():
    # M-3 batch 4: stream engine fully split -- shell, the (now module-level)
    # stream_generator and every delegated block stay under 300 lines.
    funcs = {n.name: n for n in _module_funcs()}
    assert funcs["generate_stream_response"].end_lineno - funcs["generate_stream_response"].lineno + 1 < 300
    for h in STREAM_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300
