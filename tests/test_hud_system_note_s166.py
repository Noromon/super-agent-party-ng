# S166：system_note 元频道 + 游戏 HUD（胶囊层/置顶强化/设置卡）
# 静态钉桩为主（跨 server/main/前端多文件协议面），行为面由 S163/S164 既有用例覆盖。
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
XMPP = (ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")
DIARY = (ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static" / "js" / "preload.js").read_text(encoding="utf-8")
BOTCONV = (ROOT / "static" / "js" / "methods" / "51_bots_conversations.js").read_text(encoding="utf-8")
ISLAND_HTML = (ROOT / "static" / "island.html").read_text(encoding="utf-8")
HUD_JS = (ROOT / "static" / "js" / "hud-capsule.js").read_text(encoding="utf-8")
HUD_CSS = (ROOT / "static" / "css" / "hud-capsule.css").read_text(encoding="utf-8")
PAGE_SYS = (ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")


def _seg(src, start, end):
    i = src.index(start)
    j = src.index(end, i)
    return src[i:j]


class TestSystemNoteTagging:
    def test_resume_nudge_tagged(self):
        assert '"content": RESUME_NUDGE_TEXT, "name": "system_note"' in SERVER

    def test_tool_correction_tagged(self):
        seg = _seg(SERVER, '"content": build_correction_message', "})")
        assert '"name": "system_note"' in seg

    def test_image_blocked_note_tagged(self):
        i = XMPP.index("图片路径被拦截")
        assert '"name": "system_note"' in XMPP[max(0, i - 260):i]

    def test_diary_chat_buffer_skips_note(self):
        assert 'last_msg.get("name") != "system_note"' in SERVER


class TestHumanLineFilter:
    def test_bot_conversation_card_filters_notes(self):
        assert "m.name === 'system_note'" in BOTCONV
        assert "json.messages" in BOTCONV


class TestObservationLine:
    def test_diary_push_emits_notification(self):
        seg = _seg(DIARY, "async def _push_to_im", "from py.behavior_engine import")
        assert '_nc.emit("bot"' in seg
        assert "日记主动转达" in seg


class TestHudWindow:
    def test_screen_saver_level(self):
        assert MAIN.count("'screen-saver'") >= 2  # 初设 + 30s 重申

    def test_visible_on_fullscreen(self):
        assert "setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })" in MAIN

    def test_reassert_timer_cleared_on_close(self):
        # S170 起 closed 回调挂在局部 win 上（身份守卫防旧窗迟到回调误清新窗引用）
        seg = _seg(MAIN, "win.on('closed'", "return true;")
        assert "clearInterval(_islandReassert)" in seg

    def test_capsule_hotkey(self):
        assert "Alt+Shift+H" in MAIN
        assert "'hud-toggle-capsule'" in MAIN
        # 快捷键随岛关闭注销，避免残留劫持全局按键
        seg = _seg(MAIN, "win.on('closed'", "return true;")
        assert "globalShortcut.unregister('Alt+Shift+H')" in seg

    def test_preload_whitelist(self):
        assert "hud-toggle-capsule" in PRELOAD


class TestHudModule:
    def test_html_wired(self):
        assert 'href="css/hud-capsule.css"' in ISLAND_HTML
        assert 'src="js/hud-capsule.js"' in ISLAND_HTML

    def test_consumes_notification_broadcast(self):
        assert "d.type === 'notification'" in HUD_JS
        assert "sapHudCfg" in HUD_JS

    def test_hot_reload_via_storage(self):
        assert "'storage'" in HUD_JS

    def test_idle_dim_and_capsule(self):
        assert "hud-dim" in HUD_JS
        assert "toggleCapsule" in HUD_JS

    def test_css_layer(self):
        assert "#sap-hud-layer" in HUD_CSS
        assert "hud-has-unread" in HUD_CSS

    def test_settings_card_wired(self):
        assert "sap-hud-card" in PAGE_SYS
        assert "sap-hud-pos" in PAGE_SYS
        assert "无边框窗口" in PAGE_SYS  # 独占全屏平台限制必须写明
        assert "sapHudCfg" in HUD_JS    # 卡片键位读写在 hud 模块胶水层（templates 禁内联脚本）
        assert "bindSettings" in HUD_JS
        CHAT = (ROOT / "static" / "chat.html").read_text(encoding="utf-8")
        assert 'src="js/hud-capsule.js"' in CHAT


class TestIslandCssRedlineUntouched:
    def test_island_css_not_imported_by_hud(self):
        # hud 皮肤独立文件，island.css 保持逐字节红线（完整性由 test_r6_island 校验）
        assert "island.css" not in HUD_CSS
        assert ".island" not in HUD_CSS.split("/* S166")[0]
