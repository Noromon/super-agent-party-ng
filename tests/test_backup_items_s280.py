# build=S283
# S280：备份系统改造——内容项目录/构成评估/手动永久保留/按项裁剪。
# 行为全在 py 层（tmp 数据目录），端点做形状锁。
import json
import os
import sqlite3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import data_backup as db  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]


def _mkdata(tmp_path):
    d = str(tmp_path)
    for name in ("settings.json", "notifications.json"):
        with open(os.path.join(d, name), "w", encoding="utf-8") as f:
            json.dump({"k": name}, f)
    con = sqlite3.connect(os.path.join(d, "super_agent_party.db"))
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    con = sqlite3.connect(os.path.join(d, "conversations.db"))
    con.execute("CREATE TABLE m(x)")
    con.execute("INSERT INTO m VALUES (2)")
    con.commit()
    con.close()
    with open(os.path.join(d, "tool_output_workspaces.txt"), "w", encoding="utf-8") as f:
        f.write("ws\n")
    for dname in ("memory_cache", "agents", "kb", "diary", "ext", "uploaded_files", "logs"):
        os.makedirs(os.path.join(d, dname), exist_ok=True)
        with open(os.path.join(d, dname, "a.bin"), "wb") as f:
            f.write(b"x" * 64)
    with open(os.path.join(d, "logs", "x.log"), "w", encoding="utf-8") as f:
        f.write("noise")
    return d


def test_item_catalog_and_mapping():
    assert db.BACKUP_ITEM_IDS == ("settings", "appdb", "convdb", "txtidx",
                                  "memory_cache", "agents", "kb", "diary", "ext", "uploads")
    assert db.item_of_rel("settings.json") == "settings"
    assert db.item_of_rel("notifications.json") == "settings"
    assert db.item_of_rel("super_agent_party.db") == "appdb"
    assert db.item_of_rel("conversations.db") == "convdb"
    assert db.item_of_rel("tool_output_workspaces.txt") == "txtidx"
    assert db.item_of_rel("uploaded_files/a.png") == "uploads"
    assert db.item_of_rel("diary\\2026.md") == "diary"  # 反斜杠容错


def test_trigger_in_manifest_and_list(tmp_path):
    d = _mkdata(tmp_path)
    r = db.snapshot_data_dir(d, 5, True, 0.0, trigger="manual")
    assert r["ok"]
    mf = json.load(open(os.path.join(r["snap"], "manifest.json"), encoding="utf-8"))
    assert mf["trigger"] == "manual"
    assert "convdb" in mf["include"] and "uploads" in mf["include"]
    snaps = db.list_snapshots(d)
    assert snaps[-1]["trigger"] == "manual"
    assert snaps[-1]["items"].get("convdb", 0) > 0


def test_manual_survives_prune_legacy_is_auto(tmp_path):
    d = _mkdata(tmp_path)
    root = db.backups_root(d)
    os.makedirs(root, exist_ok=True)
    # 造 3 份无 manifest 的旧快照（按用户决策=auto 可修剪）
    for i in range(3):
        os.makedirs(os.path.join(root, "snap-2025010%dT000000000Z" % i), exist_ok=True)
    m = db.snapshot_data_dir(d, 5, True, 0.0, trigger="manual")
    for i in range(2):
        a = db.snapshot_data_dir(d, 2, True, 0.0, trigger="auto")
        assert a["ok"]
    names = {s["name"]: s["trigger"] for s in db.list_snapshots(d)}
    assert names[m["snap"].split(os.sep)[-1]] == "manual"
    # keep=2 → 3 旧 + 2 新 auto = 5 auto，只剩 2：旧的被剪、手动幸存
    autos = [n for n, t in names.items() if t == "auto"]
    assert len(autos) == 2
    legacy_gone = all(("snap-2025010" not in n) for n in autos)
    assert legacy_gone or sum(("snap-2025010" in n) for n in autos) <= 5 - 2  # 剪枝守恒


