# -*- coding: utf-8 -*-
"""S142 批量 UI/窗口修复钉桩：②标签页溢出兜底 ③窗口尺寸记忆全链。

①（reasoningVisible 热更）由 tests/test_reasoning_hotapply.py 行为级覆盖，本文件只做静态链完整性。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


class TestTabsOverflowS142:
    def test_css_fallback_rule(self):
        css = _read("static", "css", "styles.css")
        assert ".el-tabs--top .el-tabs__nav-wrap:not(.is-scrollable)" in css
        i = css.find(".el-tabs--top .el-tabs__nav-wrap:not(.is-scrollable)")
        assert "overflow-x: auto" in css[i:i + 200]
        assert "scrollbar-width: thin" in css[i:i + 200]


class TestWindowSizeMemoryS142:
    def test_main_bounds_persistence(self):
        s = _read("main.js")
        assert "WINDOW_BOUNDS_FILE" in s
        assert "window-bounds.json" in s
        for fn in ("loadWindowBounds", "writeWindowBounds", "validBounds", "saveWindowBounds", "persistMaximized"):
            assert re.search(r"function " + fn + r"\(", s), fn
        assert "set-window-size-memory" in s
        # 创建时恢复 + 防抖保存 + 关闭兜底
        assert "validBounds(saved)" in s
        assert "saved.maximized" in s
        assert "setTimeout(saveWindowBounds, 500)" in s
        assert "saveWindowBounds() // S142" in s

    def test_preload_bridge(self):
        s = _read("static", "js", "preload.js")
        assert "setWindowSizeMemory" in s and "set-window-size-memory" in s

    def test_settings_chain(self):
        assert '"rememberWindowSize": true' in _read("config", "settings_template.json")
        assert "rememberWindowSize: true" in _read("static", "js", "data", "20_brain_settings.js")
        h = _read("static", "templates", "page_system.html")
        assert "systemSettings.rememberWindowSize" in h and "onWindowSizeMemoryChange" in h
        assert "windowSizeMemory" in h
        m = _read("static", "js", "methods", "60_system_settings.js")
        assert "syncWindowSizeMemory()" in m and "onWindowSizeMemoryChange()" in m
        assert "electronAPI.setWindowSizeMemory" in m
        # 启动同步链：ws init 里调用（在 loadSoulxImages 之后）
        w = _read("static", "js", "methods", "14_ws_client.js")
        assert w.find("syncWindowSizeMemory") > w.find("loadSoulxImages")

    def test_locales_parity(self):
        for f in ("zh-CN.js", "en-US.js"):
            s = _read("static", "js", "locales", f)
            assert "'windowSizeMemory'" in s and "'windowSizeMemoryDesc'" in s


class TestReasoningHotApplyChainS142:
    def test_all_managers_sync_field(self):
        for f in ("xmpp_bot_manager.py", "telegram_bot_manager.py", "feishu_bot_manager.py",
                  "wecom_bot_manager.py", "qq_bot_manager.py", "wechat_bot_manager.py"):
            s = _read("py", f)
            assert "client.reasoningVisible = config.reasoningVisible" in s, f
        d = _read("py", "discord_bot_manager.py")
        assert "client.config.reasoning_visible = config.reasoning_visible" in d
        assert os.path.exists(os.path.join(ROOT, "tests", "test_reasoning_hotapply.py"))
