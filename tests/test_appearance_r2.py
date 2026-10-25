"""R2-1 外观包（A14）落位守卫：模板/JS/CSS/preload/settings/i18n 锚点。

背景：S122b/S124 教训——渲染层改动必须可自证。外观包涉及
system 页模板、renderer watch/computed、preload zoom 通道、
独立 appearance.css（styles.css 棘轮已满），逐项钉桩。
"""
import io
import json
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def test_system_page_has_appearance_sections():
    tpl = _read("static", "templates", "page_system.html")
    for needle in (
        "backgroundImage",
        'ref="bgImageInput"',
        "handleBgUpload",
        "systemSettings.bgHistoryList",
        "deleteBgHistory",
        "customCSS",
        "custom-css-textarea",
        "fontPxModel",
        "fontSizeOptions",
        "resetFontScale",
        "codeFontPxModel",
        "codeFontSizeOptions",
        "resetCodeFontScale",
        "saveBgDialogVisible",
        "confirmSaveBg",
    ):
        assert needle in tpl, f"page_system.html missing: {needle}"


def test_system_page_free_of_v_memo():
    # S124 红线：system 页历史上虽非套件四页，外观 section 同样禁止引入 v-memo
    tpl = _read("static", "templates", "page_system.html")
    assert "v-memo" not in tpl


def test_renderer_appearance_watches_and_computed():
    rjs = _read("static", "js", "renderer.js")
    for needle in (
        "'systemSettings.backgroundURL':",
        "'systemSettings.customCSS':",
        "'systemSettings.fontScale':",
        "'systemSettings.codeFontScale':",
        "has-custom-bg",
        "custom-css-injection",
        "setZoomFactor",
        "--app-zoom",
        "--code-zoom",
        "currentFontPx()",
        "currentCodeFontPx()",
        "fontPxModel:",
        "codeFontPxModel:",
        "fontSizeOptions()",
        "codeFontSizeOptions()",
        "build=S1",
    ):
        assert needle in rjs, f"renderer.js missing: {needle}"


def test_appearance_css_registered_and_core_rules():
    css = _read("static", "css", "appearance.css")
    for needle in (
        "--app-zoom",
        "--code-zoom",
        "pre.code-block",
        "calc(var(--code-zoom, 1) / var(--app-zoom, 1))",
        "body.has-custom-bg",
        ".font-size-row",
        ".custom-css-textarea",
    ):
        assert needle in css, f"appearance.css missing: {needle}"
    idx = _read("static", "index.html")
    assert 'href="css/appearance.css"' in idx
    assert 'src="js/data/70_appearance.js"' in idx
    assert 'src="js/methods/87_appearance.js"' in idx


def test_preload_zoom_channel():
    pre = _read("static", "js", "preload.js")
    assert "webFrame" in pre
    assert "setZoomFactor" in pre
    assert "getZoomFactor" in pre


def test_methods_and_data_appearance_shards():
    mjs = _read("static", "js", "methods", "87_appearance.js")
    for needle in (
        "triggerBgUpload",
        "handleBgUpload",
        "clearBgImage",
        "openSaveBgDialog",
        "confirmSaveBg",
        "handleBgHistorySelect",
        "deleteBgHistory",
        "handleFontScaleChange",
        "resetFontScale",
        "handleCodeFontScaleChange",
        "resetCodeFontScale",
        "/load_file",
    ):
        assert needle in mjs, f"87_appearance.js missing: {needle}"
    djs = _read("static", "js", "data", "70_appearance.js")
    assert "saveBgDialogVisible" in djs and "newBgName" in djs
    b = _read("static", "js", "data", "20_brain_settings.js")
    for needle in ("fontScale: 1", "codeFontScale: 1", "customCSS: ''", "backgroundURL: ''", "bgHistoryList: []"):
        assert needle in b, f"20_brain_settings.js missing: {needle}"


