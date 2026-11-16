# S230：浏览器流程摩擦修复（evaluate_script 导航写护栏 / navigate_page 等待加载 / markdown 截断与清洗 / wait_for 措辞）
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402


def _read(*p):
    return ROOT.joinpath(*p).read_text(encoding="utf-8")


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


# ---------------- P0: evaluate_script 导航写护栏 ----------------

def test_eval_script_reads_location_normally(monkeypatch):
    calls = _capture(monkeypatch, "http://x/")
    out = asyncio.run(cdp.evaluate_script(
        "function(){ return JSON.stringify({url: location.href, ua: navigator.userAgent.slice(0,10)}); }"))
    assert out == "http://x/"
    assert calls[0][0] == "executeInActiveWebview"
    assert "setTimeout" not in calls[0][1][0]  # 不再被误包装成异步吞值


def test_eval_script_location_write_scheduled(monkeypatch):
    calls = _capture(monkeypatch, "scheduled")
    out = asyncio.run(cdp.evaluate_script("function(){ location.href='https://y.com'; return 1; }"))
    assert out.startswith("[Navigation scheduled]")
    assert "setTimeout" in calls[0][1][0]


def test_eval_script_submit_scheduled(monkeypatch):
    calls = _capture(monkeypatch, "scheduled")
    out = asyncio.run(cdp.evaluate_script("document.getElementById('f').submit()"))
    assert out.startswith("[Navigation scheduled]")
    assert "setTimeout" in calls[0][1][0]


def test_eval_script_string_replace_not_blocked(monkeypatch):
    calls = _capture(monkeypatch, "a_b")
    out = asyncio.run(cdp.evaluate_script("function(){ return 'a b'.replace(' ','_'); }"))
    assert out == "a_b"
    assert "setTimeout" not in calls[0][1][0]


def test_old_swallow_message_gone():
    src = _read("py", "cdp_tool.py")
    assert "Command scheduled" not in src
    assert "[Navigation scheduled]" in src


# ---------------- P1a: navigate_page 等待加载 ----------------

def test_navigate_default_timeout_8(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.navigate_page("url", "https://x.com"))
    assert calls[0][0] == "browserNavigate"
    assert calls[0][1] == ["url", "https://x.com", False, 8]
    assert calls[0][2] == 28  # t + 20


def test_navigate_timeout_zero_no_wait(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.navigate_page("reload", timeout=0))
    assert calls[0][1] == ["reload", None, False, 0]
    assert calls[0][2] == 20


def test_navigate_timeout_clamped(monkeypatch):
    calls = _capture(monkeypatch)
    asyncio.run(cdp.navigate_page("url", "https://x.com", timeout=999))
    assert calls[0][1][3] == 30
    assert calls[0][2] == 50


def test_navigate_schema_documents_timeout():
    fn = _tool("navigate_page")
    assert "timeout" in fn["parameters"]["properties"]
    desc = fn["description"]
    assert "WAITS" in desc and "timeout=0" in desc


def test_snapshot_schema_documents_partial():
    desc = _tool("take_snapshot")["description"]
    assert "PARTIAL" in desc or "partial" in desc


# ---------------- 渲染层 JS 接线（静态断言） ----------------

def test_js_wait_load_stop_wired():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    assert "_waitLoadStop" in src
    assert "(loaded)" in src and "(still loading)" in src
    assert "page still loading" in src  # snapshot 尾注与 wait_for 措辞
    assert "Not found: " in src


def test_js_markdown_path_cleaning_and_cap():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    assert "maxLen || 60000" in src
    assert "400000" in src
    assert "img[src^=" in src and "data:" in src
    assert src.count("AD_SOFT_SEL") >= 3  # 定义 + _applyAdblock + getPageHtml


def test_snapshot_no_hard_loading_error_for_agent_flow():
    # 快照路径不再有硬拒绝（getPageHtml 保留 isLoading 拒绝属预期，不计快照）
    src = _read("static", "js", "methods", "80_webview_agent.js")
    i = src.index("getWebviewSnapshot")
    seg = src[i:i + 600]
    assert 'return "Error: Page is loading..."' not in seg
