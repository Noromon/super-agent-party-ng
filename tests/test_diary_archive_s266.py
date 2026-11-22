# build=S277
# S266：日记上限可设置(0=无上限)+自动归档+导出+合并抢救原语。
# 动因：MAX_ENTRIES=500 硬 FIFO 静默挤走旧条目且 diary 不在自动备份内（审计实锤）。
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_system as ds  # noqa: E402


def _entry(i):
    return {"id": f"id{i}", "time": f"2026-01-{i:02d}T10:00:00", "type": "think",
            "title": f"T{i}", "content": f"C{i}"}


def _run(coro):
    return asyncio.run(coro)


def _setup(tmp_path, monkeypatch, limit=3, archive=True):
    monkeypatch.setattr(ds, "DIARY_DIR", str(tmp_path / "diary"))

    async def fake_settings():
        return {"diarySettings": {"diaryMaxEntries": limit, "diaryArchiveEnabled": archive}}
    import py.get_setting as gs
    monkeypatch.setattr(gs, "load_settings", fake_settings)


def test_policy_reads_settings(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=0)
    limit, arch = _run(ds.get_diary_policy())
    assert (limit, arch) == (0, True)


def test_overflow_archived_not_dropped(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=3, archive=True)
    data = {"entries": [_entry(i) for i in range(1, 8)]}  # 7 条 > 3
    _run(ds.save_diary_data(data, "bk1"))
    book = _run(ds.load_diary_data("bk1"))
    arch = _run(ds.load_archive("bk1"))
    assert len(book["entries"]) == 3
    assert [e["id"] for e in book["entries"]] == ["id5", "id6", "id7"]
    assert [e["id"] for e in arch] == ["id1", "id2", "id3", "id4"]  # 溢出旧条目进归档


def test_unlimited_keeps_all(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=0)
    _run(ds.save_diary_data({"entries": [_entry(i) for i in range(1, 12)]}, "bk2"))
    assert len(_run(ds.load_diary_data("bk2"))["entries"]) == 11


def test_archive_off_discards_old(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=2, archive=False)
    _run(ds.save_diary_data({"entries": [_entry(i) for i in range(1, 6)]}, "bk3"))
    assert len(_run(ds.load_diary_data("bk3"))["entries"]) == 2
    assert _run(ds.load_archive("bk3")) == []


def test_append_archive_dedup_sort(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch)
    _run(ds.append_archive("bk4", [_entry(5), _entry(2)]))
    n = _run(ds.append_archive("bk4", [_entry(2), _entry(8)]))
    arch = _run(ds.load_archive("bk4"))
    assert n == 3 and [e["id"] for e in arch] == ["id2", "id5", "id8"]


def test_merge_entries_id_dedup_time_order():
    a = [{"id": "x", "time": "2026-02-01T00:00:00", "content": "kept"}]
    b = [{"id": "x", "time": "2026-02-01T00:00:00", "content": "dup"},
         {"id": "y", "time": "2026-01-01T00:00:00"}]
    m = ds.merge_entries(a, b)
    assert len(m) == 2 and m[0]["id"] == "y" and m[1]["content"] == "kept"


def test_export_json_and_md(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=0)
    _run(ds.save_diary_data({"entries": [_entry(1), _entry(2)]}, "bk5"))
    fname, mt, raw = _run(ds.export_book("bk5", "json", False))
    payload = json.loads(raw.decode("utf-8"))
    assert fname.startswith("diary_bk5_") and len(payload["entries"]) == 2
    fname, mt, raw = _run(ds.export_book("bk5", "md", True))
    text = raw.decode("utf-8")
    assert fname.endswith(".md") and text.startswith("# 日记本导出") and "C2" in text
