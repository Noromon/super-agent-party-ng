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
        # island 联动不随迁（R6）：closed 回调里不得引用 dynamicIslandWindow
        i = g.find("open-minimal-window")
        block = g[i:i + 2600]
        assert "dynamicIslandWindow" not in block
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
        assert "build=S135" in _read("static", "js", "renderer.js")

    def test_i18n_parity(self):
        z = _read("static", "js", "locales", "zh-CN.js")
        e = _read("static", "js", "locales", "en-US.js")
        for key in ("minimalMode", "minimalModeClose"):
            assert f"'{key}'" in z and f"'{key}'" in e
