# S313: ask_flow options 字符串规范化（修"多选项合并、只有一个选项"）
# + Plan 答复确认文案的最终计划指令。
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.ask_flow import normalize_questions  # noqa: E402

AF_SRC = (_ROOT / "py" / "ask_flow.py").read_text(encoding="utf-8")


def _opts(options):
    qs, err = normalize_questions({"questions": [{"question": "Q?", "options": options}]})
    assert err == ""
    return qs[0]["options"]


class TestOptionsNormalisation:
    def test_plain_list_untouched(self):
        assert _opts(["a", "b"]) == ["a", "b"]

    def test_stringified_json_array(self):
        assert _opts(json.dumps(["甲", "乙", "丙"], ensure_ascii=False)) == ["甲", "乙", "丙"]

    def test_newlines(self):
        assert _opts("甲\n乙\n丙") == ["甲", "乙", "丙"]

    def test_ideographic_comma_split(self):
        assert _opts("切换执行模式、只改一项、调整计划") == ["切换执行模式", "只改一项", "调整计划"]

    def test_semicolon_split(self):
        assert _opts("甲；乙；丙") == ["甲", "乙", "丙"]
        assert _opts("a; b; c") == ["a", "b", "c"]

    def test_single_option_with_comma_not_split(self):
        # 选项文本内部合法含半角逗号：不拆（无分隔符可依赖时保持单选项）
        assert _opts("切执行模式, 一次改完 4 项并验证后回报") == ["切执行模式, 一次改完 4 项并验证后回报"]

    def test_invalid_string_not_json(self):
        assert _opts("[未闭合") == ["[未闭合"]

    def test_bad_json_string_error_path_still_ok(self):
        qs, err = normalize_questions({"questions": "not json"})
        assert qs == [] and "JSON" in err

    def test_plan_directive_in_confirmation(self):
        assert "立刻输出最终计划正文" in AF_SRC
        assert "禁止再探索文件" in AF_SRC
