# -*- coding: utf-8 -*-
"""M4-lite 数据快照滚动备份：snapshot/verify/restore/节流/滚动清理围栏。"""
import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import data_backup as dbk


def _mkdata(d):
    d.mkdir(parents=True, exist_ok=True)
    with open(d / "settings.json", "w", encoding="utf-8") as f:
        json.dump({"theme": "dark", "memories": []}, f)
    con = sqlite3.connect(str(d / "super_agent_party.db"))
    con.execute("CREATE TABLE conversations (id TEXT PRIMARY KEY, payload TEXT)")
    con.execute("INSERT INTO conversations VALUES ('c1', '{\"msgs\": 3}')")
    con.commit()
    con.close()
    mc = d / "memory_cache" / "mem1"
    mc.mkdir(parents=True)
    (mc / "index.faiss").write_bytes(b"FAISS" * 100)
    (d / "backend.log").write_text("noise", encoding="utf-8")
    (d / "settings.json.tmp.1234").write_text("tmp noise", encoding="utf-8")
    up = d / "uploaded_files"
    up.mkdir()
    (up / "img.png").write_bytes(b"PNG" * 50)
    return d


class TestSnapshot:
    def test_snapshot_and_verify(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        res = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        assert res["ok"] and not res.get("partial"), res
        assert res["files"] >= 3 and res["bytes"] > 0
        v = dbk.verify_snapshot(res["snap"])
        assert v["ok"], v["checks"]
        mf = json.load(open(os.path.join(res["snap"], "manifest.json"), encoding="utf-8"))
        assert "settings.json" in mf["files"]
        assert "super_agent_party.db" in mf["files"]
        assert "memory_cache/mem1/index.faiss" in mf["files"]
        # 噪音文件不入快照
        assert "backend.log" not in mf["files"]
        assert not any("tmp.1234" in k for k in mf["files"])

    def test_uploads_excluded_by_default(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        r1 = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        mf1 = json.load(open(os.path.join(r1["snap"], "manifest.json"), encoding="utf-8"))
        assert not any(k.startswith("uploaded_files") for k in mf1["files"])
        r2 = dbk.snapshot_data_dir(str(data), throttle_min_sec=0, include_uploads=True)
        mf2 = json.load(open(os.path.join(r2["snap"], "manifest.json"), encoding="utf-8"))
        assert "uploaded_files/img.png" in mf2["files"]

    def test_wal_hot_backup_contains_uncheckpointed_rows(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        dbfile = str(data / "super_agent_party.db")
        con = sqlite3.connect(dbfile)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("INSERT INTO conversations VALUES ('c2', 'wal-row')")
        con.commit()  # 未 checkpoint：数据此时只活在 -wal 中
        res = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        con.close()
        assert res["ok"]
        assert res.get("files") > 0
        snap_db = os.path.join(res["snap"], "super_agent_party.db")
        ro = sqlite3.connect("file:{}?mode=ro".format(snap_db), uri=True)
        ids = {r[0] for r in ro.execute("SELECT id FROM conversations")}
        ro.close()
        assert {"c1", "c2"} <= ids, "backup API 必须把 WAL 未落盘数据一并带入快照"

    def test_throttle(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        r1 = dbk.snapshot_data_dir(str(data))
        assert r1["ok"]
        r2 = dbk.snapshot_data_dir(str(data))  # 默认 1h 节流
        assert r2.get("skipped") and not r2.get("ok")
        r3 = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        assert r3["ok"]
        assert dbk.should_snapshot(str(data), min_interval_sec=3600) is False
        assert dbk.should_snapshot(str(tmp_path / "fresh")) is True


class TestPrune:
    def test_keep_rolls_out_oldest(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        snaps = []
        for _ in range(4):
            r = dbk.snapshot_data_dir(str(data), keep=2, throttle_min_sec=0)
            assert r["ok"]
            snaps.append(r["snap"])
        left = dbk.list_snapshots(str(data))
        assert len(left) == 2
        assert left[0]["path"] == snaps[2] and left[1]["path"] == snaps[3]

    def test_prune_fence(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        # 围栏诱饵：backups 外的同名目录 + backups 内的非 snap-* 目录
        decoy_out = data / "backups_out" / "snap-evil"
        decoy_out.mkdir(parents=True)
        (decoy_out / "keep.txt").write_text("x", encoding="utf-8")
        dbk.backups_root(str(data))  # 触发创建前先建围栏内非快照目录
        other = os.path.join(str(data), "backups", "manual-copy")
        os.makedirs(other, exist_ok=True)
        (data / "backups").mkdir(exist_ok=True)
        open(os.path.join(other, "f.txt"), "w").close()
        for _ in range(4):
            dbk.snapshot_data_dir(str(data), keep=2, throttle_min_sec=0)
        assert (decoy_out / "keep.txt").exists()
        assert os.path.isdir(other)
        assert len(dbk.list_snapshots(str(data))) == 2


class TestVerifyRestore:
    def test_corrupt_db_detected(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        r = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        snap_db = os.path.join(r["snap"], "super_agent_party.db")
        with open(snap_db, "r+b") as f:
            f.seek(60)
            f.write(b"\x00\x00\x00\x00DEADBEEF" * 40)
        v = dbk.verify_snapshot(r["snap"])
        assert not v["ok"]
        assert any(c["name"].startswith("db:") and not c["ok"] for c in v["checks"])

    def test_manifest_mismatch_detected(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        r = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        os.remove(os.path.join(r["snap"], "settings.json"))
        v = dbk.verify_snapshot(r["snap"])
        assert not v["ok"]

    def test_partial_snapshot_fails_verify(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        snap = os.path.join(dbk.backups_root(str(data)), "snap-cut")
        os.makedirs(snap)
        (data / "x.json").write_text("{}", encoding="utf-8")
        v = dbk.verify_snapshot(snap)
        assert not v["ok"]

    def test_restore_guards_and_overwrite(self, tmp_path):
        data = _mkdata(tmp_path / "data")
        r = dbk.snapshot_data_dir(str(data), throttle_min_sec=0)
        # 演练：恢复到空目录
        target = tmp_path / "restored"
        rr = dbk.restore_snapshot(r["snap"], str(target))
        assert rr["ok"] and rr["restored"] >= 3
        assert json.load(open(target / "settings.json", encoding="utf-8"))["theme"] == "dark"
        # 目标已存在且未 overwrite → 拒绝
        rr2 = dbk.restore_snapshot(r["snap"], str(target))
        assert not rr2["ok"] and "overwrite" in rr2["reason"]
        rr3 = dbk.restore_snapshot(r["snap"], str(target), overwrite=True)
        assert rr3["ok"]
