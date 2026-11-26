# -*- coding: utf-8 -*-
"""S323：扩展体系的 agent 侧门面（可见性 + 可及性）。

事故背景（2026-11-26 12:13）：agent 给 SAP 写了 sap-tieba-viewer 扩展并正常
落盘 ext/，但对它自己既不可见（能力索引零扩展信息）也不可及（无启动入口），
只好硬编码打 Electron UI 端口 4633 探测 /api → 404 → 误诊「框架没挂载」。
真 API base 是 get_port()（server.py 监听口）。本模块三件套：

A. build_host_context(): system 提示注入宿主 API base + 已安装扩展摘要，
   并如实公告桥规则（扩展 MCP 工具=插件页面打开时注册，关闭即注销）。
B. list_extensions_tool_local: 只读自查（含运行态与已注册 MCP 工具名）。
C. start_extension_node_tool_local: 请求拉起扩展 node 服务——注册进
   SENSITIVE_TOOLS（tool_registry），default/auto-approve 走审批弹窗、
   yolo/cowork 直通、plan 声明层隐藏。起 node ≠ 桥接 MCP 工具（桥在
   dynamic_island 页面打开路径），返回文本如实说明。
"""
import asyncio
import json
import logging
import os
import time
from pathlib import Path

from py.get_setting import EXT_DIR, get_port

_CACHE = {"ts": 0.0, "exts": []}
_CACHE_TTL = 30.0  # 秒：扩展安装/启停是低频事件，30s 陈旧度换每轮零 IO


def _read_pkg(ext_dir: Path):
    try:
        return json.loads((ext_dir / "package.json").read_text(encoding="utf-8"))
    except Exception:
        return None


def scan_extensions():
    """已安装扩展摘要（TTL 缓存）：id/类型/运行口/已注册 MCP 工具名。
    口径与 py/extensions.list_extensions 对齐：index.html 或 index.js 存在
    才算扩展；node 子目录/压缩包自然被 is_dir 排除。"""
    now = time.monotonic()
    if now - _CACHE["ts"] < _CACHE_TTL:
        return _CACHE["exts"]
    from py.node_runner import node_mgr
    # S300 铁律：`from server import ...` 在 python server.py 部署下会二次执行
    # 模块体（端口再竞态/全局 settings 重初始化，S300 e2e 实锤）——读 server
    # 真源必须走 srv()；测试进程 srv()=pytest main 模块，无此属性→空表。
    node_ext_mcp_tools = {}
    try:
        from py.srv_ref import srv
        node_ext_mcp_tools = getattr(srv(), "node_ext_mcp_tools", {}) or {}
    except Exception:
        pass
    exts = []
    base = Path(EXT_DIR)
    try:
        names = sorted(os.listdir(base)) if base.is_dir() else []
    except Exception:
        names = []
    for n in names:
        d = base / n
        if not d.is_dir():
            continue
        has_node = (d / "index.js").is_file()
        has_ui = (d / "index.html").is_file()
        if not (has_node or has_ui):
            continue
        pkg = _read_pkg(d) or {}
        ne = node_mgr.exts.get(n)
        running = bool(ne and ne.proc and ne.proc.returncode is None)
        mcp = [t.get("name", "") for t in (node_ext_mcp_tools.get(n) or [])
               if isinstance(t, dict) and t.get("name")]
        exts.append({
            "id": n,
            "name": str(pkg.get("name", n)),
            "version": str(pkg.get("version", "")),
            "category": str(pkg.get("category", "")),
            "description": str(pkg.get("description", ""))[:80],
            "node": has_node,
            "ui": has_ui,
            "running_port": (ne.port if running and ne else None),
            "mcp_tools": mcp,
        })
    _CACHE["ts"] = now
    _CACHE["exts"] = exts
    return exts


def invalidate_cache():
    """测试/安装后强制刷新（扩展增删时调用可即时可见）。"""
    _CACHE["ts"] = 0.0
    _CACHE["exts"] = []


