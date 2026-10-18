# -*- coding: utf-8 -*-
"""M1b: turn_log shadow write pins (server-side canonical chain groundwork)."""
import sqlite3

from test_contract_sse import collect, post_chat, sse


def chain(data_dir, conv_id):
    con = sqlite3.connect(data_dir / "conversations.db")
    try:
        rows = con.execute(
            "SELECT seq, msg FROM turn_log WHERE conversation_id = ? ORDER BY seq",
            (conv_id,)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    con.close()
    import json
    return [(s, json.loads(m)) for s, m in rows]


class TestTurnLogShadow:
    def test_stream_round_records_chain(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "shadow round one"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "shadow me"}],
                            "conversation_id": "conv-shadow-1"})
        collect(sse(r))
        rows = chain(sap.data_dir, "conv-shadow-1")
        roles = [m["role"] for _, m in rows]
        assert "user" in roles and "assistant" in roles
        assert [s for s, _ in rows] == sorted(s for s, _ in rows)

    def test_tool_round_chain_contains_calls_and_results(self, sap, mock_llm):
        mock_llm.script([
            {"kind": "tool", "name": "list_files_tool_local",
             "arguments": {"path": "."}, "id": "call_tl"},
            {"kind": "text", "content": "tool done shadow"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "list"}],
                            "conversation_id": "conv-shadow-2"})
        collect(sse(r))
        rows = chain(sap.data_dir, "conv-shadow-2")
        roles = [m["role"] for _, m in rows]
        assert "tool" in roles
        tcs = [m for m in (m for _, m in rows) if m.get("tool_calls")]
        assert tcs, "assistant.tool_calls entries must be in the shadow chain"

    def test_stateless_channel_skips_shadow(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "no conv id"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
        collect(sse(r))
        import sqlite3
        con = sqlite3.connect(sap.data_dir / "conversations.db")
        try:
            n = con.execute(
                "SELECT COUNT(*) FROM turn_log WHERE conversation_id IS NULL").fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        con.close()
        assert n == 0
