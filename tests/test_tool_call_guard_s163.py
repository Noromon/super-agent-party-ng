# -*- coding: utf-8 -*-
"""S163: 幻觉工具调用泄漏防御（py/tool_call_guard.py + server 接线）。

事故（backend.log 2026-10-29 15:53）：模型把 edit_file_tool_local 与
edit_file_patch_tool_local 拼接成未声明名 edit_file_tool_patch_tool_local，
引擎把调用块降级成正文 → XML 文本发给用户并写进会话历史（few-shot 污染），
回合 stop 终结任务中断。本文件钉桩：检测/中和/自纠重试（≤2，只提示不改写
执行——用户拍板）。ast 抽取 server 函数体测试，不 import 重型 server 模块。
"""
import ast
import asyncio
import logging
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.tool_call_guard import (  # noqa: E402
    MAX_TCG_RETRIES, REDACTION, build_correction_message,
    declared_tool_names, detect_leaked_calls, neutralize_leaked_blocks,
)

SRC = (_ROOT / "server.py").read_text(encoding="utf-8-sig")

LEAKED = (
    "让我继续修改配置。\n"
    "<tool_call>\n<function=edit_file_tool_patch_tool_local>\n"
    "<parameter=path>\ngen_config.json\n</parameter>\n"
    "</function>\n</tool_call>"
)
DECLARED = {"edit_file_tool_local", "edit_file_patch_tool_local", "shell_tool_local"}


def _func(name):
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(SRC, node)
            assert seg
            ns = {"logging": logging, "_st_cancelled": lambda _st: False,
                  "_apply_ctx_guardrail": lambda extra, msg, s: extra,
                  "_tcg_neutralize": neutralize_leaked_blocks}
            exec(compile(ast.Module(body=[node], type_ignores=[]), f"<{name}>", "exec"), ns)
            return ns[name]
    raise AssertionError(f"{name} not found")


class TestDetect:
    def test_strata_xml_form(self):
        assert detect_leaked_calls(LEAKED) == ["edit_file_tool_patch_tool_local"]

    def test_chatml_json_form(self):
        text = 'x <tool_call>{"name": "do_thing", "arguments": {}}</tool_call> y'
        assert detect_leaked_calls(text) == ["do_thing"]

    def test_multi_names_dedup_order(self):
        text = ("<tool_call><function=a_x></function></tool_call>"
                "<tool_call><function=b_y></function></tool_call>"
                "<tool_call><function=a_x></function></tool_call>")
        assert detect_leaked_calls(text) == ["a_x", "b_y"]

    def test_plain_prose_no_false_positive(self):
        assert detect_leaked_calls("I used the edit_file_patch_tool to patch the file.") == []
        assert neutralize_leaked_blocks("plain text") == "plain text"

    def test_unclosed_block_detected(self):
        text = 'blah <tool_call>\n<function=truncated_tool\n<parameter=x>1'
        assert detect_leaked_calls(text) == ["truncated_tool"]
        out = neutralize_leaked_blocks(text)
        assert "truncated_tool" not in out and REDACTION in out


class TestNeutralize:
    def test_incident_block_redacted(self):
        out = neutralize_leaked_blocks(LEAKED)
        assert "edit_file_tool_patch_tool_local" not in out
        assert "<function=" not in out and "<tool_call>" not in out
        assert out.startswith("让我继续修改配置。") and REDACTION in out

    def test_idempotent(self):
        once = neutralize_leaked_blocks(LEAKED)
        assert neutralize_leaked_blocks(once) == once


class TestCorrection:
    def test_lists_declared_and_did_you_mean(self):
        msg = build_correction_message(["edit_file_tool_patch_tool_local"], DECLARED)
        assert "NOT executed" in msg
        assert "edit_file_patch_tool_local" in msg  # did-you-mean 近似提示
        assert "VERBATIM" in msg

    def test_no_close_match_omits_hint(self):
        msg = build_correction_message(["zzz_unrelated"], DECLARED)
        assert "Closest" not in msg


class TestDeclaredNames:
    def test_dict_and_object_forms(self):
        tools = [{"function": {"name": "t_a"}},
                 types.SimpleNamespace(function=types.SimpleNamespace(name="t_b"))]
        assert declared_tool_names(tools) == {"t_a", "t_b"}

    def test_garbage_safe(self):
        assert declared_tool_names(None) == set()
        assert declared_tool_names([None, "junk", {}]) == set()


class TestContentAppendWiring:
    def test_assistant_leak_neutralized_other_roles_untouched(self):
        def _get(messages, role):
            return next((m for m in reversed(messages) if m.get("role") == role), None)

        node = next(n for n in ast.walk(ast.parse(SRC))
                    if isinstance(n, ast.FunctionDef) and n.name == "content_append")
        ns = {"_get_target_message": _get, "_tcg_neutralize": neutralize_leaked_blocks}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<ca>", "exec"), ns)
        msgs = [{"role": "assistant", "content": ""}, {"role": "user", "content": ""}]
        ns["content_append"](msgs, "assistant", LEAKED)
        ns["content_append"](msgs, "user", LEAKED)
        assert "edit_file_tool_patch_tool_local" not in msgs[0]["content"]
        assert REDACTION in msgs[0]["content"]
        assert "edit_file_tool_patch_tool_local" in msgs[1]["content"]  # user 不中和


class _FakeClient:
    def __init__(self, rounds):
        self.rounds = rounds  # [(full_content, tool_calls_list), ...] 按 create 次序
        self.calls = []

        async def _create(**kw):
            self.calls.append(kw)
            return f"resp-{len(self.calls)}"

        class _C:
            completions = types.SimpleNamespace(create=_create)
        self.chat = _C


