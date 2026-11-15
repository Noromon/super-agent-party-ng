# -*- coding: utf-8 -*-
"""S226 窥屏判断 VLM 独立路由 + 思考/引擎预设 + 自定义参数兜底。

仅作用观察调用 _vlm；auto 模式零回归（委托 vision_model_cfg）；main/vlm/custom 显式
接管端点；预设(activePreset)+自由 JSON 深度合并（自由赢、嵌套 chat_template_kwargs 不被吞）。
"""
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.screen_observe as so  # noqa: E402


def _S(observe=None, *, unified=False, vision=None, main=None):
    s = {"screenWatchSettings": {}}
    if observe is not None:
        s["screenWatchSettings"]["observe"] = observe
    if vision is not None:
        s["vision"] = vision
    if unified:
        s["unifiedModel"] = True
    for k, v in (main or {}).items():
        s[k] = v
    return s


# ---------------------------------------------------------------- 端点解析
class TestResolveCfg:
    def test_auto_delegates_vision_model_cfg_off(self):
        s = _S(vision={"enabled": True, "model": "V", "base_url": "VB", "api_key": "VK"})
        cfg = so.resolve_observe_cfg(s)
        assert cfg["enabled"] is True and cfg["model"] == "V"

    def test_auto_delegates_vision_model_cfg_unified_to_main(self):
        s = _S(unified=True, vision={"enabled": False, "model": "V"},
               main={"model": "M", "base_url": "MB", "api_key": "MK", "selectedProvider": "p"})
        cfg = so.resolve_observe_cfg(s)
        assert cfg["model"] == "M" and cfg["base_url"] == "MB" and cfg["enabled"] is True

    def test_mode_main_uses_main_and_requires_baseurl(self):
        s = _S({"mode": "main"}, main={"model": "M", "base_url": "MB", "api_key": "MK"})
        cfg = so.resolve_observe_cfg(s)
        assert cfg["enabled"] is True and cfg["model"] == "M"
        s2 = _S({"mode": "main"}, main={"model": "M", "base_url": ""})
        assert so.resolve_observe_cfg(s2)["enabled"] is False

    def test_mode_vlm_returns_vision_as_is(self):
        s = _S({"mode": "vlm"}, vision={"enabled": False, "model": "V", "temperature": 0.3})
        cfg = so.resolve_observe_cfg(s)
        assert cfg["enabled"] is False and cfg["temperature"] == 0.3

    def test_mode_custom_endpoint_and_availability(self):
        ob = {"mode": "custom", "custom": {"model": "CM", "baseUrl": "CB", "apiKey": "CK"}}
        cfg = so.resolve_observe_cfg(_S(ob))
        assert cfg["enabled"] is True and cfg["base_url"] == "CB" and cfg["model"] == "CM"
        ob2 = {"mode": "custom", "custom": {"model": "", "baseUrl": "CB"}}
        assert so.resolve_observe_cfg(_S(ob2))["enabled"] is False


