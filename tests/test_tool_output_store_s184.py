# -*- coding: utf-8 -*-
"""S184：可恢复截断（tool_output_store）+ 跨平台内容检索 + 设置/端点管线钉桩。"""
import asyncio
import json
import os
import sys
import time
import pathlib

ROOT = pathlib.Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _tos():
    from py import tool_output_store as m
    return m


def _read(*p):
    return (ROOT / pathlib.Path(*p)).read_text(encoding="utf-8")


class TestCfg:
    def test_defaults_and_clamp(self):
        m = _tos()
        assert m.tool_output_cfg({}) == (800, 20000, 7)
        assert m.tool_output_cfg({"toolOutput": {"maxOutputLines": 1, "maxOutputBytes": 1,
                                                 "retentionDays": 999}}) == (100, 5000, 90)
        assert m.tool_output_cfg({"toolOutput": "junk"}) == (800, 20000, 7)
        assert m.tool_output_cfg({"toolOutput": {"maxOutputLines": "x"}}) == (800, 20000, 7)


class TestBound:
    def test_small_passthrough(self, tmp_path):
        m = _tos()
        text = "line1\nline2\n"
        assert m.bound_output(text, str(tmp_path), {}) == text
        assert not (tmp_path / ".agent" / "tool_output").exists()

    def test_line_truncate_stashes_and_previews(self, tmp_path):
        m = _tos()
        text = "\n".join("L%04d content" % i for i in range(1, 2001))
        out = m.bound_output(text, str(tmp_path), {})
        assert "L0001" in out and "L2000" in out          # 头尾都在
        assert m.line_count(out) <= 800
        assert "output truncated; full content saved to .agent" in out.replace("\\", "/")
        d = tmp_path / ".agent" / "tool_output"
        files = list(d.iterdir())
        assert len(files) == 1 and files[0].name.startswith("tool_")
        assert files[0].read_text(encoding="utf-8") == text   # 全文无损可回读

    def test_byte_truncate_respects_budget(self, tmp_path):
        m = _tos()
        text = "\n".join("x" * 500 for _ in range(200))   # 200 行 < 800，但字节超限
        out = m.bound_output(text, str(tmp_path), {})
        assert len(out.encode("utf-8")) <= 20000
        assert "output truncated" in out

    def test_idempotent(self, tmp_path):
        m = _tos()
        text = "\n".join("r%d" % i for i in range(5000))
        once = m.bound_output(text, str(tmp_path), {})
        assert m.bound_output(once, str(tmp_path), {}) == once

    def test_no_cwd_degrades(self):
        m = _tos()
        out = m.bound_output("\n".join(map(str, range(5000))), "", {})
        assert "store unavailable" in out


class TestStoreCleanup:
    def test_stats_and_cleanup_by_mtime(self, tmp_path):
        m = _tos()
        d = tmp_path / ".agent" / "tool_output"
        d.mkdir(parents=True)
        old = d / "tool_old.txt"
        old.write_text("x" * 100, encoding="utf-8")
        old_mtime = time.time() - 8 * 86400
        os.utime(old, (old_mtime, old_mtime))
        fresh = d / "tool_fresh.txt"
        fresh.write_text("y" * 50, encoding="utf-8")
        keep = d / "not_tool_file.txt"
        keep.write_text("z", encoding="utf-8")

        assert m.store_stats(str(tmp_path)) == (2, 150)
        n, b = m.cleanup_workspace(str(tmp_path), 7)
        assert (n, b) == (1, 100) and old.exists() is False and fresh.exists()
        # retention=0 → 自动清理关闭
        assert m.cleanup_workspace(str(tmp_path), 0) == (0, 0)
        # 手动 force → 全清（含 fresh，保留非 tool_ 前缀文件）
        n, b = m.cleanup_workspace(str(tmp_path), 0, force=True)
        assert n == 1 and fresh.exists() is False and keep.exists()


class TestRgLocator:
    def test_download_urls(self):
        m = _tos()
        u = m.rg_download_url("win32", "AMD64")
        assert u == ("https://github.com/BurntSushi/ripgrep/releases/download/"
                     "14.1.1/ripgrep-14.1.1-x86_64-pc-windows-msvc.zip")
        assert "aarch64-unknown-linux-musl" in m.rg_download_url("linux", "aarch64")
        assert "apple-darwin" in m.rg_download_url("darwin", "arm64")
        assert m.rg_download_url("plan9", "amd64") is None

    def test_find_order(self, tmp_path, monkeypatch):
        m = _tos()
        fake = tmp_path / "myrg.exe"
        fake.write_text("x", encoding="utf-8")
        monkeypatch.setenv("SAP_RG_PATH", str(fake))
        assert m.find_ripgrep() == str(fake)
        monkeypatch.setenv("SAP_RG_PATH", "")
        monkeypatch.setattr(m.shutil, "which", lambda n: None)
        # 无 bundled、无 PATH → None（若开发者机装了 rg 则跳过断言 None 分支）
        if not (m.rg_bin_dir() / m._rg_name()).is_file():
            assert m.find_ripgrep() is None


