# -*- coding: utf-8 -*-
"""Contract test batch 1: SSE frame dictionary + tool round trip + approval + cancel.

Spec source: SSE frame contract / lifecycle spec (maintainer-internal docs, out-of-tree).
"""
import json

import pytest
import requests


def sse(resp):
    for raw in resp.iter_lines(decode_unicode=True):
        if not raw or not raw.startswith("data:"):
            continue
        payload = raw[5:].strip()
        if payload == "[DONE]":
            yield {"__done__": True}
        else:
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                continue


def post_chat(base, body, stream=True):
    r = requests.post(f"{base}/v1/chat/completions",
                      json={"model": "super-model", "stream": stream, **body},
                      stream=stream, timeout=120)
    assert r.status_code == 200, r.text[:400]
    r.encoding = "utf-8"
    return r


def collect(events, until_done=True):
    frames = []
    for ev in events:
        frames.append(ev)
        if ev.get("__done__"):
            break
    return frames


class TestTextStream:
    def test_meta_content_done_frames(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "hello world contract"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
        frames = collect(sse(r))

        assert frames[-1].get("__done__"), "stream must end with [DONE]"
        deltas = [f for f in frames if "choices" in f]
        assert deltas[0]["choices"][0]["delta"].get("stream_id"), \
            "first data frame must carry stream_id meta (03-A1 #1)"
        text = "".join(
            c["choices"][0]["delta"].get("content") or ""
            for c in deltas if "delta" in c["choices"][0]
        )
        assert text == "hello world contract"
        types = [f.get("type") for f in frames if isinstance(f, dict)]
        assert "context_usage" in types, "context_usage frame required (03-A1 #15)"

    def test_resume_replays_buffer(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "resume replay check"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
        frames = collect(sse(r))
        sid = next(f["choices"][0]["delta"]["stream_id"] for f in frames
                   if f.get("choices", [{}])[0].get("delta", {}).get("stream_id"))
        rr = requests.post(f"{sap}/v1/chat/resume",
                           json={"stream_id": sid, "from_index": 0}, stream=True, timeout=30)
        assert rr.status_code == 200
        rr.encoding = "utf-8"
        replay = collect(sse(rr))
        text = "".join(f.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                       for f in replay if "choices" in f)
        assert "resume replay check" in text


class TestToolRoundTrip:
    def test_tool_call_and_result_frames(self, sap, mock_llm):
        args = {"path": "."}
        mock_llm.script([
            {"kind": "tool", "name": "list_files_tool_local", "arguments": args,
             "id": "call_t1"},
            {"kind": "text", "content": "tool finished summary"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "list dir"}]})
        frames = collect(sse(r))

        tool_frames = [f["choices"][0]["delta"]["tool_content"] for f in frames
                       if f.get("choices", [{}])[0].get("delta", {}).get("tool_content")]
        calls = [t for t in tool_frames if t.get("type") == "call"]
        results = [t for t in tool_frames if t.get("type") == "tool_result"]
        assert calls and calls[0]["title"] == "list_files_tool_local"
        assert json.loads(calls[0]["content"]) == args, \
            "call frame must carry the real arguments"
        assert results, "tool_result frame must follow the call"

        # second create must carry assistant.tool_calls with REAL arguments + tool result
        hist = mock_llm.history
        assert len(hist) == 2, "engine should issue a second create after tool result"
        msgs = hist[1]["messages"]
        assistant_tc = [m for m in msgs if m.get("role") == "assistant" and m.get("tool_calls")]
        assert assistant_tc, "round-2 history must include assistant tool_calls"
        fn_args = assistant_tc[-1]["tool_calls"][0]["function"]["arguments"]
        assert json.loads(fn_args) == args, \
            "in-round arguments must be real, never '{}'"
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert tool_msgs and "Total" in json.dumps(tool_msgs, ensure_ascii=False)

    def test_tool_arguments_survive_when_frontend_history_fakes_empty(self, sap, mock_llm):
        """Regression pin for audit C-1 family: what the server SENDS BACK in history is
        exactly what it will replay next round; server-side in-round must be correct."""
        mock_llm.script([
            {"kind": "tool", "name": "read_file_tool",
             "arguments": {"file_path": "nope-missing.txt"}, "id": "call_c1"},
            {"kind": "text", "content": "handled missing file"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "read it"}]})
        collect(sse(r))
        hist = mock_llm.history
        assert len(hist) == 2
        tc = [m for m in hist[1]["messages"] if m.get("role") == "assistant" and m.get("tool_calls")]
        assert tc and json.loads(tc[-1]["tool_calls"][0]["function"]["arguments"])["file_path"] == "nope-missing.txt"


class TestApprovalProtocol:
    def test_sensitive_tool_emits_approval_frame_and_halts(self, sap, mock_llm, tmp_path):
        marker = tmp_path / "sap-approval-must-not-run.txt"
        mock_llm.script([
            {"kind": "tool", "name": "shell_tool_local",
             "arguments": {"command": f'cmd /c echo MARK > "{marker}"'}, "id": "call_ap"},
        ])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "run this"}]})
        frames = collect(sse(r))
        tool_frames = [f["choices"][0]["delta"]["tool_content"] for f in frames
                       if f.get("choices", [{}])[0].get("delta", {}).get("tool_content")]
        approval = [t for t in tool_frames
                    if t.get("type") == "tool_result" and "approval_required" in (t.get("content") or "")]
        assert approval, "default mode must emit approval_required in tool_result (03-A1 #11)"
        payload = json.loads(approval[0]["content"])
        assert payload["type"] == "approval_required"
        assert payload["tool_name"] == "shell_tool_local"
        assert "sap-approval-must-not-run" in json.dumps(payload["tool_params"])
        import time as _t
        _t.sleep(1.5)
        assert not marker.exists(), "command must NOT have been executed server-side"
        assert frames[-1].get("__done__"), "stream ends after pending approval"
        assert mock_llm.calls == 1, "engine must not continue to a new round while approval pending"


class TestCancel:
    def test_cancel_halts_stream_and_resume_returns_410(self, sap, mock_llm):
        mock_llm.script([{"kind": "slow_text", "content": "x" * 400,
                          "chunks": 80, "delay": 0.15}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "slow"}]})
        sid = None
        seen = 0
        for ev in sse(r):
            if ev.get("__done__"):
                break
            d = ev.get("choices", [{}])[0].get("delta", {})
            if d.get("stream_id"):
                sid = d["stream_id"]
            if d.get("content"):
                seen += 1
            if seen == 2 and sid:
                c = requests.post(f"{sap}/v1/streams/cancel/{sid}", timeout=10)
                assert c.status_code == 200
                break
        assert sid
        rr = requests.post(f"{sap}/v1/chat/resume",
                           json={"stream_id": sid, "from_index": 0}, timeout=10)
        assert rr.status_code == 410, "cancelled stream resume must be 410 (B1 contract)"


class TestNonStreaming:
    def test_complete_path_returns_json(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "complete mode reply"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]}, stream=False)
        data = r.json()
        assert data["choices"][0]["message"]["content"] == "complete mode reply"