# ---------------------------------------------------------------- extra_body 合并
class TestBuildExtraBody:
    def test_default_empty_zero_regression(self):
        assert so.build_observe_extra_body(_S()) == {}
        assert so.build_observe_extra_body(_S({"mode": "auto"})) == {}

    def test_active_preset_parsed_and_injected(self):
        ob = {"activePreset": "关", "presets": [
            {"name": "关", "bodyJson": '{"enable_thinking": false}'},
            {"name": "低", "bodyJson": '{"reasoning_effort": "low"}'}]}
        assert so.build_observe_extra_body(_S(ob)) == {"enable_thinking": False}

    def test_freeform_overrides_preset_same_key(self):
        ob = {"activePreset": "p", "presets": [{"name": "p", "bodyJson": '{"temperature": 1}'}],
              "extraParamsJson": '{"temperature": 0.2}'}
        assert so.build_observe_extra_body(_S(ob)) == {"temperature": 0.2}

    def test_deep_merge_preserves_nested_chat_template_kwargs(self):
        ob = {"activePreset": "v", "presets": [
            {"name": "v", "bodyJson": '{"chat_template_kwargs": {"enable_thinking": false}}'}],
            "extraParamsJson": '{"chat_template_kwargs": {"reasoning_effort": "low"}}'}
        out = so.build_observe_extra_body(_S(ob))
        assert out["chat_template_kwargs"] == {"enable_thinking": False, "reasoning_effort": "low"}

    def test_freeform_only_when_no_preset(self):
        ob = {"activePreset": "", "extraParamsJson": '{"reasoning_effort": "medium"}'}
        assert so.build_observe_extra_body(_S(ob)) == {"reasoning_effort": "medium"}

    def test_invalid_freeform_ignored_no_raise(self):
        ob = {"activePreset": "p", "presets": [{"name": "p", "bodyJson": '{"a": 1}'}],
              "extraParamsJson": "{not json"}
        assert so.build_observe_extra_body(_S(ob)) == {"a": 1}

    def test_non_object_json_ignored(self):
        assert so.build_observe_extra_body(_S({"extraParamsJson": "[1,2,3]"})) == {}

    def test_active_preset_bad_body_json_ignored(self):
        ob = {"activePreset": "p", "presets": [{"name": "p", "bodyJson": "{broken"}]}
        assert so.build_observe_extra_body(_S(ob)) == {}


# ---------------------------------------------------------------- 接线（源码级）
SW_SRC = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8")


class TestWiring:
    def test_observe_uses_resolvers(self):
        assert "screen_observe.resolve_observe_cfg" in SW_SRC
        assert "screen_observe.build_observe_extra_body" in SW_SRC
        assert "self._vlm(vision, data_uri, observe_extra)" in SW_SRC

    def test_vlm_accepts_and_sends_extra_body(self):
        assert "async def _vlm(self, vision, data_uri, extra_body=None)" in SW_SRC
        assert "extra_body=eb" in SW_SRC

    def test_vision_model_cfg_import_dropped(self):
        assert "from py.get_setting import SCREEN_WATCH_DIR, load_settings\n" in SW_SRC


# ---------------------------------------------------------------- 设置链
class TestSettingsChain:
    def test_template_defaults(self):
        d = json.loads((_ROOT / "config" / "settings_template.json").read_text(encoding="utf-8-sig"))
        ob = d["screenWatchSettings"]["observe"]
        assert ob["mode"] == "auto" and ob["activePreset"] == "" and ob["extraParamsJson"] == ""
        assert set(ob["custom"]) == {"model", "baseUrl", "apiKey"}
        assert len(ob["presets"]) == 6
        for p in ob["presets"]:
            assert json.loads(p["bodyJson"]) == json.loads(p["bodyJson"])  # 合法

    def test_schema_and_data_present(self):
        sch = (_ROOT / "static" / "js" / "settings_schema.js").read_text(encoding="utf-8")
        dat = (_ROOT / "static" / "js" / "data" / "60_cards_options.js").read_text(encoding="utf-8")
        for src in (sch, dat):
            assert "observe:" in src and "activePreset" in src and "bodyJson" in src
            assert "chat_template_kwargs" in src and "enable_thinking" in src

    def test_panel_bound_to_observe(self):
        src = (_ROOT / "static" / "templates" / "page_role.html").read_text(encoding="utf-8")
        assert 'v-model="screenWatchSettings.observe.mode"' in src
        assert 'v-model="screenWatchSettings.observe.activePreset"' in src
        assert "screenWatchSettings.observe.presets.splice" in src
        assert "screenWatchSettings.observe.presets.push" in src
        assert 'v-model="screenWatchSettings.observe.extraParamsJson"' in src
        assert "screenWatchSettings.observe.mode === 'custom'" in src

    def test_locale_parity_new_keys(self):
        zh = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
        en = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")
        for key in ("screenWatchObserve", "screenWatchObserveMode", "screenWatchObservePreset",
                    "screenWatchObserveExtra", "screenWatchObserveCustom", "screenWatchObserveDelete"):
            assert f"'{key}'" in zh and f"'{key}'" in en
