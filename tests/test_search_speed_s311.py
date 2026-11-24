# S311: search_files 提速——rg 流式早停/超时不降级/默认排除目录/计时日志。
# 事故（2026-11-24 13:13/13:14 日志）：两次 search 各 ~63s（rg 全树扫+60s
# 超时后 py 静默全树重扫=完成前 IO 爆发），模型弃用工具改用 findstr。
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import cli_tool  # noqa: E402

CLI_SRC = (_ROOT / "py" / "cli_tool.py").read_text(encoding="utf-8")


class _FakeStd:
    def __init__(self, src):
        self._src = src

    def __iter__(self):
        return iter(self._src() if callable(self._src) else self._src)

    def close(self):
        pass


class _BlockStream:
    """无输出且阻塞的假 stdout：watchdog kill（holder.dead）后才 EOF。"""

    def __init__(self, holder, max_wait=2.0):
        self.holder = holder
        self.max_wait = max_wait
        self.t0 = time.monotonic()

    def __iter__(self):
        return self

    def __next__(self):
        while time.monotonic() - self.t0 < self.max_wait:
            if self.holder.get("dead"):
                raise StopIteration
            time.sleep(0.01)
        raise StopIteration

    def close(self):
        pass


class _FakeProc:
    def __init__(self, gen, rc=0, killable=True):
        self.stdout = _FakeStd(gen)
        self.returncode = rc
        self._rc = rc
        self.kill_count = 0
        self._dead = not killable
        self.killed_early = False

    def poll(self):
        return None if not self._dead else self.returncode

    def kill(self):
        self.kill_count += 1
        self.killed_early = True
        self._dead = True
        self.returncode = -9 if self._rc == 0 else self._rc

    def wait(self, timeout=None):
        self._dead = True
        return self.returncode


def _gen_lines(n, holder=None):
    def g():
        for i in range(n):
            if holder is not None and holder.get("stop"):
                return
            yield "dir/f%d.py:%d:hit me here\n" % (i, i + 1)
    return g


class TestParser:
    def test_parse_and_sort(self):
        lines = ["b.py:5:x\n", "a.py:2:y\n", "a.py:10:z\n", "garbage\n"]
        rows, capped = cli_tool._rg_rows_from_lines(iter(lines), 99)
        assert rows == ["a.py:2:y", "a.py:10:z", "b.py:5:x"]
        assert capped is False

    def test_char_cap(self):
        rows, _ = cli_tool._rg_rows_from_lines(["a.py:1:" + "L" * 500], 10)
        assert len(rows[0].split(":", 2)[2]) <= cli_tool._SEARCH_MAX_LINE_CHARS

    def test_early_stop_consumes_only_want(self):
        consumed = []

        def g():
            for i in range(10000):
                consumed.append(i)
                yield "a%d.py:1:x\n" % i
        rows, capped = cli_tool._rg_rows_from_lines(g(), 5)
        assert len(rows) == 5 and capped is True
        assert len(consumed) == 5  # 早停=不再消费（子进程随后被 kill）


