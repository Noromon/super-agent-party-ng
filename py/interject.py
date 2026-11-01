# -*- coding: utf-8 -*-
"""S188: 插话（interject）队列——连续生成期间用户消息不丢失、不并发打流。

语义（用户拍板 2026-10-31）：
- 生成期间到达的用户消息：web 经 /v1/streams/{sid}/interject 入队、IM 在
  chat 入口拦截入队——当前最小推理单元（思考+回应/工具调用）结束后，在
  轮边界注入 request.messages，随下一轮推理一并处理；
- 审批挂起期间的 IM 消息进挂起区（_HELD），批复闭环（同意/拒绝/超时自动
  拒绝）时由 approval_store._fire 并入快照消息随重放续跑；
- 流自然结束/被用户停止而未消费的插话由前端兜底（自动补发/留待发区）。

本模块零业务依赖（仅标准库+仓内轻模块），不得反向 import server。
"""
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("app")

_IM_TARGETS: Dict[Tuple[str, str], str] = {}   # (platform, peer_id) -> stream_id
_HELD: Dict[Tuple[str, str], List[str]] = {}   # (platform, peer_id) -> [content]

MAX_INTERJECT_LEN = 8000


def register_stream(request, stream_id: str, entry: Dict[str, Any]) -> None:
    """流启动登记：挂队列容器；IM 渠道会话登记 peer→stream 目标。"""
    try:
        entry.setdefault("_interjections", [])
        if (getattr(request, "is_app_bot", False) and getattr(request, "platform", "")
                and getattr(request, "peer_id", "")):
            _IM_TARGETS[(request.platform, request.peer_id)] = stream_id
    except Exception as e:  # 登记失败不伤主流程
        logger.warning("[S188] register_stream 异常（忽略）: %r", e)


def _alive(entry) -> bool:
    return bool(entry) and not entry.get("done") and not entry.get("cancelled")


def _clean(content) -> str:
    return str(content or "").strip()[:MAX_INTERJECT_LEN]


async def web_interject(active_streams: Dict[str, Any], stream_id: str, content) -> bool:
    """web 插话入队。流不存在/已终结 → False（前端转兜底路径）。"""
    text = _clean(content)
    if not text:
        return False
    entry = active_streams.get(stream_id)
    if not _alive(entry):
        return False
    entry.setdefault("_interjections", []).append(text)
    logger.info("[S188] web 插话入队 stream=%s len=%d", str(stream_id)[:8], len(text))
    return True


def _last_user_content(request) -> str:
    for m in reversed(getattr(request, "messages", None) or []):
        if isinstance(m, dict) and m.get("role") == "user":
            return _clean(m.get("content"))
    return ""


def _static_reply(request, note: str) -> Dict[str, Any]:
    return {
        "id": "agentParty", "object": "chat.completion", "created": int(time.time()),
        "model": getattr(request, "model", "") or "super-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": note}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def im_intercept(request) -> Optional[Dict[str, Any]]:
    """IM 入口拦截：活跃流→注入队列；审批挂起→挂起区；均无→None 走正常流程。

    返回静态回执 dict（OpenAI completion 形态）时调用方直接应答，不再起流。"""
    try:
        key = (request.platform, request.peer_id)
        text = _last_user_content(request)
        if not text:
            return None
        from py import approval_store
        if approval_store.has_pending(request.platform, request.peer_id):
            _HELD.setdefault(key, []).append(text)
            logger.info("[S188] IM 插话挂起（审批未决）%s:%s len=%d",
                        request.platform, str(request.peer_id)[:8], len(text))
            return _static_reply(request, "[已排队] 你的消息将在审批闭环后合并处理。")
        from py.stream_relay import _active_streams
        sid = _IM_TARGETS.get(key)
        entry = _active_streams.get(sid) if sid else None
        if _alive(entry):
            entry.setdefault("_interjections", []).append(text)
            logger.info("[S188] IM 插话入队 %s:%s stream=%s len=%d",
                        request.platform, str(request.peer_id)[:8], str(sid)[:8], len(text))
            return _static_reply(request, "[已排队] 你的消息将在下一轮推理中一并处理。")
        _IM_TARGETS.pop(key, None)  # 陈旧目标清理
    except Exception as e:
        logger.warning("[S188] im_intercept 异常（放行原流程）: %r", e)
    return None


def take_held(key: Tuple[str, str]) -> List[str]:
    """批复闭环时取出挂起消息（approval_store._fire 调用，并入重放快照）。"""
    items = _HELD.pop(key, [])
    if items:
        logger.info("[S188] IM 挂起插话释放 %s:%s ×%d", key[0], str(key[1])[:8], len(items))
    return items


def drain_inject(_st: Dict[str, Any], request) -> List[str]:
    """轮边界注入口：弹空队列，逐条以 role=user 追加进 request.messages，
    返回注入确认（ack）SSE 帧列表（前端据此气泡转正/清待发区）。"""
    entry = _st.get("_entry") if isinstance(_st, dict) else None
    if not isinstance(entry, dict):
        return []
    queue = entry.get("_interjections") or []
    if not queue:
        return []
    frames: List[str] = []
    for text in queue:
        try:
            request.messages.append({"role": "user", "content": text})
        except Exception:
            continue
        frames.append("data: " + json.dumps(
            {"choices": [{"delta": {"interject": {"content": text}}}]},
            ensure_ascii=False) + "\n\n")
    entry["_interjections"] = []
    if frames:
        logger.info("[S188] 轮边界注入插话 ×%d（随下一轮推理处理）", len(frames))
    return frames
