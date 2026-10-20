# -*- coding: utf-8 -*-
"""D-11: per-connection send queue — no frame interleaving, slow clients
are buffered not evicted, real failures still evict."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # third-party `py` shim hijack

from py.ws_manager import ConnectionManager, _QUEUE_MAX


class FakeWS:
    def __init__(self, delay=0.0, fail=False):
        self.received = []
        self.delay = delay
        self.fail = fail

    async def accept(self):
        pass

    async def send_json(self, msg):
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("boom")
        self.received.append(msg)


class TestWsSendQueue:
    def test_serial_no_interleave(self):
        async def main():
            m = ConnectionManager()
            ws = FakeWS()
            await m.connect(ws)
            await asyncio.gather(m.broadcast({"n": 1}), m.broadcast({"n": 2}))
            await asyncio.sleep(0.05)
            assert sorted(ws.received, key=lambda d: d["n"]) == [{"n": 1}, {"n": 2}]
            m.disconnect(ws)
        asyncio.run(main())

    def test_slow_client_buffered_not_evicted(self):
        async def main():
            m = ConnectionManager()
            ws = FakeWS(delay=0.15)
            await m.connect(ws)
            await m.send_json({"a": 1}, ws, timeout=0.01)
            assert ws in m.active_connections
            await asyncio.sleep(0.3)
            assert ws.received == [{"a": 1}]
            m.disconnect(ws)
        asyncio.run(main())

    def test_queue_full_drops_oldest_keeps_newest(self):
        async def main():
            m = ConnectionManager()

            class BlockingWS(FakeWS):
                def __init__(self):
                    super().__init__(delay=10)

            ws = BlockingWS()
            await m.connect(ws)
            for i in range(_QUEUE_MAX + 5):
                await m.send_json({"i": i}, ws)
            q = m._queues[id(ws)]
            assert q.qsize() == _QUEUE_MAX
            m.disconnect(ws)
        asyncio.run(main())

    def test_real_send_failure_evicts(self):
        async def main():
            m = ConnectionManager()
            ws = FakeWS(fail=True)
            await m.connect(ws)
            await m.send_json({"x": 1}, ws)
            await asyncio.sleep(0.05)
            assert ws not in m.active_connections
        asyncio.run(main())

    def test_disconnect_cleans_queue_and_sender(self):
        async def main():
            m = ConnectionManager()
            ws = FakeWS()
            await m.connect(ws)
            key = id(ws)
            assert key in m._senders and key in m._queues
            m.disconnect(ws)
            assert key not in m._senders and key not in m._queues
        asyncio.run(main())
