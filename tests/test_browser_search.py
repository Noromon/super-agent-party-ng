# -*- coding: utf-8 -*-
"""S90：浏览器搜索引擎——模板/JS 协议/回退编排 + server 接线 pin。"""
import asyncio
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("SAP_DATA_DIR", tempfile.mkdtemp(prefix="sap_s90_"))
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import json  # noqa: E402

import pytest  # noqa: E402

import py.web_search as ws_mod  # noqa: E402
from py.web_search_browser import (  # noqa: E402
    BROWSER_ORDER, ENGINE_TEMPLATES, GUIDE_HINT, JS_TABLE,
    _resolve_target, browser_equiv, browser_search, search_result_ok)

ROOT = _ROOT


def test_templates_and_order():
    assert ENGINE_TEMPLATES["ddg"].startswith("https://duckduckgo.com/")
    assert "brave" in ENGINE_TEMPLATES  # 用户拍板：首批收录
    assert BROWSER_ORDER == ["ddg", "brave", "cnbing", "baidu", "so360"]
    for e in BROWSER_ORDER + ["bing", "general"]:
        assert JS_TABLE.get(e), f"缺 {e} 抽取 JS"
    for e in BROWSER_ORDER:
        assert ENGINE_TEMPLATES.get(e), f"缺 {e} URL 模板"


def test_js_protocol_and_safety():
    for name, js in JS_TABLE.items():
        assert "location" not in js, f"{name} JS 含 location（cdp_tool 会拦截）"
        assert "submit()" not in js, f"{name} JS 含 submit()"
        assert "anti" in js and "results" in js and "readyState" in js
    assert '"mu"' in JS_TABLE["baidu"] or "mu" in JS_TABLE["baidu"]
    assert "c-container" in JS_TABLE["baidu"]
    assert "res-list" in JS_TABLE["so360"]
    assert 'data-testid="result"' in JS_TABLE["ddg"]
    assert "b_algo" in JS_TABLE["cnbing"] and JS_TABLE["cnbing"] == JS_TABLE["bing"]
    assert "snippet" in JS_TABLE["brave"]


def test_browser_equiv_matrix():
    assert browser_equiv("duckduckgo") == "ddg"
    assert browser_equiv("bing") == "cnbing"
    assert browser_equiv("brave") == "brave"
    assert browser_equiv("tavily") is None
    assert browser_equiv("no-such") is None


def test_search_result_ok():
    ok = json.dumps([{"title": "t", "url": "u", "snippet": "s"}])
    assert search_result_ok(ok)
    assert not search_result_ok("[Error] boom")
    assert not search_result_ok("")
    assert not search_result_ok("[]")
    assert not search_result_ok("短")
    assert search_result_ok("x" * 40)


def test_resolve_target():
    assert _resolve_target("ddg")[:2] == ("ddg", "ddg")
    name, tpl, js = _resolve_target("https://x.example/s?q={q}")
    assert name == "custom" and "{q}" in tpl and js == "general"
    assert _resolve_target("nope")[0] is None


def test_browser_search_unavailable(monkeypatch):
    async def _no_targets():
        return []

    import py.cdp_tool as cdp_mod
    monkeypatch.setattr(cdp_mod, "get_targets", _no_targets)
    out = asyncio.run(browser_search("test"))
    assert out.startswith("[Error]") and "[引导]" in out


def test_fallback_wrapper(monkeypatch):
    good = json.dumps([{"title": "t", "url": "u", "snippet": "s"}])

    async def _br_ok(query, engine=None, max_results=8):
        return good

    async def _br_fail(query, engine=None, max_results=8):
        return "[Error] 全部尝试引擎均失败"

    monkeypatch.setattr(ws_mod, "browser_search", _br_ok)

    async def _fail_fn(q):
        return "[Error] http engine down"

    w = ws_mod.make_engine_with_fallback("duckduckgo", _fail_fn)
    out = asyncio.run(w("q"))
    assert out.startswith("（经内置浏览器）") and good in out

    async def _boom(q):
        raise RuntimeError("kaboom")

    w2 = ws_mod.make_engine_with_fallback("duckduckgo", _boom)
    out2 = asyncio.run(w2("q"))
    assert out2.startswith("（经内置浏览器）")  # 兜底成功只给干净结果

    monkeypatch.setattr(ws_mod, "browser_search", _br_fail)
    out3 = asyncio.run(w("q"))
    assert "http engine down" in out3 and "全部尝试引擎均失败" in out3

    async def _ok_fn(q):
        return good

    w3 = ws_mod.make_engine_with_fallback("duckduckgo", _ok_fn)
    assert asyncio.run(w3("q")) == good


def test_websearch_with_fallback_browser_mode(monkeypatch):
    good = json.dumps([{"title": "t", "url": "u", "snippet": "s"}])

    async def _br_ok(query, engine=None, max_results=8):
        return good

    async def _br_fail(query, engine=None, max_results=8):
        return "[Error] 全部尝试引擎均失败"

    monkeypatch.setattr(ws_mod, "browser_search", _br_ok)
    assert asyncio.run(ws_mod.websearch_with_fallback("browser", "q")) == good
    monkeypatch.setattr(ws_mod, "browser_search", _br_fail)
    out = asyncio.run(ws_mod.websearch_with_fallback("browser", "q"))
    assert GUIDE_HINT in out
    out2 = asyncio.run(ws_mod.websearch_with_fallback("no-such-engine", "q"))
    assert "未配置的搜索引擎" in out2


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_server_wiring_pins():
    sv = _src("server.py")
    assert sv.count("websearch_with_fallback(") >= 2
    assert sv.count('"browser_lookup": browser_search') == 2
    assert sv.count("make_engine_with_fallback as _fb") == 2
    assert sv.count("_fb(") >= 20
    assert sv.count("tools.append(browser_search_tool)") == 2
    assert "make_engine_with_fallback" in _src("py/web_search.py")

    tpl = _src("static/templates/page_toolkit.html")
    assert 'value="browser"' in tpl
    for loc in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        assert "browserEngineOption" in _src(loc)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
