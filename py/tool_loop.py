# -*- coding: utf-8 -*-
"""Shared tool-round constants (M3b lite: anti-drift single source).

The stream and complete engines historically carried 2 copies each of the
error/abort wordings; parity is pinned by tests/test_engine_parity.py while
this module removes the duplication itself.
"""

NONE_TEXT = ("[Error] 该工具调用未获得可用结果（工具未注册或不可用），"
             "请改用工具列表中的真实工具。")
SKIPPED_TEXT = "[Skipped] 未执行：同一轮中前面的工具调用正在等待用户审批，或流程被中断。"
TOOL_EXC_TMPL = "[Tool Execution Error] {type}: {exc}"


def arg_error_text(reason):
    return f"[Argument Error] {reason}，请使用合法的 JSON 参数重试该工具调用。"


def append_missing_results(messages, assistant_tool_calls, acked_ids):
    """Close tool_calls/tool pairing for calls that never executed."""
    n = 0
    for meta in assistant_tool_calls:
        if meta["id"] not in acked_ids:
            messages.append({
                "role": "tool",
                "tool_call_id": meta["id"],
                "name": meta["function"]["name"],
                "content": SKIPPED_TEXT,
            })
            n += 1
    return n
