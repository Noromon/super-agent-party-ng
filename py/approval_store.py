# -*- coding: utf-8 -*-
"""S150: IM 审批挂起表——进程内注册表 + 原子 resolve + TTL 超时。

设计（checkpoint S150，spike 结论）：
- server 工具轮与 bot 客户端同进程，快照直接持引用（deepcopy 一次），无序列化
  边界问题；resolve 后由 bot 用快照重放 /v1 实现「原位续流」（与前端
  backend_content 重放同构，属生产已验证路径）。
- handler 注册表按平台键（一平台一实例；A12 多账户时再引入 bot_id 维度）。
- 审批记录快照落盘（S191）：pending 即写 approvals_pending.json，重启后
  restore_pending 重建，用户仍可批复续跑；工具在挂起期从未执行过，无副作用残留。
"""
import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_TTL = 600  # 审批等待超时（秒），超时按 timeout 决策 resolve 并续跑收尾
_RESTART_GRACE = 120.0  # S191：重启后已过期的审批保留的宽限窗（等 bot 重连接批复）

_SNAP_FILE = "approvals_pending.json"
_snapshot_dir_override: Optional[str] = None  # 测试注入点

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


def has_pending(platform: str, peer_id: str, kind: Optional[str] = "approval") -> bool:
    """kind=None 表示不限类型（S200：与 latest_pending 家族语义对齐）。"""
    return any(
        aid in _PENDING and _PENDING[aid].get("status") == "pending"
        and (kind is None or _PENDING[aid].get("kind", "approval") == kind)
        for aid in _INDEX.get((platform, peer_id), [])
    )


def latest_pending(platform: str, peer_id: str,
                   kind: str = "approval") -> Optional[Dict[str, Any]]:
    """kind=None 表示不限类型。"""
    for aid in reversed(_INDEX.get((platform, peer_id), [])):
        rec = _PENDING.get(aid)
        if rec and rec.get("status") == "pending" \
                and (kind is None or rec.get("kind", "approval") == kind):
            return rec
    return None


def latest_pending_ask(platform: str, peer_id: str) -> Optional[Dict[str, Any]]:
    """S194：本对端待答提问卡（同一时刻至多一张）。"""
    return latest_pending(platform, peer_id, kind="ask")


def pending_count() -> int:
    return sum(1 for r in _PENDING.values() if r.get("status") == "pending")


def _snap_path() -> str:
    if _snapshot_dir_override:
        base = _snapshot_dir_override
    else:
        from py.get_setting import USER_DATA_DIR
        base = USER_DATA_DIR
    return os.path.join(base, _SNAP_FILE)


