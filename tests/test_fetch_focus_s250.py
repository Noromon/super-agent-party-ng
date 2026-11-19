# S250：focus 聚焦抓取（simple_fetch/web_render）+ 繁忙提示去误导
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
import py.text_focus as tf  # noqa: E402
import py.web_search as ws  # noqa: E402


def test_focus_blocks_basic():
    text = "\n".join(f"line {i}" for i in range(1, 101))
    blocks, total = tf.focus_blocks(text, "line 50", context=3)
    assert total == 1
    assert "line 47" in blocks and "line 53" in blocks and "line 46" not in blocks
    assert "@text" in blocks and "L47-L53" in blocks


def test_focus_blocks_merge_and_ci():
    text = "\n".join(["alpha X beta"] + ["filler"] * 5 + ["gamma x delta"] + ["tail"] * 5)
    blocks, total = tf.focus_blocks(text, "X", context=4)
    assert total == 2
    assert blocks.count("--- match") == 1  # ±4 行区间重叠 → 合并为一块
    blocks2, total2 = tf.focus_blocks(text, "GAMMA", context=0)
    assert total2 == 1 and "gamma x delta" in blocks2 and "tail" not in blocks2


def test_focus_blocks_limits_and_miss():
    text = "\n".join(f"row{k} hit" if k % 5 == 0 else "row" for k in range(1, 200))
    blocks, total = tf.focus_blocks(text, "hit", context=0, max_hits=3)
    assert total == 39 and blocks.count("--- match") == 3 and "未显示" in blocks
    assert tf.focus_blocks("hello", "zzz") == ("", 0)
    assert tf.focus_blocks("", "a") == ("", 0)


def _fetch(html, focus="", context=0):
    async def fake_settings():
        return {}

    async def fake_robots(url):
        return True

    class Resp:
        status_code = 200
        text = html
    orig = (ws.load_settings, ws.check_robots_txt, ws.requests.get)
    ws.load_settings = fake_settings
    ws.check_robots_txt = fake_robots
    ws.requests.get = lambda *a, **k: Resp()
    try:
        return asyncio.run(ws.simple_fetch("https://example.com/p", focus=focus, context=context))
    finally:
        ws.load_settings, ws.check_robots_txt, ws.requests.get = orig


def _html_with(paras):
    body = "".join(f"<p>{p}</p>" for p in paras)
    return f"<html><head><title>Doc</title></head><body><main>{body}</main></body></html>"


def test_simple_fetch_focus_hit_and_miss():
    paras = [f"para number {i} about widgets" for i in range(30)]
    paras[20] = "public static final int FLAG_LOCAL_ONLY = 64; // local only flag"
    out = _fetch(_html_with(paras), focus="FLAG_LOCAL_ONLY")
    assert out.get("match_lines") == 1
    assert "FLAG_LOCAL_ONLY = 64" in out["matches"]
    assert "sections" not in out

    out2 = _fetch(_html_with(paras), focus="NOT_THERE_XYZ")
    assert "sections" in out2 and "focus_note" in out2 and "NOT_THERE_XYZ" in out2["focus_note"]


def test_simple_fetch_toc_on_long_page():
    paras = [f"section body {i} " + "text " * 20 for i in range(50)]
    html = ("<html><head><title>T</title></head><body><main>"
            + "".join(f"<h2>Heading {i}</h2>" for i in range(20))
            + "".join(f"<p>{p}</p>" for p in paras) + "</main></body></html>")
    out = _fetch(html)
    assert "toc" in out and "Heading 0" in out["toc"] and "focus=" in out["toc"]


def _render(html, focus=""):
    async def fake_targets():
        return [1]

    async def fake_vue(method, args, **kw):
        return json.dumps({"ok": True, "title": "T", "finalUrl": "u", "html": html})
    o1, o2 = cdp.get_targets, cdp.call_vue_method
    cdp.get_targets, cdp.call_vue_method = fake_targets, fake_vue
    try:
        return asyncio.run(cdp.web_render(original_url="https://x.test", timeout=5, focus=focus))
    finally:
        cdp.get_targets, cdp.call_vue_method = o1, o2


def test_web_render_focus():
    body = ("".join(f"<p>filler {i}</p>" for i in range(200))
            + "<p>TARGET_CONSTANT = 42 meaning</p>"
            + "".join(f"<p>tailtext {i}</p>" for i in range(200)))
    out = _render(body, focus="TARGET_CONSTANT")
    assert "CONSTANT = 42" in out and "[focus]" in out  # 块内为 md 转义原文(TARGET\_CONSTANT)，匹配已剥转义
    assert "filler 3" not in out and "tailtext 150" not in out
    out2 = _render(body, focus="ABSENT_XYZ")
    assert "filler 3" in out2 and "未在正文中命中" in out2


def test_busy_hints_no_tab_count_blame():
    src = (ROOT / "py/cdp_tool.py").read_text(encoding="utf-8")
    assert "与已开标签数无关" in src
    assert "与打开标签「数量」关系不大" in src
    assert "减少同时打开的标签页数量" not in src


def test_schemas_advertise_focus():
    assert "focus" in ws.simple_fetch_tool["function"]["parameters"]["properties"]
    assert "context" in ws.simple_fetch_tool["function"]["parameters"]["properties"]
    wr = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "web_render")
    assert "focus" in wr["function"]["parameters"]["properties"]
    assert "focus" in wr["function"]["description"]
