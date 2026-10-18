# -*- coding: utf-8 -*-
"""Unit pins for py.context_builder.sanitize_tool_chains (no server needed).

Loaded by file path: pytest process must not import the repo-level `py`
package (it would shadow the pytest py-shim; see S12 checkpoint notes).
"""
import importlib.util
import pathlib

_spec = importlib.util.spec_from_file_location(
    "context_builder_under_test",
    pathlib.Path(__file__).resolve().parents[1] / "py" / "context_builder.py")
_cb = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cb)
sanitize_tool_chains = _cb.sanitize_tool_chains


def tc(tid, name="tool_x", arguments='{"a":1}'):
    return {"id": tid, "type": "function", "function": {"name": name, "arguments": arguments}}


class TestOrphanChains:
    def test_orphan_tool_dropped(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "tool", "tool_call_id": "ghost", "content": "x"},
                {"role": "assistant", "content": "ok"}]
        out = sanitize_tool_chains(msgs)
        assert [m["role"] for m in out] == ["user", "assistant"]

    def test_closed_chain_preserved_in_order(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": None, "tool_calls": [tc("c1")]},
                {"role": "tool", "tool_call_id": "c1", "content": "result"},
                {"role": "assistant", "content": "done"}]
        out = sanitize_tool_chains(msgs)
        assert out == msgs

    def test_dangling_tail_tool_calls_erased_text_kept(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "let me check", "tool_calls": [tc("c9")]}]
        out = sanitize_tool_chains(msgs)
        assert len(out) == 2
        assert out[1]["tool_calls"] is None
        assert out[1]["content"] == "let me check"

    def test_dangling_tail_no_content_popped(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "", "tool_calls": [tc("c9")]}]
        out = sanitize_tool_chains(msgs)
        assert [m["role"] for m in out] == ["user"]


class TestGhostDefense:
    def test_blank_assistant_dropped(self):
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": "   "},
                {"role": "assistant", "content": "real"},
                {"role": "user", "content": "again"}]
        out = sanitize_tool_chains(msgs)
        assert [m["role"] for m in out] == ["user", "assistant", "user"]

    def test_empty_args_chain_survives_untouched(self):
        # C-1 family pin: even with the frontend's "{}" arguments, the chain must
        # stay intact (fix belongs upstream in the producer, not by dropping here)
        msgs = [{"role": "user", "content": "hi"},
                {"role": "assistant", "content": None, "tool_calls": [tc("c1", arguments="{}")]},
                {"role": "tool", "tool_call_id": "c1", "content": "r"},
                {"role": "assistant", "content": "done"}]
        out = sanitize_tool_chains(msgs)
        assert out == msgs


class TestObjectShapes:
    def test_object_style_messages(self):
        from types import SimpleNamespace as NS
        msgs = [NS(role="user", content="hi"),
                NS(role="assistant", content=None,
                   tool_calls=[{"id": "c1", "type": "function",
                                "function": {"name": "n", "arguments": "{}"}}]),
                NS(role="tool", tool_call_id="c1", content="r"),
                NS(role="assistant", content="ok")]
        out = sanitize_tool_chains(msgs)
        assert len(out) == 4

    def test_log_sink_receives_events(self):
        sink = []
        sanitize_tool_chains([{"role": "tool", "tool_call_id": "x", "content": ""}],
                             log=sink.append)
        assert any("孤立" in s for s in sink)
