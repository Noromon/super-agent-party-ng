# -*- coding: utf-8 -*-
"""M2 pins: SSRF gate (X-8) - loopback exempt, private/reserved blocked."""
import importlib.util
from pathlib import Path

import requests

from test_token import port_of, tok

_spec = importlib.util.spec_from_file_location(
    "net_guard_standalone", Path(__file__).resolve().parent.parent / "py" / "net_guard.py")
ng = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ng)


class TestNetGuardUnit:
    def test_ip_matrix(self):
        assert ng.ip_ok("127.0.0.1") is True
        assert ng.ip_ok("127.0.0.1", allow_loopback=False) is False
        assert ng.ip_ok("169.254.169.254") is False   # metadata / link-local
        assert ng.ip_ok("10.1.2.3") is False
        assert ng.ip_ok("192.168.1.1") is False
        assert ng.ip_ok("172.16.0.9") is False
        assert ng.ip_ok("8.8.8.8") is True
        assert ng.ip_ok("not-an-ip") is False

    def test_url_domain_resolution(self):
        assert ng.url_public_ok("https://example.com/x") is True
        assert ng.url_public_ok("http://127.0.0.1:3456/health") is True
        assert ng.url_public_ok("file:///etc/passwd") is False


class TestExtensionProxyGate:
    def H(self, sap):
        return {"X-SAP-Token": tok(sap)}

    def test_metadata_blocked(self, sap):
        r = requests.get(f"{sap}/extension_proxy",
                         params={"url": "http://169.254.169.254/latest/meta-data/"},
                         headers=self.H(sap), timeout=30)
        assert r.status_code == 403

    def test_private_blocked(self, sap):
        r = requests.get(f"{sap}/extension_proxy",
                         params={"url": "http://10.0.0.5/admin"},
                         headers=self.H(sap), timeout=30)
        assert r.status_code == 403

    def test_loopback_exempt(self, sap):
        r = requests.get(f"{sap}/extension_proxy",
                         params={"url": f"http://127.0.0.1:{port_of(sap)}/health"},
                         headers=self.H(sap), timeout=30)
        assert r.status_code != 403, "loopback must stay reachable (local ecosystem)"
