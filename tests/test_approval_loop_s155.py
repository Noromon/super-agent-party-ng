# -*- coding: utf-8 -*-
"""S155：审批回调必须回到 bot loop 执行。

事故（2026-10-27）：approval_store 在主 loop 上调度 notify → 跨线程写 slixmpp
transport → 审批推送静默丢失（用户收不到授权请求）。notify/resolved 现经
_on_bot_loop 桥接；本文件用真实双 loop 验证落点。
"""
import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.xmpp_client as xc  # noqa: E402


class _BotLoopCtx:
    """后台线程持一个独立事件循环（模拟 bot loop）。"""

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


def _bare_client(bot_loop):
    c = object.__new__(xc.XmppClient)
    c._bot_loop = bot_loop
    c._approval_queue = {}
    c.sent = []
    c.sent_loops = []

    async def _send_text(jid, text):
        c.sent_loops.append(asyncio.get_running_loop())
        c.sent.append((jid, text))

    c._send_text = _send_text
    return c


def _rec():
    return {"approval_id": "a1", "platform": "xmpp", "peer_id": "u@localhost",
            "tool_name": "edit_file_tool_local", "tool_params": {"path": "x.txt"},
            "permission_mode": "default", "cwd": "", "created_at": time.time(),
            "expires_at": time.time() + 600, "messages": []}


def _run_in(ctx, coro):
    fut = asyncio.run_coroutine_threadsafe(coro, ctx.loop)
    fut.result(timeout=10)


def test_notify_bridged_from_foreign_loop():
    ctx = _BotLoopCtx()
    try:
        c = _bare_client(ctx.loop)

        async def main():
            # 调用方 = 主测试 loop（模拟 server 主 loop 的 approval_store._spawn）
            assert asyncio.get_running_loop() is not ctx.loop
            await c._on_approval_notify(_rec())

        asyncio.run(main())
        assert c.sent and c.sent[0][0] == "u@localhost"
        assert "需要审批" in c.sent[0][1]
        assert all(lp is ctx.loop for lp in c.sent_loops), "notify 未落在 bot loop"
    finally:
        ctx.stop()


def test_notify_same_loop_passthrough():
    ctx = _BotLoopCtx()
    try:
        c = _bare_client(ctx.loop)
        # /y 批复路径：调用方就是 bot loop → 直通，不得死锁
        _run_in(ctx, c._on_approval_notify(_rec()))
        assert c.sent and all(lp is ctx.loop for lp in c.sent_loops)
    finally:
        ctx.stop()


def test_resolved_stop_bridged():
    ctx = _BotLoopCtx()
    try:
        c = _bare_client(ctx.loop)
        c._approval_queue["u@localhost"] = [("queued msg", [])]

        async def main():
            await c._on_approval_resolved(_rec(), "stop", "", "")

        asyncio.run(main())
        assert c.sent and "取消" in c.sent[0][1]
        assert all(lp is ctx.loop for lp in c.sent_loops)
        assert "u@localhost" not in c._approval_queue, "stop 未清空排队"
    finally:
        ctx.stop()


def test_bridge_disabled_without_bot_loop():
    # bot 停机后 _bot_loop=None：直连路径，不得抛「no running loop」类异常
    c = _bare_client(None)

    async def main():
        await c._on_approval_notify(_rec())

    asyncio.run(main())
    assert c.sent


def test_message_task_error_logged():
    # 直接向 "app" logger 挂 handler 取证（不动全局 logging.getLogger）
    import logging as _lg

    c = _bare_client(None)
    records = []

    class _Capture(_lg.Handler):
        def emit(self, record):
            records.append(record)

    app = _lg.getLogger("app")
    h = _Capture()
    app.addHandler(h)
    try:
        async def _boom():
            raise ValueError("handle-msg-died")

        async def main():
            t = asyncio.ensure_future(_boom())
            try:
                await t
            except ValueError:
                pass
            c._log_task_error(t)

        asyncio.run(main())
    finally:
        app.removeHandler(h)
    assert records and any(
        r.exc_info and isinstance(r.exc_info[1], ValueError) for r in records)
