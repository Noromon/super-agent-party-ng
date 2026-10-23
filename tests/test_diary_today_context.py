# -*- coding: utf-8 -*-
"""S84：启动版本指纹 + 日记【今日概况】注入（纠正「今天还没说过话」幻觉）。"""
import ast
import asyncio
import datetime
import io
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s84_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

import py.diary_engine as de  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


# ---------------- 启动版本指纹 ----------------

def test_version_fingerprint_behavior():
    src = _read("server.py")
    tree = ast.parse(src)
    node = next(n for n in tree.body
                if isinstance(n, ast.FunctionDef) and n.name == "_version_fingerprint")
    ns = {"os": os, "time": __import__("time"),
          "__file__": str(_ROOT / "server.py")}
    exec(compile(ast.get_source_segment(src, node), "<x>", "exec"), ns)  # noqa: S102
    fp = ns["_version_fingerprint"]()
    assert "tree=" in fp and "HEAD=" in fp and "server.py-mtime=" in fp
    assert Path(fp.split("tree=")[1].split(" HEAD=")[0]).exists()
    assert re.search(r"HEAD=[0-9a-f]{7,}(\s+dirty)?(-| )", fp + " ")


def test_version_log_wired():
    src = _read("server.py")
    assert 'logger.info("===== 日志系统初始化成功 =====\\n[Version] " + _version_fingerprint())' in src
    assert src.index("[Version] ") > src.index("日志系统初始化成功")   # 同一启动标记内


# ---------------- 【今日概况】 ----------------

def _today_at(hm):
    return datetime.date.today().strftime("%Y-%m-%d") + "T" + hm + ":05.123456"


def test_today_entries_only_today_and_formatted(monkeypatch):
    async def fake_recent(book_id, n=5):
        return [
            # S86：真实条目字段是 time（diary_system.add_diary_entry 写入口径）
            {"type": "chatSummary", "time": _today_at("00:37"), "content": "今晚主人哭得很凶。\n第二行"},
            {"type": "think", "time": _today_at("07:05"), "content": "清晨随笔（思考类不展开只计数）"},
            # 兼容旧数据 created_at 字段
            {"type": "imMessage", "created_at": _today_at("08:15"), "content": "旧字段兼容条目"},
            {"type": "think", "time": "2026-01-01T07:00:00", "content": "昨天及更早不该出现"},
        ]

    async def no_mem():
        return []

    monkeypatch.setattr(de, "get_recent_diary_entries", fake_recent)
    monkeypatch.setattr(de, "_fetch_today_new_memories", no_mem)
    block = asyncio.run(de.build_today_context("book-a"))
    assert "00:37 对话摘要" in block and "今晚主人哭得很凶" in block
    assert "08:15 主动消息" in block          # created_at 旧字段兼容
    assert "发呆写下 1 篇思考" in block          # think 只计数（昨日那篇不计入）
    assert "清晨随笔" not in block             # think 不展开（防自证循环）
    assert "昨天及更早" not in block and "2026" not in block.split("切勿")[0].split("】")[-1]
    assert "用户今天还没找过我" in block          # 反幻觉指令句本身在场


def test_think_only_day_not_claimed_as_interaction(monkeypatch):
    async def fake_recent(book_id, n=5):
        return [{"type": "think", "time": _today_at("09:00"), "content": "他今天没来"},
                {"type": "think", "time": _today_at("10:00"), "content": "还是没来"}]

    async def no_mem():
        return []

    monkeypatch.setattr(de, "get_recent_diary_entries", fake_recent)
    monkeypatch.setattr(de, "_fetch_today_new_memories", no_mem)
    block = asyncio.run(de.build_today_context("b"))
    assert "还没有与用户交流的记录" in block and "2 篇思考" in block
    assert "他还没来找你" in block              # 允许如实写没互动
    assert "切勿写出" not in block              # 但不得反向禁写


def test_entry_time_field_contract():
    """S86 事故 pin：S84 曾按 created_at 过滤而真实条目是 time → 概况恒空。
    写入口径与读取口径必须有交叉兼容，任何一侧改名先在此爆红。"""
    ds = _read("py/diary_system.py")
    assert '"time": datetime.now().isoformat()' in ds
    de_src = _read("py/diary_engine.py")
    assert 'e.get("time") or e.get("created_at")' in de_src


def test_today_memories_and_empty_day(monkeypatch):
    async def no_entries(book_id, n=5):
        return []

    async def mems():
        return ["主人今早抱怨昨晚只睡了六个多小时"]

    monkeypatch.setattr(de, "get_recent_diary_entries", no_entries)
    monkeypatch.setattr(de, "_fetch_today_new_memories", mems)
    block = asyncio.run(de.build_today_context("b"))
    assert "新记忆：主人今早抱怨昨晚只睡了六个多小时" in block

    async def none_mem():
        return []
    monkeypatch.setattr(de, "_fetch_today_new_memories", none_mem)
    assert "确实尚未互动" in asyncio.run(de.build_today_context("b"))


def test_today_context_degrades_silently(monkeypatch):
    async def boom(book_id, n=5):
        raise RuntimeError("locked")

    async def boom2():
        raise RuntimeError("m0 down")

    monkeypatch.setattr(de, "get_recent_diary_entries", boom)
    monkeypatch.setattr(de, "_fetch_today_new_memories", boom2)
    assert "确实尚未互动" in asyncio.run(de.build_today_context("b"))


def test_fetch_today_memories_filters_by_created_at(monkeypatch):
    today = datetime.date.today().strftime("%Y-%m-%d")

    class FakeM0:
        def get_all(self, user_id=None, limit=None):
            return {"results": [
                {"memory": "今天发生的事", "created_at": today + "T08:00:00"},
                {"memory": "昨天的旧事", "created_at": "2020-01-01T08:00:00"},
                {"memory": "走 metadata 时间戳", "created_at": None,
                 "metadata": {"timetamp": today + " 09:00:00"}},
            ]}

    def fake_inst(memory_id, cur, settings):
        return FakeM0()

    settings = {"memorySettings": {"is_memory": True, "selectedMemory": "m1"},
                "memories": [{"id": "m1", "name": "x"}]}

    async def fake_load():
        return settings

    monkeypatch.setattr(de, "load_settings", fake_load)
    monkeypatch.setitem(sys.modules, "py.llm_gate",
                        __import__("types").SimpleNamespace(get_mem0_instance=fake_inst))
    out = asyncio.run(de._fetch_today_new_memories())
    assert "今天发生的事" in out and "走 metadata 时间戳" in out
    assert "昨天的旧事" not in out


def test_build_messages_has_weekday_and_today_block(monkeypatch):
    eng = de.DiaryEngine.__new__(de.DiaryEngine)
    eng.config = {}

    async def no_entries(book_id, n=5):
        return [{"type": "chatSummary", "time": _today_at("10:09"), "content": "主人抱怨睡眠"}]

    async def none_mem():
        return []

    monkeypatch.setattr(eng, "_resolve_active_book",
                        lambda: asyncio.sleep(0, result=("book-a", None, "")))
    monkeypatch.setattr(de, "get_recent_diary_entries", no_entries)
    monkeypatch.setattr(de, "_fetch_today_new_memories", none_mem)
    msgs = asyncio.run(eng._build_messages("think"))
    assert "星期" in msgs[0]["content"]
    assert "【今日概况】" in msgs[0]["content"] and "10:09 对话摘要" in msgs[0]["content"]
    assert "本次思绪不妨从" in msgs[-1]["content"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
