# build=S293
# S282：HUD 胶囊持握状态机——穿透窗下点击失灵的双保险修复。静态锁。
# 行为面由 hud_hold_harness_s282.js 驱动（7 断言）。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
ISLAND = (ROOT / "static" / "js" / "island-app.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static" / "js" / "preload.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_hold_harness_s282.js").read_text(encoding="utf-8")


def test_state_machine_wired():
    # 三源并联 + 迟滞释放；hudHoldMouse 只许状态机调用，且主窗门闩在函数首行
    for anchor in ("function hudHoldWanted() { return !!panel || domOver || pollOver; }",
                   "function updateHold()",
                   "}, 250); // 迟滞",
                   "var ISLAND_HOST = typeof location !== 'undefined' && String(location.pathname || '').indexOf('island') >= 0;"):
        assert anchor in HUD, anchor
    gate = HUD.index("function hudHoldMouse(on) {")
    assert HUD[gate:gate + 200].index("if (!ISLAND_HOST) return;") < HUD[gate:gate + 200].index("window.__sapHudHoldMouse")
    # 旧版独任解锁入口已清除
    assert "mouseenter', function () { overCapsule = true; hudHoldMouse(true); });" not in HUD


def test_dom_driver_and_poll_fallback():
    assert "document.addEventListener('mousemove', onDocMove);" in HUD
    assert "document.elementFromPoint(x, y)" in HUD
    assert "api.getCursorScreenPoint" in HUD
    assert "p.x - window.screenX" in HUD
    assert "}, 150);" in HUD  # 轮询周期
    # OS 真相仅在本窗换算命中过一次后才可纠正 DOM 态（防混合 DPI 误伤）
    assert "pollTrusted" in HUD


def test_bridge_endpoints_match():
    assert "get-cursor-screen-point" in PRELOAD and "getCursorScreenPoint" in PRELOAD
    assert "ipcMain.handle('get-cursor-screen-point'" in MAIN
    assert "screen.getCursorScreenPoint()" in MAIN


def test_island_guard_untouched():
    # island-app 侧的持握守卫仍在（HUD 持握期间岛侧不得抢关穿透）
    assert "if (ignore && window.__sapHudHoldMouse) return;" in ISLAND


def test_harness_assertions_present():
    for anchor in ("主窗实例不建 HUD 层", "零穿透 API 调用", "mousemove 命中胶囊",
                   "轮询命中矩形", "恢复 forward 穿透"):
        assert anchor in HARNESS, f"harness 缺断言锚 {anchor}"
