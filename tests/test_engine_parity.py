# -*- coding: utf-8 -*-
"""M3a: stream engine vs complete engine behavioral parity (audit T-8/D-7 drift).

Same mock script, run through both engines; the LLM-visible chain (mock
history) and final answer must match. Any RED here is a drift finding for M3b.
"""
from test_contract_sse import collect, post_chat, sse

SCRIPT_TOOL_OK = [
    {"kind": "tool", "name": "list_files_tool_local",
     "arguments": {"path": "."}, "id": "call_p1"},
    {"kind": "text", "content": "final answer after tool"},
]
SCRIPT_UNKNOWN_TOOL = [
    {"kind": "tool", "name": "edit_file_tool_patch_tool_local",
     "arguments": {"path": "a", "old_string": "b", "new_string": "c"},
     "id": "call_p2"},
    {"kind": "text", "content": "recovered reply"},
]
SCRIPT_BAD_ARGS = [
    {"kind": "tool", "name": "list_files_tool_local",
     "arguments_raw": "{not valid json", "id": "call_p3"},
    {"kind": "text", "content": "bad args recovered"},
]


def last_round_chain(mock):
    return mock.history[-1]["messages"]


def tool_rows(chain):
    return [str(m.get("content", "")) for m in chain if m.get("role") == "tool"]


def run_stream(sap, mock_llm, script, conv):
    mock_llm.script(script)
    frames = collect(sse(post_chat(sap, {"messages": [{"role": "user", "content": "go"}],
                                    "conversation_id": conv})))
    assert frames[-1].get("__done__")
    text = "".join(
        (f.get("choices") or [{}])[0].get("delta", {}).get("content") or ""
        for f in frames if f.get("choices"))
    return text, last_round_chain(mock_llm)


def run_complete(sap, mock_llm, script, conv):
    mock_llm.script(script)
    r = post_chat(sap, {"messages": [{"role": "user", "content": "go"}],
                        "conversation_id": conv}, stream=False)
    assert r.status_code == 200
    return r.json()["choices"][0]["message"]["content"], last_round_chain(mock_llm)


class TestEngineParity:
    def test_tool_round_parity(self, sap, mock_llm):
        t1, c1 = run_stream(sap, mock_llm, SCRIPT_TOOL_OK, "conv-parity-1")
        t2, c2 = run_complete(sap, mock_llm, SCRIPT_TOOL_OK, "conv-parity-2")
        assert t2 == "final answer after tool"
        assert t1.endswith("final answer after tool")
        tc1 = [m for m in c1 if m.get("tool_calls")]
        tc2 = [m for m in c2 if m.get("tool_calls")]
        assert tc1 and tc2, "both engines must keep assistant.tool_calls in chain"
        tr1, tr2 = tool_rows(c1), tool_rows(c2)
        assert len(tr1) == len(tr2) == 1, "exactly one tool result row each"
        assert tr1[0] == tr2[0], "same tool+args must produce same chain content"
        # real arguments must reach the LLM in both engines (C-1 on server side)
        fn1 = tc1[0]["tool_calls"][0]["function"]["arguments"]
        fn2 = tc2[0]["tool_calls"][0]["function"]["arguments"]
        assert '"path"' in str(fn1) and '"path"' in str(fn2)

    def test_unknown_tool_parity(self, sap, mock_llm):
        t1, c1 = run_stream(sap, mock_llm, SCRIPT_UNKNOWN_TOOL, "conv-parity-3")
        t2, c2 = run_complete(sap, mock_llm, SCRIPT_UNKNOWN_TOOL, "conv-parity-4")
        assert any("[Unknown Tool]" in r for r in tool_rows(c1)), "stream chain"
        assert any("[Unknown Tool]" in r for r in tool_rows(c2)), "complete chain"
        assert t2 == "recovered reply"

    def test_bad_args_parity(self, sap, mock_llm):
        t1, c1 = run_stream(sap, mock_llm, SCRIPT_BAD_ARGS, "conv-parity-5")
        t2, c2 = run_complete(sap, mock_llm, SCRIPT_BAD_ARGS, "conv-parity-6")
        assert any("[Argument Error]" in r for r in tool_rows(c1)), "stream chain"
        assert any("[Argument Error]" in r for r in tool_rows(c2)), "complete chain"
        assert t2 == "bad args recovered"
