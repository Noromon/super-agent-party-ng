# S248：web_render 骨架屏不再当完整正文抢答 + net-diag/ctx 诊断行
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

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def _render(payload):
    async def fake_targets():
        return [1]

    async def fake_vue(method, args, **kw):
        return json.dumps(payload)
    orig_t, orig_v = cdp.get_targets, cdp.call_vue_method
    cdp.get_targets, cdp.call_vue_method = fake_targets, fake_vue
    try:
        return asyncio.run(cdp.web_render(original_url="https://x.test", timeout=5))
    finally:
        cdp.get_targets, cdp.call_vue_method = orig_t, orig_v


def test_vue_sentinels():
    assert "__netcap" in JS and "XMLHttpRequest.prototype.open" in JS
    assert "isStalled" in JS and "stallSeen" in JS
    assert "wait_text_not_seen" in JS and "async_load_stalled" in JS
    assert "txt:((document.body&&document.body.innerText)" in JS
    assert "cookieLen" in JS and "navigator.userAgent" in JS
    assert "!wv.isLoading() && !stallSeen" in JS
    assert "executeJavaScript(NETCAP)" in JS


def test_skeleton_short_text_downgraded_by_py_fallback():
    out = _render({"ok": True, "partial": False, "title": "t", "finalUrl": "u",
                   "html": "<p>正在玩命加载数据</p>", "ua": "iPhone", "cookieLen": 5})
    assert "async_load_stalled" in out
    assert "以上应为完整正文" not in out
    assert "非完整正文" in out
    assert "[ctx] ua=iPhone" in out


def test_clean_full_body_still_declared_complete():
    body = "<p>" + ("贴吧真帖内容一条。" * 40) + "</p>"
    out = _render({"ok": True, "partial": False, "title": "t", "finalUrl": "u", "html": body})
    assert "以上应为完整正文" in out
    assert "partial=true" not in out


def test_net_diag_and_reason_passthrough():
    out = _render({"ok": True, "partial": True, "reason": "wait_text_not_seen", "title": "",
                   "finalUrl": "u", "html": "<p>骨架</p>",
                   "net": [{"u": "https://m.weibo.cn/api/a", "s": 200},
                           {"u": "https://tieba/api/data", "s": 403},
                           {"u": "https://x/api/b", "s": -1}]})
    assert "reason=wait_text_not_seen" in out
    assert "[net-diag] reqs=3" in out
    assert "tieba/api/data (403)" in out
    assert "x/api/b (failed)" in out
    assert "4xx/被拒" in out


def test_page_meta_and_net_diag_helpers():
    assert "应为完整正文" in cdp._page_meta(False)
    m = cdp._page_meta(False, True, "async_load_stalled")
    assert "partial=true reason=async_load_stalled" in m and "以上应为完整正文" not in m
    assert "登录墙信号" in cdp._page_meta(True)
    assert cdp._net_diag([]) == ""
    ok = cdp._net_diag([{"u": "a", "s": 200}] * 3)
    assert ok.count("reqs=3") == 1 and "failures" not in ok
    junk = cdp._net_diag([{"u": "x", "s": "weird"}, "not-a-dict", {"u": "y", "s": 500}])
    assert "y (500)" in junk
    assert cdp._net_diag("garbage") == ""


def test_stall_pat_basics():
    assert cdp._STALL_PAT.search("正在玩命加载数据")
    assert cdp._STALL_PAT.search("加载中...")
    assert not cdp._STALL_PAT.search("本帖讨论人工智能与机器学习应用，内容完整可读。")


def test_schema_describes_stall_and_diag():
    wr = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "web_render")
    d = wr["function"]["description"]
    assert "骨架屏" in d and "net-diag" in d and "wait_text_not_seen" in d
