# -*- coding: utf-8 -*-
"""S300：群共享记忆域（自 server.py 逐字搬移）。

COVS（跨会话共享记忆）读改写、按 chat/group 失效、LLM 抽取与 upsert、
注入端 group-memory prompt 装配。mem0 任务侧调用（_extract/_upsert）——
llm_gate 防饿死纪律：本域永不在闸内（test_engine_parity 钉）。

from __future__ import annotations：_apply_group_memory_context 的 ChatRequest 注解
在 server 定义，注解按字符串惰性化以避免循环 import（运行期零影响）。
process_extra_params 属工具域（S301 处置），经包装惰性取 server 真源。
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
import copy
from typing import TYPE_CHECKING, Dict, List, Optional, Union

if TYPE_CHECKING:  # S300：注解引用 server 侧模型，仅静态检查期导入（运行期零依赖）
    from server import ChatRequest

from py.get_setting import COVS_PATH, load_covs
from py.llm_recovery import acreate
from py.msg_utils import _extract_text_content, content_append
from py.token_guard import neutralize as _neutralize

logger = logging.getLogger("app")


def process_extra_params(*a, **k):
    """S300：工具域参数清洗的惰性真源（S301 将随工具域迁出，此处不改行为）。"""
    from py.srv_ref import srv as _srv
    return _srv().process_extra_params(*a, **k)


GROUP_MEMORY_TYPES = {"fact", "decision", "preference", "todo", "constraint", "glossary"}
GROUP_MEMORY_DONE_HINTS = ("完成", "已完成", "done", "resolved", "fixed", "closed")

def _memory_tokens(text: str) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r'[\u4e00-\u9fff]{1,6}|[a-zA-Z0-9_]{2,}', text.lower())
    return set(tokens)

def _normalize_memory_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip().lower())

def _normalize_entity_id(value: Optional[Union[str, int, float]]) -> str:
    if value is None:
        return ""
    return str(value).strip()

def _merge_group_memories(*memory_lists: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for memory_list in memory_lists:
        for item in memory_list or []:
            if not isinstance(item, dict):
                continue
            memory_type = str(item.get("memory_type", "")).strip().lower()
            summary = str(item.get("summary", "")).strip()
            content = str(item.get("content", "")).strip()
            if memory_type not in GROUP_MEMORY_TYPES or not summary or not content:
                continue
            dedupe_key = (
                memory_type,
                _normalize_memory_text(summary),
                _normalize_memory_text(content),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append({
                "memory_type": memory_type,
                "summary": summary,
                "content": content,
                "importance": max(0.0, min(1.0, float(item.get("importance", 0.5) or 0.5))),
            })
    return merged

async def _load_group_map() -> dict:
    covs = await load_covs()
    groups = covs.get("conversationGroups", []) or []
    group_map = {"default": {"id": "default", "name": "Ungrouped", "memoryConfig": {}}}
    for group in groups:
        if group and group.get("id"):
            group_map[group["id"]] = group
    return group_map

async def _fetch_group_memories(group_id: str, query_text: str, top_k: int = 6) -> list[dict]:
    if not group_id:
        return []
    query_tokens = _memory_tokens(query_text)
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM group_memory
            WHERE group_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            """,
            (group_id,),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]

    def score_memory(item: dict) -> float:
        text = f"{item.get('summary', '')}\n{item.get('content', '')}"
        overlap = len(query_tokens & _memory_tokens(text))
        importance = float(item.get("importance") or 0)
        recency = float(item.get("updated_at") or 0) / 1_000_000_000_000
        return overlap * 5 + importance * 2 + recency

    ranked = sorted(rows, key=score_memory, reverse=True)
    selected = ranked[:top_k]
    if selected:
        now_ts = int(time.time() * 1000)
        import aiosqlite
        async with aiosqlite.connect(COVS_PATH) as db:
            await db.executemany(
                "UPDATE group_memory SET last_used_at = ? WHERE id = ?",
                [(now_ts, item["id"]) for item in selected],
            )
            await db.commit()
    return selected

