# -*- coding: utf-8 -*-
"""S183：弱模型骨架补强——塌方调用显示拦截/返工可配、完成闸门、再锚、todo 回显、
头尾截断、设置管线与契约补丁钉桩。"""
import json
import os
import sys
import pathlib

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _guard():
    from py import tool_call_guard as g
    return g


def _read(*p):
    return (ROOT / pathlib.Path(*p)).read_text(encoding="utf-8")


class TestGuardPatterns:
    def test_bare_function_xml_detected(self):
        # 2026-10-31 事故形态：无 <tool_call> 包裹的裸 <function=NAME> 块
        g = _guard()
        text = ("我来查一下\n<function=local_web_runner>\n<parameter=mode>\nsearch.news\n"
                "</parameter>\n</function>\n")
        assert g.detect_leaked_calls(text) == ["local_web_runner"]

    def test_wrapped_form_still_detected(self):
        g = _guard()
        text = '<tool_call><function=web_search><parameter=q>\nhi\n</parameter></tool_call>'
        assert g.detect_leaked_calls(text) == ["web_search"]

    def test_prose_clean(self):
        g = _guard()
        assert g.detect_leaked_calls("我们讨论 function= 这种写法的语义") == []

    def test_neutralize_bare_and_wrapped(self):
        g = _guard()
        out = g.neutralize_leaked_blocks("前文\n<function=x_tool><parameter=a>\n1\n</parameter>\n</function>\n后文")
        assert "x_tool" not in out and g.REDACTION in out
        assert "前文" in out and "后文" in out

    def test_cut_position_earliest(self):
        g = _guard()
        i = g.cut_position("hello <function=a>")
        assert i == 6
        assert g.cut_position("plain prose") == -1
        i2 = g.cut_position("aa<invoke=y>bb<function=z>")
        assert i2 == 2  # 两个标记取最早（<parameter= 单独不算起始，块正则负责）

    def test_partial_tail_hold(self):
        g = _guard()
        assert g.partial_tail_len("正文未完<fun") >= 4
        assert g.partial_tail_len("正文未完<function=") == 10  # 尾部完整标记同样先扣住，下一轮由 cut_position 定位
        assert g.partial_tail_len("正常结尾。") == 0


class TestServerHelpers:
    @classmethod
    def setup_class(cls):
        global SERVER
        import server  # noqa: F401  (router_decoupling 先例：测试内可导入)
        import server as _s
        cls.s = _s

    def test_robust_cfg_defaults_and_clamp(self):
        s = self.s
        assert s._robust_cfg({}) == (6, 2)
        assert s._robust_cfg({"agentRobustness": {"reanchorEveryToolRounds": 0,
                                                  "malformedCallRepairMax": 0}}) == (0, 0)
        assert s._robust_cfg({"agentRobustness": {"reanchorEveryToolRounds": 999,
                                                  "malformedCallRepairMax": -3}}) == (50, 0)
        assert s._robust_cfg({"agentRobustness": {"reanchorEveryToolRounds": "x"}}) == (6, 2)

    def test_display_slice_cut_and_hold(self):
        s = self.s
        # 干净增量原样放行（无扣住）
        show, emit, cut = s._tcg_display_slice("", "你好", 0, -1)
        assert show == "你好" and emit == 2 and cut == -1
        # 标记成型：标记起点之后全部吞掉
        show, emit, cut = s._tcg_display_slice("ab", "cd<function=x>", 2, -1)
        assert show == "cd" and emit == 4 and cut == 4
        # 已切断后恒为空
        show, emit, cut = s._tcg_display_slice("abcd<function=x>", "zzz", 4, 4)
        assert show == "" and emit == 4 and cut == 4
        # 疑似前缀扣住
        show, emit, cut = s._tcg_display_slice("ab", "cd<f", 2, -1)
        assert show == "cd" and emit == 4 and cut == -1

    def test_todo_open_items_and_gate_text(self):
        s = self.s
        todos = [{"id": "1", "status": "done"}, {"id": "2", "status": "pending"},
                 {"id": "3", "status": "in_progress"}, "junk"]
        op = s._todo_open_items(todos)
        assert [t["id"] for t in op] == ["2", "3"]
        note = s._gate_note_text(op, 1)
        assert "完成闸门 1/2" in note and "#2[pending]" in note
        assert s.GATE_MAX == 2

    def test_notice_chunk_shape(self):
        s = self.s
        line = s._tool_notice_chunk("⚠️ t", "c")
        assert line.startswith("data: ")
        obj = json.loads(line[len("data: "):])
        tc = obj["choices"][0]["delta"]["tool_content"]
        assert tc["type"] == "error" and tc["title"].startswith("⚠️")


