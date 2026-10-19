# -*- coding: utf-8 -*-
"""M2 acceptance matrix: the four runtime-proven S1/S2 exploits from
docs/AUDIT/07-verification.md (audit_p3.py, 2026-10-18) must now REJECT.
One test per audit finding; run output archived as M2 evidence.
"""
import socket

import requests

from test_token import port_of, tok


def raw_ws_handshake(sap, path="/ws", extra_headers="", with_token=False):
    p = port_of(sap)
    s = socket.create_connection(("127.0.0.1", p), timeout=10)
    try:
        tokline = f"?sap_token={tok(sap)}" if with_token else ""
        s.sendall((f"GET {path}{tokline} HTTP/1.1\r\nHost: 127.0.0.1:{p}\r\n"
                   f"{extra_headers}"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                   "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        return s.recv(600)
    finally:
        s.close()


class TestAuditP3Regression:
    def test_X1_execute_tool_manually_now_needs_auth(self, sap):
        # was: 200 + tool executed with zero approval
        r = requests.post(f"{sap}/execute_tool_manually",
                          json={"tool_name": "read_file_tool_local",
                                "tool_params": {"path": "x"},
                                "approval_type": "once"}, timeout=15)
        assert r.status_code == 401

    def test_X2_ws_hostile_origin_no_longer_accepted(self, sap):
        # was: handshake accepted + first frame leaked full settings (~27.9MB)
        data = raw_ws_handshake(sap,
                                extra_headers="Origin: https://evil.example\r\n")
        first = data.split(b"\r\n", 1)[0]
        assert b"101" not in first, repr(data[:100])
        assert b"403" in first

    def test_X5_wildcard_cors_gone_on_internal_api(self, sap):
        # was: ACAO * + credentials on everything, OPTIONS 200 for any origin
        r = requests.get(f"{sap}/health", headers={"Origin": "https://evil.example"},
                         timeout=15)
        assert r.headers.get("access-control-allow-origin") is None
        o = requests.options(f"{sap}/execute_tool_manually",
                             headers={"Origin": "https://evil.example"}, timeout=15)
        assert o.status_code in (401, 403)
        assert o.headers.get("access-control-allow-origin") is None

    def test_X6_arbitrary_file_read_double_fenced(self, sap):
        # was: 200 + 882 bytes of C:\Windows\win.ini with no auth at all
        r = requests.get(f"{sap}/get_file_content",
                         params={"file_url": r"C:\Windows\win.ini"}, timeout=15)
        assert r.status_code == 401  # fence 1: session token
        r2 = requests.get(f"{sap}/get_file_content",
                          params={"file_url": r"C:\Windows\win.ini"},
                          headers={"X-SAP-Token": tok(sap)}, timeout=15)
        assert r2.status_code == 403  # fence 2: realpath containment
        assert "forbidden" not in r2.text.lower() or "Microsoft" not in r2.text