class _FakeResp:
    status = 200


def _run_second_round(rounds, cancelled=False, tools=None, retries_pre=0):
    client = _FakeClient(rounds)
    state = {"i": 0}

    def _loop_pass(_st, response, open_tag, close_tag, tool_calls, usage_info,
                   _ctx_peak, full_content, in_reasoning, content_buffer,
                   reasoning_buffer, _chunk_count2):
        content, tcs = rounds[min(state["i"], len(rounds) - 1)]
        state["i"] += 1
        tool_calls.extend(tcs)
        _st["full_content"] = content
        _st["usage_info"] = usage_info
        _st["_ctx_peak"] = _ctx_peak
        _st["in_reasoning"] = in_reasoning
        _st["content_buffer"] = content_buffer
        _st["reasoning_buffer"] = reasoning_buffer
        yield "data: chunk\n\n"

    async def _loop_pass_ag(_st, *a, **k):
        for c in _loop_pass(_st, *a, **k):
            yield c

    async def _final_guard(_st, content_buffer, reasoning_buffer, settings):
        if []:
            yield ""

    def _cancelled(_st):
        return cancelled

    request = types.SimpleNamespace(messages=[{"role": "user", "content": "go"}])

    def _content_append(messages, role, content):
        if role == "assistant" and content:
            content = neutralize_leaked_blocks(content)
        messages.append({"role": role, "content": content})

    ns_local = {"_st_cancelled": _cancelled, "_stream_loop_pass": _loop_pass_ag,
                "_stream_final_guard": _final_guard, "logging": logging,
                "_apply_ctx_guardrail": lambda extra, msg, s: extra,
                "content_append": _content_append}
    src_node = next(n for n in ast.walk(ast.parse(SRC))
                    if isinstance(n, ast.AsyncFunctionDef) and n.name == "_stream_second_round")
    exec(compile(ast.Module(body=[src_node], type_ignores=[]), "<sr>", "exec"), ns_local)
    helper = ns_local["_stream_second_round"]
    _st = {"tcg_retries": retries_pre} if retries_pre else {}
    extra = {}

    async def _drive():
        frames = []
        async for c in helper(_st, client, "m", [{"role": "user", "content": "go"}], extra,
                              {}, {}, request, tools, False, None, 0, False, "", "",
                              "<|open|>", "<|close|>"):
            frames.append(c)
        return frames

    frames = asyncio.run(_drive())
    return _st, client, request, frames


class TestSecondRoundSelfCorrect:
    TOOLS = [{"function": {"name": "edit_file_patch_tool_local"}}]

    def test_leak_then_structured_call_retries_once(self):
        rounds = [(LEAKED, []), ("", [{"id": "c1"}])]
        _st, client, request, frames = _run_second_round(rounds, tools=self.TOOLS)
        assert len(client.calls) == 2                      # 重发一次
        assert _st["tcg_retries"] == 1
        roles = [m.get("role") for m in request.messages]
        assert roles == ["user", "assistant", "user"]      # 中和版+纠正消息
        assert "edit_file_tool_patch_tool_local" not in request.messages[1]["content"]
        assert REDACTION in request.messages[1]["content"]
        assert "NOT executed" in request.messages[2]["content"]
        assert "Declared tools are exactly: edit_file_patch_tool_local" in request.messages[2]["content"]
        assert _st["tc_round"] == [{"id": "c1"}]           # 结构化调用交回工具循环

    def test_retry_cap_then_neutralized_close(self):
        rounds = [(LEAKED, [])]  # 永远泄漏
        _st, client, request, frames = _run_second_round(rounds, tools=self.TOOLS)
        assert len(client.calls) == MAX_TCG_RETRIES + 1
        assert _st["tcg_retries"] == MAX_TCG_RETRIES
        assert _st["tc_round"] == []
        assert all("edit_file_tool_patch_tool_local" not in m.get("content", "")
                   for m in request.messages if m.get("role") == "assistant")
        assert sum(1 for m in request.messages if m.get("role") == "assistant") == MAX_TCG_RETRIES + 1

    def test_no_tools_no_retry_but_still_neutralized(self):
        rounds = [(LEAKED, [])]
        _st, client, request, frames = _run_second_round(rounds, tools=None)
        assert len(client.calls) == 1                      # 未声明工具→不重试
        assert "tcg_retries" not in _st
        assert "edit_file_tool_patch_tool_local" not in request.messages[1]["content"]

    def test_clean_text_single_call_plain_append(self):
        rounds = [("一切正常。", [])]
        _st, client, request, frames = _run_second_round(rounds, tools=self.TOOLS)
        assert len(client.calls) == 1 and _st["tc_round"] == []
        assert request.messages[1]["content"] == "一切正常。"

    def test_cancel_terminates_with_done(self):
        rounds = [("x", [])]
        _st, client, request, frames = _run_second_round(rounds, cancelled=True)
        assert client.calls == []
        assert _st.get("tc_round_done") is True and _st["tc_round"] == []
        assert frames == ["data: [DONE]\n\n"]


class TestWiringPins:
    def test_content_append_wired(self):
        assert "_tcg_neutralize(content)" in SRC

    def test_tool_round_append_wired(self):
        assert '"content": _tcg_neutralize(full_content) or ""' in SRC

    def test_second_round_replaces_inline_block(self):
        assert "async for _c in _stream_second_round(" in SRC
        assert "tc_round_done" in SRC

    def test_prompt_anticoncat_clause(self):
        p = (_ROOT / "py" / "agent_prompt.py").read_text(encoding="utf-8")
        assert "never compose, concatenate, or blend" in p
