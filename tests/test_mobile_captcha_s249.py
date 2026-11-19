# S249：移动端仿真不再裁剪/错位 + captcha 页识别与人工接力信号
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

MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
AGENT = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_main_js_emulation_fix():
    assert "deviceScaleFactor: 0" in MAIN
    assert "deviceScaleFactor: 3" not in MAIN
    assert "wc.getContentSize()" in MAIN
    i = MAIN.index("setDeviceMetricsOverride")
    seg = MAIN[i - 400:i + 260]
    assert "_vh" in seg and "mobile: true" in seg


def test_snapshot_has_captcha_probe():
    assert "captcha_detected=true" in AGENT
    assert "img[src*=verifycode]" in AGENT
    assert "安全验证" in AGENT and "拖动滑块" in AGENT
    i = AGENT.index("getWebviewSnapshot")
    seg = AGENT[i:i + 12000]
    assert "captchaNote" in seg and "r + captchaNote + loadNote" in seg


def test_captcha_pat_hits_and_misses():
    assert cdp._CAPTCHA_PAT.search("百度安全验证 请完成下方验证")
    assert cdp._CAPTCHA_PAT.search("bfe_punish_page")
    assert not cdp._CAPTCHA_PAT.search("本帖讨论机器学习模型评测与验证码识别研究进展")


def test_wall_hint_captcha_supersedes_completeness():
    out = cdp._wall_hint(False, True)
    assert "captcha_detected=true" in out and "勿用 evaluate_script 硬解" in out
    assert "完整正文" not in out
    assert "应为完整正文" in cdp._wall_hint(False)


def test_page_meta_captcha_line_keeps_diag():
    out = cdp._page_meta(False, True, "async_load_stalled",
                         net=[{"u": "https://x/api", "s": 403}], ua="iPhone", cookie_len=7,
                         captcha=True)
    assert "captcha_detected=true" in out
    assert "login_wall_detected" not in out
    assert "[net-diag] reqs=1" in out and "x/api (403)" in out
    assert "[ctx] ua=iPhone" in out


def test_web_render_flags_captcha_page():
    async def fake_targets():
        return [1]

    async def fake_vue(method, args, **kw):
        return json.dumps({"ok": True, "title": "验证", "finalUrl": "u",
                           "html": "<p>百度安全验证 请完成下方验证</p><img src='//x/verifycode?k=1'>"})
    o1, o2 = cdp.get_targets, cdp.call_vue_method
    cdp.get_targets, cdp.call_vue_method = fake_targets, fake_vue
    try:
        out = asyncio.run(cdp.web_render(original_url="https://tieba.baidu.com", timeout=5))
    finally:
        cdp.get_targets, cdp.call_vue_method = o1, o2
    assert "captcha_detected=true" in out
    assert "以上应为完整正文" not in out


def test_snapshot_schema_advises_manual_handoff():
    ts = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "take_snapshot")
    assert "captcha_detected" in ts["function"]["description"]
    assert "manually" in ts["function"]["description"]
