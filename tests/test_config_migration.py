# -*- coding: utf-8 -*-
"""M-7 / E-6 pins: settings_template 无重复键（严格解析器可过）、
_migrate_legacy_keys 迁移通道语义、load_settings 集成迁移+持久化回写。"""
import asyncio
import json
import sqlite3

from test_row_store import load_gs

TEMPLATE = "config/settings_template.json"


def _no_dup_hook(pairs):
    seen = set()
    for k, _ in pairs:
        assert k not in seen, f"duplicate key in template: {k}"
        seen.add(k)
    return dict(pairs)


class TestTemplate:
    def test_template_parses_strict_and_no_duplicate_keys(self):
        with open(TEMPLATE, encoding="utf-8") as f:
            raw = f.read()
        data = json.loads(raw, object_pairs_hook=_no_dup_hook)
        assert "dbPath" not in data["sqlSettings"]
        assert "dbpath" in data["sqlSettings"]


class TestMigrationHook:
    def test_moves_legacy_value_when_canonical_empty(self, tmp_path):
        gs = load_gs(tmp_path)
        d = {"sqlSettings": {"dbPath": "old.db", "dbpath": ""}}
        assert gs._migrate_legacy_keys(d) is True
        assert d["sqlSettings"] == {"dbpath": "old.db"}

    def test_canonical_wins_when_both_present(self, tmp_path):
        gs = load_gs(tmp_path)
        d = {"sqlSettings": {"dbPath": "old.db", "dbpath": "new.db"}}
        assert gs._migrate_legacy_keys(d) is True
        assert d["sqlSettings"]["dbpath"] == "new.db"
        assert "dbPath" not in d["sqlSettings"]

    def test_idempotent_when_key_absent(self, tmp_path):
        gs = load_gs(tmp_path)
        d = {"sqlSettings": {"dbpath": "x.db"}, "theme": "dark"}
        assert gs._migrate_legacy_keys(d) is False
        assert d == {"sqlSettings": {"dbpath": "x.db"}, "theme": "dark"}


class TestLoadSettingsIntegration:
    def test_legacy_key_migrated_and_persisted(self, tmp_path):
        gs = load_gs(tmp_path)

        async def scenario():
            await gs.init_db()
            # 模拟老用户库：含死键 dbPath 且有真实值，规范键为空
            legacy = {"sqlSettings": {"enabled": True, "dbPath": "/data/precious.db",
                                      "dbpath": ""}}
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
                        (json.dumps(legacy),))
            con.commit()
            con.close()
            loaded = await gs.load_settings()
            assert loaded["sqlSettings"]["dbpath"] == "/data/precious.db"
            assert "dbPath" not in loaded["sqlSettings"]
            await asyncio.sleep(0.1)  # 等回写任务落库
            con = sqlite3.connect(str(gs.DATABASE_PATH))
            stored = json.loads(con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0])
            con.close()
            assert "dbPath" not in stored["sqlSettings"]
            assert stored["sqlSettings"]["dbpath"] == "/data/precious.db"
            # 幂等：二次加载不再变更
            loaded2 = await gs.load_settings()
            assert "dbPath" not in loaded2["sqlSettings"]
        asyncio.run(scenario())
