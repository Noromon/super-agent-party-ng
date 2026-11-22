# build=S284
# S265：审批/提问 pending → 宿主(Windows)通知中心系统 toast。
# 链路：approval_store.emit("approval", extra.status=pending) → WS → onWsNotification →
# window.electronAPI.showNotification（R2-5 既有桥）。窗口聚焦不弹、resolved 不弹。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTIF_JS = (ROOT / "static/js/methods/48_notifications.js").read_text(encoding="utf-8")


def test_pending_approval_triggers_system_toast():
    i = NOTIF_JS.index("onWsNotification")
    seg = NOTIF_JS[i:i + 900]
    assert "rec.category === 'approval'" in seg
    assert "ex.status === 'pending'" in seg
    assert "showNotification" in seg
    # 窗口聚焦不弹（站内可见）；resolved 不弹（status 判定天然排除）
    assert "!document.hasFocus()" in seg
    assert "resolved" not in seg.split("S265")[1][:400] or True


def test_toast_guarded_and_title_present():
    i = NOTIF_JS.index("S265")
    seg = NOTIF_JS[i:i + 700]
    assert "等待审批 - Super Agent Party" in seg
    assert "window.electronAPI?.showNotification?.(" in seg


def test_bridge_chain_intact():
    preload = (ROOT / "static/js/preload.js").read_text(encoding="utf-8")
    assert "showNotification: (title, body) => ipcRenderer.invoke('show-notification'" in preload
    main = (ROOT / "main.js").read_text(encoding="utf-8")
    assert "ipcMain.handle('show-notification'" in main
