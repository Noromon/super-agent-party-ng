# -*- coding: utf-8 -*-
"""S301：工具钩子表构建、dispatch 与审批/计划模式预检域（自 server.py 逐字搬移）。

纯移动批：函数体逐字不变；唯一文档化改写=全局态引用改走 py.srv_ref.srv()
（async_tools/async_tools_lock/mcp_call_results/node_ext_mcp_tools/_TOOL_HOOKS/
cli_permission_mode_for——原语义即调用期读 server 模块全局，逐点等价）。
_TOOLS_HOOKS 字面量与状态字典的事实源保留在 server.py（审计解析与棘轮所在）。
logger 与 setup_logger 返回同一 "app" 对象（py/log_setup.py:34），取法逐字等价。
"""
import asyncio
import copy
import json
import logging
import re
import time
from typing import AsyncIterator, List

from py.agent import is_tool_allowed_by_project_config
from py.diary_query_tool import handle_list_diary_books, handle_query_diary
from py.proxy_util import net_error_hint
from py.srv_ref import srv as _srv
from py.tool_dispatch import (_approval_payload, _is_approval_result,
                              dispatch_external_tool as _dispatch_external_tool,
                              dispatch_task_center_tool as _dispatch_task_center_tool,
                              dispatch_unknown_tool as _dispatch_unknown_tool)
from py.tool_registry import (GLOBAL_APPROVAL_TOOLS, PLAN_BLOCKED_TOOLS,
                              SENSITIVE_TOOLS)
from py.vision_tools import analyze_image, analyze_images, get_image_content, review_image, view_images
from py.ws_manager import ws_manager

logger = logging.getLogger("app")  # S301：与 server.setup_logger 返回值同一对象


_UNEXPECTED_KW_RE = re.compile(r"unexpected keyword argument '(\w+)'")


async def execute_tool(tool_id: str, tool_name: str, args: dict, settings: dict,user_prompt: str):
    try:
        results = await dispatch_tool(tool_name, args, settings)
        if isinstance(results, AsyncIterator):
            buffer = []
            async for chunk in results:
                buffer.append(chunk)
            results = "".join(buffer)
                
        if tool_name in ["query_knowledge_base"] and type(results) == list:
            from py.know_base import rerank_knowledge_base
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt,results)
            results = json.dumps(results, ensure_ascii=False, indent=4)
        async with _srv().async_tools_lock:
            _srv().async_tools[tool_id] = {
                "status": "completed",
                "result": results,
                "name": tool_name,
                "parameters": args,
            }
    except Exception as e:
        async with _srv().async_tools_lock:
            _srv().async_tools[tool_id] = {
                "status": "error",
                "result": str(e),
                "name": tool_name,
                "parameters": args,
            }

async def call_node_extension_tool(ext_id: str, tool_name: str, tool_params: dict) -> str:
    """通过WebSocket调用Node扩展的工具"""
    import uuid
    
    call_id = str(uuid.uuid4())
    future = asyncio.Future()
    _srv().mcp_call_results[call_id] = future
    
    # 广播给所有连接，找到对应的扩展
    await ws_manager.broadcast({
        "type": "call_mcp_tool",
        "data": {
            "ext_id": ext_id,
            "tool_name": tool_name,
            "tool_params": tool_params,
            "call_id": call_id
        }
    })
    
    try:
        # 等待结果，超时30秒
        result = await asyncio.wait_for(future, timeout=30.0)
        return str(result)
    except asyncio.TimeoutError:
        return f"调用扩展 {ext_id} 的工具 {tool_name} 超时"
    finally:
        if call_id in _srv().mcp_call_results:
            del _srv().mcp_call_results[call_id]

