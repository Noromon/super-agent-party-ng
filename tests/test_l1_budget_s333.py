# -*- coding: utf-8 -*-
"""S333: L1 工具输出预算/保底条数可配置化 + 默认 40k/4 → 120k/8。

用户重工具会话（262k 窗口）在旧默认下每轮边界大量 stubbing（"刚调的秒没"
语义来源=4 条保底+40k 预算同时填满，且两参数无 UI 入口）。默认调宽 +
设置页两输入项；总量防线仍由 L2/MsgTrim 把关。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


class TestDefaultsS333:
    def test_new_defaults(self):
        from py import context_manager as cm_mod
        cs = cm_mod.get_context_settings({})
        assert cs["tool_output_budget"] == 120000
        assert cs["keep_recent_tools"] == 8
        import inspect
        sig = inspect.signature(cm_mod.prune_tool_results)
        assert sig.parameters["keep_recent_tools"].default == 8

    def test_zero_still_disables_budget(self):
        from py import context_manager as cm_mod
        s = {"contextManagement": {"toolOutputBudget": 0, "keepRecentTools": 0}}
        cs = cm_mod.get_context_settings(s)
        assert cs["tool_output_budget"] == 0
        assert cs["keep_recent_tools"] == 0


class TestUiPins:
    def _src(self, rel):
        return (_ROOT / rel).read_text(encoding="utf-8-sig")

    def test_template_has_two_inputs(self):
        s = self._src("static/templates/page_model-config.html")
        assert "ctxToolOutputBudget" in s and "ctxKeepRecentTools" in s
        assert "toolOutputBudget ?? 120000" in s  # 存量用户缺键显示默认
        assert "keepRecentTools ?? 8" in s

    def test_schema_defaults_updated(self):
        s = self._src("static/js/settings_schema.js")
        assert "keepRecentTools: 8" in s
        assert "toolOutputBudget: 120000" in s

    def test_locale_keys_top_level(self):
        for loc in ("zh-CN", "en-US"):
            src = self._src(f"static/js/locales/{loc}.js")
            body = src.split("};")[0]
            assert "'ctxToolOutputBudget'" in body and "'ctxKeepRecentTools'" in body


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