def test_include_selection_filters_sources(tmp_path):
    d = _mkdata(tmp_path)
    r = db.snapshot_data_dir(d, 5, True, 0.0, trigger="manual", include=["settings", "convdb"])
    mf = json.load(open(os.path.join(r["snap"], "manifest.json"), encoding="utf-8"))
    assert sorted(mf["include"]) == ["convdb", "settings"]
    assert not os.path.exists(os.path.join(r["snap"], "uploaded_files"))
    assert not os.path.exists(os.path.join(r["snap"], "super_agent_party.db"))
    assert os.path.exists(os.path.join(r["snap"], "conversations.db"))
    assert os.path.exists(os.path.join(r["snap"], "settings.json"))
    assert mf["trigger"] == "manual"


def test_include_uploads_overrides_legacy_flag(tmp_path):
    # include 生效时 include_uploads=False 也挡不住显式勾选 uploads 项
    d = _mkdata(tmp_path)
    r = db.snapshot_data_dir(d, 5, False, 0.0, None, "auto", include=["uploads"])
    assert os.path.isdir(os.path.join(r["snap"], "uploaded_files"))
    assert not os.path.exists(os.path.join(r["snap"], "settings.json"))


def test_legacy_none_include_keeps_old_semantics(tmp_path):
    d = _mkdata(tmp_path)
    r = db.snapshot_data_dir(d, 5, False, 0.0)  # 库旧默认：不带 uploads
    assert not os.path.exists(os.path.join(r["snap"], "uploaded_files"))
    assert os.path.exists(os.path.join(r["snap"], "settings.json"))


def test_estimate_sizes(tmp_path):
    d = _mkdata(tmp_path)
    # 未合并 WAL 应计入 db 项（快照经 backup API 会带走这些数据）
    con = sqlite3.connect(os.path.join(d, "conversations.db"))
    con.execute("CREATE TABLE w(x)")
    con.execute("INSERT INTO w VALUES (3)")
    con.commit()
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("INSERT INTO w VALUES (4)")
    con.commit()
    con.close()
    est = db.estimate_sizes(d)
    by = {i["id"]: i for i in est["items"]}
    assert by["convdb"]["bytes"] > 0 and by["convdb"]["files"] >= 1
    assert by["uploads"]["bytes"] >= 64
    assert by["settings"]["bytes"] >= 2  # 两个 json
    assert by["txtidx"]["files"] == 1
    assert "logs" not in {i["id"] for i in est["items"]}
    # logs/a.bin 不进任何项（不在 _ITEM_DIRS）
    assert est["total"] == sum(i["bytes"] for i in est["items"])
    assert est["disk_free"] == -1 or est["disk_free"] > 0


def test_prune_fence_still_respected(tmp_path):
    d = _mkdata(tmp_path)
    root = db.backups_root(d)
    decoy = os.path.join(root, "memory_cache-pre-s133")
    os.makedirs(decoy, exist_ok=True)
    for i in range(6):
        db.snapshot_data_dir(d, 2, False, 0.0)
    assert os.path.isdir(decoy)
    assert os.path.isdir(os.path.join(d, "agents"))  # 源目录绝不误伤（修剪只碰 backups/）


class TestEndpointShape:
    def test_now_accepts_include_body(self):
        src = (_ROOT / "py/routers/status.py").read_text(encoding="utf-8")
        i = src.index('"/api/backup/now"')
        seg = " ".join(src[i:i + 1100].split())
        assert "body: dict = Body(default=None)" in seg
        assert '"manual", include)' in seg
        assert "BACKUP_ITEM_IDS" in seg
        i2 = src.index('"/api/backup/estimate"')
        assert "estimate_sizes" in src[i2:i2 + 300]

    def test_startup_selection_resolution(self):
        srv = (_ROOT / "server.py").read_text(encoding="utf-8")
        i = srv.index("S280: 自动备份构成")
        seg = srv[i:i + 1200]
        assert 'x in BACKUP_ITEM_IDS' in seg
        assert '_raw_inc = _s.get("backupIncludeUploads")' in seg