def _visible_exts(exts, agent_access):
    """S324：关闭态可见性=用户显式授权（扩展设置「允许AI主动拉起该插件」）；
    页面开着（running）不受开关限制——桥路径本就由用户亲手打开。
    未授权且关闭的扩展仅以计数一行提示存在（防 agent 误判「不存在」）。"""
    access = agent_access or {}
    vis = [e for e in exts if e["running_port"] or access.get(e["id"])]
    hidden = len(exts) - len(vis)
    return vis, hidden


def build_host_context(agent_access=None):
    """A：宿主环境 system 段（S323/S324）。无扩展也注入 API base 行——
    端口误诊与扩展无关。失败返回 ''（调用方跳过注入，不断主流程）。
    agent_access = settings.extensionAgentAccess {ext_id: bool}。"""
    try:
        exts = scan_extensions()
        vis, hidden = _visible_exts(exts, agent_access)
        access = agent_access or {}
        lines = [
            "# Host Environment",
            f"- Host API base: http://127.0.0.1:{get_port()} (requires host auth; "
            "from inside browser tools prefer the extension page's own origin). "
            "Never guess other ports — a 404 there does NOT mean the feature is missing.",
            "- Extension MCP bridge rule: extension tools register when the plugin "
            "PAGE IS OPENED and unregister on close. Tools not in your index = page "
            "closed, not missing code.",
        ]
        if not vis:
            lines.append("- Extensions visible to you: none."
                         + (f" ({hidden} more installed but hidden: agent access not "
                            "enabled in extension settings)" if hidden else ""))
        else:
            for e in vis:
                st = (f"running(port {e['running_port']})" if e["running_port"]
                      else "not running")
                mt = (" mcp_tools: " + ", ".join(e["mcp_tools"]) + " (registered)") \
                    if e["mcp_tools"] else ""
                launch = ""
                if access.get(e["id"]) and not e["running_port"]:
                    launch = (" | agent-start: allowed (user enabled "
                              "'Allow AI to actively start this extension')")
                lines.append(f"- Extension '{e['id']}': {'node' if e['node'] else 'static'}, "
                             f"{st}{mt}{launch}. {e['description']}")
            if hidden:
                lines.append(f"- (+ {hidden} more installed extensions hidden: agent "
                             "access off in extension settings — treat them as absent.)")
            lines.append("- Self-check: list_extensions_tool_local. To bring up a node "
                         "service: start_extension_node_tool_local (then its HTTP API is "
                         "reachable, but its MCP tools still only enter your index when "
                         "the panel page is open).")
        return "\n".join(lines)
    except Exception as e:
        logging.getLogger("app").info("[S323] 宿主环境注入跳过: %r", e)
        return ""


async def _load_agent_access():
    """settings.extensionAgentAccess 读取（S324）。失败按空=全部未授权（保守向）。"""
    try:
        from py.get_setting import load_settings
        s = await load_settings()
        acc = s.get("extensionAgentAccess")
        return acc if isinstance(acc, dict) else {}
    except Exception:
        return {}


async def list_extensions_tool_local() -> str:
    """[Local] B：只读列出对 agent 可见的扩展与运行态（plan 模式可用）。
    S324：关闭态可见性受「允许AI主动拉起该插件」开关门控（running 不受限）。"""
    exts = scan_extensions()
    vis, hidden = _visible_exts(exts, await _load_agent_access())
    if not vis:
        return ("[OK] No extensions visible to you under ext/."
                + (f" ({hidden} more installed but hidden: agent access not enabled "
                   "in extension settings.)" if hidden else
                   " Users can install them from the extensions panel; an extension = "
                   "a directory with index.html (UI) and/or index.js (node service) "
                   "+ package.json."))
    out = ["Extensions visible to you (%d):" % len(vis)]
    if hidden:
        out.append("(+ %d more installed but hidden: agent access off in extension "
                   "settings — treat them as absent.)" % hidden)
    for e in vis:
        kind = "node+ui" if (e["node"] and e["ui"]) else ("node" if e["node"] else "static-ui")
        st = (f"RUNNING port={e['running_port']}" if e["running_port"] else "not running")
        line = (f"- {e['id']} | {e['name']} v{e['version'] or '?'} | {kind} | {st}")
        if e["mcp_tools"]:
            line += f" | mcp_tools(registered): {', '.join(e['mcp_tools'])}"
        out.append(line)
        if e["description"]:
            out.append(f"    {e['description']}")
    out.append("To start a node service use start_extension_node_tool_local "
               "(default mode asks the user for approval).")
    return "\n".join(out)