def _dump():
    """S191：pending 快照原子落盘（重启后 restore_pending 重建，审批跨重启可批）。"""
    try:
        p = _snap_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        data = [r for r in _PENDING.values() if r.get("status") == "pending"]
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, p)
        sz = os.path.getsize(p)
        if sz > 512 * 1024:  # S331: 快照含全量消息+工具输出，无上限时唯一可观测点
            logging.getLogger("app").warning(
                "[Approval] 快照文件 %dKB（pending=%d 条，含全量消息）", sz // 1024, len(data))
    except Exception as e:
        logging.getLogger("app").warning("[Approval] 快照落盘失败: %r", e)


async def create(*, platform: str, peer_id: str, tool_name: str,
                 tool_params: Any = None, tool_call_id: str = "",
                 permission_mode: str = "", cwd: str = "",
                 messages: Optional[list] = None, ttl: float = DEFAULT_TTL,
                 stream_id: Optional[str] = None,
                 kind: str = "approval", questions: Optional[list] = None) -> Dict[str, Any]:
    """登记挂起记录（审批/提问卡）；同步入库（此后 has_pending 立即可见），随后异步通知。"""
    aid = uuid.uuid4().hex[:12]
    now = time.time()
    record = {
        "approval_id": aid,
        "kind": kind,
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
    if questions is not None:
        record["questions"] = questions
    _PENDING[aid] = record
    _INDEX.setdefault((platform, peer_id), []).append(aid)
    _dump()  # S191：登记即落盘，重启不丢审批
    loop = asyncio.get_running_loop()
    # 超时句柄延迟建协程（提前 resolve 时句柄被取消，避免 never-awaited 警告）
    _EXPIRE_TASKS[aid] = loop.call_later(ttl, _spawn_later, _expire, aid)
    notify = _NOTIFY.get(platform)
    if notify:
        _spawn(_safe_notify(notify, record))
    # S151：通知中心（IM 来源 pending，面板双向审批入口）
    # S194：ask 记录只收 web 来源（IM 提问直发对端，不堆面板）
    try:
        if kind == "ask" and platform != "web":
            raise _SkipPanelEmit()
        from py import notification_center
        if kind == "ask":
            notification_center.emit(
                "approval",
                f"AI 提问等待回答（web 会话 {peer_id}：{len(questions or [])} 问）",
                extra={"pending_key": aid, "source": "im",
                       "approval_id": aid, "platform": platform,
                       "peer_id": peer_id, "tool_name": tool_name,
                       "kind": "ask", "status": "pending"})
        else:
            notification_center.emit("approval", f"工具 {tool_name} 等待审批（{platform} · {peer_id}）", level="warn",
                                     extra={"pending_key": aid, "source": "im",
                                            "approval_id": aid, "platform": platform,
                                            "peer_id": peer_id, "tool_name": tool_name,
                                            "tool_params": tool_params or {},
                                            "status": "pending"})
    except _SkipPanelEmit:
        pass
    except Exception:
        pass
    return record


class _SkipPanelEmit(Exception):
    pass


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
        try:
            from py import notification_center
            notification_center.emit(
                "error", f"审批推送到 {record.get('platform')} 失败，请到通知中心批复: {e!r}",
                extra={"pending_key": record.get("approval_id"), "source": "im",
                       "approval_id": record.get("approval_id"),
                       "tool_name": record.get("tool_name")}, level="error")
        except Exception:
            pass


async def _expire(aid: str):
    record = _pop_pending(aid)
    if record is None:
        return
    if record.get("kind") == "ask":  # S194：提问卡超时=逐题按未答复结算续流
        from py import ask_flow
        await _fire(record, "timeout", "", ask_flow.timeout_result_text(record))
        return
    from py import approval_im
    await _fire(record, "timeout", "", approval_im.timeout_text(record["tool_name"]))


async def _fire(record, decision, note, result_text):
    # S151：决策事件回落通知中心（面板销账 + 审计留痕）
    # S194：ask 记录仅 web 来源进面板（与 create 侧对称）
    try:
        _is_ask = record.get("kind") == "ask"
        if not (_is_ask and record.get("platform") != "web"):
            from py import notification_center
            label = {"approve": "已批准", "always": "已批准并加白名单", "deny": "已拒绝",
                     "timeout": "超时未批", "stop": "已取消",
                     "answers": "已答复"}.get(decision, decision)
            _subject = (f"提问卡{label}（{record.get('platform')}）" if _is_ask
                        else f"审批{label}：{record.get('tool_name')}（{record.get('platform')}）")
            notification_center.emit(
                "approval", _subject,
                extra={"pending_key": record.get("approval_id"), "source": "im",
                       "approval_id": record.get("approval_id"),
                       "tool_name": record.get("tool_name"), "decision": decision,
                       "status": "resolved"})
    except Exception:
        pass
    # S188：批复闭环——释放该会话挂起的插话消息，并入快照随重放续跑（不丢消息）
    try:
        from py import interject
        for _hc in interject.take_held((record["platform"], record["peer_id"])):
            if isinstance(record.get("messages"), list):
                record["messages"].append({"role": "user", "content": _hc})
    except Exception:
        pass
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
    _dump()  # S191：销账同步快照
    return record


async def resolve(platform: str, peer_id: str, decision: str,
                  note: str = "", result_text: str = "",
                  kind: str = "approval") -> Tuple[Optional[Dict[str, Any]], str]:
    """摘除该 peer 最新一条挂起记录（kind 缺省仅审批）；不执行工具、不调续跑器
    （编排归 approval_im / ask 路径）。"""
    record = latest_pending(platform, peer_id, kind=kind)
    if record is None:
        return None, "没有待审批的任务"
    aid = record["approval_id"]
    th = _EXPIRE_TASKS.pop(aid, None)
    if th:
        th.cancel()
    return _pop_pending(aid), ""


async def resolve_by_id(aid: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """S151：按 approval_id 原子摘除（通知中心面板审批用）。提问卡不走面板批复。"""
    record = _PENDING.get(aid)
    if record is None or record.get("status") != "pending":
        return None, "该审批已失效或不存在"
    if record.get("kind") == "ask":  # S194：提问卡在会话里直接回答，面板只读
        return None, "该记录是 AI 提问卡，请在原会话中直接回复答案"
    th = _EXPIRE_TASKS.pop(aid, None)
    if th:
        th.cancel()
    return _pop_pending(aid), ""


async def cancel_all(platform: str, peer_id: str) -> int:
    """清空该 peer 全部挂起（/stop 围栏，S194 起含提问卡）：按 stop 决策 fire，
    由续跑器做本地清理。"""
    n = 0
    while True:
        record = latest_pending(platform, peer_id, kind=None)
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
    try:
        os.remove(_snap_path())
    except OSError:
        pass


async def restore_pending() -> int:
    """S191：服务重启后从快照重建挂起审批。未过期按剩余 TTL 继续等待；
    已过期给重启宽限窗（等 bot 重连接批复），仍无人批复则按 timeout 收尾。"""
    try:
        p = _snap_path()
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logging.getLogger("app").warning("[Approval] 快照读取失败: %r", e)
        return 0
    if not isinstance(data, list):
        return 0
    now = time.time()
    loop = asyncio.get_running_loop()
    n = 0
    for rec in data:
        aid = rec.get("approval_id") if isinstance(rec, dict) else None
        if not aid or aid in _PENDING or rec.get("status") != "pending":
            continue
        rec["restored_at"] = now
        _PENDING[aid] = rec
        _INDEX.setdefault((rec.get("platform"), rec.get("peer_id")), []).append(aid)
        remain = float(rec.get("expires_at", now)) - now
        _EXPIRE_TASKS[aid] = loop.call_later(max(remain, _RESTART_GRACE),
                                             _spawn_later, _expire, aid)
        n += 1
    if n:
        logging.getLogger("app").info("[Approval] 重启恢复挂起审批 %d 条", n)
        _dump()
    return n


# ---------------------------------------------------------------- S330 one-shot


_GRANTS: Dict[Tuple[str, str, str], float] = {}  # (platform, peer, tool) -> expiry
_CUR_IM_CTX = contextvars.ContextVar("sap_im_ctx", default=None)  # (platform, peer)
_GRANT_TTL = 90.0


def set_current_im_ctx(platform, peer_id):
    """chat 端点入口调用：把请求携带的 (platform, peer_id) 绑入任务上下文，
    供 hook 审批门消费 one-shot grant。非 IM 请求传空即天然不匹配。"""
    _CUR_IM_CTX.set((platform or "", peer_id or ""))


def grant_oneshot(platform, peer_id, tool_name, ttl: float = _GRANT_TTL):
    """approve 批复后同 (platform, peer, tool) 短期免弹窗（TTL 窗，见
    grant_active）：模型批复后立刻重试同一工具不再二次送审（17:21 事故）。"""
    _GRANTS[(platform or "", peer_id or "", tool_name)] = time.time() + ttl


def grant_active(tool_name) -> bool:
    """S330: TTL 窗口内有效即 True（不弹出——同轮 precheck 与 dispatch 会
    两次过审批门，pop 语义会造成第一道门吃掉 grant 第二道反而拦截）。
    一次批复 = 同 peer 同工具 90s 短窗免弹窗（防的是批复后立刻重试双弹）。"""
    ctx = _CUR_IM_CTX.get()
    if not ctx:
        return False
    exp = _GRANTS.get((ctx[0], ctx[1], tool_name))
    if exp and exp > time.time():
        return True
    _GRANTS.pop((ctx[0], ctx[1], tool_name), None)
    return False