def test_settings_template_default_keys():
    st = json.loads(_read("config", "settings_template.json"))
    ss = st.get("systemSettings", {})
    assert ss.get("fontScale") == 1
    assert ss.get("codeFontScale") == 1
    assert ss.get("customCSS") == ""
    assert ss.get("backgroundURL") == ""
    assert ss.get("bgHistoryList") == []


APPEARANCE_I18N_KEYS = [
    "uploadFailed",
    "backgroundImage",
    "saveBgImage",
    "saveBgImageTitle",
    "clearBgImage",
    "changeBgImage",
    "clickToUploadBg",
    "recommendBgRatio",
    "selectHistoryBg",
    "noBackgroundImage",
    "bgImageNamePlaceholder",
    "noBgToSave",
    "pleaseInputBgName",
    "bgSavedSuccess",
    "bgRemovedSuccess",
    "customCSS",
    "customCSSDesc",
    "customCSSPlaceholder",
    "fontSize",
    "codeFontSize",
    "autoCollapseInput",
    "autoCollapseInputDesc",
]


def test_auto_collapse_composer_sites():
    # R2-4：三页 composer 折叠消费端 + memo 键扩展（扩键预批、禁加 memo）
    for page in ("page_home.html", "page_chat_main.html"):
        tpl = _read("static", "templates", page)
        assert "systemSettings.autoCollapseInput, isChatInputActive]" in tpl, page
        assert "!isChatInputActive && !isAssistantMode && !isMobile) ? 1 :" in tpl, page
        assert '@focus="onChatInputFocus"' in tpl and '@blur="onChatInputBlur"' in tpl, page
        assert 'v-show="!systemSettings.autoCollapseInput || isChatInputActive || isAssistantMode || isMobile"' in tpl, page
        assert "compact-status-pill" in tpl, page
    ab = _read("static", "templates", "page_ai-browser.html")
    assert "systemSettings.autoCollapseInput, isChatInputActive]" in ab
    assert 'v-show="!systemSettings.autoCollapseInput || isChatInputActive"' in ab
    assert '@focus="onChatInputFocus"' in ab
    assert "compact-status-pill" in ab
    # 老 memo 站点必须仍是原站点数：三页各只有一处 composer memo 键扩展
    for page in ("page_home.html", "page_chat_main.html", "page_ai-browser.html"):
        tpl = _read("static", "templates", page)
        assert tpl.count("systemSettings.autoCollapseInput, isChatInputActive]") == 1, page


def test_auto_collapse_support_assets():
    sysp = _read("static", "templates", "page_system.html")
    assert "autoCollapseInput" in sysp and "autoCollapseInputDesc" in sysp
    d = _read("static", "js", "data", "70_appearance.js")
    assert "isChatInputActive: false" in d
    b = _read("static", "js", "data", "20_brain_settings.js")
    assert "autoCollapseInput: false" in b
    m = _read("static", "js", "methods", "87_appearance.js")
    assert "onChatInputFocus()" in m and "onChatInputBlur()" in m
    assert "unified-input-wrapper" in m  # blur 延迟判定的容器守卫
    css = _read("static", "css", "appearance.css")
    assert ".compact-status-pill" in css
    assert "min-height 0.25s" in css
    st = json.loads(_read("config", "settings_template.json"))
    assert st["systemSettings"].get("autoCollapseInput") is False
    rjs = _read("static", "js", "renderer.js")
    # 戳必须 ≥S126（每轮 UI 改动升戳纪律；前缀断言避免下轮升戳即红）
    import re
    assert re.search(r"build=S12[6-9]|build=S1[3-9]\d|build=S[2-9]\d\d", rjs)


