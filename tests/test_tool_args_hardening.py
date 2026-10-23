# -*- coding: utf-8 -*-
"""S85-A：工具参数健壮性——单键壳解包 + '}{拼接取首个非壳片段 + 流式槽位合并。"""
import ast
import copy
import io
import json
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s85a_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def _extract_server_fn(name):
    src = _read("server.py")
    tree = ast.parse(src)
    ns = {"json": json, "copy": copy}
    # 依赖注入：模块级常量与壳解包 helper 先于 parse_tool_arguments 入 ns
    deps = ["_unwrap_arg_shell", "_merge_tool_delta"]
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "_ARG_SHELL_KEYS":
            exec(compile(ast.get_source_segment(src, node), "<dep>", "exec"), ns)
    for dep in deps:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == dep:
                exec(compile(ast.get_source_segment(src, node), "<dep>", "exec"), ns)
                break
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            exec(compile(seg, "<extract>", "exec"), ns)  # noqa: S102
            return ns[name]
    raise AssertionError(f"{name} not found at server.py module level")


# ---------------- parse_tool_arguments + _unwrap_arg_shell ----------------

def test_plain_args_passthrough():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"a": 1, "q": "x"}') == ({"a": 1, "q": "x"}, None)


def test_single_key_shell_dict():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"arguments": {"path": "x"}}') == ({"path": "x"}, None)


def test_shell_with_stringified_inner():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"arguments": "{\\"path\\": \\"x\\"}"}') == ({"path": "x"}, None)


def test_double_shell_nested():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"arguments": {"arguments": {"a": 1}}}') == ({"a": 1}, None)


def test_concat_shell_takes_first_unwrapped():
    fn = _extract_server_fn("parse_tool_arguments")
    raw = '{"arguments": {"a": 1}}{"arguments": {"b": 2}}'
    assert fn(raw) == ({"a": 1}, None)


def test_concat_plain_keeps_first():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"a": 1}{"b": 2}') == ({"a": 1}, None)


def test_non_shell_single_key_untouched():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('{"query": "q"}') == ({"query": "q"}, None)


def test_empty_and_error_paths():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn("") == ({}, None)
    args, err = fn("{oops")
    assert args is None and "Invalid JSON" in err


def test_list_wrapper_unwrapped():
    fn = _extract_server_fn("parse_tool_arguments")
    assert fn('[{"arguments": {"a": 1}}]') == ({"a": 1}, None)


# ---------------- _merge_tool_delta 槽位 ----------------

def _tc(index=None, cid=None, name=None, arguments=None):
    fn = types.SimpleNamespace(name=name, arguments=arguments)
    return types.SimpleNamespace(index=index, id=cid, function=fn)


def test_merge_index_slots_interleaved():
    fn = _extract_server_fn("_merge_tool_delta")
    calls = []
    fn(calls, _tc(index=0, cid="A", name="q", arguments="{"))
    fn(calls, _tc(index=1, cid="B", name="r", arguments="["))
    cur, frag = fn(calls, _tc(index=0, arguments="}"))
    assert cur is calls[0] and cur.function.arguments == "{}"
    assert calls[1].function.arguments == "["
    assert frag == "}"


def test_merge_id_fallback_without_index():
    fn = _extract_server_fn("_merge_tool_delta")
    calls = []
    fn(calls, _tc(cid="A", name="foo", arguments="x"))
    fn(calls, _tc(cid="B", name="bar", arguments="y"))
    cur, _ = fn(calls, _tc(cid="B", arguments="z"))
    assert len(calls) == 2
    assert cur is calls[1] and calls[1].function.arguments == "yz"
    assert calls[0].function.arguments == "x"


def test_merge_legacy_no_index_no_id_backcompat():
    fn = _extract_server_fn("_merge_tool_delta")
    calls = []
    fn(calls, _tc(cid=None, name="foo", arguments="a"))
    cur, frag = fn(calls, _tc(arguments="b"))
    assert len(calls) == 1 and cur.function.arguments == "ab"
    assert frag == "b"


def test_merge_new_slot_when_index_beyond():
    fn = _extract_server_fn("_merge_tool_delta")
    calls = []
    cur, _ = fn(calls, _tc(index=2, cid="C", name="n", arguments="1"))
    assert len(calls) == 3 and cur.function.arguments == "1"
    assert calls[0].function.arguments == "" and calls[1].function.arguments == ""


def test_merge_id_backfill():
    fn = _extract_server_fn("_merge_tool_delta")
    calls = []
    fn(calls, _tc(index=0, cid=None, name="n", arguments="1"))
    fn(calls, _tc(index=0, cid="X", arguments="2"))
    assert calls[0].id == "X"
