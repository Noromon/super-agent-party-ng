# -*- coding: utf-8 -*-
"""C-19 pins: unknown tool name must be visible, never silent (shadow-chain evidence)."""
from test_contract_sse import collect, post_chat, sse


class TestUnknownToolC19:
    def test_hallucinated_tool_gives_visible_result_frame(self, sap, mock_llm):
        mock_llm.script([
            {"kind": "tool", "name": "edit_file_tool_patch_tool_local",
             "arguments": {"path": "x.md", "old_string": "a", "new_string": "b"},
             "id": "call_c19a"},
            {"kind": "text", "content": "recovered with correct tool"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "patch it"}],
                            "conversation_id": "conv-c19-1"})
        frames = collect(sse(r))
        assert frames[-1].get("__done__"), "stream must still end with [DONE]"

        visible = []
        for f in frames:
            delta = (f.get("choices") or [{}])[0].get("delta", {}) if f.get("choices") else {}
            tc = delta.get("tool_content") or {}
            if tc.get("type") == "tool_result" and tc.get("tool_call_id", True):
                visible.append(str(tc.get("content", "")))
        joined = "".join(visible)
        assert "[Unknown Tool]" in joined, \
            "unknown tool must produce visible tool_result frame, got: " + joined[:200]
        assert "edit_file_patch_tool_local" in joined, \
            "error must suggest close names for LLM self-correction"

        hist = mock_llm.history
        last_msgs = hist[-1]["messages"]
        tool_rows = [m for m in last_msgs if m.get("role") == "tool"]
        assert tool_rows and "[Unknown Tool]" in str(tool_rows[-1].get("content", "")), \
            "chain fed to next LLM round must contain the explicit error"

    def test_none_result_still_visible_via_frame(self, sap, mock_llm):
        # unknown name now returns text (C-19 fallback); None-defense frame path
        # is covered by same frame shape check using another bogus name without close match
        mock_llm.script([
            {"kind": "tool", "name": "zzz_totally_not_a_tool_zzz",
             "arguments": {}, "id": "call_c19b"},
            {"kind": "text", "content": "done"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "go"}],
                            "conversation_id": "conv-c19-2"})
        frames = collect(sse(r))
        texts = []
        for f in frames:
            delta = (f.get("choices") or [{}])[0].get("delta", {}) if f.get("choices") else {}
            tc = delta.get("tool_content") or {}
            if tc.get("type") == "tool_result":
                texts.append(str(tc.get("content", "")))
        assert any("[Unknown Tool]" in t for t in texts)
        assert not any("tool_calls" in (f.get("choices") or [{}])[0].get("delta", {})
                       and isinstance((f.get("choices") or [{}])[0]["delta"]["tool_calls"], str)
                       for f in frames if f.get("choices")), \
            "malformed string delta.tool_calls frames must be gone"
