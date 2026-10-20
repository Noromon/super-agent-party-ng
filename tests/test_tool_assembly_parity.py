# -*- coding: utf-8 -*-
"""E-1 forensics (informational phase): the streaming engine and the complete
engine assemble their LLM tool lists with copy-pasted code that has drifted.

Phase 1 (this file): both engines run against the scripted mock; the tool-name
sets sent to the LLM are captured and the drift is PRINTED (assertions only
pin the common core). Phase 2 (E-1b, after dispositioning the drift): single
source + tighten to strict set equality.
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


class TestAssemblyDriftEvidence:
    def test_stream_and_complete_tool_sets(self, sap, mock_llm, capsys):
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
        common = stream_tools & complete_tools
        assert common, "engines must share a common tool core"

        drift = {"stream_only": sorted(stream_tools - complete_tools),
                 "complete_only": sorted(complete_tools - stream_tools)}
        with capsys.disabled():
            print("[assembly-drift]", json.dumps(drift, ensure_ascii=False),
                  "| sizes:", len(stream_tools), len(complete_tools))
        # the default-config core is pinned as the regression floor for E-1b;
        # names chosen from the first evidence run (stable built-ins, no
        # external services involved)
        assert {"list_files_tool_local", "read_file_tool_local", "shell_tool_local"} <= common, \
            f"core built-ins missing from common set: {sorted(common)[:20]}"
        # informational: E-1b dispositiones the drift, then flip this to strict
        # assert stream_tools == complete_tools


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

    def test_node_ext_gap_is_the_only_assemble_divergence(self):
        """Static evidence for the dispositioning decision: the streaming
        assembler iterates node_ext_mcp_tools; the complete assembler has no
        such loop, so node-extension tools are never announced to the LLM on
        the non-streaming (IM bots / stream=false) path. Dispatch itself is
        shared, so the execution layer is ready -- only the announcement is
        missing. E-1b single-sources this once dispositioned."""
        stream_zone = SERVER_SRC[SERVER_SRC.index("tools = request.tools or []"):
                                 SERVER_SRC.index("if settings[\"tools\"][\"arxiv\"]")]
        complete_zone = SERVER_SRC[SERVER_SRC.rindex("tools = request.tools or []"):
                                   SERVER_SRC.rindex("if settings[\"tools\"][\"arxiv\"]")]
        assert "node_ext_mcp_tools" in stream_zone
        assert "node_ext_mcp_tools" not in complete_zone  # the gap (E-1b target)
        # every optional-tool switch except node-ext must be identical zones
        for key in ('"randomTopic"', "['time']", '"weather"', '"wikipedia"', '"arxiv"'):
            assert stream_zone.count(key) == complete_zone.count(key), key
