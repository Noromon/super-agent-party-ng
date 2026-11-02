# -*- coding: utf-8 -*-
"""S190 rows-first：conversation_rows 行为会话权威源；blob 降级为导出/回退。

覆盖：delta 行级写（不触 blob）、新会话插队首、groups meta 权威、行空回退
blob、旧 schema(ord 缺列)升级迁移、turn_log 前缀 diff（增长/重写/缩短）。
"""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def load_tl(tmp_path):
    import importlib.util
    import os
    os.environ["SAP_DATA_DIR"] = str(tmp_path)
    name = f"turn_log_standalone_{abs(hash(str(tmp_path)))}"
    spec = importlib.util.spec_from_file_location(
        name, _ROOT / "py" / "turn_log.py")
    tl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tl)
    return tl


def _conv(cid, title="t"):
    return {"id": cid, "title": title, "messages": [{"role": "user", "content": cid}]}


def test_delta_rows_only_never_touches_blob(tmp_path):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)

    async def _go():
        await gs.save_covs_delta_rows([_conv("A")])
        await gs.save_covs_delta_rows([_conv("B")])
        covs = await gs.load_covs()
        return [c["id"] for c in covs["conversations"]]

    ids = asyncio.run(_go())
    assert ids == ["B", "A"]  # 新会话插队首（与旧 blob 合并语义一致）
    # blob 从未被写过
    con = sqlite3.connect(tmp_path / "conversations.db")
    row = con.execute("SELECT COUNT(*) FROM settings WHERE id=1").fetchone()[0]
    con.close()
    assert row == 0


def test_delta_update_keeps_position(tmp_path):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)

    async def _go():
        await gs.save_covs_delta_rows([_conv("A"), _conv("B")])
        await gs.save_covs_delta_rows([dict(_conv("A"), title="A2")])
        covs = await gs.load_covs()
        return [(c["id"], c["title"]) for c in covs["conversations"]]

    out = asyncio.run(_go())
    assert [x[0] for x in out] == ["A", "B"]  # A 原位更新不换位
    assert out[0][1] == "A2"


def test_groups_meta_authoritative(tmp_path):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)

    async def _go():
        await gs.save_covs_delta_rows([_conv("A")], groups=[{"id": "g1"}])
        return await gs.load_covs()

    covs = asyncio.run(_go())
    assert covs["conversationGroups"] == [{"id": "g1"}]


def test_load_falls_back_to_blob_when_rows_empty(tmp_path):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)

    async def _go():
        await gs.init_covs_db()
        con = sqlite3.connect(tmp_path / "conversations.db")
        con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
                    (json.dumps({"conversations": [_conv("Z")]}),))
        con.commit()
        con.close()
        return await gs.load_covs()

    covs = asyncio.run(_go())
    assert [c["id"] for c in covs["conversations"]] == ["Z"]


def test_legacy_schema_upgrade_migrates_ord(tmp_path):
    """旧库：conversation_rows 无 ord 列（S190 前 schema）。新代码首次 init
    必须 ALTER + 按 blob 顺序补 ord，load 保序，delta 新会话仍能插队首。"""
    from test_row_store import load_gs
    db = tmp_path / "conversations.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    con.execute("CREATE TABLE conversation_rows (conv_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at REAL)")
    convs = [_conv("A", "a"), _conv("B", "b"), _conv("C", "c")]
    con.execute("INSERT INTO settings (id, data) VALUES (1, ?)",
                (json.dumps({"conversations": convs}),))
    for c in convs:
        con.execute("INSERT INTO conversation_rows (conv_id, data, updated_at) VALUES (?, ?, 1)",
                    (c["id"], json.dumps(c)))
    con.commit()
    con.close()

    gs = load_gs(tmp_path)

    async def _go():
        await gs.save_covs_delta_rows([_conv("NEW")])
        covs = await gs.load_covs()
        return [c["id"] for c in covs["conversations"]]

    assert asyncio.run(_go()) == ["NEW", "A", "B", "C"]


# ---------------- turn_log prefix diff ----------------

def _msgs(*roles):
    return [{"role": r, "content": f"m{i}"} for i, r in enumerate(roles)]


def test_turnlog_grow_shrink_rebuild(tmp_path):
    tl = load_tl(tmp_path)
    tl.COVS_PATH = str(tmp_path / "c.db")
    cid = "c1"
    db_file = str(tmp_path / "c.db")

    def seqs():
        return [r[0] for r in sqlite3.connect(db_file).execute(
            "SELECT seq FROM turn_log WHERE conversation_id=? ORDER BY seq", (cid,)).fetchall()]

    def msgs_of():
        return [r for r in sqlite3.connect(db_file).execute(
            "SELECT seq, msg FROM turn_log WHERE conversation_id=? ORDER BY seq", (cid,)).fetchall()]

    async def _all():
        con = sqlite3.connect(db_file)
        con.execute("CREATE TABLE turn_log (conversation_id TEXT, seq INTEGER, msg TEXT, created_at REAL, PRIMARY KEY (conversation_id, seq))")
        con.commit()
        con.close()
        # 增长
        assert await tl.shadow_append(cid, _msgs("u", "a")) == 2
        assert await tl.shadow_append(cid, _msgs("u", "a", "u", "a")) == 2
        # 相同 = 零写（幂等）
        assert await tl.shadow_append(cid, _msgs("u", "a", "u", "a")) == 0
        # 缩短（链重建/sanitize 后）= 删尾，不再冻结后续写入
        await tl.shadow_append(cid, _msgs("u"))
        assert seqs() == [0]
        # 缩短后再增长 = 恢复追加（旧高水位逻辑在此永久静默——本次修复的核心场景）
        assert await tl.shadow_append(cid, _msgs("u", "a")) == 1
        # 头部即不同（全重建）= 全重写
        await tl.shadow_append(cid, _msgs("x", "y"))
        return msgs_of()

    rows = asyncio.run(_all())
    assert [r[0] for r in rows] == [0, 1]
    assert '"x"' in rows[0][1] or "x" in rows[0][1]
    assert "y" in rows[1][1]
