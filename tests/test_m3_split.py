# -*- coding: utf-8 -*-
"""M-3 structural ratchet (audit 09 item 7): giant functions may only shrink.

WHITELIST = module-level functions still >=300 lines. Each M-3 batch must
REMOVE an entry (never add). tools_change_messages split (2026-10-20) moved
768 -> 205 lines into 11 module-level helpers, all verified here.
"""
import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# remaining M-3 targets, (name -> approximate line count at freeze time)
GIANT_WHITELIST = {
    "generate_stream_response": 2206,   # includes nested stream_generator
}

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
    "_dispatch_external_tool",
    "_dispatch_task_center_tool",
    "_dispatch_unknown_tool",
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


def test_complete_split_helpers_present_and_small():
    funcs = {n.name: n for n in _module_funcs()}
    assert funcs["_generate_complete_impl"].end_lineno - funcs["_generate_complete_impl"].lineno + 1 < 300
    for h in COMPLETE_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300
