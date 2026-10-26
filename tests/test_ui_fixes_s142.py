# -*- coding: utf-8 -*-
"""S142 批量 UI/窗口修复钉桩：②标签页溢出兜底 ③窗口尺寸记忆全链。

①（reasoningVisible 热更）由 tests/test_reasoning_hotapply.py 行为级覆盖，本文件只做静态链完整性。
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


class TestTabsOverflowS143:
    def test_css_real_scroll_container(self):
        css = _read("static", "css", "styles.css")
        i = css.find(".el-tabs--top .el-tabs__nav-wrap:not(.is-scrollable) .el-tabs__nav-scroll")
        assert i > 0
        assert "overflow-x: auto" in css[i:i + 160]
        assert ".el-tabs--top .el-tabs__nav-wrap:not(.is-scrollable) .el-tabs__nav { float: none; }" in css
        assert "::-webkit-scrollbar { height: 6px; }" in css
        # S142 无效版已撤销：wrap 层不再直接挂 overflow-x
        assert ".el-tabs__nav-wrap:not(.is-scrollable) {" not in css

    def test_wheel_horizontal_delegate(self):
        s = _read("static", "js", "methods", "58_shortcuts_input.js")
        assert "el-tabs__nav-scroll" in s
        assert "scrollLeft += e.deltaY" in s
        assert "passive: false" in s

    def test_narrow_settings_media(self):
        css = _read("static", "css", "styles.css")
        i = css.find("@media (max-width: 880px)")
        assert i > 0
        assert ".settings-form { padding: 16px" in css[i:i + 200]


class TestNarrowLayoutS144:
    def test_min_width_chain(self):
        # 撑宽 el-main 被裁的盲区=flex min-width:auto；三层归零让约束传导进页面
        css = _read("static", "css", "styles.css")
        assert ".main-container .content { min-width: 0; }" in css
        assert ".page { min-width: 0; }" in css
        assert ".settings-form { min-width: 0; }" in css

    def test_fluid_settings_rows_unconditional(self):
        css = _read("static", "css", "styles.css")
        assert ".settings-form .form-item-align { flex-wrap: wrap; row-gap: 4px; }" in css
        assert ".settings-form .el-form-item__label { white-space: normal; min-width: 0; }" in css
        assert ".settings-form .el-form-item__content { min-width: 0; flex-wrap: wrap; column-gap: 8px; }" in css
        assert ".settings-form .el-select { max-width: 100%; }" in css

    def test_narrow_visible_scrollbar(self):
        css = _read("static", "css", "styles.css")
        i = css.find("@media (max-width: 1024px)")
        assert i > 0
        blk = css[i:i + 460]
        assert "scrollbar-width: thin" in blk
        assert ".content::-webkit-scrollbar { display: block" in blk
        # 必须排在 .content 基础规则（scrollbar-width:none）之后，媒体查询同特异性靠层叠取胜
        assert css.find("scrollbar-width: none") < i


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
