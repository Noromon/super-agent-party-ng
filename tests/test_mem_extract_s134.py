# -*- coding: utf-8 -*-
"""S134：idx2id 不变式自动补齐 + mem0 JSON 出口修复/观测 + mem0 日志接入。"""
import json
import logging
import os
import sys

if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from py.memory_store import pad_idx2id, repair_loose_json  # noqa: E402


class TestPadIdx2Id:
    def test_fills_missing_and_idempotent(self):
        m = {0: "u0", 2: "u2"}
        n = pad_idx2id(m, 5)
        assert n == 3
        assert set(m) == {0, 1, 2, 3, 4}
        assert pad_idx2id(m, 5) == 0
        assert m[0] == "u0" and m[1].startswith("s134-orphan-")

    def test_placeholder_invisible_to_docstore(self):
        m = {}
        pad_idx2id(m, 3)
        docstore = {"u0": {}}
        assert all(docstore.get(v) is None for v in m.values())


class TestRepairLooseJson:
    def test_missing_comma_between_objects(self):
        bad = '{"memory":[{"id":"0","text":"a"} {"id":"1","text":"b"}]}'
        fixed = repair_loose_json(bad)
        assert fixed is not None
        assert len(json.loads(fixed)["memory"]) == 2

    def test_truncated_tail_closes(self):
        bad = '{"memory":[{"id":"0","text":"a"},{"id":"1","tex'
        fixed = repair_loose_json(bad)
        assert fixed is not None
        assert json.loads(fixed)["memory"][0]["id"] == "0"

    def test_valid_json_untouched(self):
        good = '{"facts": ["x, y", "z"]}'
        fixed = repair_loose_json(good)
        assert json.loads(fixed) == json.loads(good)

    def test_comma_after_string_value(self):
        bad = '{"a":"v" "b":2}'
        fixed = repair_loose_json(bad)
        assert fixed is not None and json.loads(fixed)["b"] == 2

    def test_hopeless_returns_none(self):
        assert repair_loose_json("totally not json {{{") is None


class TestPatchMem0ExtractJson:
    def test_patch_idempotent_and_repairs(self):
        import mem0.memory.main as mmm
        from py.llm_gate import patch_mem0_extract_json
        orig = mmm.extract_json
        patch_mem0_extract_json()
        assert mmm.extract_json is not orig
        patch_mem0_extract_json()
        bad = '```json\n{"memory":[{"id":"0","text":"a"} {"id":"1","text":"b"}]}\n```'
        out = mmm.extract_json(bad)
        assert len(json.loads(out)["memory"]) == 2
        good = '{"facts":["ok"]}'
        assert json.loads(mmm.extract_json(good))["facts"] == ["ok"]


class TestStaticPins:
    def test_llm_gate_custom_prompts_wired(self):
        src = open(os.path.join(ROOT, "py", "llm_gate.py"), encoding="utf-8").read()
        assert 'config["custom_fact_extraction_prompt"] = _MEM0_FACT_PROMPT' in src
        assert 'config["custom_update_memory_prompt"] = _MEM0_UPDATE_PROMPT' in src
        assert "patch_mem0_extract_json()" in src

    def test_memoryconfig_accepts_fields(self):
        from mem0.configs.base import MemoryConfig
        cfg = MemoryConfig(custom_fact_extraction_prompt="a", custom_update_memory_prompt="b")
        assert cfg.custom_fact_extraction_prompt == "a"

    def test_log_setup_mounts_mem0_logger(self):
        src = open(os.path.join(ROOT, "py", "log_setup.py"), encoding="utf-8").read()
        assert 'logging.getLogger("mem0")' in src
        setup_src = src
        assert "for lg in (logger, mem0_logger)" in setup_src

    def test_log_setup_functional(self, tmp_path):
        from py.log_setup import setup_logger
        saved_app = logging.getLogger("app").handlers[:]
        saved_mem0 = logging.getLogger("mem0").handlers[:]
        try:
            logging.getLogger("app").handlers.clear()
            logging.getLogger("mem0").handlers.clear()
            setup_logger(str(tmp_path))
            assert logging.getLogger("mem0").handlers
            logging.getLogger("mem0").warning("s134-probe")
            for h in logging.getLogger("mem0").handlers:
                h.flush()
            body = open(os.path.join(str(tmp_path), "backend.log"), encoding="utf-8").read()
            assert "s134-probe" in body
        finally:
            for lg, saved in ((logging.getLogger("app"), saved_app),
                              (logging.getLogger("mem0"), saved_mem0)):
                lg.handlers.clear()
                lg.handlers.extend(saved)