def _build_group_memory_prompt(group: dict, memories: list[dict]) -> str:
    if not memories:
        return ""
    header = [
        f"当前对话分组: {group.get('name') or group.get('id')}",
        "以下是仅限当前分组可用的长期记忆，请只在相关时使用，不要臆测或扩展未确认的信息。",
        "如果记忆中包含具体值，请优先直接复述具体值，不要用“见记忆条目”或占位说明代替：",
    ]
    lines = []
    for idx, memory in enumerate(memories, 1):
        summary = _neutralize(str(memory.get('summary') or '').strip(), store="group-recall")
        content = _neutralize(str(memory.get('content') or '').strip(), store="group-recall")
        memory_type = memory.get('memory_type', 'fact')
        if summary and content and summary != content:
            lines.append(f"{idx}. [{memory_type}] 摘要: {summary}")
            lines.append(f"   具体内容: {content}")
        else:
            lines.append(f"{idx}. [{memory_type}] {content or summary}")
    return "\n".join(header + lines)

def _trim_request_messages(messages: List[Dict], recent_count: int = None,
                           settings: dict = None) -> List[Dict]:
    system_messages = [copy.deepcopy(m) for m in messages if m.get("role") == "system"]
    dialog_messages = [copy.deepcopy(m) for m in messages if m.get("role") != "system"]
    # S330（对齐 opencode）：token 预算内全量直通——本项目已有 context_manager
    # 压缩/摘要体系，但本函数自 9fc4387f（v0.3.x 群聊盲切12）起坐落其上游，
    # 980→12 硬截把压缩体系整段截胡=失忆级裁剪（实测 est 12k/窗口 262k）。
    # 本函数退居预算超限时的硬保险；显式 recent_count（测试/调用方）仍走定窗。
    if recent_count is None:
        from py.context_manager import estimate_tokens, get_context_settings
        cs = get_context_settings(settings or {})
        recent_count = cs["keep_recent_dialog"]
        if cs["enabled"]:
            budget = max(1024, int(cs["context_window"] * cs["compact_ratio"]))
            est = estimate_tokens(system_messages + dialog_messages)
            if est <= budget:
                if len(dialog_messages) > 50:
                    logger.info("[MsgTrim] S330 预算内全量直通：%d 条 est=%d/budget=%d",
                                len(dialog_messages), est, budget)
                return copy.deepcopy(messages)
    if len(dialog_messages) <= recent_count:
        return system_messages + dialog_messages
    # S320（kerobros 审批续跑 500 事故）：旧实现盲切后 N 条——续跑快照的真实 user
    # 恰在窗口外被静默剪掉，严格 chat 模板倒扫无 user 直接 raise（No user query
    # found）。防线：切点配对安全（不落在 assistant(tool_calls)→tool 对中间）；
    # 窗口内无真实 user 时把 dialog 中最后一条真实 user 按原序并入；剪了必留痕。
    from py.task_anchor import is_genuine_user_msg
    cut = len(dialog_messages) - recent_count
    while cut > 0 and dialog_messages[cut].get("role") == "tool":
        cut -= 1
    if cut > 0:  # 并行工具对：窗口头部 tool 的发起 assistant(tool_calls) 一并带上
        _prev = dialog_messages[cut - 1]
        _tcs = _prev.get("tool_calls") if _prev.get("role") == "assistant" else None
        if _tcs:
            _ids = {tc.get("id") for tc in _tcs if isinstance(tc, dict)}
            if any(m.get("role") == "tool" and m.get("tool_call_id") in _ids
                   for m in dialog_messages[cut:]):
                cut -= 1
    kept = dialog_messages[cut:]
    if not any(is_genuine_user_msg(m) for m in kept):
        for _i in range(cut - 1, -1, -1):
            if is_genuine_user_msg(dialog_messages[_i]):
                logger.warning("[MsgTrim] S320 历史窗口无真实 user，保留 idx=%d 原文防模板拒绝", _i)
                kept = [dialog_messages[_i]] + kept
                break
    if cut > 0:
        logger.info("[MsgTrim] 历史裁剪 %d→%d 条（recent_count=%d，配对安全+保user）",
                    len(dialog_messages), len(dialog_messages) - cut, recent_count)
    return system_messages + kept

