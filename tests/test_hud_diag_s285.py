# build=S296
# S285：主进程胶囊看门狗 + HUD 诊断台。静态锁（行为面=看门狗依赖 Electron 运行时，
# 现场验证；页内新增面由 hud_hold_harness_s282.js 的 S285 断言覆盖）。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static" / "js" / "preload.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_hold_harness_s282.js").read_text(encoding="utf-8")


def test_watchdog_main_process():
    for anchor in ("function hudCapsuleWatchdogTick()", "setInterval(hudCapsuleWatchdogTick, 120)",
                   "win.isIgnoreMouseEvents()", "_hudHotspot(win.getBounds(), cfg.position)",
                   "_hudWatch.releasedBy !== 'watchdog'", "!!window.__sapHudHoldMouse",
                   "setIgnoreMouseEvents(true, { forward: true })"):
        assert anchor in MAIN, anchor
    # CSS 契约常量（.hud-pos-* 12px 偏移 / 18px 胶囊）必须体现在热点映射里
    assert "const PAD = 10, SIZE = 18, OFF = 12;" in MAIN
    # 岛窗 console 转发（生产构建无 devtools 的唯一可见通道）
    assert "win.webContents.on('console-message'" in MAIN and "'[Island:' + lvl" in MAIN


def test_diag_bridge():
    assert "ipcMain.handle('hud-diag'" in MAIN
    assert "window.__hudDiag ? window.__hudDiag() : \"HUD_REV_ABSENT\"" in MAIN
    assert "hudDiag: () => ipcRenderer.invoke('hud-diag')" in PRELOAD


def test_hud_capsule_observability():
    # rev 具体值随票号走（S286 起 harness 已锁 rev 格式），此处只锁存在性，免逐票翻修
    import re
    assert re.search(r"var HUD_REV = 'S\d{3}';", HUD)
    assert "pollTicks++;" in HUD
    assert "window.__hudDiag = function ()" in HUD
    assert "'[HudHold] '" in HUD
    assert "toast('HUD rev ' + HUD_REV)" in HUD
    # 诊断按钮接线在主窗 bindSettings（岛宿主不碰）
    assert "t.id === 'sap-hud-diag'" in HUD


def test_diag_ui_present():
    assert 'id="sap-hud-diag"' in HTML
    assert 'id="sap-hud-diag-out"' in HTML


def test_harness_covers_s285():
    assert "__hudDiag" in HARNESS and "S286" in HARNESS
