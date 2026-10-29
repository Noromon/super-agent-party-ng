# -*- coding: utf-8 -*-
"""S160 token_guard: neutralizer semantics + persistence-boundary wiring.

Hygiene rule for this whole topic: no test file may spell the control-token shape
literally; fixtures are assembled at runtime the same way the module builds its patterns.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # pytest 早期导入的 site-packages py 遮蔽仓库 py 包

from py import token_guard as tg  # noqa: E402

_LT = chr(60)
_PB = chr(124)
_GT = chr(62)
_ZW = "\u200b"


def _tag(name):
    return _LT + _PB + name + _PB + _GT


def _esc_tag(name):
    return _LT + _ZW + _PB + name + _PB + _GT


def _n_end():
    return "im" + "_" + "end"


def _n_start():
    return "im" + "_" + "start"


def _n_eot():
    return "end" + "oftext"


class TestNeutralize:
    def setup_method(self):
        tg.reset_stats()

    def test_plain_text_untouched(self):
        t = "normal text with | pipes, <angle> and code like a|>b, plus string_trim_end"
        assert tg.neutralize(t) == t

    def test_shape_replaced(self):
        out = tg.neutralize("x " + _tag(_n_end()) + " y")
        assert tg.PLACEHOLDER in out
        assert tg.detect(out) == (0, 0)

    def test_escaped_spelling_rescued(self):
        out = tg.neutralize("look: " + _esc_tag(_n_end()))
        assert tg.detect(out) == (0, 0)
        assert _ZW not in out

    def test_bare_names_replaced_with_boundaries(self):
        out = tg.neutralize(f"{_n_end()} and {_n_start()} and {_n_eot()}")
        assert out.count(tg.PLACEHOLDER) == 3
        ident = "string_" + "trim_end"
        assert tg.neutralize(f"call {ident}()") == f"call {ident}()"
        assert tg.neutralize(_n_end() + "suffix") == _n_end() + "suffix"

    def test_idempotent(self):
        once = tg.neutralize("a" + _tag(_n_end()) + _esc_tag(_n_start()) + _n_eot())
        assert tg.neutralize(once) == once

    def test_stats(self):
        tg.neutralize(_tag(_n_end()) + _n_end(), store="unit")
        st = tg.get_stats()
        assert st["by_store"]["unit"] >= 2
        assert st["total"] >= 2

    def test_deep(self):
        blob = {"conversations": [{"messages": [
            {"role": "assistant", "content": ["text", _tag(_n_end())]},
            {"role": "user", "content": "clean"},
        ]}]}
        out = tg.neutralize_deep(blob)
        assert out["conversations"][0]["messages"][0]["content"][1] == tg.PLACEHOLDER
        assert out["conversations"][0]["messages"][1]["content"] == "clean"


class TestApplyEosGuard:
    def _settings(self, **over):
        cfg = {"enabled": True, "softBias": -30, "eosTokenIds": [248044, 248046]}
        cfg.update(over)
        return {"eosGuard": cfg}

    def test_loopback_enabled(self):
        p = tg.apply_eos_guard({}, self._settings(), "http://127.0.0.1:8080/v1")
        assert p["logit_bias"] == {"248044": -30.0, "248046": -30.0}

    def test_disabled_noop(self):
        p = tg.apply_eos_guard({}, self._settings(enabled=False), "http://127.0.0.1:8080/v1")
        assert "logit_bias" not in p

    def test_non_loopback_noop(self):
        p = tg.apply_eos_guard({}, self._settings(), "https://api.example.com/v1")
        assert "logit_bias" not in p

    def test_user_logit_bias_wins(self):
        p = tg.apply_eos_guard({"logit_bias": {"1": 1}}, self._settings(), "http://localhost/v1")
        assert p["logit_bias"] == {"1": 1}

    def test_bad_config_noop(self):
        assert "logit_bias" not in tg.apply_eos_guard({}, self._settings(softBias=0), "http://127.0.0.1/v1")
        assert "logit_bias" not in tg.apply_eos_guard({}, self._settings(softBias=5), "http://127.0.0.1/v1")
        assert "logit_bias" not in tg.apply_eos_guard({}, self._settings(eosTokenIds=[]), "http://127.0.0.1/v1")

    def test_ids_sanitized(self):
        p = tg.apply_eos_guard({}, self._settings(eosTokenIds=["7", 7, "x", -1, 9]), "http://127.0.0.1/v1")
        assert p["logit_bias"] == {"7": -30.0, "9": -30.0}


class TestWiring:
    """Source-level parity checks: every persistence chokepoint passes through the guard."""

    def _src(self, *rel):
        return (ROOT.joinpath(*rel)).read_text(encoding="utf-8")

    def _func_src(self, src, marker):
        assert marker in src, marker + " missing"

    def test_server_hooks(self):
        src = self._src("server.py")
        self._func_src(src, 'from py.token_guard import neutralize as _neutralize, neutralize_deep, apply_eos_guard')
        self._func_src(src, 'store="mem0-add"')
        self._func_src(src, 'store="mem0-add-complete"')
        self._func_src(src, 'store="group-memory"')
        self._func_src(src, 'store="diary-buffer"')
        self._func_src(src, 'store="diary-recall"')
        self._func_src(src, 'store="group-recall"')
        self._func_src(src, 'neutralize_deep(relevant_memories, "recall")')
        self._func_src(src, "apply_eos_guard(reasoner_extra, settings")
        assert src.count("apply_eos_guard(reasoner_extra") == 2
        self._func_src(src, "is_quarantined: bool = False")
        assert src.count("and not request.is_quarantined") >= 4

    def test_py_module_hooks(self):
        self._func_src(self._src("py", "diary_system.py"), 'neutralize(entry[key], "diary")')
        self._func_src(self._src("py", "turn_log.py"), 'neutralize_deep(msg, "turn-log")')
        self._func_src(self._src("py", "diary_engine.py"), 'store="diary-today"')
        gs = self._src("py", "get_setting.py")
        self._func_src(gs, "def _neutralize_covs")
        assert gs.count("_neutralize_covs(") >= 3

    def test_template_has_eos_guard(self):
        tpl = json.loads(self._src("config", "settings_template.json"))
        cfg = tpl["eosGuard"]
        assert cfg["enabled"] is False
        assert cfg["softBias"] == -30
        assert isinstance(cfg["eosTokenIds"], list) and cfg["eosTokenIds"]

    def test_topic_files_contain_no_literal_shape(self):
        """The guard files themselves must not carry the contamination shape."""
        for rel in [("py", "token_guard.py"), "server.py", ("py", "get_setting.py"),
                    ("py", "diary_system.py"), ("py", "turn_log.py"), ("py", "diary_engine.py"),
                    ("scripts", "scrub_special_tokens.py"), ("tests", "test_token_guard.py"),
                    ("config", "settings_template.json")]:
            src = self._src(*(rel if isinstance(rel, tuple) else (rel,)))
            shapes, names = tg.detect(src)
            assert shapes == 0, f"shape literal found in {rel}"
            assert names == 0, f"bare token name found in {rel}"
