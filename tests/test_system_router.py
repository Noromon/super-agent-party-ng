# -*- coding: utf-8 -*-
"""System router migration contract (R1, audit 09 item 6).

DANGER endpoints are deliberately NOT exercised over HTTP: /sys/shutdown
kills the server, /start_ChromeMCP can launch a browser process, the start_*
bridges attempt real connections and /update_storage rewrites storage paths.
Those are pinned statically (route decorators present in the new module);
only idempotent read/stop endpoints are called live.
"""
import os

import requests

from test_token import tok

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYSTEM_SRC = open(os.path.join(ROOT, "py", "routers", "system.py"),
                  encoding="utf-8").read()


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestSystemRouterContract:
    def test_all_routes_present_in_module(self):
        for path in ("/start_HA", "/stop_HA", "/start_ChromeMCP",
                     "/stop_ChromeMCP", "/start_sql", "/stop_sql",
                     "/sys/shutdown", "/api/update_proxy", "/api/ip",
                     "/update_storage", "/cur_language"):
            assert '"%s"' % path in SYSTEM_SRC, path
        assert "@app." not in SYSTEM_SRC

    def test_safe_live_endpoints(self, sap):
        r = requests.get(f"{sap}/api/ip", timeout=10, headers=_h(sap))
        assert r.status_code == 200
        r = requests.get(f"{sap}/cur_language", timeout=10, headers=_h(sap))
        assert r.status_code == 200

    def test_stop_endpoints_idempotent(self, sap):
        for path in ("/stop_HA", "/stop_ChromeMCP", "/stop_sql"):
            r = requests.get(f"{sap}{path}", timeout=20, headers=_h(sap))
            assert r.status_code == 200, f"{path} -> {r.status_code}"
