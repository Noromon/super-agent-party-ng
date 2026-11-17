# S227：本地无头渲染动态页 -> Markdown（web_render）+ HTML→MD 工具 + 接线/离屏方法
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
from py.html_to_md import html_to_markdown  # noqa: E402


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ---------------- html_to_markdown ----------------

def test_html_to_md_strips_noise_keeps_link():
    md = html_to_markdown(
        "<nav>NAVX</nav><h1>Title</h1><p>Hello <a href='http://e.com'>link</a></p>"
        "<script>evil()</script><footer>FOOTX</footer>"
    )
    assert "# Title" in md
    assert "[link](http://e.com)" in md
    assert "NAVX" not in md
    assert "FOOTX" not in md
    assert "evil" not in md


def test_html_to_md_truncate():
    big = "<p>" + ("word " * 500) + "</p>"
    md = html_to_markdown(big, max_chars=80)
    assert "truncated" in md
    assert len(md) < 400


def test_html_to_md_empty():
    assert html_to_markdown("") == ""


# ---------------- web_render 编排（mock CDP，无 Electron） ----------------

def _patch(monkeypatch, targets, vue_return):
    async def _targets():
        return targets

    async def _vue(method, args=None, timeout=None):
        _vue.last_timeout = timeout
        return vue_return

    monkeypatch.setattr(cdp, "get_targets", _targets)
    monkeypatch.setattr(cdp, "call_vue_method", _vue)
    return _vue


def test_web_render_ok(monkeypatch):
    payload = json.dumps({"ok": True, "title": "T", "finalUrl": "http://x/",
                          "html": "<h1>Hello</h1><p>Body text here</p>"})
    vue = _patch(monkeypatch, [{"type": "page"}], payload)
    out = asyncio.run(cdp.web_render("x.com", timeout=20))
    assert out.startswith("# T")
    assert "Source: http://x/" in out
    assert "Body text here" in out
    # 放宽 CDP 超时：调用应带 timeout=t+20
    assert vue.last_timeout == 40


def test_web_render_unavailable(monkeypatch):
    _patch(monkeypatch, [], "{}")
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Error]")
    assert "内置浏览器" in out


def test_web_render_default_timeout(monkeypatch):
    payload = json.dumps({"ok": True, "title": "T", "finalUrl": "http://x/",
                          "html": "<p>Body text here</p>"})
    vue = _patch(monkeypatch, [{"t": 1}], payload)
    asyncio.run(cdp.web_render("https://x.com"))
    # 默认 45s -> CDP timeout = 45 + 20 = 65
    assert vue.last_timeout == 65


def test_web_render_timeout_clamp(monkeypatch):
    payload = json.dumps({"ok": True, "title": "T", "finalUrl": "http://x/",
                          "html": "<p>Body text here</p>"})
    vue = _patch(monkeypatch, [{"t": 1}], payload)
    asyncio.run(cdp.web_render("https://x.com", timeout=999))
    # clamp 到 60 -> CDP timeout = 60 + 20 = 80
    assert vue.last_timeout == 80


def test_web_render_partial_flag(monkeypatch):
    payload = json.dumps({"ok": True, "partial": True, "title": "T", "finalUrl": "http://x/",
                          "html": "<p>Partial body text</p>"})
    _patch(monkeypatch, [{"t": 1}], payload)
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert "(partial)" in out
    assert "Partial body text" in out


def test_web_render_failed(monkeypatch):
    _patch(monkeypatch, [{"t": 1}], json.dumps({"ok": False, "error": "render timeout"}))
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Fetch failed]")
    assert "render timeout" in out
    # 超时应给出可操作提示：提到内置浏览器不走 SAP 代理
    assert "代理" in out


def test_web_render_no_content_hint(monkeypatch):
    _patch(monkeypatch, [{"t": 1}], json.dumps({"ok": False, "error": "no-content"}))
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Fetch failed]")
    assert "wait_text" in out


def test_web_render_load_failed_hint(monkeypatch):
    _patch(monkeypatch, [{"t": 1}],
           json.dumps({"ok": False, "error": "load failed -105 ERR_NAME_NOT_RESOLVED"}))
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Fetch failed]")
    assert "代理" in out


def test_web_render_empty_body(monkeypatch):
    _patch(monkeypatch, [{"t": 1}], json.dumps({"ok": True, "title": "", "html": ""}))
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Empty]")


def test_web_render_bad_json_is_error(monkeypatch):
    _patch(monkeypatch, [{"t": 1}], "not-json-error-string")
    out = asyncio.run(cdp.web_render("https://x.com"))
    assert out.startswith("[Fetch failed]")


# ---------------- 注册/接线/离屏方法 ----------------

def _tool(name):
    for t in cdp.all_cdp_tools:
        if t.get("function", {}).get("name") == name:
            return t["function"]
    return None


def test_schema_registered_local_md():
    fn = _tool("web_render")
    assert fn is not None
    desc = fn["description"]
    assert "Markdown" in desc
    assert ("本地" in desc) or ("无第三方" in desc)
    assert "original_url" in fn["parameters"]["properties"]


def test_server_wiring_mirrored():
    src = _read("server.py")
    assert src.count('"web_render": web_render,') == 2
    assert src.count("handle_dialog, web_render, clean_dom,") == 2


def test_offscreen_renderer_method_present():
    src = _read("static/js/methods/80_webview_agent.js")
    assert "renderOffscreenPage(url, opts)" in src
    assert "createElement('webview')" in src
    assert "left:-20000px" in src
    assert "persist:agent-proxy' : 'persist:agent-direct" in src  # S236: 离屏走 agent 专用出口分区


def test_call_vue_method_accepts_timeout():
    assert "timeout" in inspect.signature(cdp.call_vue_method).parameters


def test_gated_by_internal_browser():
    src = _read("py/tool_assembly.py")
    assert 'tools.extend(tk["all_cdp_tools"])' in src
    assert "chromeMCPSettings']['type'] == 'internal'" in src
