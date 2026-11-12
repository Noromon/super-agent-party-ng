# -*- coding: utf-8 -*-
"""S209：技能可见性解耦 + 工作区内全局可见。

定稿语义（checkpoint [S209]）：
- CLI 关 = 直觉「无工作区」→ 仅全局 skill 可见（索引/read_skill//<skill> 同口径）
- CLI 开 + cwd → 并集（工作区优先、各自标注作用域）
- visibilityScope: workspace=并集(默认) / global=仅全局 / none=隐藏
- 全局索引块恒定注入（不受 CLI/cwd/engine 门槛约束）
- read_skill 脱离 CLI 总开关恒定公告（列表无 read_skill* 变体时补本地版）
- /<skill> 只认 shortcut 双开关（A11），与 CLI.enabled 解绑
- 修复 shortcut_commands /skills 扫描路径 .agents → .agent
"""
import asyncio
import pathlib
import sys
import types

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# S59 教训：pytest 9 的 site-packages/py.py shim 会先被 _pytest.compat 缓存，
# 遮蔽仓库 py/ 包——删掉无 __path__ 的 shim 让 import py 重新解析到仓库包
# （与 test_approval_loop_s155 同款）。
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Req:
    """最小 ChatRequest 替身（messages 列表 + 无 tools）。"""

    def __init__(self, user_text=""):
        self.messages = [{"role": "user", "content": user_text}]
        self.tools = []


def _all_texts(req):
    out = []
    for m in req.messages:
        c = m.get("content", "")
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, list):
            out.extend(x.get("text", "") for x in c if isinstance(x, dict))
    return "".join(out)


# ==================== A. server：索引注入 / /<skill> 触发 ====================

@pytest.fixture
def skill_env(tmp_path, monkeypatch):
    import py.shortcut_commands as sc

    import server

    gdir = tmp_path / "global_skills"
    ws = tmp_path / "ws"
    (gdir / "gsk").mkdir(parents=True)
    (gdir / "gsk" / "SKILL.md").write_text(
        "---\nname: gsk\ndescription: 全局技能\n---\nGLOBAL-DOC-BODY", encoding="utf-8")
    (ws / ".agent" / "skills" / "wsk").mkdir(parents=True)
    (ws / ".agent" / "skills" / "wsk" / "SKILL.md").write_text(
        "---\nname: wsk\ndescription: 工作区技能\n---\nWS-DOC-BODY", encoding="utf-8")
    monkeypatch.setattr(server, "SKILLS_DIR", str(gdir))

    async def _sc_on():
        return True

    async def _sc_off():
        return False

    monkeypatch.setattr(sc, "im_shortcuts_enabled", _sc_on)
    return types.SimpleNamespace(server=server, gdir=gdir, ws=ws)


def test_append_project_skills_union_when_cli_on(skill_env):
    server = skill_env.server
    ws = str(skill_env.ws)
    req = _Req()
    _run(server._append_project_skills(req, ws, {"enabled": True}, "workspace"))
    txt = _all_texts(req)
    assert "wsk" in txt and "gsk" in txt


def test_append_project_skills_cli_off_global_only(skill_env):
    server = skill_env.server
    ws = str(skill_env.ws)
    req = _Req()
    _run(server._append_project_skills(req, ws, {"enabled": False}, "workspace"))
    txt = _all_texts(req)
    assert "gsk" in txt and "wsk" not in txt


def test_append_project_skills_scope_global_and_none(skill_env):
    server = skill_env.server
    ws = str(skill_env.ws)
    req = _Req()
    _run(server._append_project_skills(req, ws, {"enabled": True}, "global"))
    txt = _all_texts(req)
    assert "gsk" in txt and "wsk" not in txt
    req = _Req()
    _run(server._append_project_skills(req, ws, {"enabled": True}, "none"))
    assert _all_texts(req) == ""


def test_append_project_skills_no_cwd_global_still_visible(skill_env):
    server = skill_env.server
    req = _Req()
    _run(server._append_project_skills(req, None, {"enabled": True}, "workspace"))
    txt = _all_texts(req)
    assert "gsk" in txt and "wsk" not in txt


def test_resolve_skill_dir_priority_and_fallback(skill_env):
    server = skill_env.server
    ws = str(skill_env.ws)
    # 工作区存在时优先
    got = server._resolve_skill_dir(ws, "wsk", True)
    assert got == skill_env.ws / ".agent" / "skills" / "wsk"
    # CLI 开但工作区没有 → 全局回退
    got = server._resolve_skill_dir(ws, "gsk", True)
    assert got == skill_env.gdir / "gsk"
    # CLI 关（=无工作区）→ 只看全局
    got = server._resolve_skill_dir(ws, "wsk", False)
    assert got is None
    got = server._resolve_skill_dir(ws, "gsk", False)
    assert got == skill_env.gdir / "gsk"
    # 两处皆无
    assert server._resolve_skill_dir(ws, "nope", True) is None
    assert server._resolve_skill_dir(ws, "nope", False) is None


