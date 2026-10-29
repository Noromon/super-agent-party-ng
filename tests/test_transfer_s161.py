# -*- coding: utf-8 -*-
"""S161：记忆/日记跨角色卡导入导出。

隔离红线（用户明令）：测试零触碰用户数据——日记目录/mem0 缓存目录全部 tmp，
get_mem0_instance/submit_memory_job/notification.emit 一律 fake，
绝不真调 embedding、绝不写 ~/.mem0/history.db。
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_system as diary_system  # noqa: E402
import py.get_setting as get_setting  # noqa: E402
import py.llm_gate as llm_gate  # noqa: E402
import py.notification_center as notification_center  # noqa: E402
import py.routers.transfer as transfer  # noqa: E402
from fastapi import HTTPException  # noqa: E402


class FakeM0:
    def __init__(self, store):
        self._store = store

    def get_all(self, user_id=None, limit=None):
        return {"results": [{"id": str(i), "memory": t}
                            for i, t in enumerate(self._store.get(user_id, []))]}

    def add(self, text, user_id=None, infer=False):
        assert infer is False  # 导入必须原文入库，不得走 LLM 抽取
        self._store.setdefault(user_id, []).append(text)


class Ctx:
    """一次测试的完整假环境。"""

    def __init__(self, monkeypatch, tmp_path, store=None, memories=None):
        self.store = store if store is not None else {}
        self.memories = memories if memories is not None else [
            {"id": "carda", "name": "角色A", "providerId": "p1"},
            {"id": "cardb", "name": "角色B", "providerId": "p1"},
        ]
        self.jobs = []
        self.events = []
        self.invalidated = []
        diary_dir = tmp_path / "diary"
        cache_dir = tmp_path / "memory_cache"
        diary_dir.mkdir()
        cache_dir.mkdir()
        # 初始 store 视作已在盘：建卡目录（覆盖导入 rmtree 后不存在→重建=空）
        for card in self.store:
            (cache_dir / card).mkdir(exist_ok=True)
        settings = {"memories": self.memories}

        async def _load():
            return settings

        monkeypatch.setattr(get_setting, "load_settings", _load)
        monkeypatch.setattr(get_setting, "MEMORY_CACHE_DIR", str(cache_dir))
        monkeypatch.setattr(diary_system, "DIARY_DIR", str(diary_dir))
        def _m0(mid, mem, st):
            if not (cache_dir / str(mid)).exists():
                self.store.pop(str(mid), None)  # 目录不在=索引已清，重建为空
            return FakeM0(self.store)

        monkeypatch.setattr(llm_gate, "get_mem0_instance", _m0)
        monkeypatch.setattr(llm_gate, "invalidate_memory_cache",
                            lambda mid: self.invalidated.append(mid))

        def _job(card, fn, name="mem0-add", debounce=0, wait_idle=True):
            self.jobs.append((card, name))
            fn()  # 同步执行 job 体（真机是队列异步）

        monkeypatch.setattr(llm_gate, "submit_memory_job", _job)
        monkeypatch.setattr(notification_center, "emit",
                            lambda cat, msg, **k: self.events.append((cat, msg)))
        self.cache_dir = cache_dir
        self.diary_dir = diary_dir


def _pack(sources):
    return {"sap_backup": 1, "version": 1, "exported_at": 1.0, "sources": sources}


def _seed_book(book_id, entries, character_id=None, name=""):
    asyncio.run(diary_system.save_diary_data(
        {"characterId": character_id, "characterName": name, "entries": entries}, book_id))


def _read_book(book_id):
    return asyncio.run(diary_system.load_diary_data(book_id))


# ---------- 导出 ----------

def test_export_pack_and_attachment(monkeypatch, tmp_path):
    Ctx(monkeypatch, tmp_path, store={"carda": ["喜欢猫", "住在北京"]})
    _seed_book("carda", [{"id": "e1", "time": "2026-01-01T10:00:00",
                          "type": "diary", "title": "", "content": "今天喂了猫"}],
               "carda", "角色A")
    res = asyncio.run(transfer.transfer_export(scope="all"))
    assert "attachment" in res.headers["content-disposition"]
    assert "sap-backup-" in res.headers["content-disposition"]
    pack = json.loads(res.body.decode("utf-8"))
    assert pack["sap_backup"] == 1 and pack["version"] == 1
    src = next(s for s in pack["sources"] if s["card_id"] == "carda")
    assert {m["text"] for m in src["memories"]} == {"喜欢猫", "住在北京"}
    assert src["diary_entries"][0]["id"] == "e1"
    # 全空卡（cardb 无记忆无日记）不进包
    assert all(s["card_id"] != "cardb" for s in pack["sources"])


def test_export_card_not_found(monkeypatch, tmp_path):
    Ctx(monkeypatch, tmp_path)
    try:
        asyncio.run(transfer.transfer_export(scope="card", card_id="nope"))
        assert False, "应 404"
    except HTTPException as e:
        assert e.status_code == 404


# ---------- target_stats ----------

def test_target_stats(monkeypatch, tmp_path):
    Ctx(monkeypatch, tmp_path, store={"cardb": ["a", "b"]})
    _seed_book("cardb", [{"id": "x", "time": "2026-01-01T00:00:00",
                          "type": "diary", "content": "c"}], "cardb", "角色B")
    st = asyncio.run(transfer.transfer_target_stats(card_id="cardb"))
    assert st == {"card_id": "cardb", "card_name": "角色B", "memories": 2, "diary": 1}


def test_target_stats_mem0_unavailable_returns_minus_one(monkeypatch, tmp_path):
    def _boom(mid, mem, st):
        raise RuntimeError("embedding down")
    Ctx(monkeypatch, tmp_path)
    monkeypatch.setattr(llm_gate, "get_mem0_instance", _boom)  # Ctx 之后再覆写
    st = asyncio.run(transfer.transfer_target_stats(card_id="cardb"))
    assert st["memories"] == -1


# ---------- 导入校验 ----------

def _bad_import(monkeypatch, tmp_path, req_kwargs, code):
    Ctx(monkeypatch, tmp_path)
    req = transfer.ImportReq(**req_kwargs)
    try:
        asyncio.run(transfer.transfer_import(req))
        assert False, "应拒绝"
    except HTTPException as e:
        assert e.status_code == code


def test_import_rejects_bad_pack(monkeypatch, tmp_path):
    _bad_import(monkeypatch, tmp_path,
                {"payload": {"hello": 1}, "target_card": "cardb"}, 400)


def test_import_rejects_unknown_target(monkeypatch, tmp_path):
    _bad_import(monkeypatch, tmp_path,
                {"payload": _pack([]), "target_card": "ghost"}, 404)


def test_import_rejects_bad_strategy(monkeypatch, tmp_path):
    _bad_import(monkeypatch, tmp_path,
                {"payload": _pack([]), "target_card": "cardb", "strategy": "yolo"}, 400)


# ---------- 跨卡合并导入 ----------

def test_import_merge_cross_card(monkeypatch, tmp_path):
    ctx = Ctx(monkeypatch, tmp_path, store={"cardb": ["已有记忆", "重复文本"]})
    _seed_book("cardb", [{"id": "dup", "time": "2026-01-01T00:00:00",
                          "type": "diary", "content": "重复条目"}], "cardb", "角色B")
    pack = _pack([{
        "card_id": "carda", "card_name": "角色A",
        "memories": [{"text": "重复文本"}, {"text": "新记忆一"}, {"text": "新记忆二"}],
        "diary_entries": [
            {"id": "dup", "time": "2026-01-01T00:00:00", "type": "diary", "content": "重复条目"},
            {"id": "n1", "time": "2026-02-02T00:00:00", "type": "diary", "content": "新日记"},
        ],
    }])
    req = transfer.ImportReq(payload=pack, target_card="cardb", strategy="merge")
    out = asyncio.run(transfer.transfer_import(req))
    assert out["success"] and out["memory_dup_skipped"] == 1 and out["memory_queued"] == 2
    assert out["diary_added"] == 1
    # 记忆落在目标卡 user_id=cardb（跨卡移植核心语义）
    assert set(ctx.store["cardb"]) == {"已有记忆", "重复文本", "新记忆一", "新记忆二"}
    # 日记按 id 去重 + 归属改写为目标卡
    book = _read_book("cardb")
    assert book["characterId"] == "cardb"
    assert [e["id"] for e in book["entries"]] == ["dup", "n1"]
    # 完成事件回报（通知中心）
    assert any("记忆导入完成" in m and "2/2" in m for _c, m in ctx.events)


def test_import_source_subset_selection(monkeypatch, tmp_path):
    ctx = Ctx(monkeypatch, tmp_path)
    pack = _pack([
        {"card_id": "carda", "card_name": "A", "memories": [{"text": "来自A"}], "diary_entries": []},
        {"card_id": "cardc", "card_name": "C", "memories": [{"text": "来自C"}], "diary_entries": []},
    ])
    req = transfer.ImportReq(payload=pack, target_card="cardb",
                             strategy="merge", source_ids=["cardc"])
    out = asyncio.run(transfer.transfer_import(req))
    assert out["memory_queued"] == 1
    assert "来自C" in ctx.store["cardb"] and "来自A" not in ctx.store["cardb"]


# ---------- 覆盖导入 ----------

def test_import_replace_wipes_store_dir_and_cache(monkeypatch, tmp_path):
    ctx = Ctx(monkeypatch, tmp_path, store={"cardb": ["旧记忆"]})
    _seed_book("cardb", [{"id": "old", "time": "2025-01-01T00:00:00",
                          "type": "diary", "content": "旧日记"}], "cardb", "角色B")
    # 预置真实存在的卡缓存目录（Ctx 已建）→ 覆盖导入必须删除它（tmp 内，非用户数据）
    card_dir = ctx.cache_dir / "cardb"
    (card_dir / "agent-party.faiss").write_bytes(b"fake-index")

    pack = _pack([{"card_id": "carda", "card_name": "A",
                   "memories": [{"text": "覆盖后记忆"}],
                   "diary_entries": [{"id": "nw", "time": "2026-03-03T00:00:00",
                                      "type": "diary", "content": "新日记"}]}])
    req = transfer.ImportReq(payload=pack, target_card="cardb", strategy="replace")
    out = asyncio.run(transfer.transfer_import(req))
    assert out["memory_queued"] == 1 and out["diary_added"] == 1
    assert ctx.invalidated == ["cardb"]          # 缓存必须失效
    assert not card_dir.exists()                 # 旧索引目录被清
    assert ctx.store["cardb"] == ["覆盖后记忆"]    # fake 重建后写入
    book = _read_book("cardb")
    assert [e["id"] for e in book["entries"]] == ["nw"]  # 日记整本替换


def test_import_truncation_reported(monkeypatch, tmp_path):
    Ctx(monkeypatch, tmp_path)
    entries = [{"id": f"e{i}", "time": f"2026-01-01T{i // 60:02d}:{i % 60:02d}:00",
                "type": "diary", "content": f"日记{i}"} for i in range(520)]
    pack = _pack([{"card_id": "carda", "card_name": "A", "memories": [],
                   "diary_entries": entries}])
    req = transfer.ImportReq(payload=pack, target_card="cardb", strategy="merge")
    out = asyncio.run(transfer.transfer_import(req))
    assert out["diary_truncated"] == 520 - diary_system.MAX_ENTRIES
    assert len(_read_book("cardb")["entries"]) == diary_system.MAX_ENTRIES
