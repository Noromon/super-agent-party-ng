# py/context_manager.py
# 上下文管理唯一权威点：token 估算 / L1 工具结果修剪 / tool 配对 sanitizer / 任务模式检测 / L2 LLM 摘要压缩。
# 设计前提：历史所有权在前端（全量重放），压缩结果以"摘要消息 + 近期原文"形式返回，由前端落账。


import logging
import copy
import json

from py import llm_gate

SUMMARY_HEADER = "【对话摘要·已压缩】"
SUMMARY_FOOTER = "（以上为本会话早前内容的压缩摘要，视为已发生且已确认的事实；不要重做其中已完成的动作，直接基于它继续当前任务。）"
PRUNED_STUB_FMT = "[pruned: {name}, {n} chars — 如需该结果请重新运行对应工具]"

_TOOL_SUMMARY_LIMIT = 300
_ARG_SUMMARY_LIMIT = 160
_MSG_SUMMARY_LIMIT = 700

_agent_summary_prompt = """You are a conversation compactor. Summarize the conversation segment below into a compact, information-dense checkpoint that lets another agent continue the work WITHOUT re-doing anything.

Required structure (in the conversation's own language):
## 原始任务 / Original task
## 已完成 / Completed (steps, files touched with paths, verified facts)
## 进行中 / In progress (what was being done when compacted)
## 未完成 / TODO
## 下一步 / Next step (concrete)
## 关键事实 / Key facts (paths, commands, config values, IDs — keep verbatim)
## 已知错误与坑 / Known errors & gotchas

Rules:
- Keep file paths, commands, identifiers and numbers EXACTLY.
- Never invent facts not present in the transcript.
- Be dense; drop politeness, filler and failed-attempt chatter (but keep their root causes).
"""

_roleplay_summary_prompt = """You are a roleplay chronicle keeper. Compact the roleplay/chat segment below into a chronicle that preserves continuity of story, relationships and promises. Output in the conversation's own language.

Required structure:
## 情节时间线 / Timeline (beats in order, one line each)
## 人物与关系 / Characters & relationship state
## 情感与语气进展 / Emotional & tone progression (current mood between parties)
## 双方约定与承诺 / Promises & commitments made (keep verbatim quotes where important)
## 未兑现话题与悬念 / Unresolved topics & hooks
## 场景/道具/世界观要点 / Scene, props, world facts

Rules:
- Preserve character names, coined terms, inside jokes and quoted lines EXACTLY.
- Do not editorialize or add psychological analysis beyond what happened.
"""


def _role(m):
    if isinstance(m, dict):
        return m.get("role")
    return getattr(m, "role", None)


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", "") or "")
        return "\n".join(p for p in parts if p)
    return "" if content is None else str(content)


def _tcs(m):
    if _role(m) != "assistant":
        return None
    tcs = m.get("tool_calls") if isinstance(m, dict) else getattr(m, "tool_calls", None)
    return tcs or None


# ---------------------------------------------------------------- tokens

_tiktoken_enc = None
_tiktoken_tried = False


def _get_encoder():
    global _tiktoken_enc, _tiktoken_tried
    if _tiktoken_tried:
        return _tiktoken_enc
    _tiktoken_tried = True
    try:
        import tiktoken
        try:
            _tiktoken_enc = tiktoken.get_encoding("o200k_base")
        except Exception:
            _tiktoken_enc = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _tiktoken_enc = None
    return _tiktoken_enc


