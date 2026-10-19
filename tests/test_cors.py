# -*- coding: utf-8 -*-
"""M2 pins: CORS tightened to /v1+/mcp; DNS-rebinding Host guard (X-5)."""
import requests

from test_token import port_of, tok


class TestCorsAndHost:
    def test_v1_options_preflight_ok(self, sap):
        r = requests.options(f"{sap}/v1/chat/completions", timeout=10)
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_v1_response_carries_cors_header(self, sap, mock_llm):
        mock_llm.script([{"kind": "text", "content": "cors"}])
        r = requests.post(f"{sap}/v1/chat/completions",
                          json={"messages": [{"role": "user", "content": "x"}],
                                "stream": False}, timeout=60)
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "*"

    def test_internal_api_has_no_cors_header(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "x"},
                         headers={"X-SAP-Token": tok(sap)}, timeout=10)
        assert r.headers.get("access-control-allow-origin") is None

    def test_rebound_host_rejected(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "x"},
                         headers={"X-SAP-Token": tok(sap),
                                  "Host": "evil.example.com"}, timeout=10)
        assert r.status_code == 403

    def test_ip_host_allowed(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "nope.txt"},
                         headers={"X-SAP-Token": tok(sap),
                                  "Host": f"192.168.9.9:{port_of(sap)}"}, timeout=10)
        assert r.status_code not in (401, 403)

    def test_localhost_host_allowed(self, sap):
        r = requests.get(f"{sap}/get_file_content", params={"file_url": "nope.txt"},
                         headers={"X-SAP-Token": tok(sap),
                                  "Host": f"localhost:{port_of(sap)}"}, timeout=10)
        assert r.status_code not in (401, 403)
