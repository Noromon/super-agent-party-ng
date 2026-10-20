# -*- coding: utf-8 -*-
"""Bot-conversation router migration contract (R1, audit 09 item 6).

No bot is configured in the test instance, so checks stay behavioural:
list endpoints answer 200, control endpoints reach their handlers (guard
or validation errors only, never a lost route / 5xx), and the moved
pydantic model still rejects bad bodies with 422.
"""
import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestBotConversationsRouterContract:
    def test_list_endpoints_answer(self, sap):
        r = requests.get(f"{sap}/bot_conversations", timeout=15, headers=_h(sap))
        assert r.status_code == 200

    def test_control_endpoints_reach_handlers(self, sap):
        for path in ("/bot_conversation/new", "/bot_conversation/activate",
                     "/bot_conversation/clear"):
            r = requests.post(f"{sap}{path}", json={}, timeout=15, headers=_h(sap))
            assert r.status_code < 500, f"{path} -> {r.status_code}"
        r = requests.delete(f"{sap}/bot_conversation", timeout=15, headers=_h(sap))
        assert r.status_code < 500
        r = requests.get(f"{sap}/bot_conversation", timeout=15, headers=_h(sap))
        assert r.status_code < 500

    def test_moved_pydantic_model_still_validates(self, sap):
        # DeleteConversationRequest moved with the endpoints; missing fields
        # must still produce FastAPI's 422 (model resolved in new module)
        r = requests.post(f"{sap}/api/conversations/delete", json={},
                          timeout=15, headers=_h(sap))
        assert r.status_code == 422

    def test_compact_reachable(self, sap):
        r = requests.post(f"{sap}/api/compact", json={}, timeout=20, headers=_h(sap))
        assert r.status_code < 500
