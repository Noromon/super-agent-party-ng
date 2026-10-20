# -*- coding: utf-8 -*-
"""Scriptable OpenAI-compatible mock LLM for contract tests (stdlib only)."""
import json
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _State:
    def __init__(self):
        self.lock = threading.Lock()
        self.script = deque()
        self.history = []
        self.calls = 0


class _Handler(BaseHTTPRequestHandler):
    state: _State = None

    def log_message(self, *args):
        pass

    def _json(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        st = self.state
        if self.path == "/__mock/history":
            with st.lock:
                self._json(200, st.history)
        elif self.path == "/__mock/calls":
            with st.lock:
                self._json(200, {"calls": st.calls})
        else:
            self._json(404, {"error": "unknown"})

    def do_POST(self):
        st = self.state
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path.startswith("/__mock/"):
            if self.path == "/__mock/script":
                with st.lock:
                    st.script = deque(body.get("script", []))
                    st.history = []
                    st.calls = 0
                self._json(200, {"ok": True})
            else:
                self._json(404, {"error": "unknown"})
            return
        if not self.path.endswith("/chat/completions"):
            self._json(404, {"error": "unknown"})
            return
        with st.lock:
            st.calls += 1
            st.history.append(body)
            scenario = st.script.popleft() if st.script else {"kind": "echo",
                                                              "content": "mock fallback reply"}
        if scenario.get("kind") == "error":
            self._json(500, {"error": {"message": scenario.get("message", "mock boom")}})
            return
        if not body.get("stream"):
            if scenario.get("kind") == "tool":
                args = scenario.get("arguments_raw") or json.dumps(
                    scenario.get("arguments", {}), ensure_ascii=False)
                msg = {"role": "assistant",
                       "content": scenario.get("assistant_content") or None,
                       "tool_calls": [{"id": scenario.get("id", "call_mock_ns"),
                                       "type": "function",
                                       "function": {"name": scenario.get("name", "mock_tool"),
                                                    "arguments": args}}]}
                finish = "tool_calls"
            else:
                msg = {"role": "assistant",
                       "content": scenario.get("content", scenario.get("text", "mock nonstream reply"))}
                finish = "stop"
            self._json(200, {
                "id": "chatcmpl-mock", "object": "chat.completion", "created": 0,
                "model": body.get("model", "mock"),
                "choices": [{"index": 0, "finish_reason": finish, "message": msg}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            })
            return
        self._stream(scenario)

    # ---------------- SSE ----------------
    def _start_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

    def _chunk(self, delta=None, finish=None):
        obj = {"id": "chatcmpl-mock", "object": "chat.completion.chunk", "created": 0,
               "model": "mock",
               "choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}]}
        self.wfile.write(f"data: {json.dumps(obj)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream(self, scenario):
        try:
            self._start_sse()
            kind = scenario.get("kind", "echo")
            self._chunk({"role": "assistant", "content": ""})
            if kind in ("text", "echo", "slow_text"):
                text = scenario.get("content", "mock reply")
                if kind == "slow_text":
                    n = scenario.get("chunks", 40)
                    delay = scenario.get("delay", 0.1)
                    piece = max(1, len(text) // n)
                    for i in range(0, len(text), piece):
                        self._chunk({"content": text[i:i + piece]})
                        time.sleep(delay)
                else:
                    mid = max(1, len(text) // 2)
                    self._chunk({"content": text[:mid]})
                    self._chunk({"content": text[mid:]})
                self._chunk(finish="stop")
            elif kind == "tool":
                args = scenario.get("arguments_raw") or json.dumps(
                    scenario.get("arguments", {}), ensure_ascii=False)
                tc_id = scenario.get("id", "call_mock_1")
                name = scenario.get("name", "mock_tool")
                a_id = scenario.get("assistant_content", "")
                if a_id:
                    self._chunk({"content": a_id})
                first = self._tool_delta(tc_id, name, args[: max(1, len(args) // 2)], first=True)
                self._chunk(first)
                if len(args) > 1:
                    self._chunk({"tool_calls": [{"index": 0,
                                                 "function": {"arguments": args[max(1, len(args) // 2):]}}]})
                self._chunk(finish="tool_calls")
            elif kind == "tools_interleave":
                # C-20 repro shape: two calls, one delta element per chunk,
                # indices alternating (llama.cpp/vLLM parallel-call streaming).
                heads = []
                for c in scenario.get("calls", []):
                    args = json.dumps(c.get("arguments", {}), ensure_ascii=False)
                    d = {"index": c.get("index"),
                         "id": c.get("id", f"call_{c.get('index')}_mock"),
                         "type": "function",
                         "function": {"name": c.get("name", "mock_tool"),
                                      "arguments": args[: max(1, len(args) // 2)]}}
                    heads.append((c, args, d))
                    self._chunk({"tool_calls": [d]})
                for c, args, _d in heads:
                    tail = args[max(1, len(args) // 2):]
                    if tail:
                        self._chunk({"tool_calls": [{"index": c.get("index"),
                                                     "function": {"arguments": tail}}]})
                self._chunk(finish="tool_calls")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _tool_delta(tc_id, name, args_head, first=False):
        d = {"index": 0}
        if first:
            d["id"] = tc_id
            d["type"] = "function"
            d["function"] = {"name": name, "arguments": args_head}
        else:
            d["function"] = {"arguments": args_head}
        return {"tool_calls": [d]}


class MockLLM:
    def __init__(self):
        self.state = _State()
        _Handler.state = self.state
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}/v1"

    def script(self, items):
        import requests
        requests.post(f"http://127.0.0.1:{self.port}/__mock/script",
                      json={"script": items}, timeout=10)

    @property
    def history(self):
        import requests
        return requests.get(f"http://127.0.0.1:{self.port}/__mock/history", timeout=10).json()

    @property
    def calls(self):
        import requests
        return requests.get(f"http://127.0.0.1:{self.port}/__mock/calls", timeout=10).json()["calls"]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
