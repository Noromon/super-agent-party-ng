# -*- coding: utf-8 -*-
"""M4a pins: settings/covs data-layer defenses (D-1/D-2/D-3/D-8/D-15).

get_setting is loaded standalone via importlib with SAP_DATA_DIR pointed at a
throwaway dir (never the production or the shared server-fixture dir).
"""
import asyncio
import glob
import importlib.util
import json
import os
import sqlite3
import uuid
from pathlib import Path

import pytest

GS_PATH = Path(__file__).resolve().parent.parent / "py" / "get_setting.py"


def load_gs(tmp_path):
    os.environ["SAP_DATA_DIR"] = str(tmp_path)
    name = f"gs_standalone_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, GS_PATH)
    gs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gs)
    return gs


def corrupt_row(db_path, payload="{{{garbage"):
    con = sqlite3.connect(str(db_path))
    con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)", (payload,))
    con.commit()
    con.close()


class TestSettingsDefense:
    def test_roundtrip_and_wal(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            await gs.save_settings({"zz_test": 7})
            got = await gs.load_settings()
            assert got["zz_test"] == 7
            async with gs.aiosqlite.connect(gs.DATABASE_PATH) as db:
                async with db.execute("PRAGMA journal_mode") as cur:
                    mode = (await cur.fetchone())[0]
            assert str(mode).lower() == "wal"
        asyncio.run(scenario())

    def test_corrupt_settings_quarantined_not_overwritten(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            await gs.save_settings({"zz_precious": "keepme"})
            corrupt_row(gs.DATABASE_PATH)
            got = await gs.load_settings()
            await asyncio.sleep(0.1)  # let any (forbidden) write-back task run
            assert "zz_precious" not in json.dumps(got)[:200]
            backups = glob.glob(str(tmp_path / "*.settings-corrupt-*.json"))
            assert backups, "corrupt payload must be quarantined to disk"
            assert "garbage" in open(backups[0], encoding="utf-8").read()
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            row = con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]
            con.close()
            assert "garbage" in row, "DB must NOT be overwritten with defaults"
        asyncio.run(scenario())

    def test_d2_conversations_never_in_main_settings(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            payload = {"zz_x": 1, "conversations": [{"id": "c1"}]}
            await gs.save_settings(payload)
            assert "conversations" in payload, "caller dict must stay untouched"
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            row = json.loads(con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0])
            con.close()
            assert "conversations" not in row
        asyncio.run(scenario())


class TestCovsDefense:
    def test_corrupt_covs_quarantine_and_refusal(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_covs_db()
            await gs.save_covs({"conversations": [{"id": "keep"}]})
            corrupt_row(gs.COVS_PATH)
            empty = await gs.load_covs()
            assert empty == {"conversations": []}
            backups = glob.glob(str(tmp_path / "*.covs-corrupt-*.json"))
            assert backups and "garbage" in open(backups[0], encoding="utf-8").read()
            with pytest.raises(RuntimeError):
                await gs.save_covs({"conversations": []})
            con = sqlite3.connect(str(gs.COVS_PATH))
            row = con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]
            con.close()
            assert "garbage" in row, "degraded refusal must not wipe the DB"
            # recovery path: a non-empty save is allowed and clears degraded flag
            await gs.save_covs({"conversations": [{"id": "fresh"}]})
            got = await gs.load_covs()
            assert got["conversations"][0]["id"] == "fresh"
            await gs.save_covs({"conversations": []})  # no longer degraded
        asyncio.run(scenario())

    def test_concurrent_saves_stay_parseable(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            async def one(i):
                await gs.save_settings({"zz_winner": i})
            await asyncio.gather(*[one(i) for i in range(20)])
            got = await gs.load_settings()
            assert isinstance(got.get("zz_winner"), int)
        asyncio.run(scenario())
