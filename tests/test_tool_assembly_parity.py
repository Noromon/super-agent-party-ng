# -*- coding: utf-8 -*-
"""E-1 forensics, dispositioned (S43): both engines now assemble their LLM
tool lists through the single source py/tool_assembly.build_llm_tools.

Phase 1 printed the drift; E-1b aligned the engines (node-extension tools are
announced on both paths per the S43 decision) and this file now enforces
strict set equality plus the single-source structure itself.
"""
import ast
import json
import os
import sqlite3

from test_contract_sse import post_chat, collect, sse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_SRC = (open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
              + open(os.path.join(ROOT, "py/stream_response.py"), encoding="utf-8").read()
              + open(os.path.join(ROOT, "py/complete_engine.py"), encoding="utf-8").read())  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）


def _mutate_settings(data_dir, mutate):
    """chat_endpoint reloads settings from the DB per request (L7658), so a
    direct DB edit takes effect on the very next call. Returns the original
    JSON text for restoring."""
    con = sqlite3.connect(os.path.join(str(data_dir), "super_agent_party.db"))
    original = con.execute("SELECT data FROM settings WHERE id=1").fetchone()[0]
    data = json.loads(original)
    mutate(data)
    con.execute("UPDATE settings SET data=? WHERE id=1",
                (json.dumps(data, ensure_ascii=False),))
    con.commit()
    con.close()
    return original


def _restore_settings(data_dir, original):
    con = sqlite3.connect(os.path.join(str(data_dir), "super_agent_party.db"))
    con.execute("UPDATE settings SET data=? WHERE id=1", (original,))
    con.commit()
    con.close()


def _tool_names(history):
    names = set()
    for call in history:
        for t in call.get("tools") or []:
            fn = (t.get("function") or {}).get("name") or t.get("name")
            if fn:
                names.add(fn)
    return names


class TestAssemblyParity:
    def test_stream_and_complete_tool_sets(self, sap, mock_llm):
        # --- streaming engine ---
        mock_llm.script([{"kind": "text", "content": "s-ok"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
        collect(sse(r))
        stream_tools = _tool_names(mock_llm.history)

        # --- complete engine (same endpoint, stream=false branch) ---
        mock_llm.script([{"kind": "text", "content": "c-ok"}])
        r2 = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]},
                       stream=False)
        assert r2.status_code == 200
        complete_tools = _tool_names(mock_llm.history)

        assert stream_tools, "stream engine must send some tools to the LLM"
        assert complete_tools, "complete engine must send some tools to the LLM"
        # E-1b: strict equality is the ratchet (single source can never drift)
        assert stream_tools == complete_tools, (
            f"engine drift: stream_only={sorted(stream_tools - complete_tools)} "
            f"complete_only={sorted(complete_tools - stream_tools)}")
        assert {"list_files_tool_local", "read_file_tool_local", "shell_tool_local"} <= stream_tools, \
            f"core built-ins missing: {sorted(stream_tools)[:20]}"


class TestPermissionListsSingleSource:
    """E-1a: sensitive/plan-blocked lists live only in py/tool_registry.py."""

    def test_server_no_longer_defines_lists(self):
        assert "SENSITIVE_TOOLS = [" not in SERVER_SRC
        assert "PLAN_BLOCKED_TOOLS = " not in SERVER_SRC
        assert "from py.tool_registry import" in SERVER_SRC

    def test_registry_semantics(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "sap_tool_registry", os.path.join(ROOT, "py", "tool_registry.py"))
        reg = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reg)
        assert "shell_tool_local" in reg.SENSITIVE_TOOLS
        assert "docker_sandbox" in reg.SENSITIVE_TOOLS
        assert reg.PLAN_BLOCKED_TOOLS >= set(reg.SENSITIVE_TOOLS)
        # S221: todo 属计划可视化工具，plan 允许（对齐 opencode）；桌面控制执行类纳入拦截
        assert "todo_write_tool" not in reg.PLAN_BLOCKED_TOOLS
        assert "todo_write_tool_local" not in reg.PLAN_BLOCKED_TOOLS
        assert "mouse_click" in reg.PLAN_BLOCKED_TOOLS
        assert "keyboard_press" in reg.PLAN_BLOCKED_TOOLS
        assert "screenshot" not in reg.PLAN_BLOCKED_TOOLS


def _capture_tool_sets(sap, mock_llm):
    mock_llm.script([{"kind": "text", "content": "s-ok"}])
    collect(sse(post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})))
    stream_tools = _tool_names(mock_llm.history)
    mock_llm.script([{"kind": "text", "content": "c-ok"}])
    post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]}, stream=False)
    return stream_tools, _tool_names(mock_llm.history)