def test_inject_triggered_skill_decoupled_from_cli(skill_env):
    server = skill_env.server
    ws = str(skill_env.ws)
    cli_on = {"enabled": True, "shortcut": True}
    cli_off = {"enabled": False, "shortcut": True}
    # CLI 关：工作区技能不可见、全局技能可见
    req = _Req("/wsk 干活")
    _run(server._inject_triggered_skill(req, ws, cli_off))
    assert "WS-DOC-BODY" not in _all_texts(req)
    req = _Req("/gsk 干活")
    _run(server._inject_triggered_skill(req, ws, cli_off))
    assert "GLOBAL-DOC-BODY" in _all_texts(req)
    # CLI 开：工作区优先、缺失回落全局
    req = _Req("/wsk 干活")
    _run(server._inject_triggered_skill(req, ws, cli_on))
    assert "WS-DOC-BODY" in _all_texts(req)
    req = _Req("/gsk 干活")
    _run(server._inject_triggered_skill(req, ws, cli_on))
    assert "GLOBAL-DOC-BODY" in _all_texts(req)
    # 非 / 消息不触发
    req = _Req("你好")
    _run(server._inject_triggered_skill(req, ws, cli_on))
    assert "DOC-BODY" not in _all_texts(req)


def test_inject_triggered_skill_respects_shortcut_switch(skill_env, monkeypatch):
    import py.shortcut_commands as sc

    server = skill_env.server
    ws = str(skill_env.ws)

    async def _sc_off():
        return False

    monkeypatch.setattr(sc, "im_shortcuts_enabled", _sc_off)
    # 全局总开关（A11）关闭 → 即使 CLI shortcut 开也不注入
    req = _Req("/gsk 干活")
    _run(server._inject_triggered_skill(req, ws, {"enabled": True, "shortcut": True}))
    assert "GLOBAL-DOC-BODY" not in _all_texts(req)
    # CLI shortcut 子开关关闭 → 不注入
    monkeypatch.setattr(sc, "im_shortcuts_enabled", _sc_on)
    req = _Req("/gsk 干活")
    _run(server._inject_triggered_skill(req, ws, {"enabled": True, "shortcut": False}))
    assert "GLOBAL-DOC-BODY" not in _all_texts(req)


def _sc_on():
    async def _f():
        return True
    return _f()


# ==================== B. cli_tool：read_skill 本地分支 ====================

def _mk_cli_env(tmp_path, monkeypatch):
    import py.cli_tool as ct

    gdir = tmp_path / "global_skills"
    ws = tmp_path / "ws"
    (gdir / "gsk").mkdir(parents=True)
    (gdir / "gsk" / "SKILL.md").write_text("GLOBAL-DOC-BODY", encoding="utf-8")
    (gdir / "gsk2").mkdir(parents=True)
    (gdir / "gsk2" / "SKILL.md").write_text("GLOBAL2-DOC-BODY", encoding="utf-8")
    monkeypatch.setattr(ct, "SKILLS_DIR", str(gdir))
    return ct, gdir, ws


def test_read_skill_local_cli_off_reads_global_only(tmp_path, monkeypatch):
    ct, gdir, ws = _mk_cli_env(tmp_path, monkeypatch)
    # CLI 关 → cwd 空 → 只读全局
    out = _run(ct.read_skill_tool_logic("", "gsk", is_docker=False))
    assert "GLOBAL-DOC-BODY" in out
    assert ".agents/skills/gsk" in out


def test_read_skill_local_workspace_first(tmp_path, monkeypatch):
    ct, gdir, ws = _mk_cli_env(tmp_path, monkeypatch)
    (ws / ".agent" / "skills" / "gsk").mkdir(parents=True)
    (ws / ".agent" / "skills" / "gsk" / "SKILL.md").write_text("WS-DOC-BODY", encoding="utf-8")
    out = _run(ct.read_skill_tool_logic(str(ws), "gsk", is_docker=False))
    assert "WS-DOC-BODY" in out
    assert "GLOBAL-DOC-BODY" not in out


def test_read_skill_local_workspace_missing_falls_back_to_global(tmp_path, monkeypatch):
    ct, gdir, ws = _mk_cli_env(tmp_path, monkeypatch)
    out = _run(ct.read_skill_tool_logic(str(ws), "gsk", is_docker=False))
    assert "GLOBAL-DOC-BODY" in out
    # 自动复制进工作区（后续轮命中工作区）
    assert (ws / ".agent" / "skills" / "gsk" / "SKILL.md").exists()


def test_read_skill_local_not_found(tmp_path, monkeypatch):
    ct, gdir, ws = _mk_cli_env(tmp_path, monkeypatch)
    out = _run(ct.read_skill_tool_logic(str(ws), "nope", is_docker=False))
    assert "[Error]" in out


