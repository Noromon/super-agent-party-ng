# -*- coding: utf-8 -*-
"""S204 能力索引/类别门控纪律注入（提示词世界=能力世界）。

审计实锤：Agent 工具契约曾被 CLISettings 三重开关整段熄灭（运行时 11-06 后全
通道零契约），而工具照样声明——提示词宇宙与能力世界脱节是尸块/confabulation
事故的温床（write_diary、mimic_human_interaction 均为索引外编造名）。
修复：纪律+能力索引按本轮有效声明集在 build_llm_tools 后注入（stream/ns 两处，
不受开关支配）；不可用类别零出现；S74 动作授权链（enable_tools）不动只跟随。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SERVER = ((_ROOT / "server.py").read_text(encoding="utf-8")
          + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8")
          + (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）  # S303：complete 引擎域迁出，合并面守恒（体逐字未动）
DIARY = (_ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")


class TestTaxonomy:
    def test_registries_all_classified(self):
        import py.cli_tool as ct
        from py.tool_taxonomy import OTHER, classify
        unknown = set()
        for regname in ("TOOLS_REGISTRY", "LOCAL_TOOLS_REGISTRY", "WSL_TOOLS_REGISTRY"):
            for v in getattr(ct, regname).values():
                n = v["function"]["name"]
                if classify(n) == OTHER:
                    unknown.add(n)
        assert not unknown, f"注册工具未归类: {unknown}"

    def test_diary_whitelist_classified(self):
        import re
        from py.tool_taxonomy import OTHER, classify
        m = re.search(r"DIARY_ALLOWED_TOOLS = \[(.*?)\]", DIARY, re.S)
        names = re.findall(r'"([^"]+)"', m.group(1))
        assert names
        assert all(classify(n) != OTHER for n in names)

    def test_dynamic_family_rules(self):
        from py.tool_taxonomy import classify
        assert classify("mcp__github__create_issue") == "external"
        assert classify("ha_call_service") == "external"
        assert classify("some_random_search_tool") == "web_search"
        assert classify("unknown_thing") == "other"

    def test_group_stable_order(self):
        from py.tool_taxonomy import CATEGORY_ORDER, group
        g1 = group(["DDGsearch", "edit_file_patch_tool_local", "time"])
        g2 = group(["time", "edit_file_patch_tool_local", "DDGsearch"])
        assert list(g1) == list(g2) == [c for c in CATEGORY_ORDER if c in g1]


class TestRenderGating:
    def test_index_exact_membership(self):
        from py.tool_discipline import render_tool_discipline
        declared = ["edit_file_patch_tool_local", "DDGsearch", "time"]
        out = render_tool_discipline(declared)
        assert all(n in out for n in declared)
        # 未声明名零出现（编造名事故钉）：写工具/ask/todo/日记读工具均未声明
        for absent in ("edit_file_tool_local", "ask_user_question_tool",
                       "todo_write_tool_local", "query_diary", "shell_tool_local"):
            assert absent not in out, absent

    def test_unavailable_category_label_absent(self):
        from py.tool_discipline import render_tool_discipline
        out = render_tool_discipline(["DDGsearch"])
        assert "asking the user" not in out and "todo & planning" not in out
        assert "web search & fetch" in out

    def test_blocks_follow_declarations(self):
        from py.tool_discipline import render_tool_discipline
        out = render_tool_discipline(["edit_file_patch_tool_local"])
        assert "edits array" in out                      # file_edit 块在场
        assert "full-write tool" not in out              # 未声明 file_write 不引
        out2 = render_tool_discipline(["edit_file_patch_tool_local",
                                       "edit_file_tool_local"])
        assert "full-write tool" in out2

    def test_zero_tools_single_line(self):
        from py.tool_discipline import MARKER, render_tool_discipline
        out = render_tool_discipline([])
        assert out.startswith(MARKER) and "NO tools" in out
        assert "Capability index" in out

    def test_t0_permanent_clauses(self):
        from py.tool_discipline import render_tool_discipline
        out = render_tool_discipline(["time"])
        for frag in ("never executed and will be intercepted",
                     "this turn = full set",
                     "does not exist for you now",
                     "Never invent, rename, or imitate"):
            assert frag in out


class TestServerWiring:
    def test_inject_after_build_tools_both_branches(self):
        assert SERVER.count("_inject_tool_discipline(request, tools)  # S204") == 2
        assert "\ndef _inject_tool_discipline(" in SERVER  # 模块级定义，调用在函数内
        # 两处调用都紧跟在 build_llm_tools 之后（索引随有效声明集）
        lines = SERVER.splitlines()
        pair = sum(1 for a, b in zip(lines, lines[1:])
                   if "build_llm_tools(request, settings" in a and "_inject_tool_discipline" in b)
        assert pair == 2

    def test_not_gated_by_cli_settings(self):
        seg = SERVER[SERVER.index("def _inject_tool_discipline"):]
        # S303：原以下一个 def _ns_behavior_sanitize 为段尾，该函数已迁出——改以 impl 为界（段体不变）
        seg = seg[:seg.index("async def _generate_complete_impl")]
        code = seg[seg.index('"""', seg.index('"""') + 3) + 3:]  # 去 docstring
        assert 'get("CLISettings"' not in code and "agentCorePrompt" not in code

    def test_contract_has_no_hardcoded_tool_names(self):
        ap = (_ROOT / "py" / "agent_prompt.py").read_text(encoding="utf-8")
        assert "edit_file_patch" not in ap and "ask_user_question_tool" not in ap
        assert "Capability index" in ap  # 契约指向能力索引层

    def test_marker_idempotent(self):
        assert "MARKER in (request.messages[0].get(\"content\")" in SERVER


class TestDiaryChannel:
    def test_channel_semantics_line(self):
        assert "本通道语义" in DIARY and "「当前能力索引」" in DIARY

    def test_payload_sanitize_flag(self):
        assert '"sanitize_plain_output": True' in DIARY

    def test_endpoint_sanitizer_covers_plain_output(self):
        i = SERVER.index("response_dict = await _complete_finalize")
        seg = SERVER[i:i + 400]
        assert "sanitize_plain_output" in seg and "_ns_behavior_sanitize" in seg


class TestSanitizeFunctional:
    def test_pure_block_becomes_empty_for_diary(self):
        import server
        block = ('<tool_call>\n<function=add_diary>\n<parameter=content>\n'
                 '记点什么\n</parameter>\n</function>\n</tool_call>')
        d = {"choices": [{"message": {"role": "assistant", "content": block}}]}
        assert server._ns_behavior_sanitize(d)["choices"][0]["message"]["content"] == ""