class TestNonDefaultConfigDrift:
    """E-1b forensics: with optional tools switched ON, verify the engines
    still agree (randomTopic/time/weather...), and pin the one known gap
    (node-extension tools are assembled by the streaming engine only)."""

    def test_randomtopic_on_still_zero_drift(self, sap, mock_llm):
        original = _mutate_settings(
            sap.data_dir, lambda d: d["tools"]["randomTopic"].__setitem__("enabled", True))
        try:
            stream_tools, complete_tools = _capture_tool_sets(sap, mock_llm)
            assert "get_random_topics" in stream_tools
            assert stream_tools == complete_tools, (
                "randomTopic-on must not drift: "
                f"stream_only={sorted(stream_tools - complete_tools)} "
                f"complete_only={sorted(complete_tools - stream_tools)}")
        finally:
            _restore_settings(sap.data_dir, original)

    def test_time_tool_on_still_zero_drift(self, sap, mock_llm):
        # time tool assembly condition is character-identical on both sides
        # (L4109 / L6364); prove it at runtime with the trigger mode enabled.
        original = _mutate_settings(
            sap.data_dir,
            lambda d: d["tools"]["time"].update({"enabled": True,
                                                 "triggerMode": "afterThinking"}))
        try:
            stream_tools, complete_tools = _capture_tool_sets(sap, mock_llm)
            assert stream_tools == complete_tools, (
                f"time-on drift: {sorted(stream_tools ^ complete_tools)}")
        finally:
            _restore_settings(sap.data_dir, original)

    def test_assembly_is_single_source(self):
        """E-1b end-state ratchet: both engines call build_llm_tools and the
        server file carries no inline assembly copies anymore (the old drift
        surface: complete missed node-extension tools entirely)."""
        # S304：两处调用随装配/complete 域迁出，中间参 _srv() 化（文档化改写）——钉随体更新
        assert SERVER_SRC.count("await build_llm_tools(request, settings, "
                                "_srv()._assemble_toolkit())") == 2
        assert 'tools = request.tools or []' not in SERVER_SRC
        # the node-extension announce loop lives exactly once, in the module
        asm = open(os.path.join(ROOT, "py", "tool_assembly.py"),
                   encoding="utf-8").read()
        assert "node_ext_mcp_tools" in asm
        assert asm.count("for ext_id, tools_list in") == 1
        assert asm.count("来自扩展") == 1
        # server keeps only the dispatch-side lookup over node_ext_mcp_tools
        # (execution layer), never a tool-announce loop for the LLM
        assert "来自扩展" not in SERVER_SRC
        # 批 2h3：执行层的 node 注册表扫描已迁 py/tool_dispatch.py（注入
        # 注册表活引用），server 内不再出现；唯一性转移到新模块断言
        assert SERVER_SRC.count(
            "for ext_id, tools in node_ext_mcp_tools.items()") == 0
        _td = open(os.path.join(ROOT, "py", "tool_dispatch.py"),
                   encoding="utf-8-sig").read()
        assert _td.count("for ext_id, tools in ext_mcp_tools.items()") == 1


