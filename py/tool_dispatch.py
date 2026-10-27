# -*- coding: utf-8 -*-
"""工具分发与审批哨兵（批 2h3 自 server.py 迁出，审计 09 R2-2）。

- 审批哨兵（T-9/X-9）：服务端专用前缀+哨兵字段的结构化审批信号，
  嗅探不依赖子串匹配；stream/complete 两条链共用 _is_approval_result。
- dispatch helpers：外部通道（custom_http/comfyui/HA/ChromeMCP/SQL）、
  任务中心（create_subtask 等）、未知工具（MCP → Node 扩展 → C-19
  纠错提示）。本地工具注册表 _TOOL_HOOKS 与权限 gate 属引擎同域，
  仍留 server.py（M7 与引擎合刀）；未知工具的注册表/调用器经参数注入。
"""
import difflib
import json
import logging

from py import app_state


# ---------- 审批哨兵（T-9/X-9） ----------

_APPROVAL_PREFIX = '{"__sap_approval_v1__":1,'


def _approval_payload(tool_name, tool_params, permission_mode, cwd,
                      scope=None, reason=None) -> str:
    obj = {
        "__sap_approval_v1__": 1,
        "type": "approval_required",
        "tool_name": tool_name,
        "tool_params": tool_params,
        "permission_mode": permission_mode,
        "cwd": cwd,
    }
    # S153: 附加字段（S150 起 IM 编排与审批卡容忍未知键；哨兵前缀顺序不变）
    if scope:
        obj["scope"] = scope
    if reason:
        obj["reason"] = reason
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _is_approval_result(res) -> dict:
    """命中返回审批 dict，否则 None。正文夹带字面量不会误触发（严格前缀）。"""
    if not isinstance(res, str) or not res.startswith(_APPROVAL_PREFIX):
        return None
    try:
        obj = json.loads(res)
    except Exception:
        return None
    if isinstance(obj, dict) and obj.get("__sap_approval_v1__") == 1 \
            and obj.get("type") == "approval_required":
        return obj
    return None


# ---------- 分发 helpers ----------

def _stringify_result(result) -> str:
    if isinstance(result, str):
        return result
    if hasattr(result, "model_dump"):
        return str(result.model_dump())
    return str(result)


async def dispatch_external_tool(tool_name, tool_params, settings):
    """Prefix aliases + custom_http/comfyui/HA/ChromeMCP/SQL clients.

    Returns (possibly-renamed tool_name, handled_result-or-None).
    """
    from py.custom_http import fetch_custom_http
    from py.comfyui_tool import comfyui_tool_call
    if "multi_tool_use." in tool_name:
        tool_name = tool_name.replace("multi_tool_use.", "")

    if "custom_http_" in tool_name:
        tool_name = tool_name.replace("custom_http_", "")
        logging.getLogger("app").info(tool_name)
        settings_custom_http = settings['custom_http']
        for custom in settings_custom_http:
            if custom['name'] == tool_name:
                tool_custom_http = custom
                break
        method = tool_custom_http['method']
        url = tool_custom_http['url']
        headers = tool_custom_http['headers']
        result = await fetch_custom_http(method, url, headers, tool_params)
        return tool_name, str(result)

    if "comfyui_" in tool_name:
        tool_name = tool_name.replace("comfyui_", "")
        text_input = tool_params.get('text_input', None)
        text_input_2 = tool_params.get('text_input_2', None)
        image_input = tool_params.get('image_input', None)
        image_input_2 = tool_params.get('image_input_2', None)
        logging.getLogger("app").info(tool_name)
        result = await comfyui_tool_call(tool_name, text_input, image_input, text_input_2, image_input_2)
        # S151：生成任务落通知中心（长任务完成可见性）
        try:
            from py import notification_center
            _s = str(result)
            notification_center.emit(
                "generation", f"comfyui 生成任务完成：{tool_name}" if not _s.startswith("Error")
                else f"comfyui 生成任务失败：{tool_name}", level="info" if not _s.startswith("Error") else "warn")
        except Exception:
            pass
        return tool_name, str(result)

    if settings["HASettings"]["enabled"]:
        if tool_name in app_state.HA_client._tools:
            return tool_name, _stringify_result(await app_state.HA_client.call_tool(tool_name, tool_params))

    if settings['chromeMCPSettings']['enabled'] and settings['chromeMCPSettings']['type'] == 'external':
        if tool_name in app_state.ChromeMCP_client._tools:
            return tool_name, _stringify_result(await app_state.ChromeMCP_client.call_tool(tool_name, tool_params))

    if settings["sqlSettings"]["enabled"]:
        if tool_name in app_state.sql_client._tools:
            return tool_name, _stringify_result(await app_state.sql_client.call_tool(tool_name, tool_params))

    return tool_name, None


