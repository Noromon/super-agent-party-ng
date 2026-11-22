# -*- coding: utf-8 -*-
"""S206 每模型推理参数覆盖 + 友好名/复制打磨。

语义（用户定稿）：卡片 params 作用于所有选中该卡片的角色；extra_params 模型级整体
替换角色级；优先级 请求级 > 模型卡片级 > 角色默认。缺省/null=继承角色默认。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.model_params as mp  # noqa: E402

SERVER = ((_ROOT / "server.py").read_text(encoding="utf-8")
          + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8")
          + (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）  # S303：complete 引擎域迁出，合并面守恒（体逐字未动）
PROVIDERS_JS = (_ROOT / "static" / "js" / "methods" / "22_providers.js").read_text(encoding="utf-8")
MODEL_CFG = (_ROOT / "static" / "templates" / "page_model-config.html").read_text(encoding="utf-8")


def _settings(prov_params=None, selected=1):
    return {
        "temperature": 0.9, "top_p": 0.95, "max_tokens": 4096,
        "reasoning_effort": None, "extra_params": [{"name": "a", "type": "string", "value": "1"}],
        "selectedProvider": selected,
        "modelProviders": [
            {"id": 1, "vendor": "OpenAI", "url": "u", "apiKey": "k", "modelId": "m-1"},
            {"id": 2, "vendor": "Deepseek", "url": "u2", "apiKey": "k2", "modelId": "m-2",
             "params": prov_params or {}},
        ],
    }


class TestOverrides:
    def test_no_selection_or_card(self):
        assert mp.provider_overrides(_settings(), None) == {}
        s = _settings(selected=1)  # 卡片1无 params
        assert mp.provider_overrides(s, 1) == {}
        assert mp.provider_overrides(None, 2) == {}

    def test_partial_fields_only(self):
        s = _settings({"temperature": 0.3, "top_p": None, "max_tokens": "", "reasoning_effort": "high"})
        ov = mp.provider_overrides(s, 2)
        assert ov == {"temperature": 0.3, "reasoning_effort": "high"}

    def test_invalid_values_dropped(self):
        s = _settings({"temperature": "abc", "max_tokens": 8192, "contextWindow": "auto"})
        ov = mp.provider_overrides(s, 2)
        assert ov == {"max_tokens": 8192, "contextWindow": "auto"}

    def test_extra_params_only_dicts(self):
        s = _settings({"extra_params": [{"name": "x", "type": "string", "value": "v"}, "junk"]})
        ov = mp.provider_overrides(s, 2)
        assert ov["extra_params"] == [{"name": "x", "type": "string", "value": "v"}]


class TestEffective:
    def test_main_inherit_defaults(self):
        eff = mp.effective_main_params(_settings())
        assert eff["temperature"] == 0.9 and eff["top_p"] == 0.95
        assert eff["max_tokens"] == 4096 and eff["reasoning_effort"] is None
        assert len(eff["extra_params"]) == 1

    def test_main_card_override(self):
        s = _settings({"temperature": 0.2, "extra_params": [{"name": "b", "type": "integer", "value": 2}]}, selected=2)
        eff = mp.effective_main_params(s)
        assert eff["temperature"] == 0.2 and eff["top_p"] == 0.95  # 未覆盖字段继承
        assert eff["extra_params"] == [{"name": "b", "type": "integer", "value": 2}]  # 整体替换

    def test_override_list_not_shared_with_settings(self):
        s = _settings({"extra_params": [{"name": "b"}]}, selected=2)
        eff = mp.effective_main_params(s)
        eff["extra_params"].remove(eff["extra_params"][0])
        assert len(mp.provider_overrides(s, 2)["extra_params"]) == 1  # 存档未被原地污染

    def test_role_params(self):
        s = _settings({"temperature": 0.4}, selected=2)
        role = {"selectedProvider": 2, "temperature": 0.8, "max_tokens": 2048}
        eff = mp.effective_role_params(s, role)
        assert eff["temperature"] == 0.4 and eff["max_tokens"] == 2048


class TestServerWiring:
    def test_import_and_helpers(self):
        assert "from py.model_params import effective_main_params, effective_role_params" in SERVER
        assert "def _role_param(settings, role_key, key):" in SERVER
        assert "def _main_param(settings, key):" in SERVER

    def test_stream_ns_eff_computed_once_each(self):
        assert SERVER.count("_eff_main = effective_main_params(settings)") == 3  # stream + ns + reasoner-prep
        assert "_eff_reasoner = effective_role_params(settings, settings.get('reasoner') or {})" in SERVER

    def test_no_bare_main_param_reads_left_in_endpoints(self):
        for probe in ("request.max_tokens or settings['max_tokens']",
                      "extra['temperature'] = settings['temperature']",
                      "extra['top_p'] = request.top_p or settings['top_p']"):
            assert probe not in SERVER, probe

    def test_reasoner_vision_use_role_param(self):
        # S299：vision 参数读取随视觉域迁至 py/vision_tools.py，存在性/缺席性双面合并
        _vt = (_ROOT / "py" / "vision_tools.py").read_text(encoding="utf-8")
        assert "_role_param(settings, 'reasoner', 'temperature')" in SERVER
        assert "_role_param(settings, 'vision', 'temperature')" in _vt
        assert "settings['reasoner']['temperature']" not in SERVER
        assert "settings['vision']['temperature']" not in SERVER
        assert "settings['vision']['temperature']" not in _vt

    def test_fast_single_point(self):
        i = SERVER.index("使用 fast 配置覆盖当前配置")
        seg = SERVER[i:i + 900]
        assert "_f_eff = effective_role_params(current_settings, fast_cfg)" in seg

    def test_ctx_window_override_at_single_resolution_point(self):
        cm = (_ROOT / "py" / "context_manager.py").read_text(encoding="utf-8")
        i = cm.index("def get_context_settings(settings)")
        assert "provider_overrides" in cm[i:i + 900]


class TestFrontend:
    def test_provider_label_and_copy(self):
        assert "providerLabel(provider)" in PROVIDERS_JS
        assert "currentMainModelLabel()" in PROVIDERS_JS
        for frag in ("while (this.modelProviders.some(p => p.id === newId))",
                     "JSON.parse(JSON.stringify(provider.params))",
                     "copy.displayName = `${baseName} ${this.t('copySuffix')}`"):
            assert frag in PROVIDERS_JS, frag

    def test_card_ui(self):
        for frag in ("v-model=\"provider.displayName\"", "card-params-collapse",
                     "paramInherited(provider, row.key)", "setParamInherit(provider, 'contextWindow', v)",
                     "addCardParam(provider)", "updateCardParamType(provider, index)"):
            assert frag in MODEL_CFG, frag

    def test_labels_use_provider_label(self):
        import glob as _g
        total = 0
        for f in _g.glob(str(_ROOT / "static" / "templates" / "*.html")):
            t = Path(f).read_text(encoding="utf-8")
            assert "provider.vendor+' - '+provider.modelId" not in t, f
            total += t.count(":label=\"providerLabel(provider)\"")
        assert total == 17

    def test_pills_use_friendly_label(self):
        for name in ("page_home.html", "page_dashboard.html", "page_chat_main.html", "page_ai-browser.html"):
            t = (_ROOT / "static" / "templates" / name).read_text(encoding="utf-8")
            assert "currentMainModelLabel()" in t, name

    def test_i18n_keys(self):
        zh = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
        en = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")
        for key in ("displayName", "providerParams", "inheritDefault", "copySuffix"):
            assert f"'{key}'" in zh and f"'{key}'" in en, key
