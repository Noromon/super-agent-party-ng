# -*- coding: utf-8 -*-
"""S154：XmppClient.run() 全路径收尾保证。

就绪超时（连接失败主路径）时旧实现直接抛穿 run()，slixmpp 重连任务与
aiohttp session 全部泄漏 → 僵尸重连 + 管理器线程不可恢复。
现要求：任何出口都必须 disconnect + session.close + 清扫本 loop 残留任务。
"""
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.xmpp_client as xc  # noqa: E402


class _FakeXMPP:
    def __init__(self, *a, **k):
        self.disconnect_calls = 0

    def register_plugin(self, _p):
        pass

    def add_event_handler(self, *_a):
        pass

    def connect(self, host=None, port=None):
        pass

    def disconnect(self, preserve=False):
        self.disconnect_calls += 1


class _FakeSession:
    def __init__(self, **_kw):
        self.closed = False

    async def close(self):
        self.closed = True


def _make_client():
    client = xc.XmppClient()
    client.bot_username, client.bot_password, client.domain = "u", "p", "d"
    client.service_url = "tcp://localhost:5222"
    return client


def test_run_ready_timeout_full_teardown(monkeypatch):
    box = {}

    def _session(**kw):
        s = _FakeSession()
        box["session"] = s
        return s

    def _xmpp(*a, **k):
        x = _FakeXMPP()
        box["xmpp"] = x
        return x

    async def _raise_timeout(fut, timeout=None):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(xc.aiohttp, "ClientSession", _session)
    monkeypatch.setattr(xc.aiohttp, "TCPConnector", lambda **k: object())
    monkeypatch.setattr(xc.aiohttp, "ThreadedResolver", lambda *a, **k: object())
    monkeypatch.setattr(xc.slixmpp, "ClientXMPP", _xmpp)
    monkeypatch.setattr(xc.asyncio, "wait_for", _raise_timeout)

    client = _make_client()

    async def _body():
        # 模拟 slixmpp 内部重连任务：run() 出口后必须被清扫
        ran = []

        async def _zombie():
            try:
                await asyncio.sleep(30)
                ran.append(True)
            except asyncio.CancelledError:
                raise

        zombie = asyncio.ensure_future(_zombie())
        try:
            await client.run()
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0)  # 让被取消任务完成收尾
        assert zombie.cancelled() and not ran

    asyncio.run(_body())
    assert box["session"].closed is True, "就绪超时未关闭 aiohttp session"
    assert box["xmpp"].disconnect_calls == 1, "就绪超时未 disconnect slixmpp"
    assert client.session is None
    assert client._tearing_down is True


def test_teardown_survives_missing_attrs():
    # ClientXMPP 构造失败（self.xmpp 尚未赋值）时 teardown 不得二次抛穿
    client = _make_client()
    del client.xmpp

    async def _body():
        await client._teardown()

    asyncio.run(_body())  # 不抛即通过
    assert client._tearing_down is True


def test_disconnected_log_suppressed_during_teardown():
    client = _make_client()
    client._tearing_down = True
    client._on_disconnected(None)  # 静默路径不抛
    assert client._is_ready is False
