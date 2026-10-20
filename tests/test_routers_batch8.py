# -*- coding: utf-8 -*-
"""Batch-8 routers contract (R1, audit 09 item 6).

agents/workflows/status routers moved out of server.py. backup endpoints run
the real snapshot loop inside the sandboxed SAP_DATA_DIR; the risky /v1/models
listing only asserts non-5xx; validation guards prove the moved models.
"""
import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestAgentsRouterContract:
    def test_agents_list(self, sap):
        r = requests.get(f"{sap}/v1/agents", timeout=10)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_agent_controls_reachable(self, sap):
        r = requests.post(f"{sap}/remove_agent", json={}, timeout=10, headers=_h(sap))
        assert r.status_code < 500, r.status_code
        # /a2a with no url hits the handler's own catch-all (legacy behaviour:
        # JSON body with an error field, both pre- and post-migration)
        r = requests.post(f"{sap}/a2a", json={}, timeout=10, headers=_h(sap))
        assert r.status_code in (400, 500) and "error" in r.json(), r.status_code


class TestWorkflowsRouterContract:
    def test_sticker_pack_validation(self, sap):
        # files/pack_name/descriptions are required Form fields -> 422
        r = requests.post(f"{sap}/create_sticker_pack", json={}, timeout=10,
                          headers=_h(sap))
        assert r.status_code == 422

    def test_workflow_guards(self, sap):
        r = requests.post(f"{sap}/add_workflow", json={}, timeout=15, headers=_h(sap))
        assert r.status_code < 500, r.status_code
        r = requests.delete(f"{sap}/delete_workflow/nope.json", timeout=10,
                            headers=_h(sap))
        assert r.status_code < 500
        assert not (r.status_code == 404 and r.json().get("detail") == "Not Found")


class TestStatusRouterContract:
    def test_backup_snapshot_roundtrip(self, sap):
        r = requests.post(f"{sap}/api/backup/now", timeout=60, headers=_h(sap))
        assert r.status_code == 200, r.text[:200]
        r = requests.get(f"{sap}/api/backup/list", timeout=15, headers=_h(sap))
        assert r.status_code == 200
        names = [s.get("name") for s in r.json().get("snapshots", [])]
        assert names, "backup/now must produce a visible snapshot"
        r = requests.post(f"{sap}/api/backup/verify", json={"name": names[0]},
                          timeout=30, headers=_h(sap))
        assert r.status_code == 200, r.text[:200]

    def test_status_endpoints_answer(self, sap):
        for path in ("/api/acpx/status", "/vrm_config"):
            r = requests.get(f"{sap}{path}", timeout=15, headers=_h(sap))
            assert r.status_code == 200, f"{path} -> {r.status_code}"

    def test_provider_model_listing_reachable(self, sap):
        r = requests.get(f"{sap}/v1/models", timeout=20)
        assert r.status_code < 500, r.status_code
        r = requests.post(f"{sap}/v1/providers/models", json={}, timeout=20,
                          headers=_h(sap))
        assert r.status_code == 422   # ProviderModelRequest moved with it
