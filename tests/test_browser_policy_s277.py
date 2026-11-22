# build=S289
# S277：AI 浏览器失控止血——下载策略接管（永不弹原生另存为）、触摸仿真残留封死
# （无条件复位助手/detach 记账/ON 半失败补偿）、CDP 输入 IPC 限时免疫、reset_page_state。
# 行为面：guest_check_harness.js S277 段（假悬挂回退）；本文件锁接线与静态面。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")


def _dl_seg():
    i = MAIN.index("function handleDownloadItem")
    return MAIN[i:i + 1500]


def test_download_policy_gate():
    seg = _dl_seg()
    assert "getType() === 'webview'" in seg          # 只处置 guest 下载
    assert "!item.getSavePath()" in seg              # 已显式设路径的不动
    assert "act === 'cancel'" in seg and "item.cancel();" in seg
    assert "act === 'save'" in seg and "item.setSavePath(full);" in seg
    assert "'browser_downloads'" in seg
    assert "_policyNote(webContents.id, 'download'" in seg
    # 默认策略：开启+自动存盘（另存为从此不出现）
    j = MAIN.index("global.browserPolicy = {")
    assert "enabled: true, download: 'save'" in MAIN[j:j + 200]


def test_reset_emulation_helper_unconditional():
    i = MAIN.index("async function sapResetEmulation")
    seg = MAIN[i:i + 1800]
    assert "!opts.force && !wasAttached && !known" in seg   # 记账命中可补 attach
    assert "Emulation.setEmitTouchEventsForMouse', { enabled: false }" in seg
    assert "Emulation.setTouchEmulationEnabled', { enabled: false" in seg
    assert "Emulation.clearDeviceMetricsOverride" in seg
    assert "Emulation.clearUserAgentOverride" in seg
    # detach 记账监听：attach 处全挂
    assert "function sapWatchDetach" in MAIN
    assert MAIN.count("sapWatchDetach(wc)") >= 4  # on/mobile-on/wheel/click/reset


def test_on_branch_touch_compensation():
    i = MAIN.index("let touchOn = false;")
    seg = MAIN[i:i + 2400]
    assert "touchOn = true;" in seg
    assert "if (touchOn)" in seg                      # 半失败硬回滚
    assert "emulation-failed-touch-reset" in seg
    assert "sapResetEmulation(wc, wcId, { force: true })" in seg
    # OFF 分支不再静默吞败
    j = MAIN.index("const rr = await sapResetEmulation")
    assert "reset: rr.ok ? 'ok' : ('reset-failed: '" in MAIN[j:j + 400]


def test_emergency_reset_ipc_and_bridge():
    assert "ipcMain.handle('webview-emulation-reset'" in MAIN
    i = MAIN.index("ipcMain.handle('webview-emulation-reset'")
    assert "{ force: true, defaultUA: true, detachInput: true }" in MAIN[i:i + 600]
    pre = (ROOT / "static/js/preload.js").read_text(encoding="utf-8")
    assert "emulationReset: (wcId) => ipcRenderer.invoke('webview-emulation-reset', wcId)" in pre


def test_guest_input_timeout_guard():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    assert "function _inputTmo(p, ms)" in js
    assert "__SAP_INPUT_TMO" in js
    # 全部四个 cdp 输入调用点都过守卫
    assert js.count("_inputTmo(api.cdpInputWheel") == 4
    assert js.count("_inputTmo(api.cdpInputClick") == 1
    assert "api.emulationReset(wcId)" in js
    assert "async resetPageState(reload)" in js
    # tab.mobile 失败回滚（98_browser_tabs）
    tabs = (ROOT / "static/js/methods/98_browser_tabs.js").read_text(encoding="utf-8")
    assert "const applied = !(res && res.ok === false);" in tabs
    assert "tab.mobile = !!enable && applied;" in tabs


def test_tool_registered_everywhere():
    cdp = (ROOT / "py/cdp_tool.py").read_text(encoding="utf-8")
    assert "async def reset_page_state(" in cdp
    assert '"name": "reset_page_state"' in cdp
    srv = (ROOT / "server.py").read_text(encoding="utf-8")
    # 2 imports(×1) + 2 hook 注册行(键+值 ×2) = 6
    assert srv.count("reset_page_state") == 6
    assert srv.count('"reset_page_state": reset_page_state') == 2


def test_behavior_harness_covers_s277():
    h = (ROOT / "tests/data/guest_check_harness.js").read_text(encoding="utf-8")
    for anchor in ("new Promise(() => {})", "__SAP_INPUT_TMO", "S277: 探测悬挂即弃 wheel",
                   "S277: scrollOnce 落到 JS 滚动回退", "S277: scrollAndFind 不再被弹窗卡死"):
        assert anchor in h, f"harness 缺 S277 锚 {anchor}"