class TestTodoEcho:
    def test_formatter_and_echo(self):
        from py.cli_tool import format_todo_snapshot_line, todo_echo
        todos = [{"id": str(i), "status": "done" if i % 2 else "pending"} for i in range(1, 6)]
        line = format_todo_snapshot_line(todos)
        assert line.startswith("#1[done]") and "#5[done]" in line and "#2[pending]" in line
        assert todo_echo(todos).startswith("\n[list] ")
        assert todo_echo([]) == "" and todo_echo([{"status": "done"}]) == ""


class TestPipesAndPins:
    def test_settings_pipeline(self):
        assert "['agentRobustness', 'agentRobustness']," in _read("static", "js", "settings_schema.js")
        defaults = _read("static", "js", "data", "20_brain_settings.js")
        assert "reanchorEveryToolRounds: 6" in defaults
        assert "malformedCallRepairMax: 2," in defaults
        tpl = json.loads(_read("config", "settings_template.json"))
        ar = tpl["agentRobustness"]
        assert ar["reanchorEveryToolRounds"] == 6
        assert ar["malformedCallRepairMax"] == 2
        # S207：瞬断重试键（后端 llm_recovery 兜底默认，UI 后续故事接入）
        assert ar["llmRetryMax"] == 4 and ar["llmRetryBaseDelayMs"] == 1000  # S308 加宽
        assert ar["llmRetryMidStream"] is True
        page = _read("static", "templates", "page_system.html")
        assert 'v-model="agentRobustness.reanchorEveryToolRounds"' in page
        assert 'v-model="agentRobustness.malformedCallRepairMax"' in page
        for loc in ("zh-CN", "en-US"):
            src = _read("static", "js", "locales", loc + ".js")
            for k in ("agentRobustness", "reanchorEveryToolRoundsDesc", "malformedCallRepairMaxDesc"):
                assert f"'{k}'" in src, (loc, k)

    def test_contract_clauses(self):
        # S204：调用块纪律随能力索引常驻（py/tool_discipline.py），契约只留任务纪律
        d = _read("py", "tool_discipline.py")
        assert "written into the message BODY is never executed" in d
        assert "Topic anchor (hard rule, S183)" in _read("py", "agent_prompt.py")

    def test_stream_wiring_pins(self):
        s = _read("server.py") + _read("py/stream_prep.py") + _read("py/stream_engine.py")  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
        # 显示拦截两个 pass 都接
        assert s.count("_tcg_show, _st[\"tcg_emit\"], _st[\"tcg_cut\"] = _tcg_display_slice(") == 2
        # raw 累积不再走 delta
        assert s.count('full_content += new_content.strip("\\x00")') == 2
        # TCG 门控：动态上限 + 错误块 + 闸门
        assert "_repair_max = _robust_cfg(settings)[1]" in s
        assert "畸形工具调用（已拦截，未执行）" in s
        assert "[Gate] todo 未清即收尾，完成闸门打回" in s
        assert "任务未完结即收尾" in s
        assert "async def _stream_gate_check(" in s
        assert 'if _g_act == "block":' in s
        # 再锚（M3: 独立小函数）+ turn_used_todo
        assert "async def _stream_anchor_inject(" in s
        assert "await _stream_anchor_inject(request, settings, _st, pending_abort)" in s
        assert "_st[\"anchor_rounds\"] % _rn != 0" in s
        assert '_st["turn_used_todo"] = True' in s
        # DRS 等 raw 落账全部中和（8 处）
        assert s.count('"content": _tcg_neutralize(full_content),') >= 8
        # S184 起头尾截断升级为可恢复截断（见 test_tool_output_store_s184）
        assert "def _bound_tool_output(" in s
