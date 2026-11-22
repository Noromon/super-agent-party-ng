# build=S300
# S274：HUD 角标可选 + 胶囊点击展开历史面板（鼠标桥/冲突守卫/标记已读/穿透恢复）。
# 行为面由 hud_pop_harness_s272.js 第四段驱动；本文件锁接线与静态面。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js():
    return (ROOT / "static/js/hud-capsule.js").read_text(encoding="utf-8")


def _css():
    return (ROOT / "static/css/hud-capsule.css").read_text(encoding="utf-8")


def _sys():
    return (ROOT / "static/templates/page_system.html").read_text(encoding="utf-8")


def test_badge_toggle_cfg_and_render():
    js = _js()
    assert "badge: true," in js
    i = js.index("function applyCfg")
    seg = js[i:i + 900]
    assert "(cfg.badge ? '' : ' hud-no-badge')" in seg
    assert ".sap-hud-capsule.hud-no-badge .hud-badge { display: none !important; }" in _css()


def test_capsule_clickable_and_panel_events():
    js = _js()
    assert "capsule.addEventListener('click', function () { lastNativeClickTs = Date.now(); togglePanel(); });" in js
    assert "mouseenter" in js and "hudHoldMouse(true)" in js
    b = _css()
    assert ".sap-hud-capsule { pointer-events: auto; cursor: pointer; }" in b


def test_mouse_hold_bridge_and_island_guard():
    js = _js()
    i = js.index("function hudHoldMouse")
    seg = js[i:i + 600]
    assert "window.__sapHudHoldMouse = !!on;" in seg
    assert "setIgnoreMouseEvents(false)" in seg
    assert "setIgnoreMouseEvents(true, { forward: true })" in seg
    # island-app 的恢复穿透必须让位给 HUD 持握
    ia = (ROOT / "static/js/island-app.js").read_text(encoding="utf-8")
    i2 = ia.index("setMouseIgnore(ignore) {")
    assert "if (ignore && window.__sapHudHoldMouse) return;" in ia[i2:i2 + 400]


def test_panel_data_flow():
    js = _js()
    i = js.index("async function loadPanelList")
    seg = js[i:i + 2400]
    assert "/api/notifications?limit=50" in seg
    assert "'/api/notifications/read'" in seg and "'POST'" in seg.replace("method: 'POST'", "'POST'")
    assert "clearUnread();" in seg  # 打开即清本地角标
    # 竞态：fetch 回来时面板已换/已关则不写入
    assert "panel !== myPanel" in seg
    assert "credentials: 'same-origin'" in seg


def test_panel_css_corners():
    css = _css()
    for corner in ("nw", "n", "ne", "sw", "s", "se"):
        assert f".sap-hud-panel.hud-pos-{corner}" in css
    assert ".sap-hud-panel { pointer-events: auto" in css or "pointer-events: auto;\n  overflow" in css
    assert ".hud-p-list" in css and ".hud-p-close" in css


def test_settings_card_and_escaping():
    sys_html = _sys()
    assert 'id="sap-hud-badge"' in sys_html
    js = _js()
    assert "'sap-hud-badge': 'badge'" in js
    assert "$id('sap-hud-badge').checked" in js
    # Esc 兜底
    assert "e.key === 'Escape'" in js
    # HUD 关闭时面板必须收起（防残影）
    i = js.index("function applyCfg")
    assert "closePanel(); stopPoll(); layer.classList.add('hud-hidden')" in js[i:i + 400]  # S282: 禁用时停轮询


def test_behavior_harness_covers_s274():
    h = (ROOT / "tests/data/hud_pop_harness_s272.js").read_text(encoding="utf-8")
    for anchor in ("hud-no-badge", "__sapHudHoldMouse", "/api/notifications?limit=50",
                   "/api/notifications/read", "Escape"):
        assert anchor in h, f"harness 缺 S274 断言锚 {anchor}"
