# -*- coding: utf-8 -*-
"""S151：通知中心——环形持久化、跨 loop ws 广播桥、面板审批摘除与事件回落。"""
import asyncio
import json
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.get_setting  # noqa: E402
import py.notification_center as nc  # noqa: E402


class _BotLoopCtx:
    """后台线程持独立事件循环（模拟 uvicorn 主 loop）。"""

    def __init__(self):
        self.loop = None
        ready = threading.Event()

        def _run():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()
        assert ready.wait(5)

    def stop(self):
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        self.loop.close()


def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setattr(py.get_setting, "USER_DATA_DIR", str(tmp_path))
    saved = (list(nc._items), nc._loaded, nc._loop)
    nc._items.clear()
    nc._loaded = False
    nc._loop = None

    def _restore():
        nc._items[:] = saved[0]
        nc._loaded = saved[1]
        nc._loop = saved[2]
    return _restore


def test_emit_ring_and_persistence(tmp_path, monkeypatch):
    restore = _isolate_store(tmp_path, monkeypatch)
    try:
        for i in range(nc.MAX_ITEMS + 5):
            nc.emit("system", f"ev{i}")
        assert len(nc._items) == nc.MAX_ITEMS
        assert nc._items[-1]["msg"] == "ev204"
        assert nc._items[0]["msg"] == "ev5"  # 头部 5 条被环形挤出
        with open(nc._store_path(), encoding="utf-8") as f:
            assert len(json.load(f)) == nc.MAX_ITEMS
        # 重新装载（模拟重启）
        nc._items.clear()
        nc._loaded = False
        items = nc.list_items(limit=nc.MAX_ITEMS)
        assert len(items) == nc.MAX_ITEMS
        assert items[0]["msg"] == "ev204"  # 列表为倒序（新在前）
        assert nc.list_items(category="approval") == []
    finally:
        restore()


def test_bad_category_falls_back_and_threadsafe(tmp_path, monkeypatch):
    restore = _isolate_store(tmp_path, monkeypatch)
    try:
        rec = nc.emit("nope", "x")
        assert rec["category"] == "system"
        threads = [threading.Thread(target=lambda: nc.emit("bot", "t")) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len([d for d in nc.list_items() if d["msg"] == "t"]) == 8
        with open(nc._store_path(), encoding="utf-8") as f:
            assert len(json.load(f)) == 9
    finally:
        restore()


def test_read_and_clear(tmp_path, monkeypatch):
    restore = _isolate_store(tmp_path, monkeypatch)
    try:
        a = nc.emit("system", "a")
        nc.emit("system", "b")
        assert nc.mark_read([a["id"]]) == 1
        assert [d["msg"] for d in nc.list_items(unread_only=True)] == ["b"]
        assert nc.mark_read() == 1
        assert nc.list_items(unread_only=True) == []
        assert nc.clear_all() == 2
        assert nc.list_items() == []
    finally:
        restore()


def test_broadcast_bridged_to_bound_loop(tmp_path, monkeypatch):
    restore = _isolate_store(tmp_path, monkeypatch)
    ctx = _BotLoopCtx()
    try:
        import py.ws_manager as wsm
        seen = {}

        async def fake_broadcast(message, exclude=None, timeout=None):
            seen["loop"] = asyncio.get_running_loop()
            seen["msg"] = message

        monkeypatch.setattr(wsm.ws_manager, "broadcast", fake_broadcast)
        nc.bind_loop(ctx.loop)
        rec = nc.emit("bot", "hello")  # 从测试主线程发射
        for _ in range(100):
            if "msg" in seen:
                break
            threading.Event().wait(0.02)
        assert seen["msg"] == {"type": "notification", "data": rec}
        assert seen["loop"] is ctx.loop  # 广播落在绑定 loop 上
    finally:
        ctx.stop()
        restore()


def test_broadcast_noop_without_loop(tmp_path, monkeypatch):
    restore = _isolate_store(tmp_path, monkeypatch)
    try:
        rec = nc.emit("system", "no loop")  # 不得抛穿
        assert rec["id"]
    finally:
        restore()


def test_resolve_by_id_atomic_and_pending_event(tmp_path, monkeypatch):
    import py.approval_store as store
    restore = _isolate_store(tmp_path, monkeypatch)

    async def _run():
        rec = await store.create(platform="tst151", peer_id="p1", tool_name="shell_exec")
        pend = [d for d in nc.list_items(category="approval")
                if (d.get("extra") or {}).get("pending_key") == rec["approval_id"]]
        assert pend and pend[0]["extra"]["status"] == "pending"
        got, err = await store.resolve_by_id(rec["approval_id"])
        assert got is not None and err == ""
        got2, err2 = await store.resolve_by_id(rec["approval_id"])
        assert got2 is None and err2
        store.clear_all()

    try:
        asyncio.run(_run())
    finally:
        restore()


def test_browser_entry_pins():
    """S151b 钉桩：侧栏通知入口与路由守卫必须同存（缺一即浏览器端空白页）。"""
    root = Path(__file__).resolve().parents[1]
    html = (root / "static" / "index.html").read_text(encoding="utf-8")
    nav = (root / "static" / "js" / "methods" / "54_ui_nav.js").read_text(encoding="utf-8")
    assert 'index="notifications"' in html
    assert '@click="openNotificationsPanel"' in html
    assert 'v-if="!isElectron && !isMobile"' in html  # 与顶栏铃铛(isElectron||isMobile)互补
    assert "if (key === 'notifications') return;" in nav


def test_resolve_by_id_web_deny_emits_resolved(tmp_path, monkeypatch):
    import py.approval_im as aim
    import py.approval_store as store
    restore = _isolate_store(tmp_path, monkeypatch)

    async def _run():
        rec = await store.create(platform="tst151", peer_id="p1", tool_name="shell_exec")
        aid = rec["approval_id"]
        ok, msg = await aim.resolve_by_id_web(aid, "bogus")
        assert not ok and "approve/always/deny" in msg
        ok, msg = await aim.resolve_by_id_web("missing-id", "approve")
        assert not ok and msg
        ok, msg = await aim.resolve_by_id_web(aid, "deny", note="面板拒绝")
        assert ok and msg
        for _ in range(50):
            resolved = [d for d in nc.list_items(category="approval")
                        if (d.get("extra") or {}).get("pending_key") == aid
                        and (d.get("extra") or {}).get("status") == "resolved"]
            if resolved:
                break
            await asyncio.sleep(0.02)
        assert resolved and resolved[0]["extra"]["decision"] == "deny"
        store.clear_all()

    try:
        asyncio.run(_run())
    finally:
        restore()