async def _apply_group_memory_context(request: ChatRequest) -> dict:
    request.conversation_id = _normalize_entity_id(request.conversation_id) or None
    request.user_message_id = _normalize_entity_id(request.user_message_id) or None
    request.group_id = _normalize_entity_id(request.group_id) or "default"
    group_id = request.group_id or "default"
    try:
        from py.get_setting import load_settings
        _cs = await load_settings()
    except Exception:
        _cs = None
    if not group_id or group_id == "default":
        request.messages = _trim_request_messages(request.messages, settings=_cs)
        return {"enabled": False, "group_id": group_id}

    group_map = await _load_group_map()
    group = group_map.get(group_id)
    memory_enabled = bool(group and (group.get("memoryConfig") or {}).get("enabled"))

    request.messages = _trim_request_messages(request.messages, settings=_cs)
    if not memory_enabled:
        return {"enabled": False, "group_id": group_id, "group": group}

    last_user_text = ""
    for msg in reversed(request.messages):
        if msg.get("role") == "user":
            last_user_text = _extract_text_content(msg.get("content"))
            break

    memories = await _fetch_group_memories(group_id, last_user_text, top_k=6)
    memory_prompt = _build_group_memory_prompt(group or {"id": group_id, "name": group_id}, memories)
    if memory_prompt:
        content_append(request.messages,'system',memory_prompt)
    return {"enabled": memory_enabled, "group_id": group_id, "group": group, "memories": memories}

async def _extract_group_memories(client, settings: dict, payload: dict) -> list[dict]:
    user_message = (payload.get("user_message") or "").strip()
    assistant_message = (payload.get("assistant_message") or "").strip()
    if not user_message or not assistant_message:
        return []

    extraction_prompt = (
        "你是一个结构化记忆提取器。只提取后续同组对话可复用的长期信息，"
        "不要总结整段聊天，不要保留闲聊、猜测、情绪宣泄、不确定信息和重复信息。"
        "只允许 memory_type 为 fact、decision、preference、todo、constraint、glossary。"
        "返回 JSON 数组，每项字段必须包含 memory_type、content、summary、importance。"
        "importance 取 0 到 1。若没有可提取记忆，返回 []。"
    )

    example_input = f"用户消息:\n{user_message}\n\n助手回复:\n{assistant_message}"

    def fallback_memories() -> list[dict]:
        combined = f"{user_message}\n{assistant_message}"
        results = []
        if any(keyword in combined.lower() for keyword in ["决定", "采用", "使用", "choose", "decide", "use "]):
            results.append({
                "memory_type": "decision",
                "summary": assistant_message[:120] or user_message[:120],
                "content": assistant_message or user_message,
                "importance": 0.82,
            })
        if any(keyword in combined.lower() for keyword in ["偏好", "喜欢", "prefer", "preferred"]):
            results.append({
                "memory_type": "preference",
                "summary": user_message[:120],
                "content": user_message,
                "importance": 0.72,
            })
        if any(keyword in combined.lower() for keyword in ["限制", "必须", "不能", "constraint", "must", "cannot", "can't"]):
            results.append({
                "memory_type": "constraint",
                "summary": (user_message or assistant_message)[:120],
                "content": user_message or assistant_message,
                "importance": 0.78,
            })
        if any(keyword in combined.lower() for keyword in ["todo", "待办", "后续", "需要", "next"]):
            results.append({
                "memory_type": "todo",
                "summary": user_message[:120],
                "content": user_message,
                "importance": 0.68,
            })
        return _merge_group_memories(results)

    try:
        extra_params = settings.get('extra_params') or []
        extra_body = process_extra_params(extra_params)
        response = await acreate(
            lambda: client.chat.completions.create(
            model=settings['model'],
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": example_input},
            ],
            temperature=0.1,
            stream=False,
            extra_body=extra_body,
        ), attempts=2, base_delay=1.0, label="s207-fallback_memories")
        content = response.choices[0].message.content or "[]"
        if "```json" in content:
            match = re.search(r'```json(.*?)```', content, re.DOTALL)
            content = match.group(1) if match else content.replace("```json", "").replace("```", "")
        data = json.loads(content)
    except Exception as e:
        logger.warning(f"Group memory extraction failed: {e}")
        return fallback_memories()

    if not isinstance(data, list):
        return []

    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("memory_type", "")).strip().lower()
        summary = str(item.get("summary", "")).strip()
        content = str(item.get("content", "")).strip()
        importance = float(item.get("importance", 0.5) or 0.5)
        if memory_type not in GROUP_MEMORY_TYPES or not summary or not content:
            continue
        cleaned.append({
            "memory_type": memory_type,
            "summary": summary,
            "content": content,
            "importance": max(0.0, min(1.0, importance)),
        })
    return _merge_group_memories(cleaned) or fallback_memories()