_START_TIMEOUT = 240.0  # 秒：首装扩展 npm install 可能数分钟；超时=可稍后幂等重试


async def start_extension_node_tool_local(ext_id: str = "") -> str:
    """[Local] C：拉起扩展的 node 服务（SENSITIVE：default 须用户批复）。"""
    eid = str(ext_id or "").strip()
    if not eid or "/" in eid or "\\" in eid or ".." in eid or eid.startswith("."):
        return ("[Error] ext_id must be a single extension directory name "
                "(no separators, no dot-prefix). See list_extensions_tool_local.")
    base = Path(EXT_DIR).resolve()
    d = base / eid
    try:
        d.resolve().relative_to(base)
    except Exception:
        return f"[Error] ext_id '{eid}' resolves outside the extensions directory."
    # S324 资格门：未开启「允许AI主动拉起该插件」= 连存在性都不透露。
    # 顺序在存在性检查之前；审批层（SENSITIVE_TOOLS）在其后照常生效=双重保护。
    if not (await _load_agent_access()).get(eid):
        return (f"[Error] '{eid}': agent access not enabled. The user must turn on "
                "'Allow AI to actively start this extension' in this extension's "
                "settings in the extensions panel first. Do not retry blindly.")
    if not d.is_dir():
        avail = ", ".join(e["id"] for e in scan_extensions()) or "(none visible)"
        return f"[Error] Extension '{eid}' not found. Visible: {avail}"
    if not (d / "index.js").is_file():
        return (f"[OK] '{eid}' is a static extension (no index.js) — no node service "
                "to start; it works when its page is opened in the extensions panel.")
    from py.node_runner import node_mgr
    try:
        port = await asyncio.wait_for(node_mgr.start(eid), timeout=_START_TIMEOUT)
    except asyncio.TimeoutError:
        return (f"[Warn] '{eid}' is still booting (first-time npm install can take "
                "minutes). Retry start_extension_node_tool_local later — it is "
                "idempotent and will report the port once ready.")
    except Exception as e:
        msg = str(e)[:300]
        if not (d / "node_modules").exists():
            msg += " | node_modules missing — install may have failed; check network."
        return f"[Error] Failed to start node for '{eid}': {msg}"
    return (f"[OK] '{eid}' node service is running on port {port}.\n"
            f"- Direct HTTP: http://127.0.0.1:{port}/<path> (see its README/index.js "
            "for endpoints; call via simple_fetch or browser tools).\n"
            f"- Host proxy path: /api/extensions/{eid}/node/<path> on the host API base.\n"
            "- IMPORTANT: its MCP tools are NOT added to your index by this call "
            "(they register only while the user keeps the extension page open in "
            "the panel). This is expected, NOT a failure — do not retry the start. "
            "Use the HTTP endpoints above for this session, or ask the user to "
            "open the extension page once to register its tools.")


LIST_EXTENSIONS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_extensions_tool_local",
        "description": ("List installed SAP extensions (read-only): id, kind "
                        "(node/static), running state and port, and MCP tools "
                        "currently registered from open extension pages. Use this "
                        "before concluding an extension is missing or not loaded."),
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
}

START_EXTENSION_NODE_TOOL = {
    "type": "function",
    "function": {
        "name": "start_extension_node_tool_local",
        "description": ("Start the Node.js backend service of an installed SAP "
                        "extension by its directory id (idempotent; first run may "
                        "install dependencies). Returns the service port for direct "
                        "HTTP calls. Does NOT register the extension's MCP tools — "
                        "those require the panel page to be open."),
        "parameters": {
            "type": "object",
            "properties": {
                "ext_id": {"type": "string",
                           "description": "Extension directory name under ext/, e.g. 'sap-tieba-viewer'"},
            },
            "required": ["ext_id"],
        },
    },
}
