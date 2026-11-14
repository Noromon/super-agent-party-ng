# -*- coding: utf-8 -*-
"""S219: 屏幕旁观前端面板接线钉（角色页 tile + 面板 + 默认树 + 双语 + schema 单源）。

仿 test_diary_hooks 的接线 pin 风格：模板默认树（merge_defaults 为老库自动补键）、
Vue data 初始树、tile 注册顺序（diary 后 screenWatch）、面板页唯一且嵌套在
suite-content 之后、关键控件绑定后端真实键名、SETTINGS_DEFAULTS/PAIRS 双在、
双语键齐备、div 平衡与 EOF 尾三闭合（S65.1 空白页事故同款守卫）。
"""
import json
import re

_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _read(rel):
    return (_ROOT / rel).read_text(encoding="utf-8-sig")


class TestDefaults:
    def test_template_default_tree(self):
        d = json.loads(_read("config/settings_template.json"))
        sw = d["screenWatchSettings"]
        assert sw["enabled"] is False and sw["intervalSeconds"] == 5
        assert sw["retentionHours"] == 48 and sw["digestRetentionDays"] == 30
        assert sw["digestHour"] == 4
        sp = sw["speak"]
        assert sp["enabled"] is False and sp["minImportance"] == 4
        assert sp["cooldownSeconds"] == 600 and sp["dailyLimit"] == 5
        assert sp["platforms"] == ["all"]

    def test_vue_data_initial_tree(self):
        src = _read("static/js/data/60_cards_options.js")
        assert "screenWatchSettings: {" in src

    def test_schema_pairs_and_defaults(self):
        src = _read("static/js/settings_schema.js")
        assert "['screenWatchSettings', 'screenWatchSettings']" in src
        assert re.search(r"screenWatchSettings:\s*function\s*\(\)", src)


class TestTilesAndPanel:
    def test_tile_registered_after_diary(self):
        src = _read("static/js/data/40_tts_voice.js")
        assert "{ id: 'screenWatch', title: 'ScreenWatchSystem'" in src
        assert src.index("{ id: 'diary'") < src.index("{ id: 'screenWatch'")

    def _panel_segment(self):
        role = _read("static/templates/page_role.html")
        i = role.index("subMenu === 'screenWatch'")
        return role, i

    def test_panel_page_unique_and_nested(self):
        role, i = self._panel_segment()
        assert role.count("subMenu === 'screenWatch'") == 1
        assert role.index('class="suite-content"') < i
        assert role.index("subMenu === 'diary'") < i  # 同组能力页：diary 旁
        tail = [ln.strip() for ln in role.splitlines() if ln.strip()]
        assert tail[-3:] == ["</div>", "</div>", "</div>"]  # S65.1 尾守卫
        assert role.count("<div") == role.count("</div>")

    def test_controls_bind_real_backend_keys(self):
        role, _ = self._panel_segment()
        for binding in ("screenWatchSettings.enabled",
                        "screenWatchSettings.intervalSeconds",
                        "screenWatchSettings.privacyKeywords",
                        "screenWatchSettings.retentionHours",
                        "screenWatchSettings.digestRetentionDays",
                        "screenWatchSettings.digestHour",
                        "screenWatchSettings.speak.enabled",
                        "screenWatchSettings.speak.minImportance",
                        "screenWatchSettings.speak.cooldownSeconds",
                        "screenWatchSettings.speak.dailyLimit",
                        "screenWatchSettings.speak.quietStart",
                        "screenWatchSettings.speak.platforms"):
            assert binding in role, binding
        assert 'label="all" value="all"' in role  # EP 双属性兼容写法（diary 先例）


class TestLocales:
    def test_both_languages_have_panel_keys(self):
        for loc in ("zh-CN", "en-US"):
            src = _read("static/js/locales/%s.js" % loc)
            for key in ("'ScreenWatchSystem'", "'screenWatchSystemNotice'",
                        "'screenWatchPrivacyNotice'", "'screenWatchPlatforms'",
                        "'screenWatchSpeakQuietHint'"):
                assert key in src, (loc, key)
