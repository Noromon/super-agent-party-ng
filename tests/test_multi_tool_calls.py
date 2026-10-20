# -*- coding: utf-8 -*-
"""C-20: interleaved multi tool-call streaming must aggregate by the
protocol-level tool.index, not by per-chunk delta array position.
Old bug: second call's arguments got appended into slot 0 -> two JSON docs
in one fragment ('{"path":"."}{"path":".agent/ai_todos.json"}', turn_log seq13)."""
import json

from test_contract_sse import collect, post_chat, sse

SCRIPT_INTERLEAVE = [
    {"kind": "tools_interleave", "calls": [
        {"index": 0, "id": "call_a", "name": "list_files_tool_local",
         "arguments": {"path": "."}},
        {"index": 1, "id": "call_b", "name": "list_files_tool_local",
         "arguments": {"path": "docs"}}]},
    {"kind": "text", "content": "two calls done"},
]


class TestInterleavedToolCalls:
    def test_two_calls_keep_separate_arguments(self, sap, mock_llm):
        mock_llm.script(SCRIPT_INTERLEAVE)
        frames = collect(sse(post_chat(sap, {
            "messages": [{"role": "user", "content": "go"}],
            "conversation_id": "conv-c20"})))
        assert frames[-1].get("__done__")
        chain = mock_llm.history[-1]["messages"]
        tcs = [m for m in chain if m.get("tool_calls")][0]["tool_calls"]
        assert len(tcs) == 2, "two calls must land in separate slots"
        assert [tc["id"] for tc in tcs] == ["call_a", "call_b"]
        for tc in tcs:
            args = json.loads(tc["function"]["arguments"])
            assert "path" in args
        assert json.loads(tcs[1]["function"]["arguments"])["path"] == "docs"
        tool_rows = [m for m in chain if m.get("role") == "tool"]
        assert len(tool_rows) == 2, "both calls must produce their own tool row"
        text = "".join(
            (f.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
            for f in frames if f.get("choices"))
        assert "two calls done" in text
