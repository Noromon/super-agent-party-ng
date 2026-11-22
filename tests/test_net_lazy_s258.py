# build=S283
# S258：take_snapshot 懒加载真图解析 + network_watch 导航自动重挂。
# 动因：agent 实测——"图片 src 压根不在此处，是懒加载 JS 的，接口只给相对占位路径"；
# "网络钩子会随导航失效需要重新挂"。
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_snapshot_resolves_lazy_src():
    i = JS.index("S258: 懒加载站")
    seg = JS[i:i + 1600]
    # 真图属性优先链 + 协议相对地址 + 绝对化
    assert "'_src', 'data-src', 'data-actualsrc'" in seg
    assert "new URL(String(v), location.href)" in seg
    # S259: blob:/data: 等页内源不再吐 URL 本体，直导 take_screenshot(uid) 像素路
    assert "已渲染但无外部URL" in seg and "!/^https?:/i.test(iurl)" in seg


def test_network_watch_arm_expr_extracted_with_guard():
    i = JS.index("_netwArmExpr(bodyOn)")
    seg = JS[i:i + 1500]
    # 幂等守卫：dom-ready 重复触发/重复 start 不会二次包裹 fetch
    assert "window.__netw&&window.__netw.armed)return 'armed'" in seg
    # arm 主体上提后 start 与重挂共用
    assert "window.fetch" in seg and "XMLHttpRequest.prototype.open" in seg
    assert JS.count("_netwArmExpr(") >= 3  # 定义 + start + dom-ready 重挂


def test_network_watch_auto_rearm_on_navigation():
    i = JS.index("S258：start 后每次导航 dom-ready 自动重挂")
    seg = JS[i:i + 1600]  # S260 后 start 分支加长了（等待加载+tab 配置）
    assert "wv.__netwBody = !!includeBody" in seg
    assert "addEventListener('dom-ready', wv.__netwRe)" in seg
    assert "removeEventListener('dom-ready', wv.__netwRe)" in seg  # 重挂前先摘旧听


def test_stop_removes_rearm_listener():
    i = JS.index('if (mode === "stop")')
    seg = JS[i:i + 320]
    assert "removeEventListener('dom-ready', wv.__netwRe)" in seg


def test_schemas_documented():
    ts = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "take_snapshot")
    d = ts["function"]["description"]
    assert "take_screenshot" in d and "blob:" in d and "data-actualsrc" in d
    nw = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")
    assert "自动重挂" in nw["function"]["description"]
