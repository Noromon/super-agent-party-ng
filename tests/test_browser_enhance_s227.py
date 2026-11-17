# S227：浏览器增强（反弹窗/拔元素/急停后退/取页MD/后台标签）+ 接线/渲染层/设置
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _tool(name):
    for t in cdp.all_cdp_tools:
        if t.get("function", {}).get("name") == name:
            return t["function"]
    return None


def _capture(monkeypatch, ret="ok"):
    calls = []

    async def _vue(method, args=None, timeout=None):
        calls.append((method, args, timeout))
        return ret

    monkeypatch.setattr(cdp, "call_vue_method", _vue)
    return calls


# ---------------- schemas ----------------

def test_enhance_schemas_registered():
    for n in ("clean_dom", "remove_element", "stop_loading", "escape_back", "get_page_markdown"):
        assert _tool(n) is not None, n


def test_new_page_background_param():
    props = _tool("new_page")["parameters"]["properties"]
    assert "background" in props


# ---------------- 派发 ----------------

def test_clean_dom_forwards_force(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.clean_dom(True))
    assert calls[0][0] == "cleanPage" and calls[0][1] == [True]


def test_remove_element_requires_target(monkeypatch):
    _capture(monkeypatch)
    out = asyncio.run(cdp.remove_element("  "))
    assert out.startswith("[Error]")


def test_remove_element_forwards_target(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.remove_element(".popup-close"))
    assert calls[0][0] == "removeElement" and calls[0][1] == [".popup-close"]


def test_get_page_markdown_ok(monkeypatch):
    _capture(monkeypatch, "<h2>Head</h2><p>Body text present</p>")
    out = asyncio.run(cdp.get_page_markdown())
    assert "Body text present" in out
    assert "## Head" in out


def test_get_page_markdown_error_passthrough(monkeypatch):
    _capture(monkeypatch, "Error: Page is loading...")
    out = asyncio.run(cdp.get_page_markdown())
    assert out.startswith("Error")


def test_get_page_markdown_empty(monkeypatch):
    _capture(monkeypatch, "   ")
    out = asyncio.run(cdp.get_page_markdown())
    assert out.startswith("[Empty]")


def test_new_page_background_routes(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.new_page("https://x.com", background=True))
    assert calls[0][0] == "openUrlInBackground"
    asyncio.run(cdp.new_page("https://x.com"))
    assert calls[1][0] == "openUrlInNewTab"


def test_stop_and_escape(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.stop_loading())
    asyncio.run(cdp.escape_back())
    assert calls[0][0] == "stopLoading"
    assert calls[1][0] == "escapeBack"


# ---------------- 接线（双镜像） ----------------

def test_server_wiring_mirrored():
    src = _read("server.py")
    for n in ("clean_dom", "remove_element", "stop_loading", "escape_back", "get_page_markdown"):
        assert src.count(f'"{n}": {n},') == 2, n
    assert src.count("clean_dom, remove_element,") == 2


# ---------------- 渲染层方法 ----------------

def test_renderer_methods_present():
    src = _read("static/js/methods/80_webview_agent.js")
    for m in ("_applyAdblock(wv, hard)", "cleanPage(force)", "removeElement(target)",
              "stopLoading()", "escapeBack()", "getPageHtml()", "openUrlInBackground(url, partition)"):
        assert m in src, m
    assert "__sap_adblock__" in src


def test_domready_auto_adblock():
    src = _read("static/js/methods/98_browser_tabs.js")
    assert "this.chromeMCPSettings.adblock !== false" in src
    assert "this._applyAdblock(webview, false)" in src


def test_open_bg_does_not_steal_active_menu():
    src = _read("static/js/methods/80_webview_agent.js")
    seg = src[src.index("openUrlInBackground(url, partition)"):]
    seg = seg[:seg.index("renderOffscreenPage")]
    # 不写 this.activeMenu（仅注释提到 activeMenu 不算抢占）
    assert "this.activeMenu" not in seg


# ---------------- 设置链 + locales ----------------

def test_adblock_defaults():
    assert '"adblock": true' in _read("config/settings_template.json")
    assert "adblock: true" in _read("static/js/data/20_brain_settings.js")


def test_adblock_ui_switch():
    src = _read("static/templates/page_toolkit.html")
    assert "chromeMCPAdblock" in src
    assert "chromeMCPSettings.adblock !== false" in src


def test_adblock_locale_parity():
    zh = _read("static/js/locales/zh-CN.js")
    en = _read("static/js/locales/en-US.js")
    for k in ("chromeMCPAdblock", "chromeMCPAdblockHint"):
        assert k in zh and k in en
