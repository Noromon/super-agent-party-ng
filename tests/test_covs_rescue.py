# -*- coding: utf-8 -*-
"""M4-B2'/S190 pins: rows-first 下坏 blob 无害旁路；行表+blob 同坏才降级（隔离留证、
救援成功=DEGRADED 解除+下次 save 自愈回写、行表同坏=原降级零回归、
bot: 命名空间不混入、半坏行整体放弃、reconcile 工具回归）。"""
import asyncio
import json
import sqlite3

import pytest

from test_row_store import load_gs, load_rc, rows_of


def corrupt_blob(gs):
    con = sqlite3.connect(gs.COVS_PATH)
    con.execute("UPDATE settings SET data = ? WHERE id = 1", ("{broken json!!",))
    con.commit()
    con.close()


def seed(gs, convs):
    async def scenario():
        await gs.save_covs({"conversations": convs})
    asyncio.run(scenario())


class TestRescue:
    def test_rows_intact_blob_corrupt_is_bypassed(self, tmp_path):
        """S190 rows-first：blob 降级为导出快照。blob 损坏而权威行表完好时，
        load 直接走行表、坏 blob 无害旁路（不降级、不隔离；下次全量保存自愈）。"""
        gs = load_gs(tmp_path)
        seed(gs, [{"id": "c1", "messages": [1, 2]}, {"id": "c2", "messages": []}])
        corrupt_blob(gs)

        async def scenario():
            return await gs.load_covs()
        out = asyncio.run(scenario())
        assert {c["id"] for c in out["conversations"]} == {"c1", "c2"}
        assert gs._COVS_DEGRADED is False

        # 全量保存后 blob 自愈
        async def heal():
            await gs.save_covs({"conversations": [{"id": "c1", "messages": [1, 2]},
                                                   {"id": "c2", "messages": []}]})
            con = sqlite3.connect(gs.COVS_PATH)
            data = json.loads(con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0])
            con.close()
            return data
        assert {c["id"] for c in asyncio.run(heal())["conversations"]} == {"c1", "c2"}

    def test_self_heal_writeback(self, tmp_path):
        gs = load_gs(tmp_path)
        seed(gs, [{"id": "c1"}, {"id": "c2"}])
        corrupt_blob(gs)

        async def scenario():
            rescued = await gs.load_covs()
            rescued["conversations"].append({"id": "c3"})
            await gs.save_covs(rescued)
            return await gs.load_covs()
        out = asyncio.run(scenario())
        assert {c["id"] for c in out["conversations"]} == {"c1", "c2", "c3"}

    def test_rows_also_gone_falls_back_to_legacy_degrade(self, tmp_path):
        gs = load_gs(tmp_path)
        seed(gs, [{"id": "c1"}])
        corrupt_blob(gs)
        con = sqlite3.connect(gs.COVS_PATH)
        con.execute("DELETE FROM conversation_rows")
        con.commit()
        con.close()

        async def scenario():
            out = await gs.load_covs()
            assert out == {"conversations": []}
            assert gs._COVS_DEGRADED is True
            with pytest.raises(RuntimeError):
                await gs.save_covs({"conversations": []})
        asyncio.run(scenario())

    def test_half_bad_row_aborts_rescue(self, tmp_path):
        gs = load_gs(tmp_path)
        seed(gs, [{"id": "c1"}, {"id": "c2"}])
        con = sqlite3.connect(gs.COVS_PATH)
        con.execute("UPDATE conversation_rows SET data = 'x-not-json' WHERE conv_id = 'c2'")
        con.commit()
        con.close()
        corrupt_blob(gs)

        async def scenario():
            out = await gs.load_covs()
            assert out == {"conversations": []}, "半坏行必须整体放弃，不得端出残缺库"
            assert gs._COVS_DEGRADED is True
        asyncio.run(scenario())

    def test_bot_namespace_never_rescued(self, tmp_path):
        gs = load_gs(tmp_path)
        seed(gs, [{"id": "c1"}])

        async def scenario():
            await gs.save_bot_conv("bot:xmpp:a@x", [{"role": "user", "content": "priv"}])
        asyncio.run(scenario())
        corrupt_blob(gs)

        async def scenario2():
            return await gs.load_covs()
        out = asyncio.run(scenario2())
        ids = {c["id"] for c in out["conversations"]}
        assert ids == {"c1"}, "bot: 行属手机渠道命名空间，严禁混入主会话库"


class TestReconcileRegression:
    def test_tool_reports_consistent_and_mismatch(self, tmp_path):
        gs = load_gs(tmp_path)
        rc = load_rc()
        seed(gs, [{"id": "c1"}, {"id": "c2"}])
        blob_map, rows_map, traces = rc.load_maps(gs.COVS_PATH)
        r = rc.reconcile(blob_map, rows_map, traces)
        assert r["consistent"], r
        # 行被外部删除后 = blob_only 检出
        con = sqlite3.connect(gs.COVS_PATH)
        con.execute("DELETE FROM conversation_rows WHERE conv_id = 'c2'")
        con.commit()
        con.close()
        blob_map, rows_map, traces = rc.load_maps(gs.COVS_PATH)
        r2 = rc.reconcile(blob_map, rows_map, traces)
        assert not r2["consistent"] and r2["blob_only"] == ["c2"]
