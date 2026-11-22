# build=S286
# S286：高 DPI 坐标系错位修复的静态锁。行为面（125% 物理像素光标解锁/无误伤/mousemove 救援）
# 由 hud_hold_harness_s282.js 段 3 覆盖；本文件锁实现锚点，防止后续重构悄悄删掉候选映射。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_hold_harness_s282.js").read_text(encoding="utf-8")


def test_renderer_candidates():
    for anchor in ("function dpr()", "function inVp(x, y)",
                   "hitPoint(x / dpr(), y / dpr())",
                   "document.elementFromPoint(x / dpr(), y / dpr())",
                   "'[HudDbg] raw='", "__hudDiagLite"):
        assert anchor in HUD, anchor
    # 越界才试缩放候选（防视口内误伤）——两处调用都必须先过 inVp 反条件
    assert HUD.count("!inVp(x, y)") >= 2
    assert "dpr: window.devicePixelRatio || 1" in HUD


def test_watchdog_measured_mapping():
    for anchor in ("_hudGeomProbe", "__hudDiagLite", "_hudCssPoints", "_hudCssHit",
                   "g.inner[0] / b.width", "scaleFactor",
                   "_rectHas(_hudHotspot(win.getBounds(), cfg.position), cur)"):
        assert anchor in MAIN, anchor
    # geom 不可用时必须保留 CSS 契约回退路径（上一行锚点=该路径）；geom 路径标注 [geom]
    assert "' [geom]' : ' [css]'" in MAIN


def test_harness_dpi_stage():
    assert "125% DPI" in HARNESS and "devicePixelRatio = 1.25" in HARNESS
    assert "1890, y: 990" in HARNESS and "1506, top: 786" in HARNESS
