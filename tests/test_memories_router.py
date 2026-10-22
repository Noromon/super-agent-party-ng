# -*- coding: utf-8 -*-
"""Memories router migration contract (R1, audit 09 item 6).

Memory CRUD + kb/mcp lifecycle + group-memory endpoints moved from
server.py to py/routers/memories.py. Checks stay behavioural (no memory
provider / kb / mcp configured in the test instance): validation models
must still reject bad bodies (422 proves the pydantic re-export resolved),
status endpoints must answer, nothing may 500.
"""
import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestMemoriesRouterContract:
    def test_memory_validation_models_reexported(self, sap):
        # missing required fields -> FastAPI 422, which requires the
        # MemoryAddBody / TextUpdate models to resolve in the new module
        r = requests.post(f"{sap}/memory/m-test", json={}, timeout=10,
                          headers=_h(sap))
        # S77: POST 体改 new_text 主+content 别名（双可选），空文本=端点自校验 400
        assert r.status_code == 400
        r = requests.post(f"{sap}/memory/m-test", json={"new_text": "x"},
                          timeout=10, headers=_h(sap))
        assert r.status_code == 404  # 配置不存在（证模型+路由已解析）
        r = requests.put(f"{sap}/memory/m-test/0", json={}, timeout=10,
                         headers=_h(sap))
        assert r.status_code == 422

    def test_memory_crud_routes_reachable(self, sap):
        r = requests.get(f"{sap}/memory/m-nonexistent", timeout=10, headers=_h(sap))
        assert r.status_code < 500
        # a lost route would answer FastAPI's default 404 body; the handler's
        # own not-found must carry its custom payload instead
        assert not (r.status_code == 404 and r.json().get("detail") == "Not Found")
        r = requests.delete(f"{sap}/memory/m-nonexistent/0", timeout=10,
                            headers=_h(sap))
        assert r.status_code < 500

    def test_kb_mcp_status_answer(self, sap):
        r = requests.get(f"{sap}/kb_status/kb-nope", timeout=10, headers=_h(sap))
        assert r.status_code < 500
        r = requests.get(f"{sap}/mcp_status/mcp-nope", timeout=10, headers=_h(sap))
        assert r.status_code < 500

    def test_kb_mcp_lifecycle_validation(self, sap):
        for path in ("/create_kb", "/create_mcp"):
            r = requests.post(f"{sap}{path}", json={}, timeout=15, headers=_h(sap))
            assert r.status_code in (400, 403, 422), f"{path} -> {r.status_code}"
        for path in ("/remove_kb", "/remove_mcp"):
            r = requests.post(f"{sap}{path}", json={}, timeout=15, headers=_h(sap))
            assert r.status_code < 500

    def test_group_memory_family_reachable(self, sap):
        r = requests.post(f"{sap}/api/group-memory/clear-group", json={},
                          timeout=15, headers=_h(sap))
        assert r.status_code < 500
        r = requests.post(f"{sap}/api/group-memory/clear-all", json={},
                          timeout=15, headers=_h(sap))
        assert r.status_code < 500
        r = requests.post(f"{sap}/api/group-memory/extract", json={},
                          timeout=15, headers=_h(sap))
        assert r.status_code < 500
