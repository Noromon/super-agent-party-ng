# -*- coding: utf-8 -*-
"""S77: mem0 终态套件行为测（dims 护栏 / pkl 迁移修复 / 清洗 / CRUD 终态契约）。

不启真实 mem0（llm_gate.get_mem0_instance 以假 m0 顶替）；dims 护栏用真实
小 faiss 索引（纯 CPU 毫秒级）。
"""
import asyncio
import io
import os
import pickle
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_mem0_crud_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import py.llm_gate as llm_gate  # noqa: E402
import py.routers.memories as mem_ep  # noqa: E402
from py.routers.memories import MemoryAddBody, TextUpdate  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def _cache_to(tmp_path, monkeypatch):
    import py.get_setting as gs
    monkeypatch.setattr(gs, "MEMORY_CACHE_DIR", str(tmp_path))


# ---------------- llm_gate 单点护栏 ----------------

def test_effective_dims_uses_faiss_actual(tmp_path, monkeypatch):
    import faiss
    _cache_to(tmp_path, monkeypatch)
    mid = "s77-dims"
    (tmp_path / mid).mkdir()
    faiss.write_index(faiss.IndexFlatL2(8), str(tmp_path / mid / "agent-party.faiss"))
    assert llm_gate.effective_dims(mid, 1024) == 8
    assert llm_gate.effective_dims(mid, 1024) == 8          # 缓存路径
    assert llm_gate.effective_dims("s77-ghost", 1024) == 1024  # 无索引信 settings


def test_ensure_pkl_migrates_legacy_dict(tmp_path, monkeypatch):
    import faiss
    _cache_to(tmp_path, monkeypatch)
    mid = "s77-mig"
    (tmp_path / mid).mkdir()
    faiss.write_index(faiss.IndexFlatL2(4), str(tmp_path / mid / "agent-party.faiss"))
    legacy = {"u1": {"data": "hello", "created_at": "2026-01-01T00:00:00",
                     "timetamp": "2026-01-02"}}
    ppath = tmp_path / mid / "agent-party.pkl"
    with open(ppath, "wb") as f:
        pickle.dump(legacy, f)
    llm_gate.ensure_pkl_compatible(mid)
    with open(ppath, "rb") as f:
        raw = pickle.load(f)
    assert isinstance(raw, tuple) and len(raw) == 2
    docstore, idx2id = raw
    assert idx2id == {0: "u1"}
    assert docstore["u1"]["user_id"] == mid
    assert docstore["u1"]["data"] == "hello"
    assert docstore["u1"]["updated_at"] == "2026-01-02"
    assert docstore["u1"]["hash"]


def test_ensure_pkl_repairs_missing_user_id(tmp_path, monkeypatch):
    import faiss
    _cache_to(tmp_path, monkeypatch)
    mid = "s77-rep"
    (tmp_path / mid).mkdir()
    faiss.write_index(faiss.IndexFlatL2(4), str(tmp_path / mid / "agent-party.faiss"))
    docstore = {"u1": {"data": "x", "created_at": "c1", "updated_at": "c2"}}
    ppath = tmp_path / mid / "agent-party.pkl"
    with open(ppath, "wb") as f:
        pickle.dump((docstore, {0: "u1"}), f)
    llm_gate.ensure_pkl_compatible(mid)
    with open(ppath, "rb") as f:
        doc, _ = pickle.load(f)
    assert doc["u1"]["user_id"] == mid
    assert doc["u1"]["updated_at"] == "c2"


def test_ensure_pkl_tolerates_corrupt(tmp_path, monkeypatch):
    _cache_to(tmp_path, monkeypatch)
    mid = "s77-bad"
    (tmp_path / mid).mkdir()
    ppath = tmp_path / mid / "agent-party.pkl"
    ppath.write_bytes(b"\x80\x04 garbage")
    llm_gate.ensure_pkl_compatible(mid)          # 不抛 = 通过（只记 warning）
    assert ppath.read_bytes() == b"\x80\x04 garbage"


def test_sanitize_card_strings():
    mem = {"name": "ci\x01ta", "description": "a\x0b\x1fb",
           "alternateGreetings": ["o\x00k"], "personality": None, "count": 5}
    llm_gate.sanitize_card_strings(mem)
    assert mem["name"] == "cita" and mem["description"] == "ab"
    assert mem["alternateGreetings"] == ["ok"]
    assert mem["personality"] is None and mem["count"] == 5
    llm_gate.sanitize_card_strings(None)          # 容忍非 dict


def test_mem0_instance_single_point_guards():
    import inspect
    src = inspect.getsource(llm_gate.get_mem0_instance)
    assert "sanitize_card_strings(" in src
    assert "effective_dims(" in src and "ensure_pkl_compatible(" in src
    assert "eff_dims" in src                      # 缓存键/配置用实际维度而非 stored


# ---------------- CRUD 端点终态契约（假 m0） ----------------

