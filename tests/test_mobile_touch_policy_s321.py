# S321：触摸仿真全局停发（贴吧 new_page(mobile) 把宿主窗口翻成触摸模式的事故）。
# 机制：guest 的 Emulation.setTouchEmulationEnabled(true) 经 NativeWindowKit 翻转
# 整个窗口的触摸模式，guest 销毁不复位——关光标签仍「点击须双击/光标变触摸点」。
# 本测钉桩：ON 分支不再发 enabled:true 触摸命令（顺带显式清 guest 旧残留）/
# 启动 host 自愈清扫 / reset_page_state 的 host 通道 / 工具描述政策口径。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
SAP = (ROOT / "main_lib" / "sap_emulation.js").read_text(encoding="utf-8")
AGENT = (ROOT / "static" / "js" / "methods" / "80_webview_agent.js").read_text(encoding="utf-8")
TABS = (ROOT / "static" / "js" / "methods" / "98_browser_tabs.js").read_text(encoding="utf-8")
CDP = (ROOT / "py" / "cdp_tool.py").read_text(encoding="utf-8")


class TestNoTouchEnableEver:
    def test_no_enabled_true_touch_commands(self):
        for src, name in ((MAIN, "main.js"), (SAP, "sap_emulation.js")):
            assert "setTouchEmulationEnabled', { enabled: true" not in src, name
            assert "setEmitTouchEventsForMouse', { enabled: true" not in src, name

    def test_mobile_on_branch_clears_stale_touch(self):
        i = MAIN.index("if (mobile) {")
        seg = MAIN[i:i + 2400]
        assert "setTouchEmulationEnabled', { enabled: false" in seg
        assert "setEmitTouchEventsForMouse', { enabled: false }" in seg
        assert "touch: 'off-by-policy'" in seg
        # S277 半失败补偿骨架必须健在
        assert "if (touchOn)" in seg and "emulation-failed-touch-reset" in seg

    def test_mobile_still_ua_and_viewport(self):
        i = MAIN.index("if (mobile) {")
        seg = MAIN[i:i + 2400]
        assert "Emulation.setUserAgentOverride" in seg
        assert "Emulation.setDeviceMetricsOverride" in seg


class TestHostSweep:
    def test_helper_exists_and_only_touch(self):
        i = SAP.index("async function sapHostTouchClear")
        seg = SAP[i:i + 1200]
        assert "setEmitTouchEventsForMouse', { enabled: false }" in seg
        assert "setTouchEmulationEnabled', { enabled: false" in seg
        assert "clearUserAgentOverride" not in seg  # 宿主只清触摸，不动 UA/视口
        assert "debugger.detach" in seg
        assert "sapHostTouchClear" in SAP[SAP.rindex("module.exports"):]

    def test_startup_self_heal_wired(self):
        i = MAIN.index("启动自愈")
        seg = MAIN[i:i + 480]
        assert "sapHostTouchClear" in seg
        assert "setTimeout" in seg  # 延迟执行：等主窗装载，DevTools 占用静默跳过

    def test_reset_host_channel_all_layers(self):
        i = MAIN.index("ipcMain.handle('webview-emulation-reset'")
        seg = MAIN[i:i + 900]
        assert "if (id === 0)" in seg and "sapHostTouchClear" in seg
        assert "resetPageState(reload, host)" in AGENT
        assert "apih.emulationReset(0)" in AGENT
        assert "host window touch mode cleared" in AGENT
        assert "async def reset_page_state(reload=False, host=False)" in CDP
        assert "[bool(reload), bool(host)]" in CDP


class TestPolicyWording:
    def test_tool_descriptions_state_no_touch(self):
        assert CDP.count("S321：移动模式不含触摸仿真") >= 2
        assert "S321：旧版触摸仿真的污染挂在窗口层" in CDP or "窗口层污染" in CDP

    def test_renderer_hint(self):
        assert "touch off by policy S321" in TABS
