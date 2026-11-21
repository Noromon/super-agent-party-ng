# build=S274
# S267 备份加固审计：diary/ext 曾不在快照核心目录、.txt 不在扩展白名单
# （tool_output_workspaces.txt 漏备）、uploaded_files 默认不入快照（用户资产
# 唯一副本裸奔）、transfer 导入按死上限截断、notification FIFO 200 偏短。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = (ROOT / "py/data_backup.py").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
TRANSFER = (ROOT / "py/routers/transfer.py").read_text(encoding="utf-8")
NOTIF = (ROOT / "py/notification_center.py").read_text(encoding="utf-8")
FE = (ROOT / "static/js/data/20_brain_settings.js").read_text(encoding="utf-8")


def test_core_dirs_cover_diary_and_ext():
    assert '_CORE_DIRS = ("memory_cache", "agents", "kb", "diary", "ext")' in DB


def test_txt_sources_included_and_copied():
    assert 'elif ext == ".txt":' in DB
    # txt 必须走文件复制分支（若落入 dir 分支 os.walk 会静默漏拷）
    assert 'elif kind in ("json", "txt"):' in DB


def test_snapshot_uploads_default_true_when_unset():
    i = SERVER.index("S267: uploaded_files 是用户资产唯一副本")
    seg = SERVER[i:i + 500]
    assert "_raw_inc is not None else True" in seg


def test_legacy_false_migrated_once():
    i = SERVER.index("async def _migrate_backup_uploads_flag_s267")
    seg = SERVER[i:i + 1000]
    assert "backupUploadsS267Migrated" in seg and "await save_settings(settings)" in seg
    # lifespan 内确有调用
    assert "await _migrate_backup_uploads_flag_s267(settings)" in SERVER
    # 前端默认同步为 true
    assert "backupIncludeUploads: true," in FE


def test_transfer_follows_configurable_limit():
    assert "from py.diary_system import get_diary_policy" in TRANSFER
    assert "if _lim267 else 0" in TRANSFER
    assert "from py.diary_system import MAX_ENTRIES" not in TRANSFER


def test_notification_cap_raised():
    assert "MAX_ITEMS = 500" in NOTIF
