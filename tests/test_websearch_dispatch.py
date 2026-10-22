# -*- coding: utf-8 -*-
"""搜索引擎/爬虫公告分发 pin（上游 dbaccbf7 并入后回归，S65.1）+ DDG 后端钉死（S69）。"""
import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

# Must precede any py.get_setting import: keep paths out of the production dir.
os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_websearch_test_")

# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

_S = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()


def test_engine_tools_announced_by_engine_key():
    # serper/bochaai/youcom 是 engine 值，公告必须挂 engine==（crawler UI 无这三个值）
    for v in ("serper", "bochaai", "youcom"):
        assert "settings['webSearch']['crawler'] == '%s'" % v not in _S, v
        assert _S.count("settings['webSearch']['engine'] == '%s'" % v) == 4, v  # 2 检索 + 2 公告


def test_real_crawlers_stay_on_crawler_key():
    for v in ("jina", "crawl4ai", "firecrawl"):
        assert "settings['webSearch']['crawler'] == '%s'" % v in _S, v


# ---------------------------------------------------------------- S69: DDG backend pin

def _fake_settings():
    async def _load():
        return {"webSearch": {"duckduckgo_max_results": 5},
                "systemSettings": {"proxy": "http://127.0.0.1:7890"}}
    return _load


class _FakeDDGS:
    calls = []
    ctor = []

    def __init__(self, proxy=None, timeout=None, **kw):
        _FakeDDGS.ctor.append({"proxy": proxy, "timeout": timeout})

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def text(self, query, **kwargs):
        _FakeDDGS.calls.append({"query": query, **kwargs})
        return [{"title": "T1", "href": "https://ddg.example/1", "body": "B1"},
                {"title": "T2", "href": "https://ddg.example/2", "body": "B2"}]


def test_ddgsearch_pins_single_backend_and_maps_fields(monkeypatch):
    from py import web_search as ws
    _FakeDDGS.calls.clear()
    _FakeDDGS.ctor.clear()
    monkeypatch.setattr(ws, "DDGS", _FakeDDGS)
    monkeypatch.setattr(ws, "load_settings", _fake_settings())

    out = asyncio.run(ws.DDGsearch("测试 query"))

    parsed = json.loads(out)
    assert [r["link"] for r in parsed] == ["https://ddg.example/1", "https://ddg.example/2"]
    assert parsed[0]["title"] == "T1" and parsed[0]["snippet"] == "B1"
    assert _FakeDDGS.calls[0]["backend"] == "duckduckgo"
    assert _FakeDDGS.calls[0]["max_results"] == 5
    # 代理透传（systemSettings.proxy → DDGS(proxy=)）与超时放宽
    assert _FakeDDGS.ctor[0]["proxy"] == "http://127.0.0.1:7890"
    assert _FakeDDGS.ctor[0]["timeout"] == 30


def test_ddgsearch_failure_keeps_error_contract(monkeypatch):
    from py import web_search as ws

    class _BoomDDGS(_FakeDDGS):
        def text(self, query, **kwargs):
            raise RuntimeError("ratelimited")

    monkeypatch.setattr(ws, "DDGS", _BoomDDGS)
    monkeypatch.setattr(ws, "load_settings", _fake_settings())

    out = asyncio.run(ws.DDGsearch("q"))
    assert out.startswith("[Error]")


def test_ddgsearch_backend_pin_no_langchain_auto_wrapper():
    src = io.open(_ROOT / "py" / "web_search.py", encoding="utf-8-sig").read()
    assert 'backend="duckduckgo"' in src
    assert "DuckDuckGoSearchResults" not in src
