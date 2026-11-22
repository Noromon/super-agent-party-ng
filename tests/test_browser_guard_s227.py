# S227：重定向护栏（guardRedirect，默认关闭）——主进程拦截 + 审批工具 + 接线 + 设置
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


def _capture(monkeypatch, ret="[]"):
    calls = []

    async def _vue(method, args=None, timeout=None):
        calls.append((method, args))
        return ret

    monkeypatch.setattr(cdp, "call_vue_method", _vue)
    return calls


def test_guard_schemas_registered():
    assert _tool("check_redirect") is not None
    fn = _tool("approve_navigation")
    assert fn is not None
    assert "allow" in fn["parameters"]["properties"]


def test_check_redirect_dispatch(monkeypatch):
    calls = _capture(monkeypatch, '[{"id":7,"url":"http://evil"}]')
    out = asyncio.run(cdp.check_redirect())
    assert calls[0][0] == "listPendingRedirects"
    assert "evil" in out


def test_approve_navigation_dispatch(monkeypatch):
    calls = _capture(monkeypatch, "redirect allowed")
    asyncio.run(cdp.approve_navigation(True, 7))
    assert calls[0] == ("resolveRedirect", [True, 7])
    asyncio.run(cdp.approve_navigation(False))
    assert calls[1] == ("resolveRedirect", [False, None])


def test_server_wiring_mirrored():
    # S301：钩子表构建迁 py/tool_hooks.py，两表镜像计数在合并面上守恒（表体逐字未动）
    src = (_read("server.py") + _read("py/tool_hooks.py") + _read("py/approval_exec.py"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）
    for n in ("check_redirect", "approve_navigation"):
        assert src.count(f'"{n}": {n},') == 2, n
    assert src.count("check_redirect, approve_navigation") == 2


def test_main_guard_logic():
    src = _read("main.js")
    assert "function setupRedirectGuard" in src
    assert "global.guardRedirect = false" in src
    assert "persist:party-browser-session" in src
    assert "contents.on('will-navigate'" in src
    assert "contents.on('will-redirect'" in src
    assert "e.preventDefault()" in src
    for tok in ("ipcMain.handle('set-guard-flag'", "ipcMain.handle('guard-authorize'",
                "ipcMain.handle('guard-list'", "ipcMain.handle('guard-decide'"):
        assert tok in src, tok
    assert "wc.loadURL(url)" in src


def test_preload_guard_bridge():
    src = _read("static/js/preload.js")
    for tok in ("guardAuthorize", "guardList", "guardDecide", "setGuardFlag"):
        assert tok in src, tok


def test_renderer_guard_methods():
    src = _read("static/js/methods/80_webview_agent.js")
    for m in ("_guardAuthNav(url)", "listPendingRedirects()", "resolveRedirect(allow, id)",
              "onGuardRedirectChange()"):
        assert m in src, m
    # 后台/前台导航都先授权
    tabs = _read("static/js/methods/98_browser_tabs.js")
    assert tabs.count("this._guardAuthNav(url)") == 2  # navigateTo + openUrlInNewTab


def test_guard_off_by_default_settings():
    assert '"guardRedirect": false' in _read("config/settings_template.json")
    assert "guardRedirect: false" in _read("static/js/data/20_brain_settings.js")


def test_guard_ui_and_flag_sync():
    tpl = _read("static/templates/page_toolkit.html")
    assert "chromeMCPGuard" in tpl and "onGuardRedirectChange" in tpl
    assert "setGuardFlag" in _read("static/js/renderer.js")


def test_guard_locale_parity():
    zh = _read("static/js/locales/zh-CN.js")
    en = _read("static/js/locales/en-US.js")
    for k in ("chromeMCPGuard", "chromeMCPGuardHint"):
        assert k in zh and k in en
