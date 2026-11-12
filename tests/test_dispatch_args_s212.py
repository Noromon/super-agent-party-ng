# -*- coding: utf-8 -*-
"""S212：dispatch 参数容错 + read_file_range 参数矛盾 + fake-ip 误导日志。

日志审计实锤（2026-11-12）：
1. 19:24 模型把 CDP evaluate_script 的 script_code 串味灌进
   read_file_range_tool_local → **kwargs splat 裸 TypeError 甩回模型；
2. read_file_range 两个 schema 描述宣称 end_line 有默认值（读到文件尾），
   required 却含 end_line 且函数签名无默认——模型省略必炸；
3. fake-ip 代理把域名解析进私网段时，sanitize_url 把 huggingface.co
   误报成 "internal service"（S85-D4 已让 SSRF 判定绕开 fake-ip，日志没跟上）。
"""
import asyncio
import inspect
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
# pytest 启动期 site-packages 的 py.py shim 会遮蔽仓库 py/ 包（S59 教训）
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import server  # noqa: E402
from py import cli_tool, load_files  # noqa: E402


_MIN_SETTINGS = {
    "HASettings": {"enabled": False},
    "chromeMCPSettings": {"enabled": False},
    "sqlSettings": {"enabled": False},
}


class _RecLogger:
    def __init__(self):
        self.warnings, self.errors, self.infos = [], [], []

    @staticmethod
    def _fmt(m, a):
        m = str(m)
        return m % a if a else m

    def warning(self, m, *a):
        self.warnings.append(self._fmt(m, a))

    def error(self, m, *a):
        self.errors.append(self._fmt(m, a))

    def info(self, m, *a):
        self.infos.append(self._fmt(m, a))

    def debug(self, m, *a):
        pass


@pytest.fixture()
def probe_hook(monkeypatch):
    """注册一个只读假工具并接管 server.logger（gate 全部按 settings={} 放行）。"""
    calls = []

    async def s212_probe_tool(path: str, start_line: int = 1) -> str:
        calls.append((path, start_line))
        return f"OK:{path}:{start_line}"

    monkeypatch.setitem(server._TOOL_HOOKS, "s212_probe_tool", s212_probe_tool)
    rec = _RecLogger()
    monkeypatch.setattr(server, "logger", rec)
    return rec, calls


class TestDispatchArgSelfHeal:
    def test_extra_kwarg_dropped_and_retried(self, probe_hook):
        # 19:24 事故复刻：script_code 是别的工具的参数名，空串混灌
        rec, calls = probe_hook
        out = asyncio.run(server.dispatch_tool(
            "s212_probe_tool", {"path": "a.json", "script_code": ""}, _MIN_SETTINGS))
        assert out == "OK:a.json:1"
        assert calls == [("a.json", 1)]
        assert any("script_code" in w for w in rec.warnings)

    def test_multiple_extra_kwargs_all_dropped(self, probe_hook):
        rec, calls = probe_hook
        out = asyncio.run(server.dispatch_tool(
            "s212_probe_tool", {"path": "b", "foo": 1, "bar": 2}, _MIN_SETTINGS))
        assert out == "OK:b:1"
        assert len([w for w in rec.warnings if "忽略未声明多余参数" in w]) == 2

    def test_missing_required_returns_structured_hint(self, probe_hook):
        rec, _ = probe_hook
        out = asyncio.run(server.dispatch_tool("s212_probe_tool", {"start_line": 2}, _MIN_SETTINGS))
        assert out.startswith("[Error] Invalid arguments for s212_probe_tool")
        assert "Supply all required arguments" in out

    def test_too_many_extra_kwargs_gives_up_with_generic_error(self, probe_hook):
        # 丢弃上限 3 次，第 4 个脏参数落入兜底文案（不再无限重试）
        rec, _ = probe_hook
        out = asyncio.run(server.dispatch_tool(
            "s212_probe_tool", {"path": "c", "k1": 1, "k2": 2, "k3": 3, "k4": 4}, _MIN_SETTINGS))
        assert out.startswith("Error calling tool s212_probe_tool")
        assert len([w for w in rec.warnings if "忽略未声明多余参数" in w]) == 3

    def test_non_binding_error_message_unchanged(self, monkeypatch):
        async def boom_tool(path: str) -> str:
            raise RuntimeError("boom")

        monkeypatch.setitem(server._TOOL_HOOKS, "s212_boom", boom_tool)
        monkeypatch.setattr(server, "logger", _RecLogger())
        out = asyncio.run(server.dispatch_tool("s212_boom", {"path": "x"}, _MIN_SETTINGS))
        assert out.startswith("Error calling tool s212_boom: boom")


class TestReadFileRangeEndLine:
    def test_local_reads_to_eof_when_end_line_omitted(self, tmp_path, monkeypatch):
        f = tmp_path / "f.txt"
        f.write_text("\n".join(f"line{i}" for i in range(1, 6)) + "\n", encoding="utf-8")

        async def fake_cwd():
            return str(tmp_path)

        monkeypatch.setattr(cli_tool, "_get_current_cwd", fake_cwd)
        out = asyncio.run(cli_tool.read_file_range_tool_local("f.txt", 4))
        assert "line4" in out and "line5" in out and "line3" not in out
        out2 = asyncio.run(cli_tool.read_file_range_tool_local("f.txt", 2, 3))
        assert "line2" in out2 and "line3" in out2 and "line4" not in out2

    def test_invalid_range_still_guarded(self, tmp_path, monkeypatch):
        async def fake_cwd():
            return str(tmp_path)

        monkeypatch.setattr(cli_tool, "_get_current_cwd", fake_cwd)
        out = asyncio.run(cli_tool.read_file_range_tool_local("f.txt", 0))
        assert "[Error] Invalid line range." in out

    def test_schemas_no_longer_require_end_line(self):
        for reg, key in ((cli_tool.TOOLS_REGISTRY, "read_file_range"),
                         (cli_tool.LOCAL_TOOLS_REGISTRY, "read_file_range_local")):
            params = reg[key]["function"]["parameters"]
            assert "end_line" not in params["required"], key
            assert "default" in params["properties"]["end_line"]["description"], key
        for fn in (cli_tool.read_file_range_tool, cli_tool.read_file_range_tool_local):
            sig = inspect.signature(fn)
            assert sig.parameters["end_line"].default is None, fn.__name__

    def test_wsl_alias_shares_fixed_schema(self):
        assert (cli_tool.WSL_TOOLS_REGISTRY["read_file_range_wsl"]
                is cli_tool.LOCAL_TOOLS_REGISTRY["read_file_range_local"])


class TestInternalServiceLogGate:
    def test_domain_not_logged_even_if_dns_says_private(self, monkeypatch):
        # fake-ip：域名被解析进私网段（198.18.x.x 类）也不再谎报内网
        rec = _RecLogger()
        monkeypatch.setattr(load_files, "logger", rec)
        monkeypatch.setattr(load_files, "is_private_ip", lambda h: True)
        url = load_files.sanitize_url("https://huggingface.co/api/models/x")
        assert "huggingface.co" in url
        assert not any("internal service" in m for m in rec.infos)

    def test_literal_ip_still_logged(self, monkeypatch):
        rec = _RecLogger()
        monkeypatch.setattr(load_files, "logger", rec)
        load_files.sanitize_url("http://192.168.4.5:11434/api")
        assert any("internal service" in m and "11434" in m for m in rec.infos)
