# build=S287
# S268：日记导入（文件/归档并入）——plan_import 超限投影 + import_entries dry_run/落盘。
# 用户要求：合并后超上限将触发归档/删除时，必须先弹确认（后端职责=给出精确投影数）。
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_system as ds  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _entry(i, bid="bk"):
    return {"id": f"{bid}{i}", "time": f"2026-01-{i:02d}T10:00:00", "type": "think",
            "title": f"T{i}", "content": f"C{i}"}


def _setup(tmp_path, monkeypatch, limit=5, archive=True):
    monkeypatch.setattr(ds, "DIARY_DIR", str(tmp_path / "diary"))

    async def fake_settings():
        return {"diarySettings": {"diaryMaxEntries": limit, "diaryArchiveEnabled": archive}}
    import py.get_setting as gs
    monkeypatch.setattr(gs, "load_settings", fake_settings)


def test_plan_no_overflow():
    p = ds.plan_import([_entry(1), _entry(2)], [_entry(9, "new")], limit=5, archive_on=True)
    assert p == {"added": 1, "total": 3, "overflow": 0, "dropped_mode": "archive"}


def test_plan_overflow_archive_mode():
    cur = [_entry(i) for i in range(1, 6)]           # 5 条
    inc = [_entry(1), _entry(20, "x"), _entry(21, "x")]  # 1 重复 + 2 新增
    p = ds.plan_import(cur, inc, limit=5, archive_on=True)
    assert (p["added"], p["total"], p["overflow"], p["dropped_mode"]) == (2, 7, 2, "archive")


def test_plan_overflow_drop_mode_and_unlimited():
    cur = [_entry(i) for i in range(1, 6)]
    inc = [_entry(20, "x"), _entry(21, "x")]
    p = ds.plan_import(cur, inc, limit=5, archive_on=False)
    assert p["overflow"] == 2 and p["dropped_mode"] == "drop"
    p0 = ds.plan_import(cur, inc, limit=0, archive_on=True)  # 无上限永不溢出
    assert p0["overflow"] == 0


def test_dry_run_writes_nothing(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=3, archive=True)
    _run(ds.save_diary_data({"entries": [_entry(i) for i in range(1, 4)]}, "bki"))
    res = _run(ds.import_entries("bki", [_entry(10, "n"), _entry(11, "n")], dry_run=True))
    assert res["dry_run"] and res["overflow"] == 2 and res["added"] == 2
    assert len(_run(ds.load_diary_data("bki"))["entries"]) == 3   # 未落盘
    assert _run(ds.load_archive("bki")) == []


def test_real_import_lands_with_policy(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=3, archive=True)
    _run(ds.save_diary_data({"entries": [_entry(i) for i in range(1, 4)]}, "bkj"))
    res = _run(ds.import_entries("bkj", [_entry(10, "n"), _entry(11, "n")], dry_run=False))
    assert res["dry_run"] is False and res["added"] == 2
    book = _run(ds.load_diary_data("bkj"))
    arch = _run(ds.load_archive("bkj"))
    assert len(book["entries"]) == 3 and len(arch) == 2
    # 时间序：新条目(2026-01-1x 大序)留主本，最旧挤入归档
    assert book["entries"][-1]["id"] == "n11"
    assert arch[0]["id"] == "bk1"


def test_missing_id_time_backfilled(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch, limit=50)
    res = _run(ds.import_entries("bkk", [{"content": "无id旧条目"}], dry_run=False))
    assert res["added"] == 1
    e = _run(ds.load_diary_data("bkk"))["entries"][0]
    assert e.get("id") and e.get("time")


def test_invalid_payloads_rejected(monkeypatch, tmp_path):
    _setup(tmp_path, monkeypatch)
    for bad in ([], [{"junk": 1}], "notalist"):
        try:
            _run(ds.import_entries("bkl", bad))
            assert False, "should raise"
        except ValueError:
            pass


# ---- 静态断言：端点与前端确认路径 ----

def _root_file(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_import_endpoint_registered():
    api = _root_file("py/diary_api.py")
    assert '@router.post("/import")' in api
    assert "import_entries(book_id" in api and 'payload.get("dry_run")' in api


def test_frontend_confirm_before_overflow_write():
    js = _root_file("static/js/methods/44_diary.js")
    i = js.index("diaryImportFlow")
    seg = js[i:i + 3000]
    # 必须先 dry_run 预检；overflow>0 必经 $confirm；drop 模式用删除措辞
    assert "post(true)" in seg and "if (plan.overflow > 0)" in seg
    assert "this.$confirm(" in seg
    assert "diaryImportOverflowDrop" in seg and "dropped_mode === 'drop'" in seg
    # 确认通过后才实写
    assert seg.index("$confirm(") < seg.index("post(false)")


def test_ui_hooks_present():
    html = _root_file("static/templates/page_role.html")
    assert 'triggerDiaryImport()' in html
    assert 'ref="diaryImportInput"' in html and 'type="file"' in html
    assert 'mergeDiaryArchiveToBook()' in html
