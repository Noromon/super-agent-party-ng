# S247：tab_id 稳定寻址——select/close/navigate 经 list_pages 的 id 定位，免疫 index 平移
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

_PAGES = json.dumps([
    {"index": 0, "id": 111, "title": "a", "url": "ua", "active": False},
    {"index": 1, "id": 222, "title": "b", "url": "ub", "active": True},
    {"index": 2, "id": 333, "title": "c", "url": "uc", "active": False},
])


def _spy(pages=_PAGES):
    calls = []

    async def fake(method, args, **kw):
        calls.append((method, args))
        if method == "getPagesInfo":
            return pages
        return "ok"
    return calls, fake


def _run(calls, fake, coro_fn):
    orig = cdp.call_vue_method
    cdp.call_vue_method = fake
    try:
        return asyncio.run(coro_fn())
    finally:
        cdp.call_vue_method = orig


def test_select_page_by_tab_id_resolves_current_index():
    calls, fake = _spy()
    out = _run(calls, fake, lambda: cdp.select_page(tab_id=333))
    assert out == "ok"
    assert calls[-1] == ("switchTabByIndex", [2])


def test_close_page_tab_id_precedence_and_missing():
    calls, fake = _spy()
    _run(calls, fake, lambda: cdp.close_page(pageIdx=0, tab_id=111))
    assert calls[-1] == ("closeTabByIndex", [0])  # id 解析出的 index（此处与 pageIdx 无关，resolve 为准）
    calls2, fake2 = _spy()
    out = _run(calls2, fake2, lambda: cdp.close_page(tab_id=999))
    assert out.startswith("[Error]") and "999" in out
    assert ("closeTabByIndex", 0) not in calls2  # 解析失败不触 Vue 关标签
    out2 = _run(calls2, fake2, lambda: cdp.close_page())
    assert "需要 pageIdx 或 tab_id" in out2


def test_navigate_page_tab_id_selects_first():
    calls, fake = _spy()

    async def go():
        return await cdp.navigate_page(type="url", url="https://x.test", tab_id=111, timeout=0)
    out = _run(calls, fake, go)
    assert out == "ok"
    seq = [m for m, _ in calls]
    assert seq[0] == "getPagesInfo" and seq[1] == "switchTabByIndex"  # 先选后导航
    assert ("switchTabByIndex", [0]) in calls
    assert calls[-1][0] == "browserNavigate"
    assert calls[-1][1][1] == "https://x.test"


def test_navigate_page_tab_id_error_passthrough():
    calls, fake = _spy()

    async def go():
        return await cdp.navigate_page(type="url", url="u", tab_id=777)
    out = _run(calls, fake, go)
    assert out.startswith("[Error]")
    assert not [m for m in calls if m[0] == "browserNavigate"]


def test_pageidx_legacy_path_unchanged():
    calls, fake = _spy()
    _run(calls, fake, lambda: cdp.select_page(1))
    assert ("getPagesInfo", []) not in calls  # 未传 tab_id 零额外查询
    assert calls == [("switchTabByIndex", [1])]


def test_schemas_advertise_tab_id():
    by = {t["function"]["name"]: t["function"] for t in cdp.all_cdp_tools}
    for name in ("select_page", "close_page", "navigate_page"):
        assert "tab_id" in by[name]["parameters"]["properties"], name
    assert not by["select_page"]["parameters"].get("required")
    assert not by["close_page"]["parameters"].get("required")
    assert "STABLE" in by["list_pages"]["description"]
    assert "list_pages" in by["new_page"]["description"]