def estimate_text_tokens(text: str) -> int:
    if not text:
        return 0
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text))
        except Exception:
            pass
    cjk = 0
    other = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef":
            cjk += 1
        else:
            other += 1
    return cjk + max(1, other // 4)


def estimate_tokens(messages, tools=None) -> int:
    total = 0
    for m in messages or []:
        total += 8
        total += estimate_text_tokens(_content_text(m.get("content") if isinstance(m, dict) else getattr(m, "content", None)))
        for tc in _tcs(m) or []:
            fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
            if fn:
                total += estimate_text_tokens((fn.get("name", "") if isinstance(fn, dict) else getattr(fn, "name", "")) +
                                             (fn.get("arguments", "") if isinstance(fn, dict) else getattr(fn, "arguments", "")))
    if tools:
        try:
            total += estimate_text_tokens(json.dumps(tools, ensure_ascii=False)) // 2
        except Exception:
            pass
    return total


# ---------------------------------------------------------------- L1 prune


def prune_tool_results(messages, keep_recent_tools: int = 4):
    """把最近 keep_recent_tools 条之外的 tool 消息内容替换为存根。返回 (新messages, 修剪条数)。"""
    msgs = list(messages)
    tool_idx = [i for i, m in enumerate(msgs) if _role(m) == "tool"]
    to_prune = tool_idx[:-keep_recent_tools] if keep_recent_tools > 0 else tool_idx
    pruned = 0
    for i in to_prune:
        m = msgs[i]
        if not isinstance(m, dict):
            continue
        text = _content_text(m.get("content"))
        stub = PRUNED_STUB_FMT.format(name=m.get("name") or "tool", n=len(text))
        if len(text) > len(stub):
            m = dict(m)
            m["content"] = stub
            msgs[i] = m
            pruned += 1
    return msgs, pruned


# ---------------------------------------------------------------- sanitizer (shared)


def sanitize_tool_pairs(messages):
    """tool 调用与结果配对合法性收敛：丢弃孤立 tool 结果；末尾悬空 tool_calls 清理。"""
    final = []
    pending = set()
    for msg in messages:
        role = _role(msg)
        if role == "tool":
            t_id = msg.get("tool_call_id") if isinstance(msg, dict) else getattr(msg, "tool_call_id", None)
            if t_id and t_id in pending:
                final.append(msg)
                pending.discard(t_id)
            else:
                logging.getLogger("app").info(f"[Sanitizer] 丢弃孤立的 tool 消息: {t_id}")
                continue
        elif role == "assistant":
            tcs = _tcs(msg)
            if tcs:
                for tc in tcs:
                    tid = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tid:
                        pending.add(tid)
            final.append(msg)
        else:
            final.append(msg)

    while final:
        last = final[-1]
        tcs = _tcs(last)
        if tcs and any((tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)) in pending for tc in tcs):
            content = _content_text(last.get("content") if isinstance(last, dict) else getattr(last, "content", None))
            if content.strip():
                logging.getLogger("app").info("[Sanitizer] 清除末尾悬空 tool_calls（保留文本）")
                new_last = dict(last) if isinstance(last, dict) else last
                if isinstance(new_last, dict):
                    new_last.pop("tool_calls", None)
                    final[-1] = new_last
                    break
            else:
                logging.getLogger("app").info("[Sanitizer] 弹出末尾无内容的孤立 tool_call 发起消息")
                final.pop()
                continue
        else:
            break
    return final


# ---------------------------------------------------------------- mode detect


def detect_task_mode(messages) -> str:
    """近窗（最后14条对话消息）存在 tool 活动 → agent，否则 roleplay。"""
    dialog = [m for m in messages or [] if _role(m) not in ("system",)]
    for m in dialog[-14:]:
        if _role(m) == "tool" or _tcs(m):
            return "agent"
    return "roleplay"


# ---------------------------------------------------------------- L2 compact


def _render_transcript(dialog_msgs) -> str:
    lines = []
    for m in dialog_msgs:
        role = _role(m)
        if role == "assistant":
            text = _content_text(m.get("content") if isinstance(m, dict) else getattr(m, "content", None))
            if text.strip():
                lines.append(f"assistant: {text[:_MSG_SUMMARY_LIMIT]}")
            for tc in _tcs(m) or []:
                fn = tc.get("function") if isinstance(tc, dict) else getattr(tc, "function", None)
                if fn:
                    name = fn.get("name", "") if isinstance(fn, dict) else getattr(fn, "name", "")
                    args = (fn.get("arguments", "") if isinstance(fn, dict) else getattr(fn, "arguments", "")) or ""
                    lines.append(f"assistant -> call {name}({args[:_ARG_SUMMARY_LIMIT]})")
        elif role == "tool":
            text = _content_text(m.get("content") if isinstance(m, dict) else getattr(m, "content", None))
            lines.append(f"tool_result: {text[:_TOOL_SUMMARY_LIMIT]}")
        elif role == "user":
            text = _content_text(m.get("content") if isinstance(m, dict) else getattr(m, "content", None))
            if text.strip():
                lines.append(f"user: {text[:_MSG_SUMMARY_LIMIT]}")
        elif role == "assistant":
            pass
    return "\n".join(lines)


