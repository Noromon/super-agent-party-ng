# -*- coding: utf-8 -*-
"""S224: 统一交给主模型（unifiedModel）——视觉/推理不再用独立角色，全部由主模型处理。

后端：unifiedModel 开启时 images/describe 各点走主模型分支（vision.enabled 门控加
`and not unifiedModel`），reasoner 在请求期副本关闭，watcher 用主模型做一手观察。
前端：开关 + 开启时视觉/推理选择器置灰 + 切主模型镜像同步 + 抑制视觉未启用误报警告。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.get_setting import vision_model_cfg  # noqa: E402


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8-sig")


class TestVisionModelCfg:
    def test_non_unified_returns_vision_asis(self):
        s = {"unifiedModel": False, "vision": {"enabled": True, "model": "v", "api_key": "k"},
             "model": "m", "api_key": "maink"}
        assert vision_model_cfg(s) == s["vision"]
        # 非破坏
        assert s["vision"] == {"enabled": True, "model": "v", "api_key": "k"}

    def test_unified_resolves_to_main(self):
        s = {"unifiedModel": True, "api_key": "maink", "base_url": "http://main/v1",
             "model": "mainmodel", "selectedProvider": "p1",
             "vision": {"enabled": False, "model": "", "api_key": "", "desktopVision": True}}
        cfg = vision_model_cfg(s)
        assert cfg["enabled"] is True
        assert cfg["api_key"] == "maink"
        assert cfg["base_url"] == "http://main/v1"
        assert cfg["model"] == "mainmodel"
        assert cfg["selectedProvider"] == "p1"
        assert cfg["desktopVision"] is True  # 原 vision 非模型字段保留

    def test_unified_does_not_mutate_source(self):
        s = {"unifiedModel": True, "api_key": "maink", "model": "mm", "base_url": "u",
             "vision": {"enabled": False, "model": ""}}
        vision_model_cfg(s)
        assert s["vision"]["enabled"] is False and s["vision"]["model"] == ""


class TestBackendDispatchPins:
    def test_vision_enabled_gated_five(self):
        src = _read("server.py")
        assert src.count("if settings['vision']['enabled'] and not settings.get('unifiedModel'):") == 5
        # 不再有未门控的独立 vision 分支
        assert "if settings['vision']['enabled']:" not in src

    def test_reasoner_forced_off_when_unified(self):
        src = _read("server.py")
        assert "request_settings['reasoner'] = {**current_settings['reasoner'], 'enabled': False}" in src
        i = src.index("request_settings['reasoner'] = {**current_settings['reasoner'], 'enabled': False}")
        assert "if current_settings.get('unifiedModel'):" in src[i - 120:i]

    def test_watcher_uses_resolver(self):
        src = _read("py/screen_watcher.py")
        assert "vision = vision_model_cfg(settings)" in src
        assert "vision_model_cfg" in _read("py/get_setting.py")


class TestSettingsChainPins:
    def test_template_and_schema_default(self):
        assert '"unifiedModel": false' in _read("config/settings_template.json")
        assert "unifiedModel: false" in _read("static/js/settings_schema.js")
        assert "unifiedModel: false" in _read("static/js/data/00_ui_core.js")

    def test_locales_keys(self):
        for f in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
            s = _read(f)
            for k in ("'unifiedModelConfig'", "'unifiedModelHint'", "'unifiedModelNeedsVision'"):
                assert k in s, (f, k)


class TestFrontendPins:
    def test_switch_and_gating(self):
        src = _read("static/templates/page_model-config.html")
        assert 'v-model="settings.unifiedModel"' in src
        assert "@change=\"handleUnifiedModelToggle\"" in src
        # reasoner/vision 的 enabled 开关 + provider select 共 4 处置灰
        assert src.count(':disabled="settings.unifiedModel"') >= 4

    def test_mirror_methods(self):
        src = _read("static/js/methods/22_providers.js")
        assert "mirrorRolesToMain(" in src
        assert "async handleUnifiedModelToggle()" in src
        assert "if (this.settings.unifiedModel) this.mirrorRolesToMain(provider);" in src

    def test_vision_warn_suppressed_under_unified(self):
        assert "screenWatchSettings.enabled && !visionSettings.enabled && !settings.unifiedModel" in _read("static/templates/page_role.html")
        for page in ("static/templates/page_chat_main.html", "static/templates/page_home.html"):
            assert "(screenWatchSettings.enabled && !visionSettings.enabled && !settings.unifiedModel) ?" in _read(page), page