async def dispatch_task_center_tool(tool_name, tool_params, settings):
    """create_subtask / query_task_progress / cancel_subtask / finish_task."""
    from py.task_tools import (
        create_subtask,
        query_task_progress,
        cancel_subtask,
        finish_task
    )
    cli_settings = settings.get("CLISettings", {})
    cwd = cli_settings.get("cc_path")

    if tool_name == "create_subtask":
        # 读取共识文件（如果存在）
        from pathlib import Path
        import aiofiles

        consensus_content = None
        consensus_file = Path(cwd) / ".agent" / "consensus.md"
        if consensus_file.exists():
            async with aiofiles.open(consensus_file, 'r', encoding='utf-8') as f:
                consensus_content = await f.read()

        return await create_subtask(
            workspace_dir=cwd,
            settings=settings,
            consensus_content=consensus_content,
            **tool_params  # 这行是关键：它会把 AI 传的 title, platforms 等全部解包传入
        )

    elif tool_name == "query_task_progress":
        return await query_task_progress(
            workspace_dir=cwd,
            **tool_params
        )

    elif tool_name == "cancel_subtask":
        return await cancel_subtask(
            workspace_dir=cwd,
            task_id=tool_params.get("task_id")
        )
    elif tool_name == "finish_task":
        return await finish_task(
            workspace_dir=cwd,
            task_id=tool_params.get("task_id"),
            result=tool_params.get("result"),
        )


async def dispatch_unknown_tool(tool_name, tool_params, hook_names, ext_mcp_tools, node_tool_caller,
                                settings=None):
    """MCP clients, node-extension tools, then the C-19 correction hint.

    hook_names      : 本地工具注册表的名称快照（server 的 _TOOL_HOOKS）
    ext_mcp_tools   : {ext_id: [tool_meta]} Node 扩展工具注册表（活引用）
    node_tool_caller: async (ext_id, tool_name, tool_params) -> str
    settings        : 当前请求 settings，用于解析全局 mcpCallTimeout（S63）
    """
    settings = settings or {}
    for server_name, mcp_client in app_state.mcp_client_list.items():
        if hasattr(mcp_client, '_conn') and mcp_client._conn and tool_name in mcp_client._conn.tools:
            # 超时三级解析（S63）：server 配置 callTimeout → 全局 mcpCallTimeout → call_tool 默认值
            _timeout = (getattr(mcp_client, '_config', None) or {}).get("callTimeout") \
                or settings.get("mcpCallTimeout")
            return _stringify_result(await mcp_client.call_tool(tool_name, tool_params, timeout=_timeout))

    # 2. 🔥 查询 Node 扩展的 MCP 工具
    for ext_id, tools in ext_mcp_tools.items():
        for tool in tools:
            if tool['name'] == tool_name:
                # 找到对应的扩展，通过WebSocket调用
                return await node_tool_caller(ext_id, tool_name, tool_params)

    # C-19: 未知工具不再静默返回 None——给 LLM 可自我纠错的显式指引（含近似名建议）
    _avail = set(hook_names)
    for _mc in app_state.mcp_client_list.values():
        if hasattr(_mc, '_conn') and _mc._conn:
            _tl = getattr(_mc._conn, 'tools', None) or {}
            _avail.update(_tl.keys() if isinstance(_tl, dict) else _tl)
    for _ext_tools in ext_mcp_tools.values():
        for _t_meta in _ext_tools:
            if isinstance(_t_meta, dict) and _t_meta.get('name'):
                _avail.add(_t_meta['name'])
    _guess = difflib.get_close_matches(tool_name, sorted(_avail), n=3, cutoff=0.6)
    _hint = f" 最接近的可用工具：{', '.join(_guess)}。" if _guess else ""
    return (f"[Unknown Tool] 工具 '{tool_name}' 不存在，无法执行。{_hint}"
            f"请从工具列表中选择一个真实存在的工具名重试（不要新造或拼接工具名）。")
