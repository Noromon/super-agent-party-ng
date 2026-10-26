# -*- coding: utf-8 -*-
"""S135：极简模式（上游 A4）移植钉桩。"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace").read()


class TestMinimalModeS135:
    def test_minimal_html_ported(self):
        s = _read("static", "minimal.html")
        assert len(s) > 30000
        assert "/ws/asr" in s and "new WebSocket" in s
        assert "electronAPI" in s

    def test_main_ipc_handlers(self):
        g = _read("main.js")
        for ch in ("open-minimal-window", "close-minimal-window", "get-minimal-window-state"):
            assert ch in g
        assert "let minimalWindow = null" in g
        assert "minimal.html" in g
        # R6(S139) 起 island 联动行随迁：closed 回调须通知灵动岛
        i = g.find("open-minimal-window")
        block = g[i:i + 2900]
        assert "dynamicIslandWindow" in block
        assert "minimal-window-closed" in block

    def test_preload_bridge(self):
        p = _read("static", "js", "preload.js")
        for api in ("openMinimalWindow", "closeMinimalWindow", "getMinimalWindowState", "onMinimalWindowClosed"):
            assert api in p

    def test_method_and_state(self):
        m = _read("static", "js", "methods", "54_ui_nav.js")
        assert "toggleMinimalMode()" in m
        assert "openMinimalWindow" in m and "onMinimalWindowClosed" in m
        d = _read("static", "js", "data", "50_bots_translate.js")
        assert "isMinimalMode: false" in d

    def test_topbar_button_and_stamp(self):
        h = _read("static", "index.html")
        assert 'id="minimal-mode-btn"' in h
        assert 'toggleMinimalMode' in h
        assert "fa-feather" in h
        assert "build=S143" in _read("static", "js", "renderer.js")

    def test_stream_snapshot_full_key(self):
        # S138：快照键含内容长度+尾部——上游原版只取前 300 字符，
        # 流式回复超前缀窗口后渲染被去重冻结
        h = _read("static", "minimal.html")
        a = h.find("function _doRender")
        block = h[a:a + 2200]
        assert "c.slice(-160)" in block and "c.length" in block
        assert "substring(0, 300)" not in block

    def test_zombie_ws_selfheal(self):
        h = _read("static", "minimal.html")
        assert "lastMsgAt = Date.now()" in h
        assert "Date.now() - lastMsgAt > 60000" in h
        w = _read("py", "ws_manager.py")
        assert "WS sender 失效" in w and "logger.warning" in w
        assert "_safe_close" in w

    def test_minimal_ws_auth_bootstrap(self):
        # S137：minimal 是上游无鉴权版移植——补 M2 session token 面
        h = _read("static", "minimal.html")
        assert "fetch('/session_token'" in h
        assert "sap_token=" in h and "bootWS()" in h
        g = _read("main.js")
        i = g.find("open-minimal-window")
        block = g[i:i + 1600]
        assert "webSecurity" not in block
        s = _read("server.py")
        j = s.find("if not sap_auth.ws_auth_ok(websocket):")
        assert "handshake rejected" in s[j:j + 280]

    def test_i18n_parity(self):
        z = _read("static", "js", "locales", "zh-CN.js")
        e = _read("static", "js", "locales", "en-US.js")
        for key in ("minimalMode", "minimalModeClose"):
            assert f"'{key}'" in z and f"'{key}'" in e
