# -*- coding: utf-8 -*-
"""S191: IM 渠道轮内链工具——从 SSE 帧增量累积 canonical 链、memoryList 展平重放、
审批快照对抽取。纯函数模块（不依赖 slixmpp，供 xmpp/qq 等 bot 客户端与测试共用）。

背景：IM 渠道旧实现轮末即弃整条轮内链，只留最终文本对，跨轮上下文从 ~16k 基线
重建（能力断崖）。本模块把链以 backend_content 挂在最终 assistant 条目上随
memoryList 持久化，下一轮展平重放，与 web 渠道 backend_content 机制同构。
"""
from typing import Any, Dict, List, Optional


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…[截断s191]"


def _clip_args(text: str, limit: int = 4000) -> str:
    """参数截断必须保持 JSON 合法（历史重放直接进引擎 tool_calls）。"""
    if len(text) <= limit:
        return text
    return '{"_truncated_s191": true}'


def field(frame: Any, key: str, default: str = "") -> str:
    """tool_content 帧字段双形态提取（SDK extra 字段=dict；兼容对象形态）。"""
    if frame is None:
        return default
    if isinstance(frame, dict):
        v = frame.get(key, default)
    else:
        v = getattr(frame, key, default)
    return v if isinstance(v, str) else (default if v is None else str(v))


def chain_update(chain: Optional[List[dict]], tc: Any, tool_call_id: str,
                 assistant_text: str = "") -> Optional[List[dict]]:
    """把一个 SSE delta 帧并入轮内链，返回链（无新增时原样返回）。

    call 帧 → assistant(tool_calls) 条目（参数取帧 content，缺省 "{}"）；
    tool_result 帧 → tool 条目。无 tool_call_id 的帧跳过（孤儿链交给
    sanitize 只会丢弃，不如不进链）。
    """
    tcid = str(tool_call_id or "")
    if tc is None or not tcid:
        return chain
    _type = field(tc, "type")
    title = field(tc, "title")
    content = field(tc, "content")
    if _type == "call":
        entry = {"role": "assistant", "content": "",
                 "tool_calls": [{"id": tcid, "type": "function",
                                 "function": {"name": title,
                                              "arguments": _clip_args(content or "{}")}}]}
    elif _type == "tool_result":
        entry = {"role": "tool", "tool_call_id": tcid, "name": title,
                 "content": _clip(content, 12000)}
    else:
        return chain
    if chain is None:
        chain = []
    chain.append(entry)
    return chain


def flatten_memory(entries: List[dict]) -> List[dict]:
    """memoryList → 请求历史：带 backend_content 的条目展平为链+最终文本对。

    链中条目原样透传（配对完整性交给服务端 sanitize 兜底）；无 backend_content
    的普通条目输出 {role, content} 两键（剥除本地杂项字段）。
    """
    out: List[dict] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        be = e.get("backend_content")
        if isinstance(be, list) and be:
            for m in be:
                if isinstance(m, dict) and m.get("role"):
                    out.append(m)
        out.append({"role": e.get("role", "user"), "content": e.get("content", "")})
    return out


def pairs_from_snapshot(snapshot: List[dict]) -> List[dict]:
    """审批快照（服务端 request.messages 视图）→ 工具链对（剥 system/普通文本）。

    保留 assistant(tool_calls) 与 tool 两类条目，供续流收尾后并入 memoryList，
    使审批前已完成的工具轮不随快照失效而丢失。
    """
    out: List[dict] = []
    for m in snapshot or []:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role == "tool" and m.get("tool_call_id"):
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"],
                        "name": m.get("name", ""), "content": m.get("content", "")})
        elif role == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content", "") or "",
                        "tool_calls": m["tool_calls"]})
    return out


def finalize_entry(pairs: List[dict], text: str) -> Dict[str, Any]:
    """收尾条目：最终文本 + 轮内链（backend_content）。"""
    entry: Dict[str, Any] = {"role": "assistant", "content": text}
    if pairs:
        entry["backend_content"] = pairs
    return entry


def merge_inflight(memory: List[dict], inflight: List[dict]) -> Optional[Dict[str, Any]]:
    """重启前 inflight 检查点 → 追加到 memory 尾部的恢复条目（无对则 None）。

    检查点行含中断轮的服务端消息视图；抽其中的工具对挂成一条空文本
    backend 条目——悬挂未闭合的对由服务端 sanitize 天然抹平。
    """
    pairs = pairs_from_snapshot(inflight or [])
    if not pairs:
        return None
    entry = finalize_entry(pairs, "")
    memory.append(entry)
    return entry
