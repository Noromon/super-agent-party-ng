# build=S302
# S272：HUD 弹出气泡栈——pop 开关/holdMs 保留/stackMax 同屏条数（用户要求：
# 观战消息不能只加红角标，必须弹出；且保留时长与同屏条数可调）。
# 行为面由 tests/data/hud_pop_harness_s272.js 驱动（假 DOM 实跑模块），本文件锁
# 配置形状/接线/静态面，防重构悄悄改回"仅角标"。
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js():
    return (ROOT / "static/js/hud-capsule.js").read_text(encoding="utf-8")


def _syshtml():
    return (ROOT / "static/templates/page_system.html").read_text(encoding="utf-8")


def test_cfg_defaults_and_clamps():
    js = _js()
    i = js.index("var DEFAULTS")
    seg = js[i:i + 1200]
    for k in ("pop: true", "holdMs: 8000", "stackMax: 3"):
        assert k in seg, f"DEFAULTS 缺 {k}"
    # 钳制带界（2s-120s / 1-8）
    assert "cfg.holdMs < 2000" in js and "cfg.holdMs > 120000" in js
    assert "cfg.stackMax < 1" in js and "cfg.stackMax > 8" in js
    # mergeCfg（ipc 远程推送通道）同样过钳制——不能只 loadCfg 校验
    m = js.index("function mergeCfg")
    mseg = js[m:m + 1400]
    assert "cfg.holdMs > 120000" in mseg and "cfg.stackMax > 8" in mseg


def test_notify_pops_regardless_of_capsule():
    js = _js()
    i = js.index("function onNotify")
    seg = js[i:i + 900]
    assert "if (cfg.pop) pushBubble(icon, text);" in seg
    # 弹出条件移出胶囊分支：badge 逻辑仍在 capsule 分支内，pop 在其外统一执行
    assert seg.index("cfg.capsule") < seg.index("if (cfg.pop)")
    # approvalExpand 特殊化已除（DEFAULTS 兼容占位除外）
    assert "approvalExpand)" not in js.replace("approvalExpand: true", "")


def test_stack_eviction_and_hold_semantics():
    js = _js()
    i = js.index("function trimStack")
    seg = js[i:i + 900]
    # 最老=首个未消亡节点；淡出中(__gone)不计入（否则 while 永不收敛）
    # S287：trim 只服务「远程调小 stackMax」；推送溢出入队不再撤展示中的旧条
    assert "__gone" in seg and "detachBubble(oldest, 'trim')" in seg
    assert "live <= cfg.stackMax" in seg
    p = js.index("function pushBubble")
    pseg = js[p:p + 900]
    assert "if (!force && live >= cfg.stackMax) {" in pseg  # 溢出走队列
    r = js.index("function renderBubble")
    rseg = js[r:r + 1200]
    assert "trimStack()" in rseg  # 新入即收敛
    assert "b.__t = setTimeout" in rseg and "detachBubble(b, 'timeout')" in rseg  # 保留到期淡出
    d = js.index("function detachBubble")
    assert "node.__gone = true" in js[d:d + 400] and "clearTimeout(node.__t)" in js[d:d + 400]


def test_stack_dom_and_positioning():
    js = _js()
    assert "el('div', 'sap-hud-stack hud-pos-' + cfg.position)" in js
    assert "hud-corner-' + cfg.position" in js
    css = (ROOT / "static/css/hud-capsule.css").read_text(encoding="utf-8")
    assert ".sap-hud-stack" in css
    # 六方位容器定位 + n* 反向排布（最新紧邻胶囊）+ 非胶囊模式回 12px
    for corner in ("nw", "n", "ne", "sw", "s", "se"):
        assert f".sap-hud-stack.hud-pos-{corner}" in css
    assert "column-reverse" in css
    assert "hud-solo.hud-pos" in css
    # 气泡不再自带 absolute（改由容器定位）
    seg = css[css.index(".sap-hud-bubble {"):css.index(".sap-hud-bubble {") + 400]
    assert "position: relative" in seg


def test_settings_card_controls_and_wiring():
    html = _syshtml()
    for cid in ("sap-hud-pop", "sap-hud-hold", "sap-hud-stack"):
        assert f'id="{cid}"' in html, f"设置卡缺控件 {cid}"
    assert 'min="2" max="120"' in html  # 保留秒数界
    assert 'min="1" max="8"' in html    # 同屏条数界
    js = _js()
    assert "'sap-hud-pop': 'pop'" in js
    assert "'sap-hud-hold': { key: 'holdMs', min: 2, max: 120" in js
    assert "'sap-hud-stack': { key: 'stackMax', min: 1, max: 8" in js
    assert "draft[NUMCFG[t.id].key] = numToCfg(t.id, t.value);" in js
    # 保存/发布主链路未动（S170 锚）
    assert "publishHudCfg(draft)" in js


def test_behavior_harness_green():
    r = subprocess.run(
        ["node", str(ROOT / "tests/data/hud_pop_harness_s272.js"),
         str(ROOT / "static/js/hud-capsule.js")],
        capture_output=True, text=True, timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0 and "all passed" in out, out[-600:]
