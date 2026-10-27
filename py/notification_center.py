# -*- coding: utf-8 -*-
"""S151: 通知中心——全量事件汇聚 + ws 广播 + json 环形持久化。

定位（epic 决策④：收录全量事件+分类筛选）：
- 事件类别 approval / generation / bot / error / system；append-only。
- 发射点线程任意（server 主 loop、各 bot 线程）：落盘用锁串行化，
  ws 广播经 bind_loop 记录的 uvicorn 主 loop 桥接（run_coroutine_threadsafe）。
- 审批双向：pending 事件 extra 携带 pending_key（im=approval_id，web=stream_id）
  与来源，面板据此渲染批准/拒绝按钮；决策事件同 key 回落，前端配对销账。
- 持久化 USER_DATA_DIR/notifications.json（环形上限 200 条，启动装载）。
"""
import asyncio
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

CATEGORIES = ("approval", "generation", "bot", "error", "system")
MAX_ITEMS = 200

_lock = threading.Lock()
_items: List[Dict[str, Any]] = []
_loaded = False
_loop: Optional[asyncio.AbstractEventLoop] = None


def _store_path() -> str:
    from py.get_setting import USER_DATA_DIR
    return os.path.join(USER_DATA_DIR, "notifications.json")


def _load_locked():
    global _items, _loaded
    if _loaded:
        return
    _loaded = True
    try:
        with open(_store_path(), encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            _items = [d for d in data if isinstance(d, dict) and d.get("category") in CATEGORIES]
            del _items[MAX_ITEMS:]
    except Exception:
        _items = []


def bind_loop(loop: asyncio.AbstractEventLoop):
    """lifespan 启动时记录主 loop（ws_manager 的归属循环）。"""
    global _loop
    _loop = loop


def emit(category: str, msg: str, extra: Optional[dict] = None,
         level: str = "info") -> Dict[str, Any]:
    """线程安全发射一条通知；永不抛穿调用方。"""
    if category not in CATEGORIES:
        category = "system"
    record = {
        "id": uuid.uuid4().hex[:10],
        "ts": time.time(),
        "category": category,
        "level": level if level in ("info", "warn", "error") else "info",
        "msg": (msg or "")[:500],
        "extra": extra or {},
    }
    try:
        with _lock:
            _load_locked()
            _items.append(record)
            if len(_items) > MAX_ITEMS:
                del _items[:-MAX_ITEMS]
            _save_locked()
    except Exception as e:
        logging.getLogger("app").warning("[Notify] 落盘失败: %r", e)
    _broadcast(record)
    return record


def _save_locked():
    tmp = _store_path() + ".tmp"
    os.makedirs(os.path.dirname(_store_path()), exist_ok=True)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_items, f, ensure_ascii=False)
    os.replace(tmp, _store_path())


def _broadcast(record: Dict[str, Any]):
    loop = _loop
    if loop is None or not loop.is_running():
        return
    try:
        asyncio.run_coroutine_threadsafe(_send_ws(record), loop)
    except Exception:
        pass


async def _send_ws(record: Dict[str, Any]):
    try:
        from py.ws_manager import ws_manager
        await ws_manager.broadcast({"type": "notification", "data": record})
    except Exception as e:
        logging.getLogger("app").warning("[Notify] ws 广播失败: %r", e)


def list_items(category: str = "", unread_only: bool = False,
               limit: int = 100) -> List[Dict[str, Any]]:
    with _lock:
        _load_locked()
        out = list(_items)
    if category:
        out = [d for d in out if d.get("category") == category]
    if unread_only:
        out = [d for d in out if not d.get("read")]
    return list(reversed(out[-max(1, min(limit, MAX_ITEMS)):]))


def mark_read(ids: Optional[List[str]] = None) -> int:
    n = 0
    with _lock:
        _load_locked()
        for d in _items:
            if ids is None or d.get("id") in ids:
                if not d.get("read"):
                    d["read"] = True
                    n += 1
        if n:
            _save_locked()
    return n


def clear_all() -> int:
    global _items
    with _lock:
        _load_locked()
        n = len(_items)
        _items = []
        _save_locked()
    return n
