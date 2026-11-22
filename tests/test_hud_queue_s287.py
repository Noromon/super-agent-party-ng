# build=S295
# S287：气泡溢出排队（不再撤展示中的旧条）+ [HudPop] 生命周期埋点。静态锁；
# 行为面（入队/到期补位/视口不越权）由 hud_pop_harness_s272.js 覆盖。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_pop_harness_s272.js").read_text(encoding="utf-8")
HTML = (ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")


def test_queue_plumbing():
    for anchor in ("var popQueue = [], POP_QMAX = 50;", "function pumpQueue()",
                   "function renderBubble(item)", "function pushBubble(icon, text, holdOverride, force)",
                   "renderBubble(popQueue.shift())", "while (popQueue.length > POP_QMAX) popQueue.shift();",
                   "b.__t = setTimeout(function () { detachBubble(b, 'timeout'); }, hold);",
                   "detachBubble(oldest, 'trim');", "pumpQueue(); //"):
        assert anchor in HUD, anchor
    # 溢出判定只数未消亡节点；展示中节点绝无被 trim 让位的路径
    assert "if (!force && live >= cfg.stackMax) {" in HUD
    assert "b.__birth = Date.now();" in HUD


def test_hudpop_journal():
    assert "'[HudPop] push hold='" in HUD
    assert "'[HudPop] detach '" in HUD
    assert "'[HudPop] queue live='" in HUD


def test_ui_copy_synced():
    assert "超出部分自动排队" in HTML
    assert "不等保留到期" not in HTML  # 旧「挤掉最老」文案已下线


def test_harness_covers_queue():
    assert "S287: 溢出第四条入队等待" in HARNESS
    assert "自动补位上屏" in HARNESS and "holdMs: 2000, stackMax: 2" in HARNESS
