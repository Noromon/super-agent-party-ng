# -*- coding: utf-8 -*-
"""M3a: stream engine vs complete engine behavioral parity (audit T-8/D-7 drift).

Same mock script, run through both engines; the LLM-visible chain (mock
history) and final answer must match. Any RED here is a drift finding for M3b.
"""
import ast
from pathlib import Path

from test_contract_sse import collect, post_chat, sse

ROOT = Path(__file__).resolve().parent.parent
SRC = (ROOT / "server.py").read_text(encoding="utf-8")


def _func_src(name):
    tree = ast.parse(SRC)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(SRC, node)
            assert seg
            return seg
    raise AssertionError(f"function not found: {name}")

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


class TestDriftRadar:
    """M3b groundwork: strict-xfail pins for known stream/complete drift.
    When M3d fixes one, the test XPASSes and hard-fails the suite -> remove
    the xfail marker (ratchet)."""

    def test_complete_has_cancel_fence(self):
        # M3d: fence lives in the impl body, entry (cancelled flag) in the wrapper
        wrapper = _func_src("generate_complete_response")
        assert '"cancelled": False' in wrapper
        assert "_current_stream_entry.set(entry)" in wrapper
        impl = _func_src("_generate_complete_impl")
        assert impl.count('_cur_entry.get("cancelled")') >= 2
        assert "ns_pending_abort = True" in impl

    def test_complete_enters_llm_gate(self):
        assert "llm_gate.enter()" in _func_src("generate_complete_response")
        assert "llm_gate.leave()" in _func_src("generate_complete_response")

    def test_simple_chat_enters_llm_gate(self):
        assert "llm_gate.enter()" in _func_src("simple_chat_endpoint")
        assert "llm_gate.leave()" in _func_src("simple_chat_endpoint")

    def test_stream_side_has_gate_and_fence(self):
        # positive control: the stream engine already carries both
        assert "llm_gate.enter()" in _func_src("stream_generator")
        assert "_stream_cancelled" in _func_src("stream_generator")

    def test_t4_consumer_release_wired(self):
        assert "_release_consumer(stream_id)" in _func_src("_stream_consumer_generator")
        assert "_release_consumer(stream_id)" in _func_src("resume_stream_endpoint")

    def test_t4_cancel_schedules_cleanup(self):
        assert "_cleanup_stream(" in _func_src("cancel_stream_endpoint")

    def test_t4_producer_exit_schedules_cleanup(self):
        assert "_cleanup_stream(" in _func_src("_stream_producer_wrapper")

    def test_t4_ttl_loop_mounted(self):
        assert "_stream_ttl_loop" in SRC
        assert "stream_ttl_task" in _func_src("lifespan")

    def test_t9_no_substring_sniffing_left(self):
        assert "'\"approval_required\"' in results" not in SRC
        assert "_is_approval_result(results)" in SRC

    def test_t9_emit_site_uses_sentinel(self):
        emit = _func_src("dispatch_tool")
        assert "_approval_payload(tool_name, tool_params, permission_mode, cwd)" in emit


class TestGateBlindSpotClosure:
    """T-5 D2a: direct LLM exits outside stream/complete parents must gate."""

    def test_gate_contextmanager_exists(self):
        src = (ROOT / "py" / "llm_gate.py").read_text(encoding="utf-8")
        assert "@asynccontextmanager" in src
        assert "async def gate()" in src

    def test_direct_llm_exits_gated(self):
        lt = (ROOT / "py" / "llm_tool.py").read_text(encoding="utf-8")
        po = (ROOT / "py" / "pollinations.py").read_text(encoding="utf-8")
        cm = (ROOT / "py" / "context_manager.py").read_text(encoding="utf-8")
        assert lt.count("async with llm_gate.gate():") == 2
        assert po.count("async with llm_gate.gate():") == 1
        assert "async with llm_gate.gate():" in cm

    def test_mem0_side_never_gates(self):
        # _extract_group_memories runs inside mem0 jobs: gating it would make
        # wait_chat_idle wait on its own inflight forever (starvation bug).
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        body = _func_src("_extract_group_memories")
        assert "llm_gate.enter()" not in body
        assert "llm_gate.gate()" not in body
        assert "@llm_gate.gated" not in body

    def test_all_py_direct_creates_gated(self):
        """Global ratchet: every chat.completions.create under py/ must sit in
        a gated chain (decorator or gate() in any enclosing function).
        New LLM exits must gate themselves or get an explicit exemption."""
        import ast as _ast
        exempt_funcs = {"agent_tool_call"}  # self-call via /v1 (parent gated)
        markers = ("@llm_gate.gated", "llm_gate.gate()")
        bad = []
        for path in sorted((ROOT / "py").glob("*.py")):
            if path.name == "llm_gate.py":
                continue
            src = path.read_text(encoding="utf-8-sig")
            tree = _ast.parse(src)
            funcs = [n for n in _ast.walk(tree)
                     if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))]
            for node in _ast.walk(tree):
                if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                        and node.func.attr == "create"):
                    chain = [g for g in funcs if g.lineno <= node.lineno <= g.end_lineno]
                    if not chain:
                        bad.append((path.name, "<module>", node.lineno))
                        continue
                    ok = False
                    for g in chain:
                        seg = _ast.get_source_segment(src, g) or ""
                        lines_above = src.splitlines()[: g.lineno - 1]
                        tail = lines_above[-3:]  # decorator zone above def
                        if any(m in seg for m in markers) or any(m in " ".join(tail) for m in markers):
                            ok = True
                            break
                    if not ok and chain[0].name not in exempt_funcs:
                        bad.append((path.name, chain[0].name, node.lineno))
        assert not bad, f"ungated direct LLM exits: {bad}"


class TestC5C15Pins:
    """C-5: POST /memory both-ends fix. C-15: WS save failure must ack save_error."""

    def test_post_memory_endpoint_exists(self):
        assert '@app.post("/memory/{memory_id}")' in SRC

    def test_ws_save_failures_ack_error(self):
        # save_settings + save_conversations failure paths both answer
        assert SRC.count('"type": "save_error"') >= 2

    def test_stream_id_header_exposed(self):
        # C-14: cross-origin clients must be able to read X-Stream-Id
        assert "Access-Control-Expose-Headers" in SRC
        assert '"X-Stream-Id"' in SRC
