# -*- coding: utf-8 -*-
"""S62 裁决 C：MCP 连接状态单一写者（后端落盘）+ 门控内存优先回退。

背景：processingStatus='ready' 此前只写前端内存副本且 poll 写回后不落盘，
bot 会话（xmpp 等）的 settings 走 load_settings 读盘，必须等主界面下次
autoSaveSettings（通常=主会话再发一条消息）才看到新 MCP 工具。
本文件锁三件事：
  1) server._persist_mcp_status：内存 + 磁盘 + WS 推送，failed:* 映射 server_error；
  2) tool_assembly 门控：内存实时值优先，内存缺项才回退磁盘；
  3) 静态防回潮：process_mcp 不再直写 app_state.mcp_status；前端 poll 写回带保存。
"""
import ast
import asyncio
import importlib.util
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load_tool_assembly():
    """py 目录下同名 'py' 库会遮蔽包导入（同 test_row_store 的独立加载法）。"""
    spec = importlib.util.spec_from_file_location(
        f"tool_assembly_standalone_{uuid.uuid4().hex}",
        ROOT / "py" / "tool_assembly.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _extract_async(name, rel="server.py"):
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == name:
            ns = {}
            exec(compile(ast.Module(body=[node], type_ignores=[]), "server", "exec"), ns)
            return ns
    raise AssertionError(f"{name} not found at top level of {rel}")


def _fake_settings(disk_status):
    return {
        "mcpServers": {"srv": {"disabled": False, "processingStatus": disk_status,
                               "tools": []}},
    }


def _base_settings():
    return {
        "mcpServers": {},
        "HASettings": {"enabled": False},
        "chromeMCPSettings": {"enabled": False, "type": "external"},
        "sqlSettings": {"enabled": False},
        "CLISettings": {"enabled": False, "mode_change": False},
        "visionControlSettings": {"enabled": False},
        "tools": {k: {"enabled": False} for k in
                  ("time", "weather", "wikipedia", "randomTopic", "arxiv",
                   "getFile", "autoBehavior")},
        "text2imgSettings": {"enabled": False},
        "codeSettings": {"enabled": False},
        "custom_http": [],
        "workflows": [],
    }


class _FakeClient:
    def __init__(self):
        self.disabled = False

    async def get_openai_functions(self, disable_tools=None):
        return [{"type": "function",
                 "function": {"name": "mcp_tool_1", "description": "d",
                              "parameters": {}}}]


def _fake_tk(mcp_status):
    async def none_tool(settings):
        return None

    return {
        "mcp_client_list": {"srv": _FakeClient()},
        "mcp_status": mcp_status,
        "node_ext_mcp_tools": {},
        "get_llm_tool": none_tool,
        "get_agent_tool": none_tool,
        "get_a2a_tool": none_tool,
    }


def _gate_names(mcp_status, disk_status):
    build_llm_tools = load_tool_assembly().build_llm_tools
    settings = _base_settings()
    settings["mcpServers"] = {"srv": {"disabled": False,
                                      "processingStatus": disk_status,
                                      "tools": []}}
    request = SimpleNamespace(tools=None, messages=[{"role": "user", "content": "hi"}])
    tools = asyncio.run(build_llm_tools(request, settings, _fake_tk(dict(mcp_status))))
    return {t["function"]["name"] for t in tools}


class TestStatusGate:
    def test_memory_ready_overrides_stale_disk_initializing(self):
        # 修复的主场景：后端已 ready，磁盘还停在 initializing（前端没落盘）
        assert "mcp_tool_1" in _gate_names({"srv": "ready"}, "initializing")

    def test_memory_initializing_hides_tools_despite_stale_disk_ready(self):
        # 重连窗口：内存 initializing 优先于磁盘残留 ready
        assert "mcp_tool_1" not in _gate_names({"srv": "initializing"}, "ready")

    def test_memory_failed_hides_tools(self):
        assert "mcp_tool_1" not in _gate_names({"srv": "failed: boom"}, "ready")

    def test_memory_missing_falls_back_to_disk_ready(self):
        # 启动 lifespan 路径不写 mcp_status → 回退磁盘值
        assert "mcp_tool_1" in _gate_names({}, "ready")
        assert "mcp_tool_1" not in _gate_names({}, "server_error")


class TestPersistMcpStatus:
    @pytest.fixture
    def env(self):
        ns = _extract_async("_persist_mcp_status")
        saved = {}
        state = {"settings": _fake_settings("initializing"), "saves": 0, "broadcasts": 0}

        async def load_settings():
            return state["settings"]

        async def save_settings(s):
            state["saves"] += 1
            saved["data"] = s

        async def broadcast(s, **kw):
            state["broadcasts"] += 1

        ns.update({
            "app_state": SimpleNamespace(mcp_status={}),
            "load_settings": load_settings,
            "save_settings": save_settings,
            "ws_manager": SimpleNamespace(broadcast_settings_update=broadcast),
            "logging": logging,
        })
        return ns, state

    def test_ready_writes_memory_disk_and_broadcast(self, env):
        ns, state = env
        asyncio.run(ns["_persist_mcp_status"]("srv", "ready"))
        assert ns["app_state"].mcp_status["srv"] == "ready"
        assert state["settings"]["mcpServers"]["srv"]["processingStatus"] == "ready"
        assert state["saves"] == 1
        assert state["broadcasts"] == 1

    def test_failed_maps_to_server_error_on_disk(self, env):
        ns, state = env
        asyncio.run(ns["_persist_mcp_status"]("srv", "failed: boom"))
        assert ns["app_state"].mcp_status["srv"] == "failed: boom"
        assert state["settings"]["mcpServers"]["srv"]["processingStatus"] == "server_error"

    def test_unchanged_disk_value_skips_save_but_broadcasts(self, env):
        ns, state = env
        asyncio.run(ns["_persist_mcp_status"]("srv", "initializing"))
        assert state["saves"] == 0  # 磁盘已是 initializing
        assert state["broadcasts"] == 1

    def test_unknown_server_created_in_mcp_servers(self, env):
        ns, state = env
        state["settings"]["mcpServers"] = {}
        asyncio.run(ns["_persist_mcp_status"]("fresh", "ready"))
        assert state["settings"]["mcpServers"]["fresh"]["processingStatus"] == "ready"


class TestNoRegression:
    def test_process_mcp_no_direct_memory_write(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and n.name == "process_mcp")
        direct = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Subscript)
                          and isinstance(t.value, ast.Attribute)
                          and t.value.attr == "mcp_status" for t in n.targets)]
        assert not direct, "process_mcp 状态迁移必须全部走 _persist_mcp_status"
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "_persist_mcp_status"]
        assert len(calls) >= 4

    def test_toolkit_exposes_live_mcp_status(self):
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        assert '"mcp_status": app_state.mcp_status' in src

    def test_tool_assembly_gate_uses_live_status(self):
        src = (ROOT / "py" / "tool_assembly.py").read_text(encoding="utf-8")
        assert 'tk.get("mcp_status"' in src

    def test_frontend_poll_persists_on_writeback(self):
        src = (ROOT / "static" / "js" / "methods" / "26_mcp.js").read_text(encoding="utf-8")
        start = src.index("async pollMCPStatus")
        end = src.index("editMCPServer")
        block = src[start:end]
        assert block.count("processingStatus") == 3
        assert block.count("autoSaveSettings") == 3
