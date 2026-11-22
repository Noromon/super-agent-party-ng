# build=S303
# S294：面板列表可滚动——CSS flex 滚动容器 + OS 真值滚轮/拖动接线（静态锁）。
# 行为面由 hud_panel_s291_harness.js 的 S294 场景覆盖（独立进程）。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "css" / "hud-capsule.css").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_panel_s291_harness.js").read_text(encoding="utf-8")


def test_css_scroll_container():
    # 根因①：flex 子项缺 min-height:0 永不收缩 → 列表无内部滚动，滚轮/拖动无从发生
    i = CSS.index(".hud-p-list {")
    rule = CSS[i:i + 160]
    assert "flex: 1 1 auto" in rule and "min-height: 0" in rule and "overflow-y: auto" in rule


def test_list_wiring():
    assert "panelListEl = list;" in HUD
    assert "panelListEl = null;" in HUD  # closePanel 清理
    i = HUD.index("function togglePanel()")
    j = HUD.index("loadPanelList(list)", i)
    assert "flushWheelEdge();" in HUD[i:j], "开面板必须冲刷陈旧滚轮增量（S293 教训）"


def test_wheel_and_drag_wiring():
    assert "if (panel) pollWheel();" in HUD
    assert "if (down && dragList) dragStep();" in HUD
    k = HUD.index("} else if (down && !lastLbtn) {")
    assert "beginDrag();" in HUD[k:k + 200]
    m = HUD.index("} else if (!down && lastLbtn && lbtnDownTs) {")
    assert "endDrag();" in HUD[m:m + 260]
    r = HUD.index("function routePhysicalClick")
    s = HUD.index("if (dragSkipRoute) { dragSkipRoute = false; return; }", r)
    g = HUD.index("Date.now() - lastNativeClickTs < 450", r)
    assert r < s < g, "拖动抑制判定必须先于路由其余判定"
    assert "overList()" in HUD and "scrollBy(-(d / 120) * 90);" in HUD
    assert "scrollBy(-dy / dpr());" in HUD  # 物理位移→CSS 缩放补偿


def test_harness_covers_s294():
    assert "开面冲刷——陈旧滚轮增量不闪跳列表" in HARNESS
    assert "OS 真值滚轮" in HARNESS and "物理拖动平移列表" in HARNESS
    assert "拖动释放不误关面板" in HARNESS
