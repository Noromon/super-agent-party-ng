# S167：HUD 设置卡修复（持续回填+显式保存）+ 主动预览通道 + 默认可见性
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HUD_JS = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
PAGE_SYS = (ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static" / "js" / "preload.js").read_text(encoding="utf-8")
HUD_CSS = (ROOT / "static" / "css" / "hud-capsule.css").read_text(encoding="utf-8")


class TestSettingsRefillFix:
    def test_observer_never_disconnects(self):
        # 根因回归钉：一次性 observer（找到即 disconnect）导致切页重渲染后控件回填丢失
        assert "disconnect" not in HUD_JS
        assert "MutationObserver" in HUD_JS
        assert "scheduleFill" in HUD_JS

    def test_dirty_draft_not_overwritten(self):
        assert "dirty" in HUD_JS
        assert "if (dirty) return" in HUD_JS

    def test_explicit_save_flow(self):
        assert "localStorage.setItem(CFG_KEY, JSON.stringify(draft))" in HUD_JS
        assert "sap-hud-save" in HUD_JS
        assert "sap-hud-reset" in HUD_JS
        assert "已保存" in HUD_JS


class TestSettingsCardUi:
    def test_buttons_present(self):
        assert 'id="sap-hud-open"' in PAGE_SYS
        assert 'id="sap-hud-save"' in PAGE_SYS
        assert 'id="sap-hud-status"' in PAGE_SYS
        assert "打开灵动岛并预览 HUD" in PAGE_SYS
        assert "保存设置" in PAGE_SYS

    def test_templates_still_script_free(self):
        assert "<script" not in PAGE_SYS.lower()

    def test_preview_uses_exposed_api(self):
        assert "openIslandWindow" in HUD_JS
        assert "showHudDemo" in HUD_JS


class TestGlueLoadedOnBothEntries:
    def test_index_and_chat_both_load_hud_glue(self):
        # S169 事故钉：主窗口 UI=index.html，只挂 chat.html 会导致设置卡胶水永不执行
        for page in ("index.html", "chat.html"):
            body = (ROOT / "static" / page).read_text(encoding="utf-8")
            assert 'src="js/hud-capsule.js"' in body, f"{page} 缺 hud-capsule.js"


class TestDemoChannel:
    def test_main_handle(self):
        assert "'show-hud-demo'" in MAIN
        assert "did-finish-load" in MAIN
        assert "'hud-demo'" in MAIN

    def test_preload_bridge(self):
        assert "showHudDemo: () => ipcRenderer.invoke('show-hud-demo')" in PRELOAD
        assert "'hud-demo'" in PRELOAD  # on 白名单

    def test_island_side_handler(self):
        assert "ipcRenderer.on('hud-demo', showDemo)" in HUD_JS
        assert "function showDemo" in HUD_JS
        assert "HUD 演示气泡" in HUD_JS


class TestDefaultVisibility:
    def test_dim_default_off(self):
        assert "dim: false" in HUD_JS

    def test_capsule_bigger(self):
        assert "width: 18px; height: 18px;" in HUD_CSS
