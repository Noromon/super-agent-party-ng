"""S322：search 可观测性与真错上报。

事故背景：8/8 检索 rows=0，工具把「路径不存在」与「真没命中」都伪装成
No matches，模型反复碰壁后想收尾（叠加完成闸门事故=用户视角"擅自停手"）。
S322 修复：rc 异常且 target 不存在 → notfound 真错；0 命中返回带
searched 头（目标绝对路径+可扫描文件数）；[Search] 日志带 target/rc/stderr。
"""
import asyncio
import io
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py import cli_tool  # noqa: E402
from py.tool_output_store import find_ripgrep  # noqa: E402

CLI_SRC = (_ROOT / "py" / "cli_tool.py").read_text(encoding="utf-8")


class _Proc:
    def __init__(self, lines, rc, stderr=""):
        self.stdout = iter(lines)
        self.stderr = io.StringIO(stderr)
        self.returncode = rc
        self._rc = rc

    def poll(self):
        return self._rc

    def kill(self):
        self.returncode = self._rc

    def wait(self, timeout=None):
        return self._rc


class TestNotFoundStatus:
    def _collect(self, monkeypatch, target, rc=2, stderr=""):
        monkeypatch.setattr(cli_tool.subprocess, "Popen",
                            lambda *a, **k: _Proc([], rc, stderr))
        return cli_tool._rg_search_collect("rg", ".", target, "p", "", False, 50)

    def test_rc2_missing_target_notfound(self, monkeypatch, tmp_path):
        _, _, status = self._collect(monkeypatch, str(tmp_path / "gone"),
                                     stderr="rg: gone: No such file or directory (os error 3)")
        assert status == "notfound"

    def test_rc2_existing_target_stays_fail(self, monkeypatch, tmp_path):
        _, _, status = self._collect(monkeypatch, str(tmp_path))
        assert status == "fail"

    def test_fail_log_carries_target_and_stderr(self, monkeypatch, tmp_path, caplog):
        caplog.set_level("INFO", logger="app")
        self._collect(monkeypatch, str(tmp_path / "gone"), stderr="rg: nope (os error 3)")
        joined = "\n".join(caplog.messages)
        assert "notfound" in joined and "target=" in joined and "os error 3" in joined


class TestFilesCount:
    def test_counts_respecting_skip_dirs(self, tmp_path):
        rg = find_ripgrep()
        if not rg:
            pytest.skip("no ripgrep")
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        nm = tmp_path / "node_modules" / "pkg"
        nm.mkdir(parents=True)
        (nm / "b.js").write_text("y", encoding="utf-8")
        assert cli_tool._rg_files_count(rg, str(tmp_path), str(tmp_path)) == 1

    def test_single_file_target_counts_one(self, tmp_path):
        rg = find_ripgrep()
        if not rg:
            pytest.skip("no ripgrep")
        f = tmp_path / "only.txt"
        f.write_text("z", encoding="utf-8")
        assert cli_tool._rg_files_count(rg, str(tmp_path), str(f)) == 1


class TestSearchOneDiagnostics:
    def _patch_cwd(self, monkeypatch, tmp_path):
        async def fake_cwd():
            return str(tmp_path)
        monkeypatch.setattr(cli_tool, "_get_current_cwd", fake_cwd)

    def test_notfound_returns_true_error_not_no_match(self, monkeypatch, tmp_path):
        if not find_ripgrep():
            pytest.skip("no ripgrep")
        self._patch_cwd(monkeypatch, tmp_path)
        r = asyncio.run(cli_tool._search_one("needle", "gone_sub"))
        assert r.startswith("[Error] Search target not found")
        assert "NOT 'no matches'" in r and "gone_sub" in r

    def test_zero_match_carries_searched_header(self, monkeypatch, tmp_path):
        if not find_ripgrep():
            pytest.skip("no ripgrep")
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        self._patch_cwd(monkeypatch, tmp_path)
        r = asyncio.run(cli_tool._search_one("needle_zzz_qq", "."))
        assert r.startswith(f"searched {tmp_path} (files_scanned=1) — 0 matches.")
        assert "No matches for this pattern" in r

    def test_py_fallback_header_uses_n_files(self, monkeypatch, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        self._patch_cwd(monkeypatch, tmp_path)
        monkeypatch.setattr("py.tool_output_store.find_ripgrep", lambda: None)
        r = asyncio.run(cli_tool._search_one("needle_zzz_qq", "."))
        assert "(files_scanned=1) — 0 matches." in r

    def test_py_collect_returns_n_files(self, tmp_path):
        (tmp_path / "a.py").write_text("x", encoding="utf-8")
        (tmp_path / "b.md").write_text("y", encoding="utf-8")
        rows, capped, n = cli_tool._py_search_collect(
            str(tmp_path), str(tmp_path), re.compile("q"), "", 10)
        assert rows == [] and capped is False and n == 2


class TestPins:
    def test_ok_and_timeout_logs_carry_target(self):
        seg = CLI_SRC[CLI_SRC.index("def _rg_search_collect("):]
        seg = seg[:seg.index("def _rg_files_count(")]
        assert "status=ok dur_ms=%d rows=%d capped=%s target=%s" in seg
        assert "status=timeout dur_ms=%d pattern=%r target=%s" in seg

    def test_notfound_never_falls_back_to_py(self):
        seg = CLI_SRC[CLI_SRC.index("def _search_one("):]
        seg = seg[:seg.index("def _normalize_glob_pattern(")]
        i_nf = seg.index('status == "notfound"')
        i_py = seg.index('status != "ok"')
        assert i_nf < i_py  # notfound 提前 return，不进 py 降级

    def test_skip_globs_shared(self):
        seg = CLI_SRC[CLI_SRC.index("def _rg_files_count("):]
        assert "_rg_skip_globs()" in seg
