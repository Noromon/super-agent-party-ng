# -*- coding: utf-8 -*-
"""Tasks router migration contract (R1, audit 09 item 6).

Background-task and stream-control endpoints moved from server.py to
py/routers/tasks.py. /v1 stays token-exempt by design. Deep resume/cancel
behaviour is already covered by test_contract_sse (runs through these
routes end-to-end); here we pin route presence, model validation and the
unknown-id guard paths.
"""
import requests


class TestTasksRouterContract:
    def test_tasks_list_answers(self, sap):
        r = requests.get(f"{sap}/v1/tasks/list", timeout=10)
        assert r.status_code == 200

    def test_moved_models_still_validate(self, sap):
        r = requests.post(f"{sap}/v1/tasks/create", json={}, timeout=10)
        assert r.status_code == 422
        r = requests.post(f"{sap}/v1/chat/resume", json={}, timeout=10)
        assert r.status_code == 422

    def test_unknown_id_guards(self, sap):
        r = requests.post(f"{sap}/v1/tasks/cancel/nope", timeout=10)
        assert r.status_code < 500
        r = requests.delete(f"{sap}/v1/tasks/nope", timeout=10)
        assert r.status_code < 500
        assert not (r.status_code == 404 and r.json().get("detail") == "Not Found")
        r = requests.post(f"{sap}/v1/streams/cancel/nope", timeout=10)
        assert r.status_code < 500
        assert not (r.status_code == 404 and r.json().get("detail") == "Not Found")
