# -*- coding: utf-8 -*-
"""S133：mem0 faiss idx2id 映射修复工具 + 自检护栏 + 日记 recall_query。"""
import os
import sys

import numpy as np
import pytest

if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from py.memory_store import idx2id_health, rebuild_idx2id  # noqa: E402


def _orth(n=16, seed=7):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.standard_normal((n, n)).astype("float32"))
    return q


class TestRebuildIdx2Id:
    def test_perfect_match_with_orphan_positions(self):
        q = _orth()
        pos = [0, 1, 2, 5, 7, 9, 12, 15]
        keys = [f"u{i}" for i in range(len(pos))]
        mapping, scores = rebuild_idx2id(q, keys, q[pos], tau=0.995)
        assert len(mapping) == len(pos)
        assert all(mapping[p] == keys[i] for i, p in enumerate(pos))
        assert all(s >= 0.995 for s in scores.values())

    def test_noise_rejected_not_misattributed(self):
        q = _orth()
        rng = np.random.default_rng(11)
        noise = rng.standard_normal((1, 16)).astype("float32")
        mapping, _ = rebuild_idx2id(q, ["ghost"], noise, tau=0.995)
        assert mapping == {}

    def test_duplicate_text_one_to_one(self):
        q = _orth()
        dup = np.stack([q[3], q[3]])
        mapping, _ = rebuild_idx2id(q, ["a", "b"], dup, tau=0.995)
        assert len(mapping) == 1 and mapping.get(3) in ("a", "b")

    def test_dim_mismatch_raises(self):
        with pytest.raises(ValueError):
            rebuild_idx2id(np.ones((2, 4), np.float32), ["a"], np.ones((1, 8), np.float32))

    def test_keys_rows_mismatch_raises(self):
        with pytest.raises(ValueError):
            rebuild_idx2id(np.ones((2, 4), np.float32), ["a", "b"], np.ones((1, 4), np.float32))


class TestIdx2IdHealth:
    def test_corrupted_like_production(self):
        h = idx2id_health(5338, 5328, 7)
        assert not h["ok"] and h["orphan"] == 5331

    def test_small_store_tolerates_small_orphans(self):
        assert idx2id_health(120, 100, 100)["ok"]

    def test_ratio_gate(self):
        assert not idx2id_health(10000, 9000, 500)["ok"]


class TestMemGuardWarning:
    def test_skips_non_faiss_like(self):
        from py.llm_gate import _idx2id_guard_warning
        _idx2id_guard_warning(object(), "x" * 20)

    def test_skips_healthy(self):
        from py import llm_gate

        class V:
            class index:
                ntotal = 100
            docstore = {str(i): {} for i in range(100)}
            index_to_id = {i: str(i) for i in range(100)}

        class M:
            vector_store = V()

        msgs = []
        real = llm_gate.logging.getLogger("app").warning
        llm_gate.logging.getLogger("app").warning = lambda m, *a, **k: msgs.append(m)
        try:
            _idx2id_guard_warning = llm_gate._idx2id_guard_warning
            _idx2id_guard_warning(M(), "deadbeef-1234")
            assert msgs == []
            V.index_to_id = {1: "1"}
            _idx2id_guard_warning(M(), "deadbeef-1234")
            assert msgs and "repair_memory_idx2id" in msgs[0]
        finally:
            llm_gate.logging.getLogger("app").warning = real


class TestRecallQueryWiring:
    def test_chatrequest_field(self):
        src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
        assert "\n    recall_query: str = None\n" in src

    def test_both_search_sites_use_recall_query(self):
        src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
        assert src.count('query=(getattr(request, "recall_query", None) or user_prompt)') == 2

    def test_diary_engine_passes_seed(self):
        src = open(os.path.join(ROOT, "py", "diary_engine.py"), encoding="utf-8").read()
        assert '"recall_query": recall_seed' in src
        assert "return messages, seed" in src
        assert "messages, recall_seed = await self._build_messages(action)" in src

    def test_script_cli_exists_and_compiles(self):
        import py_compile
        py_compile.compile(os.path.join(ROOT, "scripts", "repair_memory_idx2id.py"), doraise=True)
