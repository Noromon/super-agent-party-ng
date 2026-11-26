# -*- coding: utf-8 -*-
"""E-1b: single source for the LLM tool-list assembly.

The streaming and the complete engine used to carry two copy-pasted copies
that drifted (see audit 09 / checkpoint S43): the complete engine never
announced node-extension tools to the LLM, read mcpServers["tools"] without
a fallback, and carried an accidental duplicated init line. Dispositioned
(decision S43): align both engines, node-extension tools announced on both.

This module imports nothing from server.py: every process-global client and
tool object is injected through the ``tk`` toolkit dict, which server
rebuilds per request (fresh global references, no staleness).
"""

import logging
import json

from py.tool_registry import PLAN_BLOCKED_TOOLS


def _plan_hide_blocked_tools(tools, is_plan):
    """S221: plan 模式声明层隐藏——写/执行类工具对模型直接不可见（对齐 opencode
    permission-deny-invisible），根治「看得见却调用被拦」的多轮蛮干。
    非 plan 原样返回（同引用零漂移）；plan 时返回新列表，不改调用方原列表。"""
    if not is_plan:
        return tools
    kept = [t for t in tools
            if t.get("function", {}).get("name") not in PLAN_BLOCKED_TOOLS]
    hidden = len(tools) - len(kept)
    if hidden:
        logging.getLogger("app").info(
            f"[Plan Mode] 声明层隐藏 {hidden} 个写/执行工具: {len(tools)} -> {len(kept)}")
    return kept


def _ensure_read_skill_local(tools, tk):
    """S209：知识 skill 读取与 CLI 执行权限解耦——列表无 read_skill* 变体时
    恒定公告本地版（CLI 关=无工作区只读全局；CLI 开=工作区→全局）。纯只读零副作用。"""
    for t in tools:
        if str(t.get("function", {}).get("name", "")).startswith("read_skill"):
            return
    tools.append(tk["read_skill_tool_local"])


def _ensure_tool_once(tools, schema):
    """S323：按工具名去重的恒定公告（幂等，两引擎/全模式单点语义）。"""
    name = schema.get("function", {}).get("name", "")
    if not name:
        return
    for t in tools:
        if t.get("function", {}).get("name") == name:
            return
    tools.append(schema)


def _ensure_ext_visibility_tools(tools, tk):
    """S323(B)：扩展自查——纯只读，恒定公告（含 plan，read_skill 同语义先例）。
    S323(C)：起扩展 node 服务——声明层恒定公告，闸门在 SENSITIVE_TOOLS：plan 由
    _plan_hide_blocked_tools 隐藏，default/auto-approve 审批弹窗，yolo/cowork 直通
    （对齐 delete_file_tool_local 先例，dispatch 兜底同集合）。缺键=老式 toolkit，
    优雅跳过（S210 KeyError→500 事故反面教训）。"""
    for key in ("list_extensions_tool", "start_extension_node_tool"):
        schema = tk.get(key)
        if isinstance(schema, dict):
            _ensure_tool_once(tools, schema)


