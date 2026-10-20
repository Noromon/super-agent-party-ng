# -*- coding: utf-8 -*-
"""批 0-③ task_center 钉：T-6 启动对账（RUNNING→FAILED）+ D-12 原子写。"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.task_center import TaskCenter, TaskStatus


def _write_raw_task(task_dir: Path, task_id: str, status: str):
    task_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    payload = {
        "task_id": task_id, "parent_task_id": None, "title": f"t-{task_id}",
        "description": "d", "status": status, "progress": 42, "result": None,
        "error": None, "created_at": now, "updated_at": now,
        "started_at": now, "completed_at": None, "agent_type": "default",
        "context": {}, "task_type": "once", "platforms": [],
        "schedule_config": None, "next_run_at": None, "last_run_at": None,
        "occurrence_count": 0,
    }
    (task_dir / f"{task_id}.json").write_text(
        json.dumps(payload), encoding="utf-8")


def test_startup_reconcile_running_to_failed(tmp_path):
    tc = TaskCenter(str(tmp_path))
    _write_raw_task(tc.task_dir, "run01", "running")
    _write_raw_task(tc.task_dir, "pend01", "pending")

    tasks = asyncio.run(tc.list_tasks())
    by_id = {t.task_id: t for t in tasks}
    assert by_id["run01"].status == TaskStatus.FAILED
    assert "T-6" in (by_id["run01"].error or "")
    assert by_id["pend01"].status == TaskStatus.PENDING

    # 对账已落盘（重开实例读到的就是 FAILED）
    raw = json.loads((tc.task_dir / "run01.json").read_text(encoding="utf-8"))
    assert raw["status"] == "failed"
    assert raw["completed_at"] is not None


def test_startup_reconcile_idempotent(tmp_path):
    tc = TaskCenter(str(tmp_path))
    _write_raw_task(tc.task_dir, "run02", "running")
    asyncio.run(tc.list_tasks())
    first = (tc.task_dir / "run02.json").read_text(encoding="utf-8")
    asyncio.run(tc.list_tasks())
    again = (tc.task_dir / "run02.json").read_text(encoding="utf-8")
    assert first == again  # 二次对账未重复改写
    assert json.loads(again)["status"] == "failed"


def test_corrupt_task_file_does_not_break_reconcile(tmp_path):
    tc = TaskCenter(str(tmp_path))
    tc.task_dir.mkdir(parents=True, exist_ok=True)
    (tc.task_dir / "bad.json").write_text("{half-written", encoding="utf-8")
    _write_raw_task(tc.task_dir, "run03", "running")
    tasks = asyncio.run(tc.list_tasks())
    ids = {t.task_id for t in tasks}
    assert "run03" in ids and "bad" not in ids


def test_atomic_save_no_tmp_leftover_and_valid(tmp_path):
    tc = TaskCenter(str(tmp_path))

    async def scenario():
        task = await tc.create_task(title="a", description="b")
        ok = await tc.update_task_progress(task.task_id, 50)
        assert ok
        return task.task_id

    task_id = asyncio.run(scenario())
    assert not list(tc.task_dir.glob("*.tmp"))
    raw = json.loads((tc.task_dir / f"{task_id}.json").read_text(encoding="utf-8"))
    assert raw["progress"] == 50
    got = asyncio.run(tc.get_task(task_id))
    assert got is not None and got.progress == 50
