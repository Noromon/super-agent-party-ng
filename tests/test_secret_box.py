# -*- coding: utf-8 -*-
"""M4c/X-12 pins: DPAPI at-rest wrapping of secret-named settings fields.

Runs the real DPAPI (test machine is Windows). get_setting loaded standalone
via importlib with SAP_DATA_DIR pointed at a throwaway dir.
"""
import asyncio
import json
import sqlite3
import uuid
from pathlib import Path

from test_row_store import load_gs  # same standalone harness


def raw_row(db_path):
    con = sqlite3.connect(str(db_path))
    row = con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]
    con.close()
    return row


SECRET = "sk-live-" + uuid.uuid4().hex
NESTED = "tg-" + uuid.uuid4().hex
ARR = "ghp_" + uuid.uuid4().hex


class TestSecretBox:
    def test_roundtrip_and_ciphertext_at_rest(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            await gs.save_settings({"api_key": SECRET})
            raw = raw_row(gs.DATABASE_PATH)
            assert SECRET not in raw and "dpapi:" in raw
            got = await gs.load_settings()
            assert got["api_key"] == SECRET
        asyncio.run(scenario())

    def test_nested_and_list_fields_wrapped(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            payload = {"sub": {"bot_token": NESTED}, "arr": [{"secret": ARR}, {"plain": 1}]}
            await gs.save_settings(payload)
            raw = raw_row(gs.DATABASE_PATH)
            assert NESTED not in raw and ARR not in raw
            got = await gs.load_settings()
            assert got["sub"]["bot_token"] == NESTED
            assert got["arr"][0]["secret"] == ARR
            assert got["arr"][1]["plain"] == 1
        asyncio.run(scenario())

    def test_non_secret_names_untouched(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            payload = {"bing_search_url": "http://example/?k=visible",
                       "google_cse_id": "cse-id-visible", "token": "", "zz": "x"}
            await gs.save_settings(payload)
            raw = raw_row(gs.DATABASE_PATH)
            assert "visible" in raw and "cse-id-visible" in raw and "dpapi:" not in raw
            got = await gs.load_settings()
            assert got["bing_search_url"] == "http://example/?k=visible"
            assert got["token"] == ""
        asyncio.run(scenario())

    def test_legacy_plaintext_self_heals_on_next_save(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
                        (json.dumps({"api_key": SECRET}),))
            con.commit()
            con.close()
            got = await gs.load_settings()          # legacy plaintext still readable
            assert got["api_key"] == SECRET
            await gs.save_settings({**got})          # next save encrypts
            raw = raw_row(gs.DATABASE_PATH)
            assert SECRET not in raw and "dpapi:" in raw
        asyncio.run(scenario())

    def test_tampered_ciphertext_passes_through_not_fatal(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            await gs.save_settings({"api_key": SECRET})
            raw = raw_row(gs.DATABASE_PATH)
            broken = raw.replace('"api_key": "dpapi:', '"api_key": "dpapi:QUJDREVG not-really-b64@@')
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)", (broken,))
            con.commit()
            con.close()
            got = await gs.load_settings()           # must not raise
            assert str(got["api_key"]).startswith("dpapi:")  # explicit garbage, logged
        asyncio.run(scenario())

    def test_caller_dict_never_mutated(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            payload = {"api_key": SECRET}
            await gs.save_settings(payload)
            assert payload["api_key"] == SECRET      # in-memory stays plaintext
        asyncio.run(scenario())
