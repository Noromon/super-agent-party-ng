# -*- coding: utf-8 -*-
"""S150: IM 审批挂起表——进程内注册表 + 原子 resolve + TTL 超时。

设计（checkpoint S150，spike 结论）：
- server 工具轮与 bot 客户端同进程，快照直接持引用（deepcopy 一次），无序列化
  边界问题；resolve 后由 bot 用快照重放 /v1 实现「原位续流」（与前端
  backend_content 重放同构，属生产已验证路径）。
- handler 注册表按平台键（一平台一实例；A12 多账户时再引入 bot_id 维度）。
- 审批记录只在内存存活：进程重启即失效（/y 得到"没有待审批"提示），
  工具在挂起期从未执行过，无副作用残留。
"""
import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_TTL = 600  # 审批等待超时（秒），超时按 timeout 决策 resolve 并续跑收尾

_PENDING: Dict[str, Dict[str, Any]] = {}
_INDEX: Dict[Tuple[str, str], List[str]] = {}  # (platform, peer_id) -> [approval_id]
_NOTIFY: Dict[str, Callable] = {}      # platform -> async fn(record)
_RESOLVER: Dict[str, Callable] = {}    # platform -> async fn(record, decision, note, result_text)
_EXPIRE_TASKS: Dict[str, asyncio.TimerHandle] = {}
_LOOP_TASKS: set = set()  # 持引用防 GC


def register_handlers(platform: str, notify: Optional[Callable] = None,
                      resolver: Optional[Callable] = None):
    if notify:
        _NOTIFY[platform] = notify
    if resolver:
        _RESOLVER[platform] = resolver


def has_handlers(platform: str) -> bool:
    return platform in _RESOLVER


def has_pending(platform: str, peer_id: str) -> bool:
    return any(
        aid in _PENDING and _PENDING[aid].get("status") == "pending"
        for aid in _INDEX.get((platform, peer_id), [])
    )


def latest_pending(platform: str, peer_id: str) -> Optional[Dict[str, Any]]:
    for aid in reversed(_INDEX.get((platform, peer_id), [])):
        rec = _PENDING.get(aid)
        if rec and rec.get("status") == "pending":
            return rec
    return None


def pending_count() -> int:
    return sum(1 for r in _PENDING.values() if r.get("status") == "pending")


async def create(*, platform: str, peer_id: str, tool_name: str,
                 tool_params: Any = None, tool_call_id: str = "",
                 permission_mode: str = "", cwd: str = "",
                 messages: Optional[list] = None, ttl: float = DEFAULT_TTL,
                 stream_id: Optional[str] = None) -> Dict[str, Any]:
    """登记挂起审批；同步入库（此后 has_pending 立即可见），随后异步通知。"""
    aid = uuid.uuid4().hex[:12]
    now = time.time()
    record = {
        "approval_id": aid,
        "platform": platform,
        "peer_id": peer_id,
        "tool_name": tool_name,
        "tool_params": tool_params if tool_params is not None else {},
        "tool_call_id": tool_call_id,
        "permission_mode": permission_mode,
        "cwd": cwd,
        "stream_id": stream_id,
        "messages": messages if messages is not None else [],
        "created_at": now,
        "expires_at": now + ttl,
        "status": "pending",
    }
    _PENDING[aid] = record
    _INDEX.setdefault((platform, peer_id), []).append(aid)
    loop = asyncio.get_running_loop()
    # 超时句柄延迟建协程（提前 resolve 时句柄被取消，避免 never-awaited 警告）
    _EXPIRE_TASKS[aid] = loop.call_later(ttl, _spawn_later, _expire, aid)
    notify = _NOTIFY.get(platform)
    if notify:
        _spawn(_safe_notify(notify, record))
    return record


def _spawn(coro):
    t = asyncio.create_task(coro)
    _LOOP_TASKS.add(t)
    t.add_done_callback(_LOOP_TASKS.discard)
    t.add_done_callback(_done_log)  # S155：后台任务静默死亡归案


def _done_log(t):
    if t.cancelled():
        return
    exc = t.exception()
    if exc is not None:
        logging.getLogger("app").error("[Approval] 后台任务异常: %r", exc,
                                       exc_info=exc)


def _spawn_later(fn, *args):
    _spawn(fn(*args))


async def _safe_notify(notify, record):
    try:
        await notify(record)
    except Exception as e:  # 通知失败不影响挂起本身（用户可稍后 /y 补救）
        logging.getLogger("app").warning("[Approval] 挂起通知失败: %r", e)


async def _expire(aid: str):
    record = _pop_pending(aid)
    if record is None:
        return
    from py import approval_im
    await _fire(record, "timeout", "", approval_im.timeout_text(record["tool_name"]))


async def _fire(record, decision, note, result_text):
    resolver = _RESOLVER.get(record["platform"])
    if not resolver:
        logging.getLogger("app").info(
            "[Approval] 无平台续跑器（%s），审批 %s 按 %s 落账但未续流",
            record["platform"], record["approval_id"], decision)
        return
    try:
        await resolver(record, decision, note, result_text)
    except Exception as e:
        logging.getLogger("app").error("[Approval] 续跑器异常: %r", e, exc_info=True)


def _pop_pending(aid: str) -> Optional[Dict[str, Any]]:
    """原子摘除（同一事件循环内无 await，天然互斥）。"""
    record = _PENDING.get(aid)
    if record is None or record.get("status") != "pending":
        return None
    record["status"] = "resolved"
    _PENDING.pop(aid, None)
    lst = _INDEX.get((record["platform"], record["peer_id"]))
    if lst and aid in lst:
        lst.remove(aid)
    _EXPIRE_TASKS.pop(aid, None)
    return record


async def resolve(platform: str, peer_id: str, decision: str,
                  note: str = "", result_text: str = "") -> Tuple[Optional[Dict[str, Any]], str]:
    """摘除该 peer 最新一条挂起审批；不执行工具、不调续跑器（编排归 approval_im）。"""
    record = latest_pending(platform, peer_id)
    if record is None:
        return None, "没有待审批的任务"
    aid = record["approval_id"]
    th = _EXPIRE_TASKS.pop(aid, None)
    if th:
        th.cancel()
    return _pop_pending(aid), ""


async def cancel_all(platform: str, peer_id: str) -> int:
    """清空该 peer 全部挂起（/stop 围栏）：按 stop 决策 fire，由续跑器做本地清理。"""
    n = 0
    while True:
        record = latest_pending(platform, peer_id)
        if record is None:
            break
        aid = record["approval_id"]
        th = _EXPIRE_TASKS.pop(aid, None)
        if th:
            th.cancel()
        rec = _pop_pending(aid)
        if rec is None:
            break
        n += 1
        await _fire(rec, "stop", "", "")
    return n


def clear_all():
    """测试/停机辅助：清空登记并取消全部超时句柄。"""
    for th in _EXPIRE_TASKS.values():
        th.cancel()
    _EXPIRE_TASKS.clear()
    _PENDING.clear()
    _INDEX.clear()
