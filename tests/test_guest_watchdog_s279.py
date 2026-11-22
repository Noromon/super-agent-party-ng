# build=S288
# S279：guest 崩溃/挂起看门狗 + 崩溃自动重载（crashReload 可配）+ reset_page_state 审计。
# 全部经 _policyNote → browser_policy_report 对 agent 可见。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")


def _wd_seg():
    i = MAIN.index("render-process-gone', (ev, details)")
    return MAIN[i - 300:i + 1400]


def test_guest_watchdog_journals():
    seg = _wd_seg()
    assert "render process gone: " in seg
    assert "'freeze', 'renderer unresponsive" in seg
    assert "reset_page_state reload=true 自救" in seg
    assert "'freeze', 'renderer responsive again'" in seg
    assert "contents.on('unresponsive'" in seg and "contents.on('responsive'" in seg


def test_crash_reload_once_with_anti_loop():
    seg = _wd_seg()
    assert "pol.crashReload === false" in seg
    assert "< 30000" in seg
    assert "auto-reload skipped (30s anti-loop)" in seg
    assert "contents.reload(); _policyNote" in seg


def test_crash_reload_plumbing():
    j = MAIN.index("pol.crashReload = o.crashReload !== false;")
    assert "crashReload: pol.crashReload" in MAIN[j:j + 600]  # 持久化
    k = MAIN.index("saved.crashReload === 'boolean'")
    assert "global.browserPolicy.crashReload = saved.crashReload" in MAIN[k:k + 200]
    brain = (ROOT / "static/js/data/20_brain_settings.js").read_text(encoding="utf-8")
    assert "crashReload: true" in brain
    tk = (ROOT / "static/templates/page_toolkit.html").read_text(encoding="utf-8")
    assert "browserPolicySettings.crashReload !== false" in tk
    for p in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        s = (ROOT / p).read_text(encoding="utf-8")
        assert "'browserPolicyCrashReload'" in s and "'browserPolicyCrashReloadHint'" in s, p


def test_manual_reset_is_journaled():
    i = MAIN.index("ipcMain.handle('webview-emulation-reset'")
    seg = MAIN[i:i + 900]
    assert "'reset', 'reset_page_state executed" in seg
    assert "return rr;" in seg
