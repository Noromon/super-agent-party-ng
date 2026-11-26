"""S323：扩展对 agent 的可见性（A 宿主上下文）与可及性（B 只读自查 / C 批复启动）。

事故钉：12:13 会话 agent 把 Electron UI 口 4633 当 API 口打 → 404 → 误诊
「框架没挂载扩展」。API base 恒取自 get_port()，注入文本必须不含任何硬编码口。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py import agent_ext_tools as A  # noqa: E402
from py.tool_registry import PLAN_BLOCKED_TOOLS, SENSITIVE_TOOLS  # noqa: E402

TA_SRC = (_ROOT / "py" / "tool_assembly.py").read_text(encoding="utf-8")
TH_SRC = (_ROOT / "py" / "tool_hooks.py").read_text(encoding="utf-8")
SRV_SRC = (_ROOT / "server.py").read_text(encoding="utf-8")


def _mkext(root: Path, name: str, *, node=True, ui=True, desc="d"):
    d = root / name
    d.mkdir(parents=True)
    if node:
        (d / "index.js").write_text("//", encoding="utf-8")
    if ui:
        (d / "index.html").write_text("<html></html>", encoding="utf-8")
    if node or ui:
        (d / "package.json").write_text(json.dumps(
            {"name": name, "version": "1.2.3", "description": desc}), encoding="utf-8")
    return d


class _Mgr:
    def __init__(self, exts=None, start_ret=None, start_exc=None):
        self.exts = exts or {}
        self._ret = start_ret
        self._exc = start_exc

    async def start(self, ext_id):
        if self._exc:
            raise self._exc
        return self._ret


@pytest.fixture(autouse=True)
def _cache_reset():
    A.invalidate_cache()
    yield
    A.invalidate_cache()


class TestScan:
    def test_filters_and_fields(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "demo-ext")
        (tmp_path / "pkg.zip").write_bytes(b"x")           # 非目录
        (tmp_path / "noentry").mkdir()                      # 无入口文件
        exts = A.scan_extensions()
        assert [e["id"] for e in exts] == ["demo-ext"]
        e = exts[0]
        assert e["node"] and e["ui"] and e["version"] == "1.2.3"
        assert e["running_port"] is None and e["mcp_tools"] == []

    def test_running_port_from_mgr(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "run-ext")

        class _P:
            returncode = None
        ne = type("NE", (), {"proc": _P(), "port": 9911})()
        monkeypatch.setattr("py.node_runner.node_mgr", _Mgr(exts={"run-ext": ne}))
        e = A.scan_extensions()[0]
        assert e["running_port"] == 9911

    def test_dead_proc_not_running(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "dead-ext")
        ne = type("NE", (), {"proc": type("P", (), {"returncode": 1})(), "port": 1})()
        monkeypatch.setattr("py.node_runner.node_mgr", _Mgr(exts={"dead-ext": ne}))
        assert A.scan_extensions()[0]["running_port"] is None

    def test_ttl_cache(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "a1")
        assert len(A.scan_extensions()) == 1
        _mkext(tmp_path, "a2")
        assert len(A.scan_extensions()) == 1            # TTL 内不重扫
        _real_mono = time.monotonic
        monkeypatch.setattr(A.time, "monotonic",
                            lambda: _real_mono() + A._CACHE_TTL + 1)
        assert len(A.scan_extensions()) == 2            # TTL 过期后重扫


class TestHostContext:
    def test_api_base_from_get_port_and_bridge_rule(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        monkeypatch.setattr(A, "get_port", lambda: 3456)
        _mkext(tmp_path, "demo-ext", desc="tieba viewer")
        ctx = A.build_host_context()
        assert "http://127.0.0.1:3456" in ctx
        assert "PAGE IS OPENED" in ctx and "demo-ext" in ctx
        assert "not running" in ctx and "4633" not in ctx   # 无硬编码口（误诊根因）

    def test_empty_dir_still_injects(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        monkeypatch.setattr(A, "get_port", lambda: 3456)
        ctx = A.build_host_context()
        assert "Host API base" in ctx and "none" in ctx

    def test_registered_mcp_tools_shown(self, monkeypatch, tmp_path):
        import types
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        monkeypatch.setattr(A, "get_port", lambda: 3456)
        _mkext(tmp_path, "demo-ext")
        monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(
            node_ext_mcp_tools={"demo-ext": [{"name": "tieba_view_thread"}]}))
        ctx = A.build_host_context()
        assert "mcp_tools: tieba_view_thread (registered)" in ctx


class TestListTool:
    def test_lists_running_and_mcp(self, monkeypatch, tmp_path):
        import types
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "demo-ext")
        ne = type("NE", (), {"proc": type("P", (), {"returncode": None})(),
                             "port": 9911})()
        monkeypatch.setattr("py.node_runner.node_mgr", _Mgr(exts={"demo-ext": ne}))
        monkeypatch.setitem(sys.modules, "server", types.SimpleNamespace(
            node_ext_mcp_tools={"demo-ext": [{"name": "tieba_x"}]}))
        out = asyncio.run(A.list_extensions_tool_local())
        assert "RUNNING port=9911" in out and "tieba_x" in out
        assert "start_extension_node_tool_local" in out

    def test_empty_hint(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        out = asyncio.run(A.list_extensions_tool_local())
        assert "No installed extensions" in out


class TestStartTool:
    def test_rejects_bad_ids(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        for bad in ("", "a/b", "a\\b", "..", "..x", ".hidden"):
            assert asyncio.run(
                A.start_extension_node_tool_local(bad)).startswith("[Error]")

    def test_unknown_ext_lists_available(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "demo-ext")
        out = asyncio.run(A.start_extension_node_tool_local("ghost"))
        assert "not found" in out and "demo-ext" in out

    def test_static_ext_no_node_needed(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "stat-ext", node=False)
        out = asyncio.run(A.start_extension_node_tool_local("stat-ext"))
        assert "static extension" in out

    def test_start_ok_reports_port_and_limitation(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "node-ext")
        monkeypatch.setattr("py.node_runner.node_mgr", _Mgr(start_ret=7777))
        out = asyncio.run(A.start_extension_node_tool_local("node-ext"))
        assert "port 7777" in out and "127.0.0.1:7777" in out
        assert "panel page" in out  # 如实注明：起 node ≠ MCP 工具进索引

    def test_start_timeout_is_retryable_hint(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "slow-ext")

        class _MgrHang:
            exts = {}

            async def start(self, ext_id):
                await asyncio.sleep(30)
        real_wait_for = asyncio.wait_for

        async def fast_timeout(coro, timeout=None):
            coro.close()
            raise asyncio.TimeoutError()
        monkeypatch.setattr(asyncio, "wait_for", fast_timeout)
        out = asyncio.run(A.start_extension_node_tool_local("slow-ext"))
        assert "[Warn]" in out and "idempotent" in out
        monkeypatch.setattr(asyncio, "wait_for", real_wait_for)

    def test_start_fail_missing_node_modules(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "brk-ext")
        monkeypatch.setattr("py.node_runner.node_mgr",
                            _Mgr(start_exc=RuntimeError("端口未就绪")))
        out = asyncio.run(A.start_extension_node_tool_local("brk-ext"))
        assert "[Error]" in out and "node_modules missing" in out


class TestWiringPins:
    def test_c_is_sensitive_and_plan_blocked(self):
        assert "start_extension_node_tool_local" in SENSITIVE_TOOLS
        assert "start_extension_node_tool_local" in PLAN_BLOCKED_TOOLS

    def test_assembly_announces_both(self):
        assert "_ensure_ext_visibility_tools(tools, tk)" in TA_SRC
        seg = TA_SRC[TA_SRC.index("def _ensure_ext_visibility_tools"):]
        assert '"list_extensions_tool"' in seg[:600]
        assert '"start_extension_node_tool"' in seg[:600]
        assert "_ensure_tool_once(tools, schema)" in seg

    def test_no_bare_import_server(self):  # S300 铁律：读 server 真源必须走 srv()
        src = (_ROOT / "py" / "agent_ext_tools.py").read_text(encoding="utf-8")
        lines = [ln.strip() for ln in src.splitlines()]
        bad = [ln for ln in lines
               if ln.startswith(("import server", "from server import"))]
        assert not bad, bad
        assert "srv_ref import srv" in src

    def test_hooks_dispatch_mapped(self):
        assert '"list_extensions_tool_local": list_extensions_tool_local' in TH_SRC
        assert ('"start_extension_node_tool_local": '
                'start_extension_node_tool_local') in TH_SRC

    def test_server_injects_host_context(self):
        assert "build_host_context" in SRV_SRC and "S323(A)" in SRV_SRC

    def test_schemas_are_dicts(self):  # S210 事故先例：公告位值必须 schema dict
        assert isinstance(A.LIST_EXTENSIONS_TOOL, dict)
        assert isinstance(A.START_EXTENSION_NODE_TOOL, dict)