async def build_llm_tools(request, settings, tk):
    """Assemble the OpenAI-format tool list announced to the LLM.

    request  : ChatRequest (reads .tools / .messages)
    settings : merged settings dict
    tk       : toolkit dict from server._assemble_toolkit()
    """
    tools = request.tools or []
    tool_names = set()
    if tk["mcp_client_list"]:
        _live_status = tk.get("mcp_status", {})
        for server_name, mcp_client in tk["mcp_client_list"].items():
            if server_name in settings['mcpServers']:
                if 'disabled' not in settings['mcpServers'][server_name]:
                    settings['mcpServers'][server_name]['disabled'] = False
                # 连接状态以内存实时值为准（process_mcp 单一写者，S62 裁决 C）；
                # 内存没有该 server（启动 lifespan 路径）再回退磁盘 processingStatus
                _status = _live_status.get(server_name)
                if _status is None:
                    _status = settings['mcpServers'][server_name].get('processingStatus')
                if settings['mcpServers'][server_name]['disabled'] is False and _status == 'ready':
                    disable_tools = []
                    for tool in settings['mcpServers'][server_name].get("tools", []):
                        if tool.get("enabled", True) is False:
                            disable_tools.append(tool["name"])
                    function = await mcp_client.get_openai_functions(disable_tools=disable_tools)
                    if function:
                        tools.extend(function)
    # 🔥 Node 扩展的工具（S43 裁决：两引擎统一公告）
    for ext_id, tools_list in tk["node_ext_mcp_tools"].items():
        for tool in tools_list:
            tool_name = tool.get('name')
            if tool_name and tool_name not in tool_names:
                tool_names.add(tool_name)
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": tool.get('description', f'来自扩展 {ext_id} 的工具'),
                        "parameters": tool.get('parameters', {
                            "type": "object",
                            "properties": {},
                            "required": []
                        })
                    }
                })
            else:
                logging.getLogger("app").info(f"[WARNING] 跳过重复工具: {tool_name}")

    get_llm_tool_fuction = await tk["get_llm_tool"](settings)
    if get_llm_tool_fuction:
        tools.append(get_llm_tool_fuction)
    get_agent_tool_fuction = await tk["get_agent_tool"](settings)
    if get_agent_tool_fuction:
        tools.append(get_agent_tool_fuction)
    get_a2a_tool_fuction = await tk["get_a2a_tool"](settings)
    if get_a2a_tool_fuction:
        tools.append(get_a2a_tool_fuction)
    if settings["HASettings"]["enabled"]:
        ha_tool = await tk["HA_client"].get_openai_functions(disable_tools=[])
        if ha_tool:
            tools.extend(ha_tool)
    if settings['chromeMCPSettings']['enabled'] and settings['chromeMCPSettings']['type'] == 'external':
        chromeMCP_tool = await tk["ChromeMCP_client"].get_openai_functions(disable_tools=[])
        if chromeMCP_tool:
            tools.extend(chromeMCP_tool)
    if settings['chromeMCPSettings']['enabled'] and settings['chromeMCPSettings']['type'] == 'internal':
        tools.extend(tk["all_cdp_tools"])
    if settings['sqlSettings']['enabled']:
        sql_tool = await tk["sql_client"].get_openai_functions(disable_tools=[])
        if sql_tool:
            tools.extend(sql_tool)
    if settings['CLISettings']['enabled']:
        _cli_mode = tk["cli_permission_mode_for"](settings)
        if settings['CLISettings']['engine'] == 'ds':
            tools.extend(tk["get_tools_for_permission"](_cli_mode))
        elif settings['CLISettings']['engine'] == 'local':
            tools.extend(tk["get_local_tools_for_permission"](_cli_mode))
        elif settings['CLISettings']['engine'] == 'wsl':
            tools.extend(tk["get_wsl_tools_for_permission"](_cli_mode))
        elif settings['CLISettings']['engine'] == 'acp':
            if _cli_mode != "plan":
                tools.append(tk["acp_agent_tool"])
    if settings['CLISettings']['mode_change'] and tk["cli_permission_mode_for"](settings) != "plan":
        tools.append(tk["mode_change_tool"])
    _ensure_read_skill_local(tools, tk)
    _ensure_ext_visibility_tools(tools, tk)  # S323(B/C)：扩展可见性/可及性门面
    if settings['visionControlSettings']['enabled']:
        tools.extend(tk["computer_use_tools"])
        if settings['visionControlSettings']['mouse']:
            tools.extend(tk["mouse_use_tools"])
        if settings['visionControlSettings']['keyboard']:
            tools.extend(tk["keyboard_use_tools"])
        if not settings['visionControlSettings']['desktopVision']:
            tools.extend(tk["desktopVision_use_tools"])
    if settings['tools']['time']['enabled'] and settings['tools']['time']['triggerMode'] == 'afterThinking':
        tools.append(tk["time_tool"])
    if settings["tools"]["weather"]['enabled']:
        tools.append(tk["weather_tool"])
        tools.append(tk["location_tool"])
        tools.append(tk["timer_weather_tool"])
    if settings["tools"]["wikipedia"]['enabled']:
        tools.append(tk["wikipedia_summary_tool"])
        tools.append(tk["wikipedia_section_tool"])
    if settings["tools"]["randomTopic"]['enabled']:
        tools.extend(tk["random_topics_tools"])
    if settings["tools"]["arxiv"]['enabled']:
        tools.append(tk["arxiv_tool"])
    # A5 日记系统（上游 3840/6177 两公告点，fork 单点=两引擎共用）
    if (settings.get("diarySettings") or {}).get("enabled", False):
        tools.append(tk["diary_query_tool"])
        tools.append(tk["diary_books_tool"])
    if settings['text2imgSettings']['enabled']:
        if settings['text2imgSettings']['engine'] == 'pollinations':
            tools.append(tk["pollinations_image_tool"])
        elif settings['text2imgSettings']['engine'] == 'openai':
            tools.append(tk["openai_image_tool"])
        elif settings['text2imgSettings']['engine'] == 'openaiChat':
            tools.append(tk["openai_chat_image_tool"])
    if settings['tools']['getFile']['enabled']:
        tools.append(tk["file_tool"])
        tools.append(tk["image_tool"])
        tools.append(tk["view_images_tool"])  # S243: 一手视觉优先
        tools.append(tk["analyze_image_tool"])
        tools.append(tk["review_image_tool"])
        tools.append(tk["analyze_images_tool"])
    if settings['tools']['autoBehavior']['enabled'] and request.messages[-1]['role'] == 'user':
        tools.append(tk["auto_behavior_tool"])
    if settings["codeSettings"]['enabled']:
        if settings["codeSettings"]["engine"] == "e2b":
            tools.append(tk["e2b_code_tool"])
        elif settings["codeSettings"]["engine"] == "sandbox":
            tools.append(tk["local_run_code_tool"])
    if settings["custom_http"]:
        for custom_http in settings["custom_http"]:
            if custom_http["enabled"]:
                if custom_http['body'] == "":
                    custom_http['body'] = "{}"
                custom_http_tool = {
                    "type": "function",
                    "function": {
                        "name": f"custom_http_{custom_http['name']}",
                        "description": f"{custom_http['description']}",
                        "parameters": json.loads(custom_http['body']),
                    },
                }
                tools.append(custom_http_tool)
    if settings["workflows"]:
        for workflow in settings["workflows"]:
            if workflow["enabled"]:
                comfyui_properties = {}
                comfyui_required = []
                if workflow["text_input"] is not None:
                    comfyui_properties["text_input"] = {
                        "description": "第一个文字输入，需要输入的提示词，用于生成图片或者视频，如果无特别提示，默认为英文",
                        "type": "string"
                    }
                    comfyui_required.append("text_input")
                if workflow["text_input_2"] is not None:
                    comfyui_properties["text_input_2"] = {
                        "description": "第二个文字输入，需要输入的提示词，用于生成图片或者视频，如果无特别提示，默认为英文",
                        "type": "string"
                    }
                    comfyui_required.append("text_input_2")
                if workflow["image_input"] is not None:
                    comfyui_properties["image_input"] = {
                        "description": "第一个图片输入，需要输入的图片，必须是图片URL，可以是外部链接，也可以是服务器内部的URL，例如：https://www.example.com/xxx.png  或者  http://127.0.0.1:3456/xxx.jpg",
                        "type": "string"
                    }
                    comfyui_required.append("image_input")
                if workflow["image_input_2"] is not None:
                    comfyui_properties["image_input_2"] = {
                        "description": "第二个图片输入，需要输入的图片，必须是图片URL，可以是外部链接，也可以是服务器内部的URL，例如：https://www.example.com/xxx.png  或者  http://127.0.0.1:3456/xxx.jpg",
                        "type": "string"
                    }
                    comfyui_required.append("image_input_2")
                comfyui_parameters = {
                    "type": "object",
                    "properties": comfyui_properties,
                    "required": comfyui_required
                }
                comfyui_tool = {
                    "type": "function",
                    "function": {
                        "name": f"comfyui_{workflow['unique_filename']}",
                        "description": f"{workflow['description']}+\n如果要输入图片提示词或者修改提示词，尽可能使用英语。\n返回的图片结果，请将图片的URL放入![image]()这样的markdown语法中，用户才能看到图片。如果是视频，请将视频的URL放入<video controls> <source src=''></video>的src中，用户才能看到视频。如果有多个结果，则请用换行符分隔开这几个图片或者视频，用户才能看到多个结果。",
                        "parameters": comfyui_parameters,
                    },
                }
                tools.append(comfyui_tool)
    # S221: plan 模式统一尾滤——含 request.tools 带入的原生写/执行工具与 visionControl
    # 键鼠类（dispatch 层 _plan_mode_block 仍留作兜底）。纪律能力索引(S204)在本函数之后
    # 注入，自动与隐藏后的有效声明集一致，无需额外处理。
    _is_plan = bool(settings['CLISettings']['enabled']) and \
        tk["cli_permission_mode_for"](settings) == "plan"
    tools = _plan_hide_blocked_tools(tools, _is_plan)
    return tools