def _build_tool_hooks():
    """Tool-name -> callable table (audit 09 M-3: built once on first use).

    Imports stay function-local so aliases (e.g. py.utility_tools.time) do
    not leak into module scope; only the resulting dict is published to the
    module-level _TOOL_HOOKS that dispatch_tool and audit tooling read.
    """
    from py.web_search import (
        DDGsearch, 
        searxng,
        Tavily_search,
        Bing_search,
        Google_search,
        Brave_search,
        Exa_search,
        Serper_search,
        bochaai_search,
        youcom_search,
        jina_crawler,
        Crawl4Ai_search,
        firecrawl_search,
        simple_fetch,
        markdown_new,
        make_engine_with_fallback as _fb, browser_search,
    )
    from py.know_base import query_knowledge_base
    from py.agent_tool import agent_tool_call
    from py.a2a_tool import a2a_tool_call
    from py.llm_tool import custom_llm_tool
    from py.pollinations import pollinations_image,openai_image,openai_chat_image
    from py.load_files import get_file_content
    from py.code_interpreter import e2b_code,local_run_code
    from py.custom_http import fetch_custom_http
    from py.comfyui_tool import comfyui_tool_call
    from py.utility_tools import (
        time,
        get_weather,
        get_location_coordinates,
        get_weather_by_city,
        get_wikipedia_summary_and_sections,
        get_wikipedia_section_content,
        search_arxiv_papers
    )
    from py.autoBehavior import auto_behavior

    # Docker CLI 工具（原有）
    from py.cli_tool import (
        docker_sandbox,
        list_files_tool,
        read_file_tool,
        read_file_range_tool, 
        tail_file_tool,     
        search_files_tool,
        edit_file_tool,
        edit_file_patch_tool, 
        glob_files_tool,       
        todo_write_tool, 
        list_processes_tool,
        get_process_logs_tool,
        kill_process_tool,
    docker_manage_ports_tool,
    read_skill_tool,
    # WSL 沙箱引擎（S132/A13，Windows 专属）
    shell_tool_wsl,
    get_wsl_tools_for_permission,
)

    # 新增：本地环境 CLI 工具（假设保存在 py/local_cli_tool.py）
    from py.cli_tool import (
        shell_tool_local,           # 本地 bash 执行（对应 docker_sandbox）
        list_files_tool_local,     # 本地文件列表
        read_file_tool_local,      # 本地文件读取
        read_file_range_tool_local, # <--- 新增导入
        tail_file_tool_local,       # <--- 新增导入
        search_files_tool_local,   # 本地文件搜索
        edit_file_tool_local,      # 本地文件写入
        edit_file_patch_tool_local,# 本地精确替换
        delete_file_tool_local,    # S315 本地删除（入 trash）
        glob_files_tool_local,     # 本地 glob 查找
        todo_write_tool_local,     # 本地任务管理
        ask_user_question_tool,    # S194 结构化提问（主流内被拦截挂起）
        local_net_tool,            # 本地网络工具
        read_skill_tool_local,
    )

    # S323：扩展可见性/可及性门面
    from py.agent_ext_tools import (
        list_extensions_tool_local,
        start_extension_node_tool_local,
    )

    from py.cdp_tool import (
        list_pages,
        navigate_page,
        new_page,
        close_page,
        select_page,
        take_snapshot,
        wait_for,
        click,
        fill,
        hover,
        press_key,
        evaluate_script,
        take_screenshot,
        fill_form,
        drag,
        handle_dialog, web_render, clean_dom, remove_element, stop_loading, escape_back, reset_page_state, browser_policy_report, get_page_markdown, check_redirect, approve_navigation, scroll_and_find, network_watch, collect_list  # S255/S269: S253 曾漏注册
    )
    from py.random_topic import get_random_topics,get_categories

    from py.task_tools import (
        create_subtask,
        query_task_progress,
        cancel_subtask,
        finish_task
    )
    
    from py.computer_use_tool import (
        mouse_move,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        mouse_scroll,
        mouse_hold,
        copy_to_input_box,
        keyboard_press,
        keyboard_sequence,
        keyboard_hotkey,
        keyboard_hold,
        wait,
        screenshot
    )

    from py.mode_change import update_workspace_settings
    from py.acpx_tools import acpx_agent

    # ==================== 2. 定义工具映射表 ====================
    _srv()._TOOL_HOOKS = {
        "DDGsearch": _fb("duckduckgo", DDGsearch), "browser_lookup": browser_search, "searxng": _fb("searxng", searxng),
        "Tavily_search": _fb("tavily", Tavily_search),
        "query_knowledge_base": query_knowledge_base,
        "jina_crawler": jina_crawler,
        "Crawl4Ai_search": Crawl4Ai_search,
        "firecrawl_search": firecrawl_search,
        "simple_fetch":simple_fetch,
        "markdown_new":markdown_new,
        "agent_tool_call": agent_tool_call,
        "a2a_tool_call": a2a_tool_call,
        "custom_llm_tool": custom_llm_tool,
        "pollinations_image":pollinations_image,
        "get_file_content":get_file_content,
        "get_image_content": get_image_content,
        "secondhand_describe_image": analyze_image,
        "secondhand_review_image": review_image,
        "secondhand_describe_images": analyze_images,
        "view_images": view_images,  # S243: 一手视觉直注
        "e2b_code": e2b_code,
        "local_run_code": local_run_code,
        "openai_image": openai_image,
        "openai_chat_image":openai_chat_image,
        "query_diary": handle_query_diary,
        "list_diary_books": handle_list_diary_books,
        "Bing_search": _fb("bing", Bing_search),
        "Google_search": _fb("google", Google_search),
        "Brave_search": _fb("brave", Brave_search),
        "Exa_search": _fb("exa", Exa_search),
        "Serper_search": _fb("serper", Serper_search),
        "bochaai_search": _fb("bochaai", bochaai_search),
        "youcom_search": _fb("youcom", youcom_search),
        "comfyui_tool_call": comfyui_tool_call,
        "time": time,
        "get_weather": get_weather,
        "get_location_coordinates": get_location_coordinates,
        "get_weather_by_city":get_weather_by_city,
        "get_wikipedia_summary_and_sections": get_wikipedia_summary_and_sections,
        "get_wikipedia_section_content": get_wikipedia_section_content,
        "search_arxiv_papers": search_arxiv_papers,
        "auto_behavior": auto_behavior,
        "list_pages": list_pages,
        "new_page": new_page,
        "close_page": close_page,
        "select_page": select_page,
        "navigate_page": navigate_page,
        "take_snapshot": take_snapshot,
        "click": click,
        "fill": fill,
        "evaluate_script": evaluate_script,
        "take_screenshot": take_screenshot,
        "hover": hover,
        "press_key": press_key,
        "wait_for": wait_for,
        "fill_form":fill_form,
        "drag": drag,
        "handle_dialog": handle_dialog, "web_render": web_render, "clean_dom": clean_dom, "remove_element": remove_element, "stop_loading": stop_loading, "escape_back": escape_back, "reset_page_state": reset_page_state, "browser_policy_report": browser_policy_report, "get_page_markdown": get_page_markdown, "check_redirect": check_redirect, "approve_navigation": approve_navigation, "scroll_and_find": scroll_and_find, "network_watch": network_watch, "collect_list": collect_list,  # S255/S269: 补 S253 幽灵工具
        "get_random_topics":get_random_topics,
        "get_categories":get_categories,
        
        # Docker Sandbox 相关工具（原有）
        "docker_sandbox": docker_sandbox,
        "list_files_tool": list_files_tool,
        "read_file_tool": read_file_tool,
        "read_file_range_tool": read_file_range_tool, # <--- 映射新工具
        "tail_file_tool": tail_file_tool,             # <--- 映射新工具
        "search_files_tool": search_files_tool,
        "edit_file_tool": edit_file_tool,
        "edit_file_patch_tool": edit_file_patch_tool,
        "glob_files_tool": glob_files_tool,
        "todo_write_tool": todo_write_tool,
        "list_processes_tool": list_processes_tool,
        "get_process_logs_tool": get_process_logs_tool,
        "kill_process_tool": kill_process_tool,
        "docker_manage_ports_tool": docker_manage_ports_tool,
        "read_skill_tool": read_skill_tool,
        
        # 本地环境工具（新增）- 与 Docker 版本功能相同但操作本地文件系统
        "shell_tool_local": shell_tool_local,                     # 本地 bash 执行
    "shell_tool_wsl": shell_tool_wsl,                         # WSL bash 执行（S132/A13）
        "list_files_tool_local": list_files_tool_local,         # 本地文件列表
        "read_file_tool_local": read_file_tool_local,           # 本地文件读取
        "read_file_range_tool_local": read_file_range_tool_local, # <--- 映射新工具
        "tail_file_tool_local": tail_file_tool_local,             # <--- 映射新工具
        "search_files_tool_local": search_files_tool_local,     # 本地文件搜索
        "edit_file_tool_local": edit_file_tool_local,           # 本地文件写入
        "edit_file_patch_tool_local": edit_file_patch_tool_local,  # 本地精确替换
        "delete_file_tool_local": delete_file_tool_local,          # S315 本地删除（入 trash）
        "glob_files_tool_local": glob_files_tool_local,         # 本地 glob 查找
        "todo_write_tool_local": todo_write_tool_local,         # 本地任务管理
        "ask_user_question_tool": ask_user_question_tool,        # S194 提问兜底（主流在工具轮已挂起，不会走到）
        "local_net_tool": local_net_tool,                       # 本地网络工具
        "read_skill_tool_local": read_skill_tool_local,         # 本地技能读取
        "list_extensions_tool_local": list_extensions_tool_local,        # S323(B) 只读
        "start_extension_node_tool_local": start_extension_node_tool_local,  # S323(C) SENSITIVE

        # 任务中心工具（新增）
        "create_subtask": create_subtask,
        "query_task_progress": query_task_progress,
        "cancel_subtask": cancel_subtask,
        "finish_task":finish_task,

        # 鼠标键盘控制
        "mouse_move":mouse_move,
        "mouse_click":mouse_click,
        "mouse_double_click":mouse_double_click,
        "mouse_drag":mouse_drag,
        "mouse_scroll":mouse_scroll,
        "mouse_hold":mouse_hold,
        "copy_to_input_box":copy_to_input_box,
        "keyboard_press":keyboard_press,
        "keyboard_sequence":keyboard_sequence,
        "keyboard_hotkey":keyboard_hotkey,
        "keyboard_hold":keyboard_hold,
        "wait":wait,
        "screenshot":screenshot,

        "update_workspace_settings":update_workspace_settings,
        "acpx_agent":acpx_agent,
    }