class TestSearchTool:
    @staticmethod
    def _ws(tmp_path, monkeypatch, rg=None):
        import py.cli_tool as ct
        (tmp_path / "a.py").write_text("def alpha():\n    pass\ndef beta():\n    pass\n",
                                       encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_text("ALPHA here\nnothing\n", encoding="utf-8")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "s.js").write_text("alpha in node_modules\n", encoding="utf-8")
        (tmp_path / "d.bin").write_bytes(b"\x00alpha\x00")

        async def _cwd():
            return str(tmp_path)
        monkeypatch.setattr(ct, "_get_current_cwd", _cwd)
        from py import tool_output_store as tos
        monkeypatch.setattr(tos, "find_ripgrep", lambda: rg)
        return ct

    def test_substring_and_format(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch)
        out = asyncio.run(ct.search_files_tool_local("alpha"))
        assert out.startswith("a.py:1:")
        assert "node_modules" not in out and "d.bin" not in out

    def test_invalid_regex(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch)
        out = asyncio.run(ct.search_files_tool_local("def (unclosed"))
        assert out.startswith("[Error] Invalid regex")

    def test_case_insensitive_flag(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch)
        # b.txt 内是大写 ALPHA：大小写敏感时只中 a.py，忽略大小写后 b.txt 也中
        assert "sub/b.txt" not in asyncio.run(ct.search_files_tool_local("alpha"))
        assert "sub/b.txt:1:" in asyncio.run(
            ct.search_files_tool_local("alpha", case_insensitive=True))

    def test_include_filter(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch)
        out = asyncio.run(ct.search_files_tool_local("nothing", include="*.txt"))
        assert out.startswith("sub/b.txt:2:") and "a.py" not in out
        out2 = asyncio.run(ct.search_files_tool_local("alpha", include="*.py"))
        assert "a.py:1:" in out2

    def test_offset_paging(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch)
        p1 = asyncio.run(ct.search_files_tool_local("pass", max_results=1))
        assert "Continue with offset=1" in p1
        p2 = asyncio.run(ct.search_files_tool_local("pass", max_results=1, offset=1))
        assert p1.splitlines()[0] != p2.splitlines()[0]
        assert "a.py:4:" in p2

    def test_rg_engine_used(self, tmp_path, monkeypatch):
        ct = self._ws(tmp_path, monkeypatch, rg="FAKE_RG")
        calls = []

        class FakeProc:
            returncode = 0
            stdout = "a.py:1:def alpha():\n"

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return FakeProc()
        monkeypatch.setattr(ct.subprocess, "run", fake_run)
        out = asyncio.run(ct.search_files_tool_local("alpha", include="*.py",
                                                     case_insensitive=True))
        assert calls and calls[0][0] == "FAKE_RG"
        assert "-i" in calls[0] and "--glob" in calls[0] and "*.py" in calls[0]
        assert out.startswith("a.py:1:")


class TestPins:
    def test_server_wiring(self):
        s = _read("server.py") + _read("py/stream_prep.py") + _read("py/stream_engine.py")  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
        assert "def _bound_tool_output(" in s
        assert "await _bound_tool_output_async(response['result'])" in s
        assert s.count('"content": _bound_tool_output(tool_result_text, settings)') >= 2
        assert "TOOL_RESULT_CHAR_CAP" not in s          # 旧盲切常量已除名
        assert "_cap_tool_result" not in s
        # reasoner 摘要通道保持纯截断
        assert "truncate_tool_result(str(_r_result), 8000)" in s
        # 清理循环：启动 + 关停
        assert "_tool_output_sweep_task(first_run=True)" in s
        assert "await _t10_shutdown(temp_sweep_task, tool_output_task)" in s
        assert "tool_output_task.cancel()" in s

    def test_cli_search_core(self):
        c = _read("py", "cli_tool.py")
        assert "def _rg_search_collect(" in c and "def _py_search_collect(" in c
        assert 'cmd = ["git", "grep"' not in c          # 双引擎语义漂移根除
        assert '"offset": {"type": "integer"' in c
        assert '"case_insensitive"' in c

    def test_system_endpoints(self):
        s = _read("py", "routers", "system.py")
        for p in ('"/tool_output_stats"', '"/tool_output_cleanup"',
                  '"/ripgrep_status"', '"/ripgrep_install"'):
            assert p in s
        assert "_rg_install_download" in s and "RG_VERSION_PIN" not in s  # pin 常量只住 store

    def test_settings_pipeline(self):
        assert "['toolOutput', 'toolOutput']," in _read("static", "js", "settings_schema.js")
        defaults = _read("static", "js", "data", "20_brain_settings.js")
        assert "maxOutputLines: 800" in defaults and "retentionDays: 7" in defaults
        tpl = json.loads(_read("config", "settings_template.json"))
        assert tpl["toolOutput"] == {"retentionDays": 7, "maxOutputLines": 800,
                                     "maxOutputBytes": 20000}
        page = _read("static", "templates", "page_system.html")
        for vm in ("toolOutput.retentionDays", "toolOutput.maxOutputLines",
                   "toolOutput.maxOutputBytes"):
            assert 'v-model="%s"' % vm in page
        for fn in ("loadToolOutputStats", "cleanupToolOutput",
                   "loadRipgrepStatus", "installRipgrep"):
            assert fn in _read("static", "js", "methods", "60_system_settings.js")
            assert fn in page or fn in _read("static", "js", "methods", "60_system_settings.js")
        for loc in ("zh-CN", "en-US"):
            src = _read("static", "js", "locales", loc + ".js")
            for k in ("toolOutput", "toolOutputRetentionDesc", "ripgrepInstallBtn",
                      "toolOutputCleanupBtn"):
                assert "'%s'" % k in src, (loc, k)
