# S170：岛窗生命周期守卫 + HUD 配置 ipc 主通道 + 方位 CSS 冲突修复
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static" / "js" / "preload.js").read_text(encoding="utf-8")
HUD_JS = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
HUD_CSS = (ROOT / "static" / "css" / "hud-capsule.css").read_text(encoding="utf-8")


def _seg(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class TestIslandLifecycleGuard:
    def test_reentry_lock(self):
        assert "islandOpening" in MAIN
        seg = _seg(MAIN, "ipcMain.handle('open-island-window'", "islandOpening = true;")
        assert "if (islandOpening) return true;" in seg

    def test_closed_identity_guard(self):
        # 旧窗迟到的 closed 回调不得清空新窗引用（泄漏岛群根因回归钉）
        seg = _seg(MAIN, "win.on('closed'", "return true;")
        assert "if (dynamicIslandWindow !== win) return;" in seg
        i = seg.index("if (dynamicIslandWindow !== win) return;")
        assert "dynamicIslandWindow = null" in seg[i:]  # 置空只允许发生在守卫之后
        assert "clearInterval(_islandReassert)" in seg[:i]  # 自己的 timer 无条件清

    def test_focus_returned_to_main(self):
        seg = _seg(MAIN, "win.on('closed'", "finally")
        assert "mainWindow.focus()" in seg

    def test_null_sites_are_guarded(self):
        # 合法置空共 3 处：入口关旧窗（同步）、gone 身份守卫内、closed 身份守卫后
        seg = _seg(MAIN, "ipcMain.handle('open-island-window'", "ipcMain.handle('close-island-window'")
        assert seg.count("dynamicIslandWindow = null") == 3
        assert seg.count("dynamicIslandWindow === win") >= 2


class TestHudCfgIpcChannel:
    def test_main_handles(self):
        assert "'hud-cfg-publish'" in MAIN
        assert "'hud-cfg-get'" in MAIN
        assert "hud_cfg.json" in MAIN
        # 岛页就绪即补推持久化配置
        seg = _seg(MAIN, "await win.loadURL", "setAlwaysOnTop")
        assert "send('hud-cfg'" in seg

    def test_preload_bridge(self):
        assert "publishHudCfg: (cfg) => ipcRenderer.invoke('hud-cfg-publish', cfg)" in PRELOAD
        assert "getHudCfg: () => ipcRenderer.invoke('hud-cfg-get')" in PRELOAD
        assert "'hud-cfg'" in PRELOAD

    def test_island_pull_and_push(self):
        assert "getHudCfg()).then" in HUD_JS
        assert "ipcRenderer.on('hud-cfg'" in HUD_JS
        assert "function mergeCfg" in HUD_JS
        assert "if (cfg.enabled && !layer) build();" in HUD_JS

    def test_save_dual_writes(self):
        seg = _seg(HUD_JS, "localStorage.setItem(CFG_KEY, JSON.stringify(draft))", "dirty = false;")
        assert "publishHudCfg(draft)" in seg


class TestPreviewNoRebuild:
    def test_state_checked_before_open(self):
        seg = _seg(HUD_JS, "sap-hud-open", "预览需在桌面端主窗口中使用")
        assert "getIslandWindowState" in seg
        assert "if (open) { if (api.showHudDemo) api.showHudDemo(); }" in seg


class TestPositionCss:
    def test_no_transform_conflict_on_bubble(self):
        # hud-pos-n/s 的 translateX(-50%) 不得再被气泡动画 transform 覆盖
        assert "translateY" not in HUD_CSS
        seg = _seg(HUD_CSS, ".sap-hud-bubble {", ".sap-hud-bubble.hud-show")
        assert "transform" not in seg
