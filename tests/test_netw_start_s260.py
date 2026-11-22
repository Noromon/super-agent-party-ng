# build=S296
# S260：network_watch start 起不来修复（logs 09:48 轮实锤：start 在加载期报
# 'Failed networkWatch after 3 retries. Electron Webview Error'；mobile 切换重建
# webview 元素令 S258 元素级 dom-ready 监听蒸发）。
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_start_error_translated_to_actionable_hint():
    async def fake(method, args, timeout=None, **kw):
        return "Failed networkWatch after 3 retries. Last error: Electron Webview Error"
    orig = cdp.call_vue_method
    cdp.call_vue_method = fake
    try:
        out = asyncio.run(cdp.network_watch("start", "", True))
    finally:
        cdp.call_vue_method = orig
    assert "幂等安全" in out and "重试 start" in out and "Electron Webview Error" not in out

    async def fake2(method, args, timeout=None, **kw):
        return "Error executing networkWatch: ... GUEST_VIEW_MANAGER_CALL: boom"
    cdp.call_vue_method = fake2
    try:
        out2 = asyncio.run(cdp.network_watch("start"))
    finally:
        cdp.call_vue_method = orig
    assert "页面正在加载" in out2

    # 正常 armed 不被改写
    async def fake3(method, args, timeout=None, **kw):
        return "armed"
    cdp.call_vue_method = fake3
    try:
        assert asyncio.run(cdp.network_watch("start")) == "armed"
    finally:
        cdp.call_vue_method = orig


def test_vue_start_waits_for_load():
    i = JS.index("S260：先等加载停止")
    seg = JS[i:i + 600]
    assert "_waitLoadStop(wv, 8000)" in seg
    assert "页面仍在加载" in seg and "幂等安全" in seg  # 忙时明确文案（非裸 Electron 错误）


def test_vue_tab_scoped_config_with_self_reattach():
    i = JS.index("S260：重挂配置提升到 Vue 实例的 tab 维度")
    seg = JS[i:i + 1000]
    assert "this.__netwTabs = this.__netwTabs || {}" in seg
    assert "cfg && !wv.__netwRe" in seg  # 元素重建后（无监听）自愈
    assert "wv.executeJavaScript(this._netwArmExpr(cfg.body))" in seg  # 当前文档补 arm
    j = JS.index("this.__netwTabs[tabId] = { body: !!includeBody }")  # start 记录 tab 配置
    assert j > i
    k = JS.index('if (mode === "stop")')
    assert "delete this.__netwTabs[tabId]" in JS[k:k + 400]  # stop 清配置


def test_schema_documents_wait_and_selfheal():
    nw = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")
    d = nw["function"]["description"]
    assert "自动等页面加载完成" in d and "自愈" in d
