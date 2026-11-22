# build=S302
# S278：AI 浏览器行为策略引擎——下载/上传框/JS弹窗/离页/权限 的可配置自动处置 +
# 决策记账回报（browser_policy_report）。静态锁：主进程钩子、IPC/桥、设置面、双注册。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")


def test_policy_schema_and_defaults():
    assert "'file-input'" in MAIN and "ev.preventDefault();" in MAIN
    assert "will-prevent-unload" in MAIN and "ev.allow();" in MAIN
    assert "javascript-dialog-opening" in MAIN and "ev.cancel();" in MAIN
    assert "auto-closed(fallback)" in MAIN
    assert "setPermissionRequestHandler" in MAIN and "callback(false);" in MAIN
    # CDP 主管 + 记账
    assert "Page.javascriptDialogOpening" in MAIN
    assert "Page.handleJavaScriptDialog" in MAIN
    assert "Page.enable" in MAIN and "Page.disable" in MAIN
    assert "function sapReconcileDialogWatch" in MAIN


def test_policy_ipc_and_persistence():
    assert "ipcMain.handle('set-browser-policy'" in MAIN
    i = MAIN.index("ipcMain.handle('set-browser-policy'")
    seg = MAIN[i:i + 1200]
    assert "saveEnvVariable('browserPolicySettings'" in seg
    assert "sapReconcileDialogWatch();" in seg
    assert "['save', 'cancel', 'ask'].includes(o.download)" in seg
    assert "ipcMain.handle('policy-take'" in MAIN
    # 启动合并持久化
    j = MAIN.index("globalConfig.browserPolicySettings")
    assert "['dismiss', 'accept', 'ask'].includes(saved.jsDialog)" in MAIN[j - 300:j + 800]


def test_guest_hooks_registered():
    i = MAIN.index("contents.on('file-input'")
    seg = MAIN[i - 400:i + 1800]
    assert "getType() === 'webview'" in seg
    assert "beforeunload auto-allowed" in seg
    assert "contents.once('destroyed'" in seg


def test_renderer_wiring():
    pre = (ROOT / "static/js/preload.js").read_text(encoding="utf-8")
    assert "setBrowserPolicy: (obj) => ipcRenderer.invoke('set-browser-policy', obj)" in pre
    assert "browserPolicyTake: (wcId) => ipcRenderer.invoke('policy-take', wcId)" in pre
    brain = (ROOT / "static/js/data/20_brain_settings.js").read_text(encoding="utf-8")
    i = brain.index("browserPolicySettings")
    seg = brain[i:i + 300]
    assert "enabled: true" in seg and "download: 'save'" in seg
    assert "jsDialog: 'dismiss'" in seg and "beforeUnload: true" in seg
    schema = (ROOT / "static/js/settings_schema.js").read_text(encoding="utf-8")
    assert "['browserPolicySettings', 'browserPolicySettings']," in schema
    # 双通道推送：autoSave + 启动双推
    sysm = (ROOT / "static/js/methods/60_system_settings.js").read_text(encoding="utf-8")
    assert "window.electronAPI.setBrowserPolicy(JSON.parse(JSON.stringify(this.browserPolicySettings || {})))" in sysm
    ren = (ROOT / "static/js/renderer.js").read_text(encoding="utf-8")
    assert "_pushBrowserPolicy" in ren and "setTimeout(_pushBrowserPolicy, 2000)" in ren


def test_ui_controls():
    tk = (ROOT / "static/templates/page_toolkit.html").read_text(encoding="utf-8")
    for anchor in ("browserPolicyTitle", 'v-model="browserPolicySettings.download"',
                   'v-model="browserPolicySettings.fileInput"', 'v-model="browserPolicySettings.jsDialog"',
                   "browserPolicySettings.enabled !== false", "browserPolicySettings.beforeUnload !== false"):
        assert anchor in tk, anchor
    for p in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        s = (ROOT / p).read_text(encoding="utf-8")
        for k in ("browserPolicyTitle", "browserPolicyDownload", "browserPolicyOptSave",
                  "browserPolicyOptBlock", "browserPolicyOptAccept", "browserPolicyNote"):
            assert f"'{k}'" in s, f"{p} 缺 {k}"


def test_report_tool_everywhere():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    assert "async browserPolicyReport(pageIndex)" in js
    assert "api.browserPolicyTake(wcId)" in js
    assert "no auto-decisions on this tab" in js
    cdp = (ROOT / "py/cdp_tool.py").read_text(encoding="utf-8")
    assert "async def browser_policy_report(" in cdp
    assert '"name": "browser_policy_report"' in cdp
    # S301：钩子表构建迁 py/tool_hooks.py，两表计数在合并面上守恒（表体逐字未动）
    srv = ((ROOT / "server.py").read_text(encoding="utf-8")
           + (ROOT / "py/tool_hooks.py").read_text(encoding="utf-8"))
    assert srv.count("browser_policy_report") == 6  # 2 imports + 2 hook 行(键+值)
    assert srv.count('"browser_policy_report": browser_policy_report') == 2
