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
    # R1 router migration: endpoint functions may live in py/routers/*.py
    # 批 1: 断点续传中继函数已迁 py/stream_relay.py
    # S300: 群记忆域已迁 py/group_memory.py（_extract_group_memories 永不在闸内钉随行）
    sources = [SRC, (ROOT / "py" / "stream_relay.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "group_memory.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "tool_hooks.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8"),
               (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")] + \
        [f.read_text(encoding="utf-8")
         for f in sorted((ROOT / "py" / "routers").glob("*.py"))]
    for src in sources:
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                seg = ast.get_source_segment(src, node)
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
        # M-3 split: the second fence + abort marking moved into _ns_tool_round
        wrapper = _func_src("generate_complete_response")
        assert '"cancelled": False' in wrapper
        assert "_current_stream_entry.set(entry)" in wrapper
        impl = _func_src("_generate_complete_impl") + _func_src("_ns_tool_round")
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
        assert "_st_cancelled" in _func_src("stream_generator")  # S131: explicit-entry fence

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
        # S303：NS 轮审批哨兵随 complete 引擎迁出，扫描面并入（反钉更严）
        SRC = ((ROOT / "server.py").read_text(encoding="utf-8")
               + (ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8"))
        assert "'\"approval_required\"' in results" not in SRC
        assert "_is_approval_result(results)" in SRC

    def test_t9_emit_site_uses_sentinel(self):
        # M-3 split: approval emit moved from dispatch_tool into _sensitive_approval
        emit = _func_src("_sensitive_approval")
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
        # S299：视觉域 VLM 出口自 server.py 逐字迁入。server 不在本棘轮扫描面内=
        # 历史上从未闸过；迁入即加闸属行为改动，违纯移动纪律——按棘轮自述走显式
        # 豁免（钉 (文件,函数) 对，不豁免同名未来新出口）。加闸与否并入引擎战役终评。
        exempt_pairs = {("vision_tools.py", n) for n in (
            "get_image_content", "analyze_image", "analyze_images",
            "review_image", "images_add_in_messages")} | \
            {("group_memory.py", "_extract_group_memories")}  # S300：mem0 侧永不在闸内（同文件 never-gates 钉）
        # S302a：主链两处手写重试环（裸 create）随轮次引擎迁入——server 扫描面历史上
        # 从未闸它们（s207“全文裸 create=2”金标准）；迁入即加闸=行为改动，违纯移动。
        exempt_pairs |= {("stream_engine.py", "_stream_first_round_with_recovery"),
                         ("stream_engine.py", "_stream_second_round")}
        # S302a：其余 acreate 包裹的 lambda create 为 server 时代「从未在闸内」的
        # 引擎调用点（闸在端点层 hold），迁入 py 扫描面即触发；纯移动不加闸，
        # 显式豁免同名对（加闸与否并入引擎战役终评，同 S299 先例）。
        exempt_pairs |= {("stream_engine.py", n) for n in (
            "_stream_drs_round", "_stream_drs_loop_round",
            "_stream_reasoner_update")} | \
            {("stream_prep.py", n) for n in (
                "_stream_deepsearch_pre", "_stream_reasoner_prep")} | \
            {("complete_engine.py", n) for n in (
                "_complete_reasoner_prep", "_complete_drs_step",
                "_ns_reasoner_pass",
                "_generate_complete_impl")}  # S303/S304：同 S302a 先例，server 时代从未在闸内
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
                # 注释对齐：闸针对 chat 系出口（chat.completions/embeddings/
                # responses）；whisper 转写等非 chat API 不占 mem0 防撞闸
                if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                        and node.func.attr == "create"
                        and isinstance(node.func.value, _ast.Attribute)
                        and node.func.value.attr in ("completions", "embeddings", "responses")):
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
                    if not ok and chain[0].name not in exempt_funcs \
                            and (path.name, chain[0].name) not in exempt_pairs:
                        bad.append((path.name, chain[0].name, node.lineno))
        assert not bad, f"ungated direct LLM exits: {bad}"


class TestC5C15Pins:
    """C-5: POST /memory both-ends fix. C-15: WS save failure must ack save_error."""

    def test_post_memory_endpoint_exists(self):
        # C-5 pin updated by the R1 router migration (audit 09 item 6): the
        # memory CRUD endpoints now live in py/routers/memories.py
        mem = (ROOT / "py" / "routers" / "memories.py").read_text(encoding="utf-8")
        assert '@router.post("/memory/{memory_id}")' in mem

    def test_ws_save_failures_ack_error(self):
        # save_settings + save_conversations failure paths both answer
        assert SRC.count('"type": "save_error"') >= 2

    def test_stream_id_header_exposed(self):
        # C-14: cross-origin clients must be able to read X-Stream-Id
        assert "Access-Control-Expose-Headers" in SRC
        assert '"X-Stream-Id"' in SRC

    def test_backup_toggle_domain_consistency(self):
        # S280: 手动快照的构成随请求 body 直传（后端不再读键）；自动快照两个设置键
        # （主键 backupAutoItems / 遗留键 backupIncludeUploads）都必须读
        # systemSettings 域（前端持久化域），顶层旧写法仅作兼容回退
        assert '("systemSettings") or {}).get("backupAutoItems"' in SRC
        assert '("systemSettings") or {}).get("backupIncludeUploads"' in SRC
        status_src = (ROOT / "py" / "routers" / "status.py").read_text(encoding="utf-8")
        assert '(body or {}).get("include")' in status_src
