# -*- coding: utf-8 -*-
"""Single source of truth for LLM-visible chain construction (M1 ownership sink).

Extracted verbatim from the three copy-pasted Sanitizer blocks in server.py
(stream round-1 / stream tool-round / complete engine). Behavior preserved,
plus one deliberate defense line: assistant entries with blank content and no
tool_calls are dropped (S10/C-2 ghost-entry family).
"""


def _get(msg, key):
    return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)


def _set(msg, key, value):
    if isinstance(msg, dict):
        msg[key] = value
    else:
        setattr(msg, key, value)


def _is_blank(content):
    if content is None:
        return True
    if isinstance(content, str):
        return not content.strip()
    if isinstance(content, (list, tuple)):
        return len(content) == 0
    return False


def sanitize_tool_chains(chat_messages, log=None):
    """Drop orphan tool messages / blank assistant entries; close dangling tool_calls.

    Input/output are OpenAI-shaped message entries (dict or object both accepted).
    """
    def _log(msg_text):
        if log:
            log(msg_text)

    final_messages = []
    pending_tool_call_ids = set()

    for msg in chat_messages:
        role = _get(msg, "role")

        if role == "tool":
            t_id = _get(msg, "tool_call_id")
            # 核心校验：如果这个 tool 消息不在我们记录的待响应 ID 列表中，直接丢弃
            if t_id and t_id in pending_tool_call_ids:
                final_messages.append(msg)
                pending_tool_call_ids.remove(t_id)
            else:
                _log(f"[Sanitizer] 丢弃孤立的 tool 消息: {t_id}")
                continue

        elif role == "assistant":
            tcs = _get(msg, "tool_calls")
            if tcs:
                current_tcs_ids = {tc.get("id") if isinstance(tc, dict) else tc.id for tc in tcs}
                final_messages.append(msg)
                for tid in current_tcs_ids:
                    pending_tool_call_ids.add(tid)
            elif _is_blank(_get(msg, "content")):
                # 空 assistant 幽灵项：既无 tool_calls 又无正文，LLM 链上只会污染上下文
                _log("[Sanitizer] 丢弃空 assistant 幽灵项")
                continue
            else:
                final_messages.append(msg)

        else:
            final_messages.append(msg)

    # 最终反向检查：末尾带 tool_calls 但未闭合的 assistant，抹除 tool_calls 保留文本，
    # 无文本则整条弹出（防 API 报错）
    while final_messages:
        last_msg = final_messages[-1]
        tcs = _get(last_msg, "tool_calls")
        if tcs and any((_get(tc, "id") in pending_tool_call_ids) for tc in tcs):
            content = _get(last_msg, "content")
            if content:
                _set(last_msg, "tool_calls", None)
                _log("[Sanitizer] 抹除末尾未闭合的 tool_calls")
                break
            else:
                final_messages.pop()
                _log("[Sanitizer] 弹出末尾无内容的孤立 tool_call 发起消息")
        else:
            break

    return final_messages
