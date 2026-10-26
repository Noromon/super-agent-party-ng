# -*- coding: utf-8 -*-
"""S83：日记长期记忆召回多样化——思绪种子 + 日记专用抽样。"""
import ast
import asyncio
import io
import os
import random
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s83_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

import py.diary_engine as de  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def _extract_server_fn(name):
    src = _read("server.py")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            ns = {"random": random}
            exec(compile(seg, "<extract>", "exec"), ns)  # noqa: S102
            return ns[name]
    raise AssertionError(f"{name} not found at server.py module level")


# ---------------- B：_diary_recall_sample 行为测 ----------------

def test_sample_subset_and_count():
    fn = _extract_server_fn("_diary_recall_sample")
    payload = {"results": [{"id": i} for i in range(6)]}
    out = fn(payload, 2)
    assert len(out["results"]) == 2
    assert all(r["id"] in range(6) for r in out["results"])
    assert payload["results"].__len__() == 6           # 原对象不破坏


def test_sample_diverse_across_seeds():
    fn = _extract_server_fn("_diary_recall_sample")
    payload = {"results": [{"id": i} for i in range(9)]}
    seen = set()
    for s in range(8):
        random.seed(s)
        seen.add(tuple(sorted(r["id"] for r in fn(payload, 2)["results"])))
    assert len(seen) >= 3                              # 多次抽样确实不同


def test_sample_short_circuits():
    fn = _extract_server_fn("_diary_recall_sample")
    few = {"results": [{"id": 0}]}
    assert fn(few, 3) is few
    assert fn({"results": []}, 1) == {"results": []}
    assert fn(None, 1) is None                          # 异常结构原样返回
    assert fn({"results": [{"id": 1}, {"id": 2}]}, 2) == {"results": [{"id": 1}, {"id": 2}]}


def test_server_diary_branch_pins():
    src = _read("server.py")
    assert '_diary_recall_sample(' in src
    assert 'getattr(request, "platform", "") == "diary"' in src
    assert "max(memoryLimit * 3, 6)" in src
    assert src.count("def _diary_recall_sample") == 1
    # 主对话（流式路径 L3899 一带）不受影响：仍是 limit=memoryLimit
    assert src.count("limit=memoryLimit") >= 1


# ---------------- A：思绪种子 ----------------

def test_seed_pool_and_prev_quote(monkeypatch):
    async_calls = []

    async def fake_recent(book_id, n=5):
        async_calls.append((book_id, n))
        return [{"content": "甲" * 80 + "\n第二行内容"}]

    monkeypatch.setattr(de, "get_recent_diary_entries", fake_recent)
    random.seed(0)
    seed = asyncio.run(de.build_recall_seed("book-x", prev_ratio=1.0))
    assert "上一篇日记你写到" in seed and "甲" in seed
    assert "\n" not in seed                              # 换行已压平
    assert "甲" * 40 in seed and "甲" * 41 not in seed   # 截断恰在 40 字
    assert "第二行" not in seed
    random.seed(7)
    assert asyncio.run(de.build_recall_seed("b", prev_ratio=0.0)) in de.RECALL_SEEDS


def test_seed_fallback_on_read_failure(monkeypatch):
    async def boom(book_id, n=5):
        raise RuntimeError("db locked")

    monkeypatch.setattr(de, "get_recent_diary_entries", boom)
    random.seed(3)
    assert asyncio.run(de.build_recall_seed("b", prev_ratio=1.0)) in de.RECALL_SEEDS


def test_build_messages_async_with_seed(monkeypatch):
    eng = de.DiaryEngine.__new__(de.DiaryEngine)
    eng.config = {}
    monkeypatch.setattr(eng, "_resolve_active_book",
                        lambda: asyncio.sleep(0, result=("book-a", None, "")))
    seq = iter(de.RECALL_SEEDS)
    monkeypatch.setattr(random, "random", lambda: 0.99)   # 恒走词池
    monkeypatch.setattr(random, "choice", lambda pool: next(iter(seq)))
    msgs, seed = asyncio.run(eng._build_messages("think"))
    user = msgs[-1]["content"]
    assert "本次思绪不妨从" in user and user.startswith("[system]:")
    assert msgs[0]["role"] == "system"
    assert seed in user   # S133b：seed 同时作为 recall_query 单独回传


def test_two_triggers_query_diversity(monkeypatch):
    eng = de.DiaryEngine.__new__(de.DiaryEngine)
    eng.config = {}
    monkeypatch.setattr(eng, "_resolve_active_book",
                        lambda: asyncio.sleep(0, result=("book-a", None, "")))
    monkeypatch.setattr(random, "random", lambda: 0.99)
    pool = list(de.RECALL_SEEDS)
    picked = iter([pool[0], pool[1]])
    monkeypatch.setattr(random, "choice", lambda _p: next(picked))
    m1, s1 = asyncio.run(eng._build_messages("think"))
    m2, s2 = asyncio.run(eng._build_messages("think"))
    assert s1 != s2 and m1[-1]["content"] != m2[-1]["content"]  # 种子与 query 都变 → 召回不同


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
