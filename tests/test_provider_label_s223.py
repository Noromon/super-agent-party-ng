# -*- coding: utf-8 -*-
"""S223: 模型下拉友好名 + vision 警告独立化的接线钉。

providerLabel 是 S206 单源（displayName 优先→vendor-modelId 回退）；本 story 把
8 处服务选择器的展开列表项从写死 modelId 对齐到该单源（主行友好名，配了 displayName
才有右侧灰字 modelId 溯源行），并把旁板 vision 未启用警告从 banner 简介文字升级为
独立 el-alert（S222 混排形态被用户否决：难注意）。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class TestProviderDropdown:
    def test_eight_option_names(self):
        src = _read("static/templates/page_model-config.html")
        assert src.count('class="provider-option-name"') == 8
        assert src.count("providerLabel(provider)") == 16  # 8 处 label + 8 处主行

    def test_no_bare_modelid_option(self):
        # 旧回归钉：裸 <span class="model-id">{{ provider.modelId }}</span> 必须清零，
        # 新形态必须带 displayName v-if（无友好名不显示重复溯源行）
        src = _read("static/templates/page_model-config.html")
        assert '<span class="model-id">{{ provider.modelId }}</span>' not in src
        assert src.count('v-if="(provider.displayName') == 8

    def test_css_rule_present(self):
        # CSS 防恶化裁决：styles.css 冻结，新样式独立文件且已挂载入 index
        css = _read("static/css/provider-label.css")
        assert ".provider-option-name" in css
        assert "provider-label.css" in _read("static/index.html")

    def test_provider_label_precedence_source(self):
        # S206 单源优先链不被破坏：displayName 判定先于 vendor-modelId 回退
        src = _read("static/js/methods/22_providers.js")
        body = src[src.index("providerLabel(provider) {"):]
        head = body[:400]
        assert head.index("displayName") < head.index("provider.vendor")


class TestVisionWarnAlert:
    def test_independent_alert_replaces_inline_note(self):
        role = _read("static/templates/page_role.html")
        # 独立 alert 形态
        i = role.index('screenWatchSettings.enabled && !visionSettings.enabled && !settings.unifiedModel')
        seg = role[max(0, i - 160):i + 240]
        assert "el-alert" in seg and 'type="warning"' in seg
        assert ":closable=\"false\"" in seg
        # 旧 banner 内混排 <p> 形态清零
        assert '<p v-if="screenWatchSettings.enabled && !visionSettings.enabled"' not in role

    def test_quick_buttons_tooltip_kept(self):
        for page in ("static/templates/page_chat_main.html",
                     "static/templates/page_home.html"):
            assert "(screenWatchSettings.enabled && !visionSettings.enabled && !settings.unifiedModel) ? t('screenWatchVisionWarn')" in _read(page), page