def _split_for_compaction(messages, keep_recent_dialog: int):
    sys_msgs = [m for m in messages if _role(m) == "system"]
    dialog = [m for m in messages if _role(m) != "system"]
    keep_recent_dialog = max(4, keep_recent_dialog)
    if len(dialog) <= keep_recent_dialog + 2:
        return None
    # 避免把 assistant(tool_calls) 与 tool 结果对切开：从切点向前找到安全边界
    split = len(dialog) - keep_recent_dialog
    while split > 1:
        prev = dialog[split - 1]
        cur = dialog[split]
        if _tcs(prev) and _role(cur) == "tool":
            split -= 1
            continue
        if _role(prev) == "assistant" and _role(cur) == "user":
            break
        if _role(prev) == "tool" and _role(cur) in ("assistant", "user"):
            break
        split -= 1
    if split <= 1:
        return None
    return sys_msgs, dialog[:split], dialog[split:]


async def compact_messages(client, model, messages, task_mode=None, focus=None,
                          keep_recent_dialog: int = 12, extra_params=None,
                          reasoner_client=None, reasoner_model=None):
    """L2 摘要压缩。返回 {messages, summary, task_mode, compacted_count} 或 None（无需/无法压缩）。"""
    split = _split_for_compaction(messages, keep_recent_dialog)
    if split is None:
        return None
    sys_msgs, old_dialog, recent_dialog = split

    task_mode = task_mode or detect_task_mode(messages)
    transcript = _render_transcript(old_dialog)
    if not transcript.strip():
        return None
    sys_prompt = _agent_summary_prompt if task_mode == "agent" else _roleplay_summary_prompt
    if focus:
        sys_prompt += f"\nExtra focus for this compaction (weigh these aspects MORE, but still cover all sections): {focus}\n"

    use_client = reasoner_client if (reasoner_client is not None and reasoner_model) else client
    use_model = reasoner_model if (reasoner_client is not None and reasoner_model) else model
    kwargs = {"model": use_model,
              "messages": [
                  {"role": "system", "content": sys_prompt},
                  {"role": "user", "content": f"Conversation segment to compact:\n\n{transcript}"},
              ],
              "stream": False}
    if extra_params:
        kwargs["extra_body"] = extra_params
    try:
        # T-5: compact 摘要调用入闸（/api/compact 独立调用场景是盲区；stream 内重入安全）
        async with llm_gate.gate():
            resp = await use_client.chat.completions.create(**kwargs)
        summary = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logging.getLogger("app").info(f"[Compact] 摘要调用失败: {e}")
        return None
    if not summary:
        return None

    summary_msg = {"role": "user", "content": f"{SUMMARY_HEADER}\n{summary}\n{SUMMARY_FOOTER}",
                   "reasoning_content": ""}
    new_messages = sys_msgs + [summary_msg] + recent_dialog
    new_messages = sanitize_tool_pairs(new_messages)
    return {"messages": new_messages, "summary": summary, "task_mode": task_mode,
            "compacted_count": len(old_dialog)}


# ---------------------------------------------------------------- settings helper


def get_context_settings(settings):
    cm = settings.get("contextManagement", {}) or {}
    return {
        "enabled": bool(cm.get("enabled", True)),
        "context_window": int(cm.get("contextWindow", 32000) or 32000),
        "compact_ratio": float(cm.get("compactRatio", 0.8) or 0.8),
        "keep_recent_tools": int(cm.get("keepRecentTools", 4) or 4),
        "keep_recent_dialog": int(cm.get("keepRecentDialog", 12) or 12),
        "auto_agent_compact": bool(cm.get("autoAgentCompact", True)),
    }