def test_skill_cwd_or_none_follows_cli_switch(monkeypatch):
    import py.cli_tool as ct

    async def _load_off():
        return {"CLISettings": {"enabled": False, "cc_path": "C:\\off"}}

    monkeypatch.setattr(ct, "load_settings", _load_off)
    assert _run(ct._skill_cwd_or_none()) == ""

    async def _load_on():
        return {"CLISettings": {"enabled": True, "cc_path": "C:\\on"}}

    monkeypatch.setattr(ct, "load_settings", _load_on)
    assert _run(ct._skill_cwd_or_none()) == "C:\\on"


# ==================== C. tool_assembly：read_skill 恒定公告 ====================

def _mk_ta_settings(cli_enabled):
    return {
        "mcpServers": {},
        "HASettings": {"enabled": False},
        "chromeMCPSettings": {"enabled": False, "type": "external"},
        "sqlSettings": {"enabled": False},
        "CLISettings": {"enabled": cli_enabled, "engine": "local", "mode_change": False},
        "visionControlSettings": {"enabled": False},
        "tools": {
            "time": {"enabled": False, "triggerMode": ""},
            "weather": {"enabled": False},
            "wikipedia": {"enabled": False},
            "randomTopic": {"enabled": False},
            "arxiv": {"enabled": False},
            "getFile": {"enabled": False},
            "autoBehavior": {"enabled": False},
        },
        "diarySettings": {},
        "text2imgSettings": {"enabled": False},
        "codeSettings": {"enabled": False},
        "custom_http": [],
        "workflows": [],
    }


def _mk_ta(tk_extra=None):
    async def _none(_s):
        return None

    tk = {
        "mcp_client_list": {},
        "node_ext_mcp_tools": {},
        "get_llm_tool": _none,
        "get_agent_tool": _none,
        "get_a2a_tool": _none,
        "read_skill_tool_local": {
            "type": "function",
            "function": {"name": "read_skill_tool_local", "description": "d", "parameters": {}},
        },
    }
    tk.update(tk_extra or {})
    return tk


def _ta_names(tools):
    return [t.get("function", {}).get("name", "") for t in tools]


def test_tool_assembly_read_skill_announced_when_cli_off():
    import py.tool_assembly as ta

    tools = _run(ta.build_llm_tools(_Req(), _mk_ta_settings(False), _mk_ta()))
    assert "read_skill_tool_local" in _ta_names(tools)


def test_tool_assembly_no_duplicate_when_variant_present():
    import py.tool_assembly as ta

    tk = _mk_ta({
        "get_local_tools_for_permission": lambda m: [
            {"type": "function",
             "function": {"name": "read_skill_tool_local", "description": "x", "parameters": {}}},
        ],
        "cli_permission_mode_for": lambda s: "acceptEdits",
    })
    tools = _run(ta.build_llm_tools(_Req(), _mk_ta_settings(True), tk))
    assert _ta_names(tools).count("read_skill_tool_local") == 1


def test_tool_assembly_appends_local_when_cli_on_without_variant():
    import py.tool_assembly as ta

    tk = _mk_ta({
        "get_local_tools_for_permission": lambda m: [
            {"type": "function",
             "function": {"name": "run_command", "description": "x", "parameters": {}}},
        ],
        "cli_permission_mode_for": lambda s: "acceptEdits",
    })
    tools = _run(ta.build_llm_tools(_Req(), _mk_ta_settings(True), tk))
    assert "read_skill_tool_local" in _ta_names(tools)
    assert "run_command" in _ta_names(tools)


# ==================== D. 静态钉：描述 / 路径修复 ====================

def test_read_skill_descriptions_document_lookup_order():
    src = (_ROOT / "py" / "cli_tool.py").read_text(encoding="utf-8")
    # 两处注册表（docker/local）描述均写明 工作区→全局 查找顺序
    assert src.count("Lookup order: workspace .agent/skills/ first, then the global skills dir") == 2
    assert "When CLI/workspace is disabled only global skills are available" in src


def test_shortcut_skills_path_fixed_to_single_agent():
    src = (_ROOT / "py" / "shortcut_commands.py").read_text(encoding="utf-8")
    assert 'Path(cwd) / ".agent" / "skills"' in src
    assert 'Path(cwd) / ".agents" / "skills"' not in src


def test_server_index_call_decoupled_from_engine_gate():
    src = (_ROOT / "server.py").read_text(encoding="utf-8")
    # 调用点：_append_project_skills 带 cli_settings 参数（新签名）
    assert "await _append_project_skills(request, cwd, cli_settings, visibilityScope)" in src
    # /<skill> 注入在 CLI 门槛之外（紧跟 _inject_workspace_memory 门槛块之后、bot 平台块之前）
    inj = src.index("await _inject_workspace_memory(request, cwd, cli_settings)")
    trig = src.index("await _inject_triggered_skill(request, cwd, cli_settings)")
    bot = src.index("if request.is_app_bot and request.platform and request.platform != \"diary\":", inj)
    assert inj < trig < bot


def test_m3_append_project_skills_name_preserved():
    # m3 ratchet 钉名保留（test_m3_split STREAM/TCM helpers 依赖）
    src = (_ROOT / "server.py").read_text(encoding="utf-8")
    assert "async def _append_project_skills(request, cwd, cli_settings, visibilityScope):" in src
