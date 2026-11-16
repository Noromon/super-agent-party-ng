# S229：内置浏览器移动端渲染/设备仿真（web_render/new_page/navigate_page 的 mobile + CDP Emulation + App 墙清洗）
import asyncio
import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

OKJSON = json.dumps({"ok": True, "title": "T", "finalUrl": "http://x/", "html": "<p>hi</p>"})


def _read(*p):
    return ROOT.joinpath(*p).read_text(encoding="utf-8")


def _tool(name):
    for t in cdp.all_cdp_tools:
        if t.get("function", {}).get("name") == name:
            return t["function"]
    return None


def _patch(monkeypatch, ret=None):
    calls = []

    async def _targets():
        return [{"type": "page"}]

    async def _vue(method, args=None, timeout=None):
        calls.append((method, args, timeout))
        return ret

    monkeypatch.setattr(cdp, "get_targets", _targets)
    monkeypatch.setattr(cdp, "call_vue_method", _vue)
    return calls


# ---------------- schema ----------------

def test_schema_mobile_flags():
    for n in ("web_render", "new_page", "navigate_page"):
        props = _tool(n)["parameters"]["properties"]
        assert "mobile" in props, n
        assert props["mobile"]["type"] == "boolean", n
    assert "移动" in _tool("web_render")["description"]
    assert "mobile" in _tool("navigate_page")["description"]


# ---------------- 派发 ----------------

def test_web_render_mobile_true_offscreen(monkeypatch):
    calls = _patch(monkeypatch, OKJSON)
    asyncio.run(cdp.web_render("x.com", mobile=True))
    ro = [c for c in calls if c[0] == "renderOffscreenPage"]
    assert ro and ro[0][1][1].get("mobile") is True


def test_web_render_mobile_default_false(monkeypatch):
    calls = _patch(monkeypatch, OKJSON)
    asyncio.run(cdp.web_render("https://x.com"))
    ro = [c for c in calls if c[0] == "renderOffscreenPage"]
    assert ro and ro[0][1][1].get("mobile") is False


def test_new_page_mobile_sets_tab_then(monkeypatch):
    calls = _patch(monkeypatch, "ok")
    asyncio.run(cdp.new_page("https://x.com", mobile=True))
    assert calls[0][0] == "openUrlInNewTab"
    assert ("setTabMobile" in [c[0] for c in calls])
    stm = [c for c in calls if c[0] == "setTabMobile"][0]
    assert stm[1] == [None, True, True]


def test_new_page_no_mobile_no_settabmobile(monkeypatch):
    calls = _patch(monkeypatch, "ok")
    asyncio.run(cdp.new_page("https://x.com"))
    assert calls[0][0] == "openUrlInNewTab"
    assert "setTabMobile" not in [c[0] for c in calls]


def test_navigate_page_mobile_sets_then_navigates(monkeypatch):
    calls = _patch(monkeypatch, "ok")
    asyncio.run(cdp.navigate_page("url", "https://x.com", mobile=True))
    assert calls[0][0] == "setTabMobile" and calls[0][1] == [None, True, False]
    assert calls[1][0] == "browserNavigate"


def test_navigate_page_no_mobile_only_navigates(monkeypatch):
    calls = _patch(monkeypatch, "ok")
    asyncio.run(cdp.navigate_page("reload"))
    assert [c[0] for c in calls] == ["browserNavigate"]


def test_signatures_defaults():
    assert inspect.signature(cdp.web_render).parameters["mobile"].default is False
    assert inspect.signature(cdp.new_page).parameters["mobile"].default is False
    assert inspect.signature(cdp.navigate_page).parameters["mobile"].default is None


# ---------------- 渲染层 JS 接线（静态断言，无 Electron） ----------------

def test_render_offscreen_mobile_js():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    assert "MOBILE_UA" in src
    assert "Linux; Android 13; Pixel 7" in src
    assert "Chrome/124" in src
    assert "mobile ? 414" in src
    assert "mobile ? MOBILE_UA" in src


def test_walls_selector_wired():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    assert "const WALLS_SEL" in src
    assert src.count("WALLS_SEL") >= 4  # 定义 + 离屏清洗 + _applyAdblock + getPageHtml
    low = src.lower()
    assert "open-app" in low and "login" in low and "download-app" in low


def test_settabmobile_method_present():
    src = _read("static", "js", "methods", "98_browser_tabs.js")
    for token in ("setTabMobile", "toggleTabMobile", "setWebviewMobile",
                  "getWebContentsId", "mobile: false"):
        assert token in src, token


def test_preload_bridge():
    src = _read("static", "js", "preload.js")
    assert "setWebviewMobile" in src and "set-webview-mobile" in src


def test_main_handler():
    src = _read("main.js")
    for token in ("ipcMain.handle('set-webview-mobile'", "SAP_MOBILE_UA",
                  "Emulation.setUserAgentOverride", "Emulation.setDeviceMetricsOverride",
                  "Emulation.setTouchEmulationEnabled", "_sapMobileDbg",
                  "debugger.attach", "debugger.detach", "webContents.fromId"):
        assert token in src, token
    assert "Linux; Android 13; Pixel 7" in src


def test_toggle_button_in_both_hosts():
    for rel in (("static", "index.html"), ("static", "templates", "page_chat_bar.html")):
        src = _read(*rel)
        assert "toggleTabMobile" in src, rel
        assert "browserMobile" in src, rel
        assert "fa-mobile-screen-button" in src, rel


def test_i18n_mobile_keys():
    zh = _read("static", "js", "locales", "zh-CN.js")
    en = _read("static", "js", "locales", "en-US.js")
    for k in ("browserMobile", "browserMobileNoPage"):
        assert k in zh and k in en, k
