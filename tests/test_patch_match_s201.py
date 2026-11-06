# -*- coding: utf-8 -*-
"""S201 py/patch_match 共享补丁内核：分级匹配/歧义安全/多编辑原子/诊断回显。"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.patch_match import apply_edits  # noqa: E402


def _e(old, new, **kw):
    return dict(old_string=old, new_string=new, **kw)


class TestExactLevel:
    def test_single_hit(self):
        r = apply_edits("alpha\nbeta\ngamma", [_e("beta", "BETA")])
        assert r.ok and "BETA" in r.content and "beta" not in r.content
        assert "exact match" in r.report and r.edit_lines == [2]

    def test_ambiguous_requires_replace_all(self):
        r = apply_edits("x\nx\nx", [_e("x", "y")])
        assert not r.ok and "ambiguous" in r.report and "3 times" in r.report
        assert not r.content

    def test_replace_all_counts(self):
        r = apply_edits("x\nx\nx", [_e("x", "y", replace_all=True)])
        assert r.ok and r.content == "y\ny\ny" and "3 replacement" in r.report

    def test_empty_old_rejected(self):
        r = apply_edits("abc", [_e("", "y")])
        assert not r.ok and "write tool" in r.report


class TestLineEndingLevels:
    def test_crlf_file_lf_old_preserves_style(self):
        r = apply_edits("a\r\nb\r\nc", [_e("b", "B")])
        assert r.ok and r.content == "a\r\nB\r\nc"
        assert "exact match" in r.report  # 单行无换行差异仍属精确级

    def test_lf_old_multiline_into_crlf_file(self):
        r = apply_edits("a\r\nb\r\nc\r\n", [_e("a\nb", "X\nY")])
        assert r.ok and "CRLF line endings adapted" in r.report
        assert r.content == "X\r\nY\r\nc\r\n"

    def test_crlf_old_into_lf_file(self):
        r = apply_edits("a\nb\nc", [_e("a\r\nb", "X")])
        assert r.ok and r.content == "X\nc"
        assert "normalized to LF" in r.report


class TestWindowLevels:
    def test_indentation_insensitive_applies(self):
        content = "def f():\n    return 1\n"
        r = apply_edits(content, [_e("def f():\nreturn 1", "def f():\n    return 2")])
        assert r.ok and "return 2" in r.content
        assert "whitespace/indentation" in r.report

    def test_approximate_unique_applies(self):
        content = "alpha one\nbeta two\ngamma three\ndelta four\n"
        r = apply_edits(content, [_e("beta twoo\ngamma three", "B G")])
        assert r.ok and "approximate match" in r.report and "B G" in r.content

    def test_below_threshold_no_apply(self):
        content = "alpha one\nbeta two\ngamma three\n"
        r = apply_edits(content, [_e("zzz nine\nqqq ten", "X")])
        assert not r.ok and "not found" in r.report

    def test_near_miss_echoes_actual_with_line_numbers(self):
        content = "head\n    target_line(arg=1)\n  tail\n"
        r = apply_edits(content, [_e("    target_line(arg=22, flag=True, other=None)", "X")])
        assert not r.ok and "arg=1" in r.report and "2|" in r.report
        assert "VERBATIM" in r.report


class TestMultiEdit:
    def test_sequential_apply(self):
        r = apply_edits("a\nb\nc", [_e("a", "A"), _e("b", "B"), _e("c", "C")])
        assert r.ok and r.content == "A\nB\nC"

    def test_second_edit_sees_first_result(self):
        r = apply_edits("x", [_e("x", "y"), _e("y", "z")])
        assert r.ok and r.content == "z"

    def test_atomicity_second_fails_nothing_applied(self):
        r = apply_edits("a\nb", [_e("a", "A"), _e("nope", "N")])
        assert not r.ok and not r.content and "edit 2" in r.report

    def test_bad_edit_spec(self):
        r = apply_edits("a", [_e("a", "b"), {"new_string": "no old"}])
        assert not r.ok and "edit 2" in r.report


class TestReports:
    def test_success_includes_diff(self):
        r = apply_edits("keep\nold\nkeep2", [_e("old", "new")])
        assert r.ok and "-old" in r.report and "+new" in r.report

    def test_delete_with_empty_new(self):
        r = apply_edits("a\nb\nc", [_e("b\n", "")])
        assert r.ok and "b" not in r.content

import asyncio  # noqa: E402


def _run_local(tmp_path, monkeypatch, **kw):
    import py.cli_tool as ct
    monkeypatch.setattr(ct, "_get_current_cwd", lambda: asyncio.sleep(0, str(tmp_path)))
    return asyncio.run(ct.edit_file_patch_tool_local(**kw))


class TestLocalToolFunctional:
    def test_single_edit_writes_and_echoes_diff(self, tmp_path, monkeypatch):
        (tmp_path / "a.txt").write_text("keep\nold\nkeep2", encoding="utf-8")
        out = _run_local(tmp_path, monkeypatch, path="a.txt", old_string="old", new_string="new")
        assert "Patched" in out and "-old" in out and "+new" in out
        assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "keep\nnew\nkeep2"

    def test_edits_array_atomic_batch(self, tmp_path, monkeypatch):
        (tmp_path / "b.txt").write_text("a\nb\nc", encoding="utf-8")
        out = _run_local(tmp_path, monkeypatch, path="b.txt",
                         edits=[{"old_string": "a", "new_string": "A"},
                                {"old_string": "b", "new_string": "B"}])
        assert "Patched" in out and (tmp_path / "b.txt").read_text(encoding="utf-8") == "A\nB\nc"

    def test_edits_array_failure_writes_nothing(self, tmp_path, monkeypatch):
        (tmp_path / "c.txt").write_text("a\nb\nc", encoding="utf-8")
        out = _run_local(tmp_path, monkeypatch, path="c.txt",
                         edits=[{"old_string": "a", "new_string": "A"},
                                {"old_string": "zzz", "new_string": "Z"}])
        assert out.startswith("[Error]") and "edit 2" in out
        assert (tmp_path / "c.txt").read_text(encoding="utf-8") == "a\nb\nc"

    def test_ambiguous_aborts_with_locations(self, tmp_path, monkeypatch):
        (tmp_path / "d.txt").write_text("dup\nx\ndup\n", encoding="utf-8")
        out = _run_local(tmp_path, monkeypatch, path="d.txt", old_string="dup", new_string="y")
        assert "ambiguous" in out and "line 1" in out and "line 3" in out
        assert (tmp_path / "d.txt").read_text(encoding="utf-8") == "dup\nx\ndup\n"
        out2 = _run_local(tmp_path, monkeypatch, path="d.txt", old_string="dup",
                          new_string="y", replace_all=True)
        assert "Patched" in out2 and "2 replacement" in out2

    def test_mismatch_echoes_snippet_file_untouched(self, tmp_path, monkeypatch):
        (tmp_path / "e.txt").write_text("head\n    target_line(arg=1)\n  tail\n", encoding="utf-8")
        out = _run_local(tmp_path, monkeypatch, path="e.txt",
                         old_string="    target_line(arg=22, flag=True, other=None)", new_string="X")
        assert "arg=1" in out and "2|" in out
        assert "target_line(arg=1)" in (tmp_path / "e.txt").read_text(encoding="utf-8")


class TestSchemaUpgrade:
    def test_both_registries_optional_params(self):
        from py.cli_tool import LOCAL_TOOLS_REGISTRY, TOOLS_REGISTRY
        for key, reg in (("edit_file_patch", TOOLS_REGISTRY),
                         ("edit_file_patch_local", LOCAL_TOOLS_REGISTRY)):
            fn = reg[key]["function"]
            props = fn["parameters"]["properties"]
            assert fn["parameters"]["required"] == ["path"]
            assert "edits" in props and "replace_all" in props
            assert "atomic" in fn["description"] and "closest actual snippet" in fn["description"]

    def test_wsl_shares_local_object(self):
        from py.cli_tool import LOCAL_TOOLS_REGISTRY, WSL_TOOLS_REGISTRY
        assert WSL_TOOLS_REGISTRY["edit_file_patch_wsl"] is LOCAL_TOOLS_REGISTRY["edit_file_patch_local"]

    def test_prompt_contract_updated(self):
        src = (_ROOT / "py" / "agent_prompt.py").read_text(encoding="utf-8")
        assert "retry the patch directly from that echo" in src
        assert "edits array" in src