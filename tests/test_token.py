# -*- coding: utf-8 -*-
"""M2 pins: loopback session-token kernel (X-1/X-2/X-10)."""
import socket
from urllib.parse import urlparse

import requests


def tok(sap):
    return (sap.data_dir / ".session_token").read_text(encoding="utf-8").strip()


def port_of(sap):
    return urlparse(str(sap)).port


class TestTokenKernel:
    def test_protected_endpoint_401_without_token(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "x"}, timeout=10)
        assert r.status_code == 401

    def test_with_header_token_passes(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "nope.txt"},
                         headers={"X-SAP-Token": tok(sap)}, timeout=10)
        assert r.status_code not in (401, 403)

    def test_forged_origin_rejected_even_with_token(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "x"},
                         headers={"X-SAP-Token": tok(sap),
                                  "Origin": "http://evil.example.com"}, timeout=10)
        assert r.status_code == 403

    def test_loopback_origin_with_token_ok(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "nope.txt"},
                         headers={"X-SAP-Token": tok(sap),
                                  "Origin": f"http://127.0.0.1:{port_of(sap)}"}, timeout=10)
        assert r.status_code not in (401, 403)

    def test_v1_stays_exempt(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "tokenless ok"}])
        r = requests.post(f"{sap}/v1/chat/completions",
                          json={"messages": [{"role": "user", "content": "hi"}],
                                "stream": False}, timeout=60)
        assert r.status_code == 200

    def test_session_token_bootstrap_sets_cookie(self, sap):
        r = requests.get(f"{sap}/session_token", timeout=10)
        assert r.status_code == 200
        assert r.json().get("token") == tok(sap)
        assert "sap_token=" in r.headers.get("set-cookie", "")

    def test_session_token_bootstrap_origin_guard(self, sap):
        r = requests.get(f"{sap}/session_token",
                         headers={"Origin": "http://evil.example.com"}, timeout=10)
        assert r.status_code == 403

    def test_ws_handshake_rejected_without_token(self, sap):
        p = port_of(sap)
        s = socket.create_connection(("127.0.0.1", p), timeout=10)
        try:
            s.sendall((f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                       "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            data = s.recv(400)
        finally:
            s.close()
        assert b"403" in data.split(b"\r\n", 1)[0], \
            "unauthenticated /ws handshake must be refused, got: " + repr(data[:80])

    def test_ws_handshake_with_query_token_upgrades(self, sap):
        p = port_of(sap)
        s = socket.create_connection(("127.0.0.1", p), timeout=10)
        try:
            s.sendall((f"GET /ws?sap_token={tok(sap)} HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                       "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            data = s.recv(400)
        finally:
            s.close()
        assert b"101" in data.split(b"\r\n", 1)[0], repr(data[:80])


def machine_tok(sap):
    return (sap.data_dir / ".machine_token").read_text(encoding="utf-8").strip()


def raw_ws_handshake(sap, path="/ws", extra_headers="", query=""):
    p = port_of(sap)
    s = socket.create_connection(("127.0.0.1", p), timeout=10)
    try:
        s.sendall((f"GET {path}{query} HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                   f"{extra_headers}"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        return s.recv(400)
    finally:
        s.close()


class TestWsHeaderAuth:
    """Handshake must accept the X-SAP-Token header (xmpp-bridge style)."""

    def test_handshake_with_session_header(self, sap):
        data = raw_ws_handshake(sap, extra_headers=f"X-SAP-Token: {tok(sap)}\r\n")
        assert b"101" in data.split(b"\r\n", 1)[0], repr(data[:80])

    def test_handshake_with_machine_header(self, sap):
        data = raw_ws_handshake(sap, extra_headers=f"X-SAP-Token: {machine_tok(sap)}\r\n")
        assert b"101" in data.split(b"\r\n", 1)[0], repr(data[:80])

    def test_handshake_with_bad_header_still_rejected(self, sap):
        data = raw_ws_handshake(sap, extra_headers=f"X-SAP-Token: {machine_tok(sap)}x\r\n")
        assert b"403" in data.split(b"\r\n", 1)[0], repr(data[:80])


class TestMachineToken:
    def test_http_with_machine_token_header(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "nope.txt"},
                         headers={"X-SAP-Token": machine_tok(sap)}, timeout=10)
        assert r.status_code not in (401, 403)

    def test_wrong_token_still_401(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "x"},
                         headers={"X-SAP-Token": machine_tok(sap) + "x"}, timeout=10)
        assert r.status_code == 401

    def test_ws_handshake_with_machine_token(self, sap):
        p = port_of(sap)
        s = socket.create_connection(("127.0.0.1", p), timeout=10)
        try:
            s.sendall((f"GET /ws?sap_token={machine_tok(sap)} HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                       "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                       "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                       "Sec-WebSocket-Version: 13\r\n\r\n").encode())
            data = s.recv(400)
        finally:
            s.close()
        assert b"101" in data.split(b"\r\n", 1)[0], repr(data[:80])

    def test_machine_token_persisted_stable(self, sap):
        m1 = machine_tok(sap)
        assert len(m1) >= 20 and m1 != tok(sap)
