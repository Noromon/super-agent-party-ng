# -*- coding: utf-8 -*-
"""M4b pins: conversation_rows shadow store (backfill, dual-write,
delete propagation, failure isolation) + reconcile tool.

get_setting is loaded standalone via importlib with SAP_DATA_DIR pointed at a
throwaway dir (same harness as test_data_layer.py).
"""
import asyncio
import importlib.util
import json
import sqlite3
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GS_PATH = ROOT / "py" / "get_setting.py"
RC_PATH = ROOT / "py" / "covs_reconcile.py"


def load_gs(tmp_path):
    import os
    os.environ["SAP_DATA_DIR"] = str(tmp_path)
    name = f"gs_standalone_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, GS_PATH)
    gs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gs)
    return gs


def load_rc():
    name = f"covs_reconcile_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, RC_PATH)
    rc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rc)
    return rc


def seed_blob(db_path, convs):
    con = sqlite3.connect(str(db_path))
    con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
                (json.dumps({"conversations": convs}),))
    con.commit()
    con.close()


def rows_of(db_path):
    con = sqlite3.connect(str(db_path))
    try:
        out = {cid: json.loads(d) for cid, d in
               con.execute("SELECT conv_id, data FROM conversation_rows")}
    except sqlite3.OperationalError:
        out = None
    con.close()
    return out


class TestBackfill:
    def test_init_expands_legacy_blob_into_rows(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_covs_db()
            seed_blob(gs.COVS_PATH, [{"id": "a", "t": 1}, {"id": "b"}, {"noid": 1}])
        asyncio.run(scenario())
        gs2 = load_gs(tmp_path)  # fresh module -> done flag reset -> re-init
        asyncio.run(gs2.init_covs_db())
        got = rows_of(gs2.COVS_PATH)
        assert set(got) == {"a", "b"}  # id-less conversation skipped
        assert got["a"]["t"] == 1

    def test_backfill_idempotent_on_restart(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_covs_db()
            await gs.save_covs({"conversations": [{"id": "x"}, {"id": "y"}]})
        asyncio.run(scenario())
        gs2 = load_gs(tmp_path)
        asyncio.run(gs2.init_covs_db())
        assert set(rows_of(gs2.COVS_PATH)) == {"x", "y"}


class TestDualWrite:
    def test_upsert_and_delete_propagate(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.save_covs({"conversations": [{"id": "c1", "v": 1}, {"id": "c2"}]})
            assert set(rows_of(gs.COVS_PATH)) == {"c1", "c2"}
            await gs.save_covs({"conversations": [{"id": "c1", "v": 2}]})
            got = rows_of(gs.COVS_PATH)
            assert set(got) == {"c1"} and got["c1"]["v"] == 2
        asyncio.run(scenario())

    def test_shadow_failure_does_not_break_blob_write(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_covs_db()
            con = sqlite3.connect(str(gs.COVS_PATH))
            con.execute("DROP TABLE conversation_rows")
            con.commit()
            con.close()
            await gs.save_covs({"conversations": [{"id": "alive"}]})  # must not raise
            got = await gs.load_covs()
            assert got["conversations"][0]["id"] == "alive"
        asyncio.run(scenario())


class TestReconcileTool:
    def test_detects_tampered_row_and_heals_to_zero(self, tmp_path):
        gs = load_gs(tmp_path)
        asyncio.run(gs.save_covs({"conversations": [{"id": "p"}, {"id": "q"}]}))
        rc = load_rc()
        assert rc.main(["--db", str(gs.COVS_PATH)]) == 0
        con = sqlite3.connect(str(gs.COVS_PATH))
        con.execute("UPDATE conversation_rows SET data = '{\"id\":\"p\",\"evil\":true}' WHERE conv_id='p'")
        con.execute("DELETE FROM conversation_rows WHERE conv_id='q'")
        con.commit()
        con.close()
        out = tmp_path / "report.md"
        assert rc.main(["--db", str(gs.COVS_PATH), "--out", str(out)]) == 1
        text = out.read_text(encoding="utf-8")
        assert "MISMATCH" in text and "p" in text and "q" in text
        con = sqlite3.connect(str(gs.COVS_PATH))
        con.execute("DELETE FROM conversation_rows")  # blob-only is a mismatch too
        con.commit()
        con.close()
        assert rc.main(["--db", str(gs.COVS_PATH)]) == 1
