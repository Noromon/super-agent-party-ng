# S246：浏览器读屏健壮性（agent 意见单落地）
#  UID_EXPIRED 结构化错误 / snapshot 图片行 url / wait_for 三模 / html_to_md 图+熔断 / meta 墙检测
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402
import py.html_to_md as h2m  # noqa: E402


def _read(*parts):
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


# ---------------- Vue 侧静态哨兵 ----------------

def test_vue_uid_expired_and_snapshot_url():
    js = _read("static", "js", "methods", "80_webview_agent.js")
    assert js.count("UID_EXPIRED: page DOM rebuilt") == 3  # click/fill/hover
    assert "url=' + iurl" in js                            # snapshot 图片行带 url
    assert "el.currentSrc || el.src" in js
    assert "mode = 'text'" in js and "querySelector(" in js  # wait_for 三模
    assert "S246W|" in js and "wallTxt" in js               # getPageHtml 墙前缀
    assert "wv.getURL()" in js and "wv.getTitle()" in js


# ---------------- html_to_md：内容图 + 重复熔断 ----------------

def test_img_becomes_markdown_link():
    md = h2m.html_to_markdown('<p>正文</p><img src="https://cdn.x/a.png" alt="证据图">')
    assert "证据图" in md and "(https://cdn.x/a.png)" in md


def test_data_uri_img_omitted():
    md = h2m.html_to_markdown('<p>x</p><img src="data:image/png;base64,' + "A" * 4000 + '">')
    assert "data-uri omitted" in md and "base64" not in md


def test_repeat_run_and_line_collapsed():
    md = h2m.html_to_markdown("<p>" + "m" * 300 + "</p>")
    assert "repeat collapsed" in md and len(md) < 100
    big = "\n".join(["li"] * 60)
    md2 = h2m._denoise(big)
    assert "repeated pattern collapsed" in md2
    # 正常内容不误伤（含中文 30 连字——旧阈值会误杀）
    normal = "行一\n行二\n行三\n\n段落 *强调* [链接](http://a.b)"
    assert h2m._denoise(normal) == normal
    assert h2m._denoise("哈哈哈哈哈哈" * 5) == "哈哈哈哈哈哈" * 5


# ---------------- wait_for 三选一 ----------------

def test_wait_for_exclusive_params():
    assert "三者之一" in asyncio.run(cdp.wait_for())
    assert "三者之一" in asyncio.run(cdp.wait_for(text="a", selector="b"))
    calls = []

    async def _spy(m, args):
        calls.append((m, args))
        return "Found: a"
    orig = cdp.call_vue_method
    cdp.call_vue_method = _spy
    try:
        assert asyncio.run(cdp.wait_for(text="a", timeout=5000)) == "Found: a"
        assert asyncio.run(cdp.wait_for(js="document.title!==''")) == "Found: a"
    finally:
        cdp.call_vue_method = orig
    assert calls[0] == ("webviewWaitFor", ["a", 5000, "text"])
    assert calls[1] == ("webviewWaitFor", ["document.title!==''", 1000, "js"])


# ---------------- get_page_markdown meta 化 ----------------

def _md_via(fake_ret):
    async def _spy(m, args):
        return fake_ret
    orig = cdp.call_vue_method
    cdp.call_vue_method = _spy
    try:
        return asyncio.run(cdp.get_page_markdown())
    finally:
        cdp.call_vue_method = orig


def test_get_page_markdown_meta_and_wall():
    import json
    out = _md_via(json.dumps({"html": "<h1>帖标题</h1><p>正文内容" + "字" * 30 + "</p>",
                              "url": "https://tieba.baidu.com/p/1", "title": "帖子",
                              "wallN": 0, "wallTxt": False}))
    assert out.startswith("# 帖子\nSource: https://tieba.baidu.com/p/1")  # meta title 头 + 正文 h1 并存
    assert "帖标题" in out and "login_wall_detected=false" in out
    out2 = _md_via(json.dumps({"html": "<p>登录后查看全部内容" + "字" * 30 + "</p>",
                               "url": "u", "title": "", "wallN": 2, "wallTxt": True}))
    assert "login_wall_detected=true" in out2
    out3 = _md_via(json.dumps({"html": "<p>" + "登录后查看全部评论内容。" * 10 + "</p>", "url": "u",
                               "title": "", "wallN": 0, "wallTxt": False}))  # 正文自带墙词→Python 兜底
    assert "login_wall_detected=true" in out3


def test_get_page_markdown_legacy_plain_html_compat():
    out = _md_via("<p>旧版纯字符串返回" + "容" * 30 + "</p>")
    assert "旧版纯字符串返回" in out and "login_wall_detected=false" in out


def test_wall_pat_keywords():
    assert cdp._WALL_PAT.search("扫码登录") and cdp._WALL_PAT.search("Please log in to continue")
    assert not cdp._WALL_PAT.search("正常帖子正文")


# ---------------- schema 同步 ----------------

def test_schemas_updated():
    by = {t["function"]["name"]: t["function"] for t in cdp.all_cdp_tools}
    wf = by["wait_for"]["parameters"]["properties"]
    assert {"text", "selector", "js"} <= set(wf) and not by["wait_for"]["parameters"].get("required")
    assert "view_images" in by["take_snapshot"]["description"]
    assert "共享登录态" in by["web_render"]["description"]
    assert "page-meta" in by["get_page_markdown"]["description"]
