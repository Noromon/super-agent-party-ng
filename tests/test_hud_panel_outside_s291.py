# build=S294
# S291：lpress 快击边沿（采样间点击不丢）+ 面板外一点即收。静态锁；
# 行为面由独立进程 tests/data/hud_panel_s291_harness.js 覆盖（隔离旧实例对
# 边沿标志的抢消费）。
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HUD = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
HARNESS = (ROOT / "tests" / "data" / "hud_panel_s291_harness.js").read_text(encoding="utf-8")


def test_lpress_edge_paths():
    assert "var press = !!(j && j.lpress);" in HUD
    # 三路互斥：快击直达 / 按下沿记时 / 释放沿长按语义——lpress 消费后清 lbtnDownTs 防双发
    i = HUD.index("if (press && !down) {")
    seg = HUD[i:i + 520]
    assert "lbtnDownTs = 0;" in seg and "routePhysicalClick(80);" in seg
    assert "} else if (down && !lastLbtn) {" in seg
    assert "} else if (!down && lastLbtn && lbtnDownTs) {" in seg


def test_outside_close_both_channels():
    # 物理路由：面板外一点即收（胶囊优先短路在外判之前）
    assert "if (!inBoth(panel)) closePanel();" in HUD
    j = HUD.index("if (inBoth(capsule)) { togglePanel(); return; }")
    assert j < HUD.index("if (!inBoth(panel)) closePanel();")
    # 健康机原生通道：document 捕获层点击，面板/胶囊之外即收
    assert "while (n) { if (n === panel || n === capsule) break; n = n.parentNode; }" in HUD


def test_s292_ownership_split():
    # 物理通道存活窗：心跳打点 + 捕获层让位（幻影 click 不得双行动）
    assert "msOkTs = Date.now();" in HUD
    assert "if (Date.now() - msOkTs < 3000) return;" in HUD
    i = HUD.index("if (Date.now() - msOkTs < 3000) return;")
    j = HUD.index("closePanel();", i)
    assert i < j, "让位判断必须先于捕获层 close"
    HARNESS = (ROOT / "tests" / "data" / "hud_panel_s291_harness.js").read_text(encoding="utf-8")
    assert "关了又开=回归" in HARNESS and "捕获层恢复掌控" in HARNESS


def test_harness_covers_s291():
    assert "S293: 武装即冲刷" in HARNESS and "首击必死回归锁" in HARNESS
    assert "首次真实点击即时生效" in HARNESS
    assert "面板外物理按下 → 一点即收" in HARNESS
    assert "让位（面板未被抢关）" in HARNESS and "面板内按下不触发外部收起" in HARNESS


def test_s293_flush_on_arm():
    # 武装即冲刷：holdActive 置位处必须冲刷累积边沿
    i = HUD.index("holdActive = true; hudHoldMouse(true); flushMouseEdge();")
    assert HUD.index("function flushMouseEdge()") < i
    assert "'/api/mouse-state'" in HUD[HUD.index("function flushMouseEdge()"):i]


def test_behavior_harness_green():
    r = subprocess.run(
        ["node", str(ROOT / "tests/data/hud_panel_s291_harness.js"),
         str(ROOT / "static/js/hud-capsule.js")],
        capture_output=True, text=True, timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    bad = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
    assert r.returncode == 0 and "all passed" in out, "; ".join(bad) or out[-600:]
