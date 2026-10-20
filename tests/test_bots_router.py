# -*- coding: utf-8 -*-
"""Bots router migration contract (R1, audit 09 item 6).

The IM bot control endpoints moved from server.py to py/routers/bots.py.
No bot credentials exist in the test instance, so checks stay behavioural:
status endpoints answer 200 with a payload, control endpoints reach the
handler (never 404), everything authenticated (401 must not fake a pass).
"""
import requests

from test_token import tok

PLATFORMS = ["qq", "wechat", "feishu", "dingtalk", "discord", "slack",
             "telegram", "xmpp", "wecom"]


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestBotsRouterContract:
    def test_status_endpoints_answer(self, sap):
        for p in PLATFORMS:
            r = requests.get(f"{sap}/{p}_bot_status", timeout=10, headers=_h(sap))
            assert r.status_code == 200, f"{p}_bot_status -> {r.status_code}"
            assert r.json() is not None

    def test_control_endpoints_reach_handler(self, sap):
        for p in PLATFORMS:
            for verb, path in (("post", f"/start_{p}_bot"),
                               ("post", f"/stop_{p}_bot"),
                               ("post", f"/reload_{p}_bot")):
                r = requests.request(verb, f"{sap}{path}", timeout=20,
                                     headers=_h(sap))
                assert r.status_code != 404, f"{path} lost its route"
                assert r.status_code < 500, f"{path} -> {r.status_code}"

    def test_xmpp_cert_flow_alive(self, sap):
        r = requests.get(f"{sap}/xmpp_cert_pending", timeout=10, headers=_h(sap))
        assert r.status_code == 200
        # empty key hits the validation branch (400): proof the handler runs
        # (a valid-but-unknown key would return the handler's own 404, which
        # is indistinguishable from a lost route)
        r = requests.post(f"{sap}/xmpp_cert_decision",
                          json={"key": "", "decision": "reject"},
                          timeout=10, headers=_h(sap))
        assert r.status_code == 400