def _plan_mode_block(tool_name, settings):
    """Plan-mode read-only hard block (rule 0). Returns message or None."""
    if tool_name in PLAN_BLOCKED_TOOLS:
        from py.cli_tool import normalize_permission_mode
        _engine0 = settings.get("CLISettings", {}).get("engine", "")
        if _engine0 == "local":
            _env0 = settings.get("localEnvSettings", {})
        elif _engine0 == "ds":
            _env0 = settings.get("dsSettings", {})
        elif _engine0 == "wsl":
            _env0 = settings.get("wslSettings", {})
        else:
            _env0 = settings.get("acpSettings", {})
        if normalize_permission_mode(_env0.get("permissionMode", "default")) == "plan":
            logging.getLogger("app").info(f"[Permission] plan mode blocked '{tool_name}'")
            return ("[Blocked] 你当前处于计划模式（只读），该工具本回合对你不可见、不可调用。"
                    "请把拟执行的改动写进计划正文（文件、步骤、验证方式）交给用户确认，"
                    "用只读工具继续调研；用户确认并切换模式后再执行。")

    return None

def _sensitive_approval(tool_name, tool_params, settings):
    """Human-in-the-loop approval gate for SENSITIVE_TOOLS."""
    if tool_name in SENSITIVE_TOOLS:
        
        # 获取相关配置
        cli_settings = settings.get("CLISettings", {})
        cwd = cli_settings.get("cc_path")
        # 修复：local 环境应该从 localEnvSettings 读取权限模式
        engine = cli_settings.get("engine", "")
        
        if engine == "local":
            env_settings = settings.get("localEnvSettings", {})
        elif engine == "ds":
            env_settings = settings.get("dsSettings", {})
        elif engine == "wsl":
            env_settings = settings.get("wslSettings", {})
        else:
            env_settings = settings.get("acpSettings", {})

        permission_mode = _srv().cli_permission_mode_for(settings)

        is_allowed = False

        # --- 规则 A: 全局 YOLO 模式 (Bypass Permissions) ---
        if permission_mode == "yolo" or permission_mode == "cowork":
            is_allowed = True
            
        # --- 规则 B: 自动批准模式 (Accept Edits) ---
        # 允许文件编辑类工具（包括全量写入、精确替换、任务管理）
        # 但依然拦截终端命令（docker/bash）
        elif permission_mode == "auto-approve":
            if tool_name in ["edit_file_tool", "edit_file_patch_tool", "todo_write_tool", "edit_file_tool_local", "edit_file_patch_tool_local", "todo_write_tool_local"]:
                is_allowed = True
            # docker/bash 等危险命令在此模式下依然默认拦截，除非在项目白名单中
        
        # --- 规则 C: 默认模式 (Default) ---
        # 默认全部拦截
        
        # --- 规则 C2: 全局白名单 (S329: 插件域与 cwd 解耦) ---
        # GLOBAL_APPROVAL_TOOLS 的 "Allow Always" 存 settings.globalAllowedTools
        # （data 目录级），换工作区不需重新授权。
        if not is_allowed and tool_name in GLOBAL_APPROVAL_TOOLS:
            if tool_name in (settings.get("globalAllowedTools") or []):
                is_allowed = True
                logging.getLogger("app").info(
                    f"[Permission] Tool '{tool_name}' allowed by global config.")

        # --- 规则 C3: one-shot 放行 (S330) ---
        # 用户刚 /y 批准过（或面板批准）且模型随即重试同一工具：消费一次性
        # grant 直接放行，不再二次送审（17:21 双弹窗事故）。
        if not is_allowed:
            try:
                from py.approval_store import grant_active
                if grant_active(tool_name):
                    is_allowed = True
                    logging.getLogger("app").info(
                        f"[Permission] Tool '{tool_name}' allowed by one-shot grant.")
            except Exception:
                pass

        # --- 规则 D: 项目级白名单覆盖 (Project Config Override) ---
        # 如果以上规则未通过，检查 .agent/config.json
        # 如果用户之前点击过 "Allow Always"，这里会返回 True
        if not is_allowed and cwd:
            if is_tool_allowed_by_project_config(cwd, tool_name):
                is_allowed = True
                logging.getLogger("app").info(f"[Permission] Tool '{tool_name}' allowed by project config.")

        # --- 最终判定 ---
        if not is_allowed:
            # 返回前端特定的 JSON 结构，触发审批 UI
            logging.getLogger("app").info(f"[Permission] Blocked '{tool_name}', requesting approval.")
            return _approval_payload(tool_name, tool_params, permission_mode, cwd)

    return None

