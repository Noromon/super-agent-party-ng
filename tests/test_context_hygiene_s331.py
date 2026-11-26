# -*- coding: utf-8 -*-
"""S331: 双层任务锚（原文不被覆盖）+ IM 平台记忆窗留痕 + 持久化卫生。

审计结论：服务端主链已全留痕，残余隐患=锚钝化(每轮覆盖成最新句)+前端 compact
slice(-6) 丢任务源头+8 平台静默 pop(0) 窗+行表 delete-on-vanished/inflight 孤儿。
"""
import asyncio
import sqlite3
import sys
import time
from pathlib import Path
from types import SimpleNamespace

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # 驱逐 site-packages 的 py 单体库（s323 同法）

import pytest  # noqa: E402

from py import get_setting as GS  # noqa: E402
from py import im_chain as IC  # noqa: E402
from py import task_anchor as TA  # noqa: E402


class TestAnchorOriginal:
    def _db(self, tmp_path, monkeypatch):
        p = str(tmp_path / "covs.db")
        monkeypatch.setattr(TA, "COVS_PATH", p)
        TA._migrated.add(p)  # 新库经 _CREATE_SQL 直建（含 original），跳 ALTER
        return p

    def test_original_pinned_while_text_rolls(self, tmp_path, monkeypatch):
        self._db(tmp_path, monkeypatch)

        async def _t():
            await TA.remember_anchor("c1", "最初的任务原文")
            await TA.remember_anchor("c1", "最新的一句话")
            assert await TA.fetch_anchor("c1") == "最新的一句话"
            assert await TA.fetch_anchor_original("c1") == "最初的任务原文"
        asyncio.run(_t())

    def test_legacy_table_gets_altered(self, tmp_path, monkeypatch):
        p = self._db(tmp_path, monkeypatch)
        TA._migrated.discard(p)  # 模拟存量库：先建旧两列表
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE task_anchor (conv_id TEXT PRIMARY KEY, "
                    "text TEXT NOT NULL, updated_at REAL)")
        con.commit()
        con.close()

        async def _t():
            await TA.remember_anchor("c1", "原文任务")
            assert await TA.fetch_anchor_original("c1") == "原文任务"
        asyncio.run(_t())

    def test_resume_injects_original_not_latest(self, tmp_path, monkeypatch):
        self._db(tmp_path, monkeypatch)

        async def _t():
            await TA.remember_anchor("c1", "主人原任务")
            await TA.remember_anchor("c1", "后来的某句话")
            req = SimpleNamespace(conversation_id="c1", is_app_bot=False,
                                  behavior_trigger=False,
                                  messages=[{"role": "system", "content": "s"},
                                            {"role": "assistant", "content": "a"}])
            await TA.anchor_stream_in(req)
            users = [m for m in req.messages if m["role"] == "user"]
            assert users and users[0]["content"] == "主人原任务"
        asyncio.run(_t())


class TestTrimMemory:
    def test_single_pop_and_pair(self):
        m = [{"r": i} for i in range(6)]
        IC.trim_memory("t", "p", m, 4)
        assert len(m) == 4 and m[0]["r"] == 2
        IC.trim_memory("t", "p", m, 1, pair=True)  # 成对弹出：4→2→0
        assert len(m) == 0

    def test_logs_only_on_trim(self, caplog):
        m = [1, 2]
        with caplog.at_level("INFO"):
            IC.trim_memory("t", "p", m, 10)
        assert "[MemTrim]" not in caplog.text
        with caplog.at_level("INFO"):
            IC.trim_memory("t", "p", m, 1)
        assert "[MemTrim]" in caplog.text

    def test_no_platform_silent_windows_left(self):
        """扫描器：所有 IM 客户端不得再有绕过 trim_memory 的记忆窗 pop(0)。"""
        files = ["xmpp_client.py", "dingtalk_bot_manager.py",
                 "feishu_bot_manager.py", "telegram_client.py",
                 "qq_bot_manager.py", "discord_bot_manager.py",
                 "slack_bot_manager.py"]
        for fn in files:
            src = (_ROOT / "py" / fn).read_text(encoding="utf-8-sig")
            assert "while len(self.memory" not in src, f"{fn} 仍有静默记忆窗"


class TestPinsS331:
    def _src(self, rel):
        return (_ROOT / rel).read_text(encoding="utf-8-sig")

    def test_frontend_compact_keeps_first_user(self):
        s = self._src("static/js/methods/12_context_todos.js")
        assert "kept.unshift(firstUser)" in s

    def test_complete_engine_has_anchor_hook(self):
        assert "anchor_stream_in" in self._src("py/complete_engine.py")

    def test_qq_windows_upgraded_to_double(self):
        s = self._src("py/qq_bot_manager.py")
        assert s.count("trim_memory(\"qq") == 2
        assert "self.memoryLimit * 2)" in s

    def test_sync_rows_delete_is_enumerated(self):
        s = self._src("py/get_setting.py")
        assert "全量保存将删除" in s

    def test_dump_size_and_compact_warnings(self):
        assert "快照文件" in self._src("py/approval_store.py")
        cm = self._src("py/context_manager.py")
        assert '[Compact] 摘要调用失败' in cm and "warning" in cm.split("[Compact] 摘要调用失败")[0][-120:]


class TestInflightGc:
    def test_stale_rows_swept_fresh_kept(self, tmp_path, monkeypatch):
        p = str(tmp_path / "covs.db")
        monkeypatch.setattr(GS, "COVS_PATH", p)
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE conversation_rows (conv_id TEXT PRIMARY KEY, "
                    "data TEXT NOT NULL, updated_at REAL, ord INTEGER)")
        now = time.time()
        con.executemany(
            "INSERT INTO conversation_rows VALUES (?,?,?,?)",
            [("bot:xmpp:a#inflight", "[]", now - 90000, None),   # 旧孤儿
             ("bot:xmpp:b#inflight", "[]", now, None),           # 在途
             ("bot:xmpp:c", "[]", now - 90000, None)])           # 非 inflight 旧行不动
        con.commit()
        con.close()
        n = asyncio.run(GS.gc_stale_inflight(max_age=86400))
        assert n == 1
        con = sqlite3.connect(p)
        ids = {r[0] for r in con.execute("SELECT conv_id FROM conversation_rows")}
        con.close()
        assert ids == {"bot:xmpp:b#inflight", "bot:xmpp:c"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