class _FakeM0:
    def __init__(self):
        self.calls = []

    def get_all(self, user_id=None, limit=None):
        self.calls.append(("get_all", user_id, limit))
        return {"results": [
            {"id": "u1", "memory": "m1", "created_at": "2026-01-01T08:00:00+08:00",
             "updated_at": None},
            {"id": "u2", "memory": "m2", "created_at": "2026-01-02T08:00:00+08:00"},
        ]}

    def add(self, text, user_id=None, infer=None):
        self.calls.append(("add", text, user_id, infer))

    def update(self, memory_id=None, data=None):
        self.calls.append(("update", memory_id, data))

    def delete(self, memory_id=None):
        self.calls.append(("delete", memory_id))


@pytest.fixture()
def fake_env(monkeypatch):
    fake = _FakeM0()
    monkeypatch.setattr(llm_gate, "get_mem0_instance", lambda mid, cm, st: fake)

    async def fake_load():
        return {"memories": [{"id": "mid1", "providerId": "p1"}],
                "model": "m", "api_key": "k", "base_url": ""}
    monkeypatch.setattr(mem_ep, "load_settings", fake_load)
    return fake


def test_get_memory_flat(fake_env):
    flat = asyncio.run(mem_ep.read_memory("mid1"))
    assert [r["idx"] for r in flat] == [0, 1]
    assert flat[0]["uuid"] == "u1" and flat[0]["text"] == "m1"
    # updated_at None → or 回退 created_at（7af53da0）
    assert flat[0]["timetamp"] == flat[0]["created_at"]
    assert fake_env.calls[0][0] == "get_all"


def test_get_memory_accepts_plain_list(monkeypatch):
    class _ListM0:
        def get_all(self, user_id=None, limit=None):
            return [{"id": "a", "memory": "x", "created_at": ""}]
    monkeypatch.setattr(llm_gate, "get_mem0_instance",
                        lambda mid, cm, st: _ListM0())

    async def fake_load():
        return {"memories": [{"id": "mid1", "providerId": "p"}]}
    monkeypatch.setattr(mem_ep, "load_settings", fake_load)
    flat = asyncio.run(mem_ep.read_memory("mid1"))
    assert flat[0]["uuid"] == "a" and flat[0]["text"] == "x"


def test_get_memory_validation(fake_env, monkeypatch):
    with pytest.raises(HTTPException) as e:
        asyncio.run(mem_ep.read_memory("nope"))       # 配置不存在
    assert e.value.status_code == 404

    async def noprovider():
        return {"memories": [{"id": "mid1"}]}
    monkeypatch.setattr(mem_ep, "load_settings", noprovider)
    with pytest.raises(HTTPException) as e:
        asyncio.run(mem_ep.read_memory("mid1"))       # 无 embedding provider
    assert e.value.status_code == 400


def test_post_prefers_new_text_with_content_alias(fake_env):
    asyncio.run(mem_ep.add_memory_text("mid1", MemoryAddBody(new_text="A", content="B")))
    assert ("add", "A", "mid1", False) in fake_env.calls
    asyncio.run(mem_ep.add_memory_text("mid1", MemoryAddBody(content="C")))
    assert ("add", "C", "mid1", False) in fake_env.calls
    with pytest.raises(HTTPException):
        asyncio.run(mem_ep.add_memory_text("mid1", MemoryAddBody()))


def test_put_delete_uuid(fake_env):
    asyncio.run(mem_ep.update_text("mid1", "u42", TextUpdate(new_text="z")))
    assert ("update", "u42", "z") in fake_env.calls
    asyncio.run(mem_ep.delete_text("mid1", "u42"))
    assert ("delete", "u42") in fake_env.calls


def test_crud_lock_and_retired_direct_faiss():
    src = _read("py/routers/memories.py")
    assert "with _m0_crud_lock:" in src
    assert "load_index_and_meta" not in src and "IndexFlatL2" not in src
    import py.memory_store as ms
    assert hasattr(ms, "fmt_iso8605_to_local")
    assert not hasattr(ms, "load_index_and_meta")
    assert "from py.memory_store import" not in _read("server.py")


# ---------------- 前端/契约 pins ----------------

def test_s77_frontend_pins():
    js = _read("static/js/methods/94_vector_logs.js")
    assert "editRowUuid" in js and "new_text" in js and "editRowIdx" not in js
    data = _read("static/js/data/60_cards_options.js")
    assert "newVectorText: ''" in data and "editRowUuid: ''" in data
    role = _read("static/templates/page_role.html")
    assert "addMemoryEntry" in role and "deleteVectorRow($index)" in role
    assert "deleteVectorRow(vectorTable[$index].idx)" not in role
    io_js = _read("static/js/methods/70_memory_io.js")
    assert "_sanitizeCardText" in io_js and "const s = this._sanitizeCardText.bind(this)" in io_js
    pm = _read("static/js/methods/32_persona_memory.js")
    assert "embeddingDimsChanged" in pm
    for loc in ("zh-CN", "en-US"):
        s = _read(f"static/js/locales/{loc}.js")
        for k in ("editText", "addMemoryEntry", "embeddingDimsChanged",
                  "existingMemoriesPreserved"):
            assert k in s, (loc, k)
