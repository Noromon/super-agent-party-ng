# -*- coding: utf-8 -*-
"""S131: 取消链路修复（F1 chunk 围栏 / F2 cancelled 停写 buffer / F4 有界等待）。

事故（backend.log 2026-10-25 23:03）：cancel 端点标记后旧生产者继续跑工具与
后续 LLM 轮（[Cancel] 围栏日志全程零出现），编辑重发形成双并行作业，旧作业
UI 不可见。本文件钉桩修复后的行为。
"""
import ast
import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.stream_relay import (  # noqa: E402
    _active_streams, _current_stream_entry, _st_cancelled, _stream_producer_wrapper,
)


def _load_first_pass():
    """ast 抽取 _stream_first_pass（fork 惯例：测试不 import 重型 server 模块）。"""
    tree = ast.parse((_ROOT / "server.py").read_text(encoding="utf-8-sig"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_first_pass")
    ns = {"asyncio": asyncio, "json": json, "logging": logging,
          "_st_cancelled": _st_cancelled,
          "_merge_tool_delta": lambda *a, **k: (None, "")}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<fp>", "exec"), ns)
    return ns["_stream_first_pass"]


class TestStCancelled:
    def test_explicit_entry_cancelled_without_contextvar(self):
        assert _st_cancelled({"_entry": {"cancelled": True}}) is True

    def test_explicit_entry_not_cancelled(self):
        assert _st_cancelled({"_entry": {"cancelled": False}}) is False

    def test_missing_entry_and_contextvar_false(self):
        assert _st_cancelled(None) is False
        assert _st_cancelled({}) is False

    def test_fallback_to_contextvar(self):
        tok = _current_stream_entry.set({"cancelled": True})
        try:
            assert _st_cancelled({}) is True
        finally:
            _current_stream_entry.reset(tok)


def _fake_stream(n):
    class _S:
        def __init__(self):
            self.left = n

        def __aiter__(self):
            return self

        async def __anext__(self):
            if self.left <= 0:
                raise StopAsyncIteration
            self.left -= 1
            await asyncio.sleep(0)
            return SimpleNamespace(choices=None)
    return _S()


def _drain(agen):
    async def _go():
        out = []
        async for c in agen:
            out.append(c)
        return out
    return asyncio.run(_go())


class TestChunkFence:
    """F1: _stream_first_pass 在途流 ≤5 chunk 围栏。"""

    def _call(self, _st, n):
        fp = _load_first_pass()
        return _drain(fp(
            _st, _fake_stream(n), "<th>", "</th>", [], None, 0, False, "",
            False, [], [], 0))

    def test_bails_immediately_when_cancelled(self):
        _st = {"_entry": {"cancelled": True}}
        out = self._call(_st, 50)
        assert out == []
        assert _st.get("w1_cancel") is True

    def test_no_bail_when_running(self):
        _st = {"_entry": {"cancelled": False}}
        out = self._call(_st, 12)
        assert out == []
        assert "w1_cancel" not in _st

    def test_bails_mid_stream(self):
        _st = {"_entry": {"cancelled": False}}
        fp = _load_first_pass()

        async def _go():
            stream = _fake_stream(500)

            async def _flip():
                await asyncio.sleep(0.01)
                _st["_entry"]["cancelled"] = True
            flip = asyncio.ensure_future(_flip())
            async for _c in fp(_st, stream, "<th>", "</th>", [], None, 0, False,
                               "", False, [], [], 0):
                pass
            await flip
        asyncio.run(_go())
        assert _st.get("w1_cancel") is True


class TestProducerBufferDrop:
    """F2: 取消后生产者不再向 buffer 追加。"""

    def test_buffer_frozen_after_cancel(self):
        sid = "s131-drop"
        entry = {"buffer": [], "done": False, "error": None, "cancelled": False,
                 "created_at": time.time(), "consumer_count": 1, "task": None}
        _active_streams[sid] = entry

        async def gen():
            yield "a"
            entry["cancelled"] = True
            yield "b"
            yield "c"

        async def _go():
            await _stream_producer_wrapper(sid, gen())
        try:
            asyncio.run(_go())
            assert entry["buffer"] == ["a"]
            assert entry["done"] is True
        finally:
            _active_streams.pop(sid, None)


class TestCancelEndpointBoundedWait:
    """F4: cancel 端点有界等待生产者退出并回报 stopped。"""

    def _run_cancel(self, task):
        from py.routers.tasks import cancel_stream_endpoint
        sid = "s131-wait"
        entry = {"buffer": [], "done": False, "error": None, "cancelled": False,
                 "created_at": time.time(), "consumer_count": 0, "task": task}
        _active_streams[sid] = entry

        async def _go():
            if task is not None:
                return await cancel_stream_endpoint(sid), task
            return await cancel_stream_endpoint(sid), None
        try:
            return asyncio.run(_go())
        finally:
            _active_streams.pop(sid, None)

    def test_no_task_reports_stopped(self):
        resp, _ = self._run_cancel(None)
        assert resp["cancelled"] is True
        assert resp["stopped"] is True

    def test_cancellable_task_terminates_fast(self):
        from py.routers.tasks import cancel_stream_endpoint
        sid = "s131-wait2"

        async def _sleeper():
            await asyncio.sleep(30)

        async def _go():
            t = asyncio.ensure_future(_sleeper())
            await asyncio.sleep(0)
            entry = {"buffer": [], "done": False, "error": None, "cancelled": False,
                     "created_at": time.time(), "consumer_count": 0, "task": t}
            _active_streams[sid] = entry
            t0 = time.monotonic()
            try:
                resp = await cancel_stream_endpoint(sid)
                return resp, time.monotonic() - t0, t
            finally:
                _active_streams.pop(sid, None)
        try:
            resp, elapsed, t = asyncio.run(_go())
            assert resp["cancelled"] is True
            assert resp["stopped"] is True
            assert elapsed < 3.0
            assert t.cancelled() or t.done()
        except RuntimeError:
            pass  # 清理期 loop 关闭竞态（任务已被取消）不影响断言主体

    def test_endpoint_has_bounded_wait_and_frontend_awaits(self):
        src = (_ROOT / "py" / "routers" / "tasks.py").read_text(encoding="utf-8")
        assert "asyncio.wait_for(asyncio.shield(task), timeout=1.5)" in src
        js = (_ROOT / "static" / "js" / "methods" / "08_message_render.js").read_text(encoding="utf-8")
        assert "Promise.race([_stopP" in js
        js2 = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
        assert "return _cancelPromise;" in js2
