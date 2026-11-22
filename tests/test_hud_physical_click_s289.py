# build=S295
# S289：HUD 物理点击通道静态锁（行为面=点圈开面板/点关闭钮收起/原生去重，
# 由 hud_hold_harness_s282.js 段 4 覆盖）。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_hold_harness_s282.js").read_text(encoding="utf-8")


def test_physical_channel_plumbing():
    for anchor in ("fetch('/api/mouse-state', { credentials: 'same-origin' })",
                   "function pollMouseState()", "function routePhysicalClick(settleMs)",
                   "if (holdActive) pollMouseState();",
                   "Date.now() - lastNativeClickTs < 450 || !holdActive || !lastPollP",
                   "panelCloseEl = cl;", "panelCloseEl = null;",
                   "lastNativeClickTs = Date.now(); togglePanel();"):
        assert anchor in HUD, anchor
    # 让位窗必须存在且带可配置结算延迟（S291 默认 120ms / 快击 80ms）
    assert "}, settleMs || 120);" in HUD
    assert "routePhysicalClick(80);" in HUD
    # 端点缺失静默（旧后端不刷屏）
    assert "msMuteUntil = Date.now() + 5000;" in HUD


def test_cursor_and_event_journal():
    assert "document.documentElement.style.cursor = hit ? 'pointer' : ''" in HUD
    assert "'[HudEv] no-native-enter lastEv='" in HUD
    # 捕获监听只记账（无 console），高频安全
    assert HUD.index("lastEv = { x: e.clientX") < HUD.index("}, true);")


def test_harness_covers_physical_click():
    assert "S289: 原生点击不可达时按键循环→物理通道展开面板" in HARNESS
    assert "物理通道让位" in HARNESS and "mouse-state" in HARNESS
