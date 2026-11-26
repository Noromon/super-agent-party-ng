# -*- coding: utf-8 -*-
"""M-3 structural ratchet (audit 09 item 7): giant functions may only shrink.

WHITELIST = module-level functions still >=300 lines. Entries may only be
REMOVED, never added; re-freezing an already-listed entry upward needs an
explicit S-number note (RA-25 errata, S66: the old "never add" wording went
stale when S65-P3 legitimately re-froze two entries on 2026-10-21).
tools_change_messages split (2026-10-20) moved 768 -> 205 lines into 11
module-level helpers, all verified here.
"""
import ast
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]

# whitelist retired 2026-10-20: server.py has no module-level function >=300
GIANT_WHITELIST = {
    # S65-P3：lifespan +19 行（引擎启动/停止钩子）、ws +5 行（save_settings 热更）越过 300 线，冻结现值，后续拆分时下调
    # S146（M5）：lifespan +2 行（外联 API 免 token 开关同步钩子），冻结现值
    "lifespan": 313,  # S280 ???????? +4
    # S71：ws +4 行（get_diary_im_targets 两行分支，重活已抽 _ws_diary_im_targets 模块级 helper），重冻结 302->306
    "websocket_endpoint": 306,
    # S132（WSL 引擎）：execute_tool_manually +3 行（wsl hooks/import）越过 300 线，冻结现值，后续拆分时下调
    # S150 拆出 execute_approved_tool（298 含端点体）、S153 路径门 grants 注入 +16 →
    # 314 重冻结（改名条目按 S66 勘误惯例带注）
    "execute_approved_tool": 314,
    # S296（RA-25 勘误惯例）：绕圈熔断接线 +3（observe 调用/注入循环）越线，
    # helper 化（_spiral_observe/_spiral_observe_ns）后重冻结现值，后续只准缩
    "_stream_tool_round": 303,
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
    "_stream_second_round",  # S163：工具循环轮（自纠重试）自 stream_generator 拆出
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


def _pb_funcs():
    # S300：提示词装配域迁至 py/prompt_builders.py，棘轮随迁（存在性+<300 语义不变）
    tree = ast.parse((_ROOT / "py" / "prompt_builders.py").read_text(encoding="utf-8-sig"))
    return [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


# S304（RA-25 勘误惯例）：S300-S304 域拆分后，函数行数为唯一事实源——
# 棘轮扫描面并入迁出模块（server re-export 仅 import 行）；新增上限见
# test_composition_root_line_budgets（composition root 总量锁 + 引擎单文件封顶）。

# S304：composition root 终态锁——server.py 为端点/lifespan/全局状态装配层，
# 只准缩不许涨（re-export import 行浮动在预算内）；引擎文件同法冻结现值。
FILE_LINE_BUDGETS = {
        "server.py": 3170,  # S327: +__UI_BUILD 指纹注入
    "py/stream_engine.py": 1750,   # S302 勘误：纯移动后现值 1725
    "py/stream_prep.py": 1475,
    "py/complete_engine.py": 1010,
    "py/prompt_builders.py": 935,
    "py/stream_response.py": 650,
    "py/vision_tools.py": 600,
    "py/tool_hooks.py": 590,
    "py/group_memory.py": 415,  # S320 勘误：_trim_request_messages 保 user+配对安全+留痕（现值 414）
    "py/approval_exec.py": 350,
}


def test_composition_root_line_budgets():
    for rel, cap in FILE_LINE_BUDGETS.items():
        n = len((_ROOT / rel).read_text(encoding="utf-8-sig").splitlines())
        assert n <= cap, "%s grew: %d -> %d lines (cap %d) -- 引擎域只准缩" % (rel, cap, n, cap)


def test_giant_function_whitelist_only_shrinks():
    found = {}
    nodes = list(_module_funcs())
    # S304：execute_approved_tool/stream_generator 等 >=300 行巨体随域拆分迁出，
    # 冻结值随迁扫描（体逐字未动；只准缩语义不变）
    for rel in ("py/stream_response.py", "py/approval_exec.py"):
        tree = ast.parse((_ROOT / rel).read_text(encoding="utf-8-sig"))
        nodes += [n for n in tree.body
                  if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for n in nodes:
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
    # S300：装配器本体迁 py/prompt_builders.py（server 侧仅存调用），存在性/尺寸钉改指新源
    pb = {n.name: n for n in _pb_funcs()}
    for h in TCM_HELPERS:
        assert h in pb, "helper %s missing" % h
        assert pb[h].end_lineno - pb[h].lineno + 1 < 300


def _tk_funcs():
    # S301：dispatch/钩子/审批预检域迁 py/tool_hooks.py，棘轮随迁（存在性+<300 语义不变）
    tree = ast.parse((_ROOT / "py" / "tool_hooks.py").read_text(encoding="utf-8-sig"))
    return [n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def test_dispatch_split_helpers_and_hooks_literal():
    tk = {n.name: n for n in _tk_funcs()}
    assert tk["dispatch_tool"].end_lineno - tk["dispatch_tool"].lineno + 1 < 300
    for h in DISPATCH_HELPERS:
        assert h in tk, "helper %s missing" % h
        assert tk[h].end_lineno - tk[h].lineno + 1 < 300
    # py/audit_tools.py parses this literal to audit hook-table consistency
    # S301：钩子表构建函数已迁出，字面量钉改扫 py/tool_hooks.py（执行侧拷贝仍在 server，S304 随迁）
    src = (_ROOT / "py" / "tool_hooks.py").read_text(encoding="utf-8-sig")
    assert "_TOOL_HOOKS = {" in src or "_srv()._TOOL_HOOKS = {" in src


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
    # S303：complete 引擎域迁 py/complete_engine.py，存在性/尺寸钉合并扫描（体逐字未动）
    for path in (_ROOT / "py" / "complete_engine.py",):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault(n.name, n)
    assert funcs["_generate_complete_impl"].end_lineno - funcs["_generate_complete_impl"].lineno + 1 < 300
    for h in COMPLETE_HELPERS:
        assert h in funcs, "helper %s missing" % h
        assert funcs[h].end_lineno - funcs[h].lineno + 1 < 300


def test_stream_split_helpers_present_and_small():
    # M-3 batch 4: stream engine fully split -- shell, the (now module-level)
    # stream_generator and every delegated block stay under 300 lines.
    # S302a/S304：helper 域与响应装配层已迁出，存在性/尺寸钉合并扫描（体逐字未动）
    funcs = {n.name: n for n in _module_funcs()}
    for path in (_ROOT / "py" / "stream_prep.py", _ROOT / "py" / "stream_engine.py",
                 _ROOT / "py" / "stream_response.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs.setdefault(n.name, n)
    assert funcs["generate_stream_response"].end_lineno - funcs["generate_stream_response"].lineno + 1 < 300
    for h in STREAM_HELPERS:
        assert h in funcs, "helper %s missing" % h
        # S296：GIANT_WHITELIST 重冻结条目按冻结值封顶（只准缩，不允许新增）
        cap = GIANT_WHITELIST.get(h, 299)
        assert funcs[h].end_lineno - funcs[h].lineno + 1 <= cap
