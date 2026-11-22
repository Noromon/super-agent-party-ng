# build=S303
# S295：网页探索绕圈事故修复（浏览器层）——network_watch 游标语义/零命中清单、
# collect_list 零命中骨架、browser_lookup 死标签探测+死因清单、CJK 编码指引。
# JS 表达式以静态锁覆盖（行为面依赖真 webview）；browser_lookup 逻辑走单测。
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_mod = sys.modules.get("py")
if _mod is not None and not hasattr(_mod, "__path__"):
    del sys.modules["py"]

JS = (ROOT / "static" / "js" / "methods" / "80_webview_agent.js").read_text(encoding="utf-8")
SRC = (ROOT / "py" / "web_search_browser.py").read_text(encoding="utf-8")
CDP = (ROOT / "py" / "cdp_tool.py").read_text(encoding="utf-8")
DISC = (ROOT / "py" / "tool_discipline.py").read_text(encoding="utf-8")


def test_netw_cursor_only_to_last_hit_and_skip_inventory():
    assert "w.c=lastHit>=0?lastHit+1:from;" in JS  # 过滤条目不再被游标吞掉
    assert "w.c=E.length;" not in JS  # 旧的一刀切前进已绝迹
    assert "skipped_urls" in JS and "pattern 命中 0 条" in JS


def test_collect_list_zero_hit_skeleton():
    i = JS.index("collected: items.length")
    seg = JS[JS.index("if (items.length === 0) {"):i + 900]
    assert "skeleton" in seg and "cards_last_scan" in seg
    assert "no-repeat-container" in seg


def test_cjk_guidance_everywhere_it_matters():
    for txt in (SRC, CDP, DISC):
        assert ("%XX" in txt or "％XX" in txt), "CJK 手敲编码禁令缺失"
    assert "原样中文" in CDP and "Chromium" in CDP  # url 参数描述
    assert "NEVER hand-type" in DISC


def test_timeout_reports_attempted_engines():
    # 死因清单：errs 由外层持引用下传，超时也要吐进度
    assert "已尝试：{detail}" in SRC
    assert "_browser_search(query, engine, max_results, tried, budget)" in SRC
    assert "未尝试（时间预算耗尽）" in SRC


def test_reuse_probe_and_newtab_fallback(monkeypatch):
    from py import web_search_browser as w

    calls = []

    async def fake_pages():
        return [{"index": 3, "url": "https://cn.bing.com/old"}]

    class FakeCdp:
        @staticmethod
        async def select_page(idx):
            calls.append(("select", idx))

        @staticmethod
        async def navigate_page(type=None, url=None):
            calls.append(("nav", url))
            return "Navigating (loaded)"

        @staticmethod
        async def evaluate_script(js):
            calls.append(("eval", "probe"))
            return "Error: No active webview"  # 死通道

        @staticmethod
        async def close_page(idx):
            calls.append(("close", idx))

        @staticmethod
        async def new_page(url):
            calls.append(("new", url))
            return "Success"

    import types
    mod = types.ModuleType("py.cdp_tool")
    for k in ("select_page", "navigate_page", "evaluate_script", "close_page", "new_page"):
        setattr(mod, k, getattr(FakeCdp, k))
    monkeypatch.setitem(sys.modules, "py.cdp_tool", mod)
    monkeypatch.setattr(w, "_read_pages", fake_pages)

    ok = asyncio.run(w._open_or_reuse("https://cn.bing.com/search?q=x"))
    assert ok is True
    ops = [c[0] for c in calls]
    assert ops == ["select", "nav", "eval", "close", "new"], ops  # 探测失败→关死标签→新开


def test_guide_hint_warns_encoding():
    from py import web_search_browser as w
    assert "严禁手敲 %XX" in w.GUIDE_HINT
    err = w._err("测试")
    assert "原样中文" in err and "captcha" in err