class TestCollect:
    def test_ok_path(self, monkeypatch):
        proc = _FakeProc(_gen_lines(3), rc=1)
        monkeypatch.setattr(cli_tool.subprocess, "Popen", lambda *a, **k: proc)
        rows, capped, status = cli_tool._rg_search_collect(
            "rg", ".", ".", "pat", "", False, 50)
        assert status == "ok" and len(rows) == 3 and capped is False
        assert proc.kill_count >= 1  # 正常结束后仍确保回收

    def test_truncated_kills_and_ok(self, monkeypatch):
        consumed = []

        def g():
            for i in range(10000):
                consumed.append(i)
                yield "a%d.py:1:x\n" % i
        proc = _FakeProc(g)
        monkeypatch.setattr(cli_tool.subprocess, "Popen", lambda *a, **k: proc)
        rows, capped, status = cli_tool._rg_search_collect(
            "rg", ".", ".", "pat", "", False, 5)
        assert status == "ok" and capped is True
        assert len(consumed) == 5 and proc.kill_count >= 1

    def test_timeout_status_not_fail(self, monkeypatch):
        holder = {}
        proc = _FakeProc(_BlockStream(holder))
        monkeypatch.setattr(cli_tool.subprocess, "Popen", lambda *a, **k: proc)
        rows, capped, status = cli_tool._rg_search_collect(
            "rg", ".", ".", "pat", "", False, 50, timeout=0.2)
        assert (rows, capped, status) == (None, False, "timeout")
        assert proc.kill_count >= 1

    def test_fail_rc(self, monkeypatch):
        proc = _FakeProc(_gen_lines(0), rc=2)
        monkeypatch.setattr(cli_tool.subprocess, "Popen", lambda *a, **k: proc)
        assert cli_tool._rg_search_collect("rg", ".", ".", "p", "", False, 50)[2] == "fail"

    def test_launch_error_fail(self, monkeypatch):
        def boom(*a, **k):
            raise OSError("no exec")
        monkeypatch.setattr(cli_tool.subprocess, "Popen", boom)
        assert cli_tool._rg_search_collect("rg", ".", ".", "p", "", False, 50)[2] == "fail"

    def test_cmd_has_new_flags(self, monkeypatch):
        seen = {}

        def fake_popen(cmd, *a, **k):
            seen["cmd"] = cmd
            seen["kw"] = k
            return _FakeProc(_gen_lines(0), rc=1)
        monkeypatch.setattr(cli_tool.subprocess, "Popen", fake_popen)
        cli_tool._rg_search_collect("rg", ".", ".", "p", "", False, 50)
        cmd = " ".join(seen["cmd"])
        assert "--max-filesize" in cmd
        assert "!**/node_modules/**" in cmd and "!**/.git/**" in cmd
        assert "!*.png" in cmd and "!*.exe" in cmd  # S313 ext 负向 glob（对齐 py 引擎）

    def test_s313_stdin_devnull_and_always_path(self, monkeypatch):
        # 真因钉桩：无路径参数+stdin 非 TTY（Electron pipe）→ rg 读 stdin 永久挂起。
        import subprocess as _sp
        seen = {}

        def fake_popen(cmd, *a, **k):
            seen["cmd"] = cmd
            seen["kw"] = k
            return _FakeProc(_gen_lines(0), rc=1)
        monkeypatch.setattr(cli_tool.subprocess, "Popen", fake_popen)
        cli_tool._rg_search_collect("rg", "/cwd", "/cwd", "p", "", False, 50)  # rel="."
        assert seen["kw"].get("stdin") == _sp.DEVNULL
        assert seen["cmd"][-2:] == ["--", "."]
        cli_tool._rg_search_collect("rg", "/cwd", "/cwd/sub", "p", "", False, 50)
        assert seen["cmd"][-2:] == ["--", "sub"]


class TestCaller:
    def test_timeout_no_silent_rescan(self):
        seg = CLI_SRC[CLI_SRC.index("def _search_one"):]
        seg = seg[:seg.index("def _normalize_glob_pattern")]
        assert 'status == "timeout"' in seg and "timed out after" in seg
        assert "Narrow the scope" in seg
        assert "status != \"ok\"" in seg  # 仅 fail/缺 rg 才降级 py
        assert "[Search] engine=py" in seg and "[Search] engine=rg" in CLI_SRC


class TestRealRgIntegration:
    def test_bundled_rg_still_searches(self, tmp_path):
        import pytest as _pt
        from py.tool_output_store import find_ripgrep
        rg = find_ripgrep()
        if not rg:
            _pt.skip("no ripgrep")
        f = tmp_path / "hello.py"
        f.write_text("x = 1\nneedle_line = 2\n", encoding="utf-8")
        rows, capped, status = cli_tool._rg_search_collect(
            rg, str(tmp_path), str(tmp_path), "needle_line", "", False, 10)
        assert status == "ok" and len(rows) == 1 and "hello.py:2" in rows[0]
