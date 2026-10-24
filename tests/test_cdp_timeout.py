# S94：CDP 全链超时 + 退出链不被渲染进程劫持 + 懒加载 webview
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import py.cdp_tool as cdp  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class _HangWS:
    def __init__(self):
        self.sent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, msg):
        self.sent = msg

    async def recv(self):
        await asyncio.Event().wait()


class _CountingConnect:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1
        return _HangWS()


@pytest.fixture()
def hang_env(monkeypatch):
    conn = _CountingConnect()
    monkeypatch.setattr(cdp.websockets, "connect", conn)

    async def _fake_ws_url():
        return "ws://fake"

    monkeypatch.setattr(cdp, "get_main_window_ws", _fake_ws_url)
    monkeypatch.setattr(cdp, "CDP_CALL_TIMEOUT", 0.3)
    return conn


def test_cdp_command_raises_timeout(hang_env):
    with pytest.raises(asyncio.TimeoutError):
        asyncio.run(cdp.cdp_command("ws://fake", "Runtime.evaluate", {}, timeout=0.3))


def test_call_vue_method_timeout_returns_error_without_retry(hang_env):
    out = asyncio.run(cdp.call_vue_method("openUrlInNewTab", ["https://example.com"]))
    assert isinstance(out, str)
    assert "超时" in out
    # S94 关键语义：超时只尝试一次，不重试（防 new_page 类副作用重复执行）
    assert hang_env.calls == 1


def test_main_js_quit_chain_timeout():
    src = _read("main.js")
    seg = src[src.index("before-quit"):]
    assert "Promise.race" in seg
    assert "3000" in seg[:1500]


def test_ai_browser_webview_lazy_src():
    src = _read("static/templates/page_ai-browser.html")
    assert ':src="tab.loaded ? tab.url' in src
    src2 = _read("static/js/methods/98_browser_tabs.js")
    assert "tab.loaded = true" in src2


def test_cdp_tool_timeout_wiring():
    src = _read("py/cdp_tool.py")
    assert "CDP_CALL_TIMEOUT" in src
    assert "asyncio.wait_for" in src
    assert "except asyncio.TimeoutError" in src
