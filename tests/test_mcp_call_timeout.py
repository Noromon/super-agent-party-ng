# -*- coding: utf-8 -*-
"""S63：MCP 调用超时（默认 180s）+ 三级解析（server callTimeout → 全局 mcpCallTimeout → 默认）。

背景：call_tool 此前无超时，远端不返回即永久悬挂并持有 _lock，把后续所有请求的
工具装配（list_tools）链成僵尸锁；重连循环 finally 拿锁也被链死。现全部限时，
且调用前后有 INFO/ERROR 日志可直接定位卡在哪一层。
"""
import asyncio
import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def _load(rel, stem):
    spec = importlib.util.spec_from_file_location(
        f"{stem}_{uuid.uuid4().hex}", ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_mcp_clients():
    return _load("py/mcp_clients.py", "mcp_clients_standalone")


def load_tool_dispatch(app_state_obj):
    """tool_dispatch 顶层 `from py import app_state`，桩住 py 命名空间再加载。
    tool_dispatch 读 app_state.mcp_client_list（生产里 app_state 是模块+全局属性），
    故把 mcp_client_list 挂到桩模块属性上。"""
    saved = {k: sys.modules.get(k) for k in ("py", "py.app_state")}
    pkg = types.ModuleType("py")
    pkg.__path__ = []
    sub = types.ModuleType("py.app_state")
    sub.mcp_client_list = app_state_obj.mcp_client_list
    sys.modules["py"] = pkg
    sys.modules["py.app_state"] = sub
    try:
        return _load("py/tool_dispatch.py", "tool_dispatch_standalone")
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


class _HangingSession:
    async def call_tool(self, name, params):
        await asyncio.sleep(30)
        return "late"

    async def list_tools(self):
        await asyncio.sleep(30)


class _FastSession:
    async def call_tool(self, name, params):
        await asyncio.sleep(0.02)
        return "sentinel"

    async def list_tools(self):
        return SimpleNamespace(tools=[])


def _client(mod, session, config=None, name="srv"):
    c = mod.McpClient()
    c._name = name
    c._config = config if config is not None else {}
    c._conn = SimpleNamespace(session=session, tools=["x"])
    return c


class TestCallToolTimeout:
    def test_hang_returns_error_and_releases_lock(self):
        mod = load_mcp_clients()
        c = _client(mod, _HangingSession())

        async def scenario():
            res = await c.call_tool("x", {"cmd": "echo hi"}, timeout=0.2)
            async with c._lock:  # 拿得到锁 = 超时后未僵尸化
                released = True
            return res, released
        res, released = asyncio.run(scenario())
        assert res.startswith("[Error]") and "timed out" in res and "srv.x" in res
        assert released

    def test_fast_call_returns_result(self):
        mod = load_mcp_clients()
        c = _client(mod, _FastSession())
        assert asyncio.run(c.call_tool("x", {}, timeout=5)) == "sentinel"

    def test_explicit_timeout_beats_server_config(self):
        mod = load_mcp_clients()
        c = _client(mod, _HangingSession(), config={"callTimeout": 3600})
        res = asyncio.run(c.call_tool("x", {}, timeout=0.2))
        assert "timed out after 0.2s" in res

    def test_server_config_call_timeout_used_when_no_arg(self):
        mod = load_mcp_clients()
        c = _client(mod, _HangingSession(), config={"callTimeout": 0.2})
        res = asyncio.run(c.call_tool("x", {}))
        assert "timed out after 0.2s" in res

    def test_default_timeout_is_180(self):
        mod = load_mcp_clients()
        assert mod.DEFAULT_CALL_TIMEOUT == 180

    def test_list_tools_timeout_degrades_to_empty(self):
        mod = load_mcp_clients()
        mod.LIST_TOOLS_TIMEOUT = 0.2
        c = _client(mod, _HangingSession())
        assert asyncio.run(c.get_openai_functions()) == []


class _SpyClient:
    def __init__(self, config=None):
        self._conn = SimpleNamespace(tools=["x"])
        self._config = config if config is not None else {}
        self.seen_timeout = "unset"

    async def call_tool(self, tool_name, tool_params, timeout=None):
        self.seen_timeout = timeout
        return "ok"


def _dispatch(spy, settings):
    app_state = SimpleNamespace(mcp_client_list={"s": spy})
    mod = load_tool_dispatch(app_state)

    async def scenario():
        return await mod.dispatch_unknown_tool("x", {}, set(), {}, None, settings)
    return asyncio.run(scenario()), spy.seen_timeout


class TestDispatchTimeoutResolution:
    def test_global_settings_mcp_call_timeout(self):
        res, t = _dispatch(_SpyClient(), {"mcpCallTimeout": 33})
        assert res == "ok" and t == 33

    def test_server_call_timeout_wins_over_global(self):
        res, t = _dispatch(_SpyClient(config={"callTimeout": 5}), {"mcpCallTimeout": 33})
        assert res == "ok" and t == 5

    def test_absent_settings_passes_none_for_default(self):
        res, t = _dispatch(_SpyClient(), None)
        assert res == "ok" and t is None

    def test_zero_or_empty_falls_through(self):
        # el-input-number min=10，防御性：0/空串不应覆盖（falsy 走下一级）
        _, t = _dispatch(_SpyClient(config={"callTimeout": 0}), {"mcpCallTimeout": 44})
        assert t == 44


class TestWiringPins:
    def _src(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_mcp_clients_timeouts_wired(self):
        src = self._src("py/mcp_clients.py")
        assert "await asyncio.wait_for(" in src
        assert "self._conn.session.call_tool(tool_name, tool_params), timeout)" in src
        assert "wait_for(self._lock.acquire(), MONITOR_LOCK_TIMEOUT)" in src
        assert "wait_for(self._conn.session.list_tools(), LIST_TOOLS_TIMEOUT)" in src

    def test_dispatch_reads_timeout_chain(self):
        src = self._src("py/tool_dispatch.py")
        assert "callTimeout" in src and "mcpCallTimeout" in src

    def test_server_passes_settings_to_dispatch(self):
        assert "call_node_extension_tool, settings)" in self._src("server.py")

    def test_frontend_default_registered(self):
        assert "mcpCallTimeout: 180," in self._src("static/js/settings_schema.js")

    def test_template_default_is_180(self):
        data = json.loads((ROOT / "config" / "settings_template.json").read_text(encoding="utf-8"))
        assert data["mcpCallTimeout"] == 180