def _approval_precheck(tool_name, tool_params, settings):
    """S172：审批/路径门必须在 dispatch **之前**同步预检——asyncTools 管道曾先回
    「已启动」占位文本、把审批哨兵吞进后台结果表，导致 pending_abort 永不触发、
    Web 审批卡与 IM /y /n 全部失联（2026-10-30 事故：拦截 18 次无一次送审）。
    与 dispatch_tool 相同的只读检查；命中返回哨兵，未命中 None（不注入 grants，零副作用）。"""
    approval = _sensitive_approval(tool_name, tool_params, settings)
    if approval is not None:
        return approval
    try:
        from py import path_scope
        _ps = path_scope.evaluate(tool_name, tool_params or {}, settings)
        if _ps is not None and _ps.block is not None:
            return _ps.block
    except Exception:
        return None
    return None

def _pending_approval_reply_dict(ap, model):
    """S172：历史尾部=未批复审批哨兵 → 静止态提示（不再动模型，掐灭自动重放风暴）。"""
    note = (f"[等待审批] 操作 {ap.get('tool_name', '?')} 尚未获得用户批复，本轮不继续执行；"
            "请在会话审批卡批复，或在 IM 回复 /y 或 /n。")
    return {
        "id": "agentParty", "object": "chat.completion", "created": int(time.time()),
        "model": model or "super-model",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": note}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

async def _im_approval_hangup(request, messages, results):
    """S150/S172：IM 渠道审批挂起登记（自 stream 巨函数抽出，流式/非流式共用）。"""
    try:
        from py import approval_im, approval_store
        _ap = _is_approval_result(results)
        if not (_ap and request.is_app_bot and request.platform and request.peer_id
                and approval_store.has_handlers(request.platform)):
            return
        _hit_id = ""
        for _m in reversed(messages):
            if _m.get("role") == "tool" and _is_approval_result(_m.get("content")) is not None:
                _hit_id = _m.get("tool_call_id", "")
                break
        await approval_store.create(
            platform=request.platform, peer_id=request.peer_id,
            tool_name=_ap.get("tool_name", ""), tool_params=_ap.get("tool_params"),
            tool_call_id=_hit_id, permission_mode=_ap.get("permission_mode", ""),
            cwd=_ap.get("cwd", ""),
            messages=approval_im.strip_system_messages(copy.deepcopy(messages)))
    except Exception as _ape:
        logging.getLogger("app").warning("[Approval] 挂起审批登记失败（降级为仅前端流程）: %r", _ape)

async def _invoke_tool_hook(tool_name: str, tool_call, params: dict):
    """单次 hook 调用（S212：由 dispatch 的自愈环反复调用，丢弃脏参后重试）。"""
    if tool_name in ("shell_tool_local", "docker_sandbox", "shell_tool_wsl"):
        # 异步生成器：调用即返回 AsyncIterator，无需 await
        return tool_call(**params)
    if tool_name == "acpx_agent":
        # 常规异步函数：必须 await 才能获得实际结果
        return await tool_call(**params)

    ret_out = await tool_call(**params)
    if tool_name == "auto_behavior":
        await ws_manager.broadcast_settings_update(ret_out)
        ret_out = "任务设置成功！"
    return ret_out

async def dispatch_tool(tool_name: str, tool_params: dict, settings: dict) -> str | List | AsyncIterator[str] | None :
    logging.getLogger("app").debug(f"[dispatch] {tool_name} {str(tool_params)[:500]}")
    
    # ==================== 1. 工具映射表（首次使用时构建一次，M-3 拆分） ====================
    if not _srv()._TOOL_HOOKS:  # S301：单一事实源仍在 server 模块全局（审计字面量/棘轮所在）
        _build_tool_hooks()
    _TOOL_HOOKS = _srv()._TOOL_HOOKS
    
    # ==================== 3. 权限拦截逻辑 (Human-in-the-loop) ====================
    # 敏感/受限工具清单单一来源=py/tool_registry.py（E-1，顶部已导入）
    # 规则 0: 计划模式只读硬拦截（对全部写入/执行类工具生效，不经审批弹窗）
    blocked = _plan_mode_block(tool_name, settings)
    if blocked is not None:
        return blocked

    # 只有当调用的工具属于敏感工具列表时才进行拦截检查
    approval = _sensitive_approval(tool_name, tool_params, settings)
    if approval is not None:
        return approval

    # S153: 路径门（工作区外本地路径 / 读取族任意本地路径）——独立于工具名白名单
    # （opencode external_directory 语义；哨兵复用 → 前端审批卡与 IM /y/n/a 自动生效）
    try:
        from py import path_scope
        _ps = path_scope.evaluate(tool_name, tool_params or {}, settings)
        if _ps is not None:
            if _ps.block is not None:
                # S182(T4) 日志分线：旧文案把参数错误也报成"批复等待"，制造了
                # 查无实据的审批幽灵（事故实证 2026-10-31）。哨兵与错误分开报，
                # 且只陈述此刻真实成立的状态。
                if _ps.payload is not None:
                    logging.getLogger("app").warning(f"[PathScope] '{tool_name}' 区外路径：审批哨兵已回注模型（本轮收尾时将登记审批卡并推送会话渠道+通知中心；模型若继续则不登记）")
                else:
                    logging.getLogger("app").info(f"[PathScope] '{tool_name}' 路径参数错误，错误原文已回注模型（非审批、无批复等待）")
                return _ps.block
            if _ps.grants:
                path_scope.set_grants(_ps.grants)
    except Exception as _pse:
        logging.getLogger("app").warning("[PathScope] 路径门异常（放行）: %r", _pse)

    # ==================== 4. 常规工具处理逻辑 (原有代码) ====================

    tool_name, handled = await _dispatch_external_tool(tool_name, tool_params, settings)
    if handled is not None:
        return handled
                
    # ==================== 5. 任务中心工具特殊处理 ====================
    if tool_name in ["create_subtask", "query_task_progress", "cancel_subtask","finish_task"]:
        return await _dispatch_task_center_tool(tool_name, tool_params, settings)

    if tool_name not in _TOOL_HOOKS:
        return await _dispatch_unknown_tool(tool_name, tool_params,
                                            set(_TOOL_HOOKS), _srv().node_ext_mcp_tools,
                                            call_node_extension_tool, settings)
        
    tool_call = _TOOL_HOOKS[tool_name]
    params = dict(tool_params or {})
    # S212：模型串味多传未声明参数（日志实证 2026-11-12 19:24：CDP 的 script_code
    # 灌进 read_file_range）时静默丢弃重试，缺参返回结构化可自纠错误，
    # 不再把裸 Python TypeError 甩给模型。审批/路径门在环外只过一次。
    for _attempt in range(4):
        try:
            return await _invoke_tool_hook(tool_name, tool_call, params)
        except TypeError as e:
            _msg = str(e)
            m = _UNEXPECTED_KW_RE.search(_msg)
            if m and m.group(1) in params and _attempt < 3:
                params.pop(m.group(1))
                logger.warning(f"[dispatch] {tool_name} 忽略未声明多余参数 '{m.group(1)}'（模型多传）后重试")
                continue
            if "required" in _msg and "argument" in _msg:
                logger.error(f"Error calling tool {tool_name}: {e}")
                return (f"[Error] Invalid arguments for {tool_name}: {e}. "
                        "Supply all required arguments per the tool schema and retry.")
            logger.error(f"Error calling tool {tool_name}: {e}")
            return f"Error calling tool {tool_name}: {e}{net_error_hint(e)}"
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return f"Error calling tool {tool_name}: {e}{net_error_hint(e)}"
