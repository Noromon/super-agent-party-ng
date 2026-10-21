# -*- coding: utf-8 -*-
"""E-1 forensics, dispositioned (S43): both engines now assemble their LLM
tool lists through the single source py/tool_assembly.build_llm_tools.

Phase 1 printed the drift; E-1b aligned the engines (node-extension tools are
announced on both paths per the S43 decision) and this file now enforces
strict set equality plus the single-source structure itself.
"""
import json
import os
import sqlite3

from test_contract_sse import post_chat, collect, sse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SRC = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()


def _mutate_settings(data_dir, mutate):
    """chat_endpoint reloads settings from the DB per request (L7658), so a
    direct DB edit takes effect on the very next call. Returns the original
    JSON text for restoring."""
    con = sqlite3.connect(os.path.join(str(data_dir), "super_agent_party.db"))
    original = con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]
    data = json.loads(original)
    mutate(data)
    con.execute("UPDATE settings SET data=? WHERE id=1",
                (json.dumps(data, ensure_ascii=False),))
    con.commit()
    con.close()
    return original


def _restore_settings(data_dir, original):
    con = sqlite3.connect(os.path.join(str(data_dir), "super_agent_party.db"))
    con.execute("UPDATE settings SET data=? WHERE id=1", (original,))
    con.commit()
    con.close()


def _tool_names(history):
    names = set()
    for call in history:
        for t in call.get("tools") or []:
            fn = (t.get("function") or {}).get("name") or t.get("name")
            if fn:
                names.add(fn)
    return names


class TestAssemblyParity:
    def test_stream_and_complete_tool_sets(self, sap, mock_llm):
        # --- streaming engine ---
        mock_llm.script([{"kind": "text", "content": "s-ok"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
        collect(sse(r))
        stream_tools = _tool_names(mock_llm.history)

        # --- complete engine (same endpoint, stream=false branch) ---
        mock_llm.script([{"kind": "text", "content": "c-ok"}])
        r2 = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]},
                       stream=False)
        assert r2.status_code == 200
        complete_tools = _tool_names(mock_llm.history)

        assert stream_tools, "stream engine must send some tools to the LLM"
        assert complete_tools, "complete engine must send some tools to the LLM"
        # E-1b: strict equality is the ratchet (single source can never drift)
        assert stream_tools == complete_tools, (
            f"engine drift: stream_only={sorted(stream_tools - complete_tools)} "
            f"complete_only={sorted(complete_tools - stream_tools)}")
        assert {"list_files_tool_local", "read_file_tool_local", "shell_tool_local"} <= stream_tools, \
            f"core built-ins missing: {sorted(stream_tools)[:20]}"


class TestPermissionListsSingleSource:
    """E-1a: sensitive/plan-blocked lists live only in py/tool_registry.py."""

    def test_server_no_longer_defines_lists(self):
        assert "SENSITIVE_TOOLS = [" not in SERVER_SRC
        assert "PLAN_BLOCKED_TOOLS = " not in SERVER_SRC
        assert "from py.tool_registry import" in SERVER_SRC

    def test_registry_semantics(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sap_tool_registry", os.path.join(ROOT, "py", "tool_registry.py"))
        reg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reg)
        assert "shell_tool_local" in reg.SENSITIVE_TOOLS
        assert "docker_sandbox" in reg.SENSITIVE_TOOLS
        assert reg.PLAN_BLOCKED_TOOLS >= set(reg.SENSITIVE_TOOLS)
        assert "todo_write_tool" in reg.PLAN_BLOCKED_TOOLS


def _capture_tool_sets(sap, mock_llm):
    mock_llm.script([{"kind": "text", "content": "s-ok"}])
    collect(sse(post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})))
    stream_tools = _tool_names(mock_llm.history)
    mock_llm.script([{"kind": "text", "content": "c-ok"}])
    post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]}, stream=False)
    return stream_tools, _tool_names(mock_llm.history)


class TestNonDefaultConfigDrift:
    """E-1b forensics: with optional tools switched ON, verify the engines
    still agree (randomTopic/time/weather...), and pin the one known gap
    (node-extension tools are assembled by the streaming engine only)."""

    def test_randomtopic_on_still_zero_drift(self, sap, mock_llm):
        original = _mutate_settings(
            sap.data_dir, lambda d: d["tools"]["randomTopic"].__setitem__("enabled", True))
        try:
            stream_tools, complete_tools = _capture_tool_sets(sap, mock_llm)
            assert "get_random_topics" in stream_tools
            assert stream_tools == complete_tools, (
                "randomTopic-on must not drift: "
                f"stream_only={sorted(stream_tools - complete_tools)} "
                f"complete_only={sorted(complete_tools - stream_tools)}")
        finally:
            _restore_settings(sap.data_dir, original)

    def test_time_tool_on_still_zero_drift(self, sap, mock_llm):
        # time tool assembly condition is character-identical on both sides
        # (L4109 / L6364); prove it at runtime with the trigger mode enabled.
        original = _mutate_settings(
            sap.data_dir,
            lambda d: d["tools"]["time"].update({"enabled": True,
                                                 "triggerMode": "afterThinking"}))
        try:
            stream_tools, complete_tools = _capture_tool_sets(sap, mock_llm)
            assert stream_tools == complete_tools, (
                f"time-on drift: {sorted(stream_tools ^ complete_tools)}")
        finally:
            _restore_settings(sap.data_dir, original)

    def test_assembly_is_single_source(self):
        """E-1b end-state ratchet: both engines call build_llm_tools and the
        server file carries no inline assembly copies anymore (the old drift
        surface: complete missed node-extension tools entirely)."""
        assert SERVER_SRC.count("await build_llm_tools(request, settings, "
                                "_assemble_toolkit())") == 2
        assert 'tools = request.tools or []' not in SERVER_SRC
        # the node-extension announce loop lives exactly once, in the module
        asm = open(os.path.join(ROOT, "py", "tool_assembly.py"),
                   encoding="utf-8").read()
        assert "node_ext_mcp_tools" in asm
        assert asm.count("for ext_id, tools_list in") == 1
        assert asm.count("来自扩展") == 1
        # server keeps only the dispatch-side lookup over node_ext_mcp_tools
        # (execution layer), never a tool-announce loop for the LLM
        assert "来自扩展" not in SERVER_SRC
        # 批 2h3：执行层的 node 注册表扫描已迁 py/tool_dispatch.py（注入
        # 注册表活引用），server 内不再出现；唯一性转移到新模块断言
        assert SERVER_SRC.count(
            "for ext_id, tools in node_ext_mcp_tools.items()") == 0
        _td = open(os.path.join(ROOT, "py", "tool_dispatch.py"),
                   encoding="utf-8-sig").read()
        assert _td.count("for ext_id, tools in ext_mcp_tools.items()") == 1
