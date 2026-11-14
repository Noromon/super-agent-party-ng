# -*- coding: utf-8 -*-
"""S220: 屏幕旁观快捷开关接线钉（聊天工具条 toggle + 可选列表三字典 + 双语）。

口径：按钮=behavior 同款内联 toggle（开即存即热更新引擎，见 S219 实测热更新链）；
可见性由 MoreButtonDict 族（More/large/small 三字典，「更多按钮」可选列表）控制，
默认 enabled=false 与 privacy 类条目一致；主 MoreButtonDict 不入 settings_schema
PAIRS（纯前端初始值=新条目对老库零迁移），large/small 走 14_ws_client 按 name
map 合并（本地列表为底=新增条目在老配置下保留）。
"""
_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _read(rel):
    return (_ROOT / rel).read_text(encoding="utf-8-sig")


class TestOptionalList:
    def test_three_dicts_registered(self):
        src = _read("static/js/data/30_tiles_vrm.js")
        assert src.count('{"name": "screenWatchButton", "enabled": false}') == 3

    def test_each_dict_after_behavior(self):
        # 三处均紧随 behaviorBotton 之后（同组引擎类开关聚在一起）
        import re
        src = _read("static/js/data/30_tiles_vrm.js")
        hits = re.findall(
            r'\{"name": "behaviorBotton", "enabled": false\},\s*\{"name": "screenWatchButton"', src)
        assert len(hits) == 3, len(hits)


class TestToolbarToggle:
    def test_both_pages_wired(self):
        for page in ("static/templates/page_chat_main.html", "static/templates/page_home.html"):
            src = _read(page)
            assert "screenWatchSettings.enabled=!screenWatchSettings.enabled; autoSaveSettings();" in src, page
            assert "b.name === 'screenWatchButton'" in src, page
            assert "screen-watch-btn" in src, page
            assert src.count("screenWatchSettings.enabled=!screenWatchSettings.enabled") == 1, page

    def test_no_vision_freefall_toggle_is_engine_side(self):
        # 门控在后端 tick（vision 未启用自动退避，S215 已钉）；前端按钮不做禁用态——
        # 与 behavior/HA 同款纯 toggle，此 pin 防前端误加 :disabled 破坏一致语义
        for page in ("static/templates/page_chat_main.html", "static/templates/page_home.html"):
            seg = _read(page).split("screen-watch-btn")[0]
            btn = seg.rsplit("<el-button", 1)[1]
            assert ":disabled" not in btn, page


class TestRestoreChainSafety:
    def test_main_dict_not_persisted(self):
        # 主 MoreButtonDict 不入 PAIRS → 每次加载用前端初始数组，新条目必然出现
        src = _read("static/js/settings_schema.js")
        assert "['MoreButtonDict'" not in src

    def test_large_small_have_map_merge(self):
        src = _read("static/js/methods/14_ws_client.js")
        assert src.count(".map(existingButton =>") == 2  # large/small 按 name 合并


class TestLocales:
    def test_key_both_languages(self):
        for loc in ("zh-CN", "en-US"):
            assert "'screenWatchButton':" in _read("static/js/locales/%s.js" % loc), loc
