# build=S276
# S263：mobile touch 仿真复位加固——残留曾致触摸圆点/首击被吞/右键菜单消失/wheel 失真。
# 根因：desktop off 从不显式关 setEmitTouchEventsForMouse（只靠 detach 隐式清理，
# detach 可失败），且整套清理被 isAttached&&_sapMobileDbg.has 双条件闸住直接跳过；
# wheel/click 还把桌面 tab attach 混进 _sapMobileDbg 污染语义。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")


def _off_seg():
    i = MAIN.index("S263: touch 仿真残留事故")
    return MAIN[i:i + 1400]


def test_off_disables_emit_touch_explicitly():
    seg = _off_seg()
    assert "setEmitTouchEventsForMouse', { enabled: false }" in seg
    assert "setTouchEmulationEnabled', { enabled: false" in seg
    assert "clearDeviceMetricsOverride" in seg and "clearUserAgentOverride" in seg


def test_off_reset_not_gated_by_set_membership():
    seg = _off_seg()
    # 复位以 isAttached 为闸，set 成员只决定 detach 归属
    assert "if (wc.debugger.isAttached())" in seg
    assert "isAttached() && _sapMobileDbg.has(wcId)" not in seg
    assert "if (_sapMobileDbg.has(wcId))" in seg


def test_wheel_click_attach_uses_separate_set():
    assert "_sapInputDbg" in MAIN
    # mobile 专属集合不再收 wheel/click 的临时 attach
    assert MAIN.count("_sapInputDbg.add(wcId)") >= 2
    seg = MAIN[MAIN.index("cdp-input-wheel"):MAIN.index("cdp-input-click")]
    assert "_sapMobileDbg" not in seg


def test_arm_body_cap_lowered():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    assert "CAP=BODY?80:500" in js
