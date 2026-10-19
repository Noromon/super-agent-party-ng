# -*- coding: utf-8 -*-
"""Bot-session row store ("phone") pins: CRUD under the bot: namespace,
non-interference with the blob<->rows shadow sync, reconcile exclusion,
and view redaction of payloads.
"""
import asyncio
import json
import sqlite3

import pytest

from test_row_store import load_gs, load_rc, rows_of


def bot_rows(db_path):
    con = sqlite3.connect(str(db_path))
    out = {cid: data for cid, data in con.execute(
        "SELECT conv_id, data FROM conversation_rows WHERE conv_id LIKE 'bot:%'")}
    con.close()
    return out


class TestCrud:
    def test_roundtrip_and_prefix_guard(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.save_bot_conv("bot:xmpp:a@x.local", [{"role": "user", "content": "hi"}])
            msgs = await gs.load_bot_conv("bot:xmpp:a@x.local")
            assert msgs[0]["content"] == "hi"
            assert await gs.load_bot_conv("bot:xmpp:none") is None
            with pytest.raises(ValueError):
                await gs.save_bot_conv("regular-id", [])
            with pytest.raises(ValueError):
                await gs.delete_bot_conv("regular-id")
        asyncio.run(scenario())

    def test_blob_sync_never_wipes_bot_rows(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.save_bot_conv("bot:xmpp:keep@x", [{"role": "user", "content": "precious"}])
            await gs.save_covs({"conversations": [{"id": "c1"}, {"id": "c2"}]})
            # a second blob save with c2 removed must delete c2's row but NOT bot: rows
            await gs.save_covs({"conversations": [{"id": "c1"}]})
            rows = rows_of(gs.COVS_PATH)
            assert "c1" in rows and "c2" not in rows
            assert "bot:xmpp:keep@x" in rows, "blob sync must never touch bot: namespace"
        asyncio.run(scenario())

    def test_list_order_and_preview(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.save_bot_conv("bot:xmpp:alice@x", [{"role": "user", "content": "A" * 300}])
            await gs.save_bot_conv("bot:telegram:42", [{"role": "assistant", "content": "B"}])
            await gs.save_covs({"conversations": [{"id": "blob-c"}]})
            return await gs.list_bot_convs()
        items = asyncio.run(scenario())
        ids = {it["conv_id"] for it in items}
        assert ids == {"bot:xmpp:alice@x", "bot:telegram:42"}   # blob conversations excluded
        alice = next(it for it in items if it["conv_id"] == "bot:xmpp:alice@x")
        assert alice["count"] == 1 and alice["last_text"].startswith("AAA")
        assert len(alice["last_text"]) <= 120

    def test_delete_and_clear(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.save_bot_conv("bot:xmpp:gone@x", [{"role": "user", "content": "x"}])
            await gs.save_bot_conv("bot:xmpp:cleared@x", [{"role": "user", "content": "y"}])
            await gs.delete_bot_conv("bot:xmpp:gone@x")
            await gs.save_bot_conv("bot:xmpp:cleared@x", [])
            assert await gs.load_bot_conv("bot:xmpp:gone@x") is None
            assert await gs.load_bot_conv("bot:xmpp:cleared@x") == []
        asyncio.run(scenario())


class TestRedact:
    def test_data_uri_and_long_text(self, tmp_path):
        gs = load_gs(tmp_path)
        big_img = "data:image/png;base64," + "A" * 100000
        msgs = [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": big_img}},
                {"type": "text", "text": "look"}]},
            {"role": "assistant", "content": "x" * 9000},
        ]
        out = gs.redact_messages_for_view(msgs)
        assert out[0]["content"][0]["image_url"]["url"].startswith("[data-uri")
        assert out[0]["content"][1]["text"] == "look"
        assert len(out[1]["content"]) < 3000 and "…" in out[1]["content"]
        # input not mutated
        assert msgs[1]["content"].startswith("xxxx") and len(msgs[1]["content"]) == 9000


class TestReconcileExclusion:
    def test_bot_rows_invisible_to_three_way_audit(self, tmp_path):
        gs = load_gs(tmp_path)
        asyncio.run(gs.save_covs({"conversations": [{"id": "c1"}]}))
        asyncio.run(gs.save_bot_conv("bot:xmpp:ui@x", [{"role": "user", "content": "hi"}]))
        rc = load_rc()
        assert rc.main(["--db", str(gs.COVS_PATH)]) == 0
        con = sqlite3.connect(str(gs.COVS_PATH))
        con.execute("UPDATE conversation_rows SET data='[]' WHERE conv_id='bot:xmpp:ui@x'")
        con.commit()
        con.close()
        assert rc.main(["--db", str(gs.COVS_PATH)]) == 0   # tampered bot row: still consistent