def test_vendor_params_r25():
    # R2-5 vendor_params 簇：推荐参数字典 + 计算属性 + 一键添加 + 双 UI 区块
    vp = _read("static", "js", "vendor_params.js")
    assert "window.vendorSuggestedParams" in vp and "'Gemini'" in vp and "'siliconflow'" in vp
    idx = _read("static", "index.html")
    assert 'src="js/vendor_params.js"' in idx
    assert 'src="js/methods/89_vendor_params.js"' in idx
    rjs = _read("static", "js", "renderer.js")
    for needle in (
        "mainVendorName()",
        "fastVendorName()",
        "mainSuggestedParams()",
        "fastSuggestedParams()",
        "window.vendorSuggestedParams",
    ):
        assert needle in rjs, needle
    m = _read("static", "js", "methods", "89_vendor_params.js")
    for needle in (
        "addMainSuggestedParam",
        "addFastSuggestedParam",
        "paramExistsInMain",
        "paramExistsInFast",
        "formatVendorName",
    ):
        assert needle in m, needle
    mc = _read("static", "templates", "page_model-config.html")
    assert "mainSuggestedParams.length > 0" in mc
    assert "fastSuggestedParams.length > 0" in mc
    assert "addMainSuggestedParam(param)" in mc
    assert "addFastSuggestedParam(param)" in mc
    css = _read("static", "css", "appearance.css")
    assert ".suggested-params" in css and ".suggested-card" in css
    # 字典内全部 desc 键必须 zh/en 成对存在
    import re

    descs = sorted(set(re.findall(r"desc: '([a-zA-Z0-9_]+)'", vp)))
    assert len(descs) >= 30
    zh = _read("static", "js", "locales", "zh-CN.js")
    en = _read("static", "js", "locales", "en-US.js")
    for key in descs + ["suggestedParams"]:
        assert f"'{key}'" in zh and f"'{key}'" in en, key


def test_topbar_panel_buttons_r2():
    # R2 ④：顶栏左右面板切换按钮 + 右侧面板记住拖拽宽度
    idx = _read("static", "index.html")
    assert '@click="handleHistoryToggle()"' in idx
    assert '@click="toggleSidePanel"' in idx
    assert "t('chatHistory')" in idx and "t('extensionsView')" in idx
    m = _read("static", "js", "methods", "90_panel_resize.js")
    assert "toggleSidePanel()" in m
    assert m.count("savedSidePanelWidth") >= 4
    assert "const saved = this.savedSidePanelWidth;" in m
    d = _read("static", "js", "data", "20_brain_settings.js")
    assert "savedSidePanelWidth: null" in d


def test_completion_notification_r25():
    # R2-5：生成完毕系统通知（Electron IPC 链 + 流尾挂点 + 开关 + 默认关）
    mjs = _read("main.js")
    assert "ipcMain.handle('show-notification'" in mjs
    assert "new Notification({ title, body }).show()" in mjs
    pre = _read("static", "js", "preload.js")
    assert "invoke('show-notification'" in pre
    st = _read("static", "js", "methods", "10_chat_stream.js")
    assert "enableNotifications && !document.hasFocus()" in st
    assert "electronAPI?.showNotification" in st
    tpl = _read("static", "templates", "page_system.html")
    assert "enableNotifications" in tpl and "enableNotificationsDesc" in tpl
    b = _read("static", "js", "data", "20_brain_settings.js")
    assert "enableNotifications: false" in b
    stj = json.loads(_read("config", "settings_template.json"))
    assert stj["systemSettings"].get("enableNotifications") is False
    zh = _read("static", "js", "locales", "zh-CN.js")
    en = _read("static", "js", "locales", "en-US.js")
    for key in ("enableNotifications", "enableNotificationsDesc", "aiGenerationComplete"):
        assert f"'{key}'" in zh and f"'{key}'" in en, key


def test_appearance_i18n_parity():
    zh = _read("static", "js", "locales", "zh-CN.js")
    en = _read("static", "js", "locales", "en-US.js")
    for key in APPEARANCE_I18N_KEYS:
        quoted = f"'{key}'"
        assert quoted in zh, f"zh-CN.js missing i18n key: {key}"
        assert quoted in en, f"en-US.js missing i18n key: {key}"