async def _upsert_group_memories(group_id: str, source_chat_id: str, source_message_id: str, memories: list[dict]) -> None:
    if not group_id or not source_chat_id or not memories:
        return
    now_ts = int(time.time() * 1000)
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        db.row_factory = aiosqlite.Row
        for memory in memories:
            # S160：控制 token 形状净化（写侧收口，防持久群记忆成为强化源）
            memory["content"] = _neutralize(memory.get("content") or "", store="group-memory")
            memory["summary"] = _neutralize(memory.get("summary") or "", store="group-memory")
            normalized_summary = _normalize_memory_text(memory["summary"])
            normalized_content = _normalize_memory_text(memory["content"])
            async with db.execute(
                """
                SELECT * FROM group_memory
                WHERE group_id = ? AND memory_type = ? AND status = 'active'
                """,
                (group_id, memory["memory_type"]),
            ) as cursor:
                existing_rows = [dict(row) for row in await cursor.fetchall()]

            duplicate = None
            superseded_ids = []
            for row in existing_rows:
                row_summary = _normalize_memory_text(row.get("summary"))
                row_content = _normalize_memory_text(row.get("content"))
                if row_summary == normalized_summary or row_content == normalized_content:
                    duplicate = row
                    break
                if (
                    memory["memory_type"] in {"decision", "preference", "constraint", "todo"}
                    and (normalized_summary in row_summary or row_summary in normalized_summary)
                ):
                    superseded_ids.append(row["id"])

            if memory["memory_type"] == "todo" and any(hint in normalized_content for hint in GROUP_MEMORY_DONE_HINTS):
                superseded_ids.extend([row["id"] for row in existing_rows if row["memory_type"] == "todo"])
                continue

            if duplicate:
                await db.execute(
                    """
                    UPDATE group_memory
                    SET importance = MAX(importance, ?), updated_at = ?, last_used_at = ?
                    WHERE id = ?
                    """,
                    (memory["importance"], now_ts, now_ts, duplicate["id"]),
                )
                continue

            if superseded_ids:
                await db.executemany(
                    "UPDATE group_memory SET status = 'superseded', updated_at = ? WHERE id = ?",
                    [(now_ts, item_id) for item_id in superseded_ids],
                )

            await db.execute(
                """
                INSERT INTO group_memory (
                    id, group_id, source_chat_id, source_message_id, memory_type, content, summary,
                    importance, status, version, created_at, updated_at, last_used_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    group_id,
                    source_chat_id,
                    source_message_id,
                    memory["memory_type"],
                    memory["content"],
                    memory["summary"],
                    memory["importance"],
                    now_ts,
                    now_ts,
                    now_ts,
                    json.dumps({"normalized_summary": normalized_summary}, ensure_ascii=False),
                ),
            )
        await db.commit()

async def _invalidate_group_memories_by_chat(source_chat_id: str) -> None:
    if not source_chat_id:
        return
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory WHERE source_chat_id = ?",
            (source_chat_id,),
        )
        await db.commit()

async def _invalidate_group_memories_by_group(group_id: str) -> None:
    if not group_id:
        return
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory WHERE group_id = ?",
            (group_id,),
        )
        await db.commit()

async def _invalidate_all_group_memories() -> None:
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory",
        )
        await db.commit()