class TestToolkitContract:
    """S210：tool_assembly 引用的全部 tk["X"] ⊆ _assemble_toolkit 键集。

    S210 事故：S209 给 tool_assembly 加了严格 tk["read_skill_tool_local"] 引用，
    但 _assemble_toolkit() 构建的真 tk 与 _TOOL_HOOKS 执行调度表是两个字典，
    漏注册前者——单测假 tk 自带键全绿，线上 CLI 关/acp 每条消息 KeyError→500。
    本契约钉让漏注册在提交期直接红（tk.get 可选引用不算，天然排除）。
    """

    def _tk_referenced_keys(self):
        tree = ast.parse(open(os.path.join(ROOT, "py", "tool_assembly.py"),
                              encoding="utf-8").read())
        keys = set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Subscript)
                    and isinstance(node.value, ast.Name) and node.value.id == "tk"
                    and isinstance(node.slice, ast.Constant)
                    and isinstance(node.slice.value, str)):
                keys.add(node.slice.value)
        return keys

    def _toolkit_keys(self):
        tree = ast.parse(SERVER_SRC)
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "_assemble_toolkit")
        for node in ast.walk(fn):
            if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
        raise AssertionError("_assemble_toolkit must return a dict literal")

    def test_tk_references_registered_in_toolkit(self):
        referenced = self._tk_referenced_keys()
        assert referenced, "tool_assembly must reference tk['...'] at all"
        missing = referenced - self._toolkit_keys()
        assert not missing, (
            "tool_assembly 引用而 _assemble_toolkit 未注册的 tk 键: "
            f"{sorted(missing)} —— 线上命中即 KeyError→500（S210 教训）")

    def test_read_skill_local_key_present(self):
        assert "read_skill_tool_local" in self._toolkit_keys()

    def test_assemble_toolkit_runtime_has_key(self):
        # 运行时兜底：函数体内 import 缺失会让 dict 字面量在调用处 NameError，
        # 静态键集测试查不到，这里真调一次 _assemble_toolkit()
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
            del sys.modules["py"]
        import server
        assert "read_skill_tool_local" in server._assemble_toolkit()

    def _append_extend_tk_keys(self):
        """tool_assembly 里直接 tools.append(tk["X"]) / tools.extend(tk["X"]) 的键。"""
        tree = ast.parse(open(os.path.join(ROOT, "py", "tool_assembly.py"),
                              encoding="utf-8").read())
        append_keys, extend_keys = set(), set()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("append", "extend")
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "tools" and len(node.args) == 1):
                arg = node.args[0]
                if (isinstance(arg, ast.Subscript) and isinstance(arg.value, ast.Name)
                        and arg.value.id == "tk" and isinstance(arg.slice, ast.Constant)
                        and isinstance(arg.slice.value, str)):
                    (append_keys if node.func.attr == "append" else extend_keys).add(arg.slice.value)
        return append_keys, extend_keys

    def test_announced_tk_values_are_schemas(self):
        # S211 事故：键已注册但绑了函数本体，公告列表混入裸 callable →
        # openai 客户端 json.dumps TypeError。键存在性钉抓不到值类型错，
        # 这里按 append/extend 公告位逐一断言运行时值类型。
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
            del sys.modules["py"]
        import server
        tk = server._assemble_toolkit()
        append_keys, extend_keys = self._append_extend_tk_keys()
        assert append_keys and extend_keys
        for key in sorted(append_keys):
            assert isinstance(tk[key], dict), (
                f"tk[{key!r}] 公告位（tools.append）必须是 schema dict，"
                f"实为 {type(tk[key]).__name__}")
        for key in sorted(extend_keys):
            value = tk[key]
            assert isinstance(value, list) and all(isinstance(i, dict) for i in value), (
                f"tk[{key!r}] 公告位（tools.extend）必须是 list[dict]，"
                f"实为 {type(value).__name__}")

    def test_cli_off_announces_read_skill_e2e(self, sap, mock_llm):
        # S210/S211 线上路径端到端钉：CLI 关真实走一遍端点（SAP→LLM 的
        # json.dumps 序列化即两起事故的炸点），公告必须含 read_skill_tool_local
        original = _mutate_settings(
            sap.data_dir, lambda d: d["CLISettings"].update({"enabled": False}))
        try:
            mock_llm.script([{"kind": "text", "content": "ok"}])
            r = post_chat(sap, {"messages": [{"role": "user", "content": "hi"}]})
            assert r.status_code == 200
            collect(sse(r))
            names = _tool_names(mock_llm.history)
            assert "read_skill_tool_local" in names, (
                f"CLI 关必须公告 read_skill_tool_local，实到: {sorted(names)[:25]}")
        finally:
            _restore_settings(sap.data_dir, original)

    def test_announced_schema_signature_contract(self):
        # S212 契约：公告 schema 与执行 hook 签名不得互相说谎——
        # ①schema 声明参数函数必须有；②函数无默认值的参数 schema 必须 required
        # （否则模型照 schema 省略参数必炸裸 TypeError，read_file_range/end_line 潜伏雷）；
        # ③schema required 的参数函数必须有。动态 hook（**kwargs 兜底/不可内省）跳过。
        import inspect
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
            del sys.modules["py"]
        import server
        server._build_tool_hooks()
        tk = server._assemble_toolkit()
        schemas = []
        for value in tk.values():
            if isinstance(value, dict) and value.get("type") == "function":
                schemas.append(value["function"])
            elif isinstance(value, list):
                schemas += [i["function"] for i in value
                            if isinstance(i, dict) and i.get("type") == "function"]
        assert len(schemas) >= 40, f"公告 schema 数异常（{len(schemas)}），扫描前提破坏"
        checked = 0
        for fn in schemas:
            name = fn.get("name", "?")
            hook = server._TOOL_HOOKS.get(name)
            if hook is None:
                continue
            try:
                sig = inspect.signature(hook)
            except (TypeError, ValueError):
                continue
            plist = [p for p in sig.parameters.values() if p.name != "self"]
            if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in plist):
                continue
            names = {p.name for p in plist}
            spec = fn.get("parameters") or {}
            props = set(spec.get("properties", {}))
            req = set(spec.get("required", []))
            assert props <= names, (
                f"{name}: schema 声明了函数签名没有的参数: {sorted(props - names)}"
                "（模型照 schema 传参必 TypeError）")
            silent_required = {p.name for p in plist
                               if p.default is inspect.Parameter.empty
                               and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                              inspect.Parameter.KEYWORD_ONLY)
                               and p.name not in req}
            assert not silent_required, (
                f"{name}: 函数强制但 schema 未标 required 的参数: {sorted(silent_required)}"
                "（模型照 schema 省略必 TypeError——S212 read_file_range 教训）")
            assert req <= names, f"{name}: schema required 但函数无此参数: {sorted(req - names)}"
            checked += 1
        assert checked >= 40, f"可内省契约覆盖仅 {checked} 个 schema，覆盖面异常"
