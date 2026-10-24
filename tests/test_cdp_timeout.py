# S94：CDP 全链超时 + 退出链不被渲染进程劫持 + 懒加载 webview
import asyncio
import re
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


def test_s95_tab_url_writes_set_loaded():
    src = _read("static/js/methods/98_browser_tabs.js")
    # navigateTo / goHome / loadUrlInCurrentTab 三处 URL 写回必须同步放行懒加载
    assert src.count("currentTab.loaded = true") == 3
    # openUrlInNewTab / onNewWindow 两处建 tab 即带 URL，直接置 loaded
    assert src.count("loaded: true,") == 2


def test_s95_main_js_unresponsive_probe():
    src = _read("main.js")
    for token in ("[WinUnresponsive]", "[WinResponsive]", "[WinRendererGone]"):
        assert token in src
    # S98 起探针集中于 attachFreezeProbe，两条建窗路径必须都调用（数量 pin 在
    # test_s98_freeze_auto_profiler）
    assert src.count("on('unresponsive'") >= 1


def test_s95_timeout_budget_tightened():
    src = _read("py/cdp_tool.py")
    m = re.search(r"^CDP_CALL_TIMEOUT\s*=\s*([0-9.]+)", src, re.M)
    assert m and float(m.group(1)) <= 30
    ws = _read("py/web_search.py")
    assert "requests.get(url, headers=headers, timeout=30" in ws


def test_s98_freeze_auto_profiler():
    src = _read("main.js")
    assert "function attachFreezeProbe" in src
    # unresponsive 触发即采样，profile 落盘可回传分析
    assert "Profiler.setSamplingInterval" in src
    assert "sap-freeze-profile-" in src
    assert "[FreezeDiag]" in src
    # 两条建窗路径都必须挂上
    assert src.count("attachFreezeProbe(mainWindow)") == 2
