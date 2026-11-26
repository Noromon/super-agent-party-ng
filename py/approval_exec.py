# -*- coding: utf-8 -*-
"""S304：IM 批复执行通道（execute_approved_tool）——自 server.py 逐字搬移。

纯移动批；文档化改写仅 _srv() 懒访问：_active_streams（server 全局流表）、
_approval_exec_dedup（S185 幂等状态机及其锁/集合留 server 事实源）。
本模块内本地 _TOOL_HOOKS 副本表与 py/tool_hooks.py 注册表的一致性由
tests/test_tool_registry_parity_s255.py 双表钉锁守护。
"""
import logging

from py.agent import add_tool_to_project_config
from py.diary_query_tool import handle_list_diary_books, handle_query_diary
from py.get_setting import load_settings, save_settings
from py.srv_ref import srv as _srv
from py.tool_registry import GLOBAL_APPROVAL_TOOLS
from py.vision_tools import (analyze_image, analyze_images, get_image_content,
                             review_image, view_images)


async def record_always_allow(tool_name, settings, cwd, save_fn):
    """S329: "总是允许"落库路由——插件域工具(GLOBAL_APPROVAL_TOOLS)写全局层
    settings.globalAllowedTools，与工作区(cwd)无关；系统高危类照旧写 cwd
    项目配置(.party/config.json)。返回 (ok, err_msg)。"""
    if tool_name in GLOBAL_APPROVAL_TOOLS:
        gl = list(settings.get("globalAllowedTools") or [])
        if tool_name not in gl:
            gl.append(tool_name)
            settings["globalAllowedTools"] = gl
            await save_fn(settings)
        return True, None
    if not cwd:
        return False, "[System Error] No working directory found to save config."
    add_tool_to_project_config(cwd, tool_name)
    return True, None


async def execute_approved_tool(tool_name, tool_params, approval_type="once", stream_id=None):
    """S150: 审批通过后执行工具（前端审批卡与 IM /y 批复共用）。返回 {"result": ...}。

    原 execute_tool_manually 函数体原样搬入；端点变薄壳（M-3 棘轮：巨函数只许缩）。
    """
    # 安全围栏：所属生成流已被用户取消时，拒绝执行审批工具
    _appr_stream_id = stream_id
    if _appr_stream_id:
        _appr_entry = _srv()._active_streams.get(_appr_stream_id)
        if _appr_entry and _appr_entry.get("cancelled"):
            logging.getLogger("app").info(f"[Cancel] 拒绝执行工具 {tool_name}：其生成流 {_appr_stream_id} 已被取消")
            return {"result": "[Cancelled] 该工具所属的生成已被用户取消，拒绝执行"}
    # S185：审批执行一次性消费（helper 内实现幂等吞掉重复批复）
    _dedup_hit = await _srv()._approval_exec_dedup(_appr_stream_id, tool_name, tool_params, approval_type)
    if _dedup_hit is not None: return _dedup_hit
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    # S153: 路径门批复执行——外部/本地直读类注入本次调用的目录授权（grants），
    # 使被批工具内部的 resolve_strict_path 按批复范围放行
    from py import path_scope
    _ps_grants = path_scope.approved_call_grants(tool_name, tool_params or {}, cwd)
    if _ps_grants:
        path_scope.set_grants(_ps_grants)
    # ==================== 核心逻辑：处理 "Always" ====================
    if approval_type == "always":
        # S153: 路径门类"不再询问"→ allowed_dirs 目录白名单（与 allowed_tools 隔离，
        # 工具白名单永远绕不过路径门）
        if _ps_grants:
            try:
                from py.agent import add_dirs_to_project_config
                add_dirs_to_project_config(cwd, _ps_grants)
                logging.getLogger("app").info(f"[PathScope] allowed_dirs += {_ps_grants} ({cwd})")
            except Exception as e:
                return {"result": f"[System Error] Failed to save dir permission: {str(e)}"}
        # "不再询问"落库：S329 路由——插件域→全局层(无需 cwd)；系统高危→cwd 项目配置
        try:
            _ok, _err = await record_always_allow(tool_name, settings, cwd, save_settings)
            if not _ok:
                return {"result": _err}
            logging.getLogger("app").info(
                f"[Permission] Always-allow recorded: {tool_name} "
                f"({'global' if tool_name in GLOBAL_APPROVAL_TOOLS else 'project:' + str(cwd)})")
        except Exception as e:
            return {"result": f"[System Error] Failed to save permission: {str(e)}"}

    # ==================== 1. 导入所有工具函数 ====================
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
    # WSL 沙箱引擎（S132/A13，complete 域 hooks 用 shell_tool_wsl）
    shell_tool_wsl,
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
        edit_file_patch_tool_local, delete_file_tool_local,  # 本地精确替换 / S315 删除入 trash
        glob_files_tool_local,     # 本地 glob 查找
        todo_write_tool_local, ask_user_question_tool,  # 本地任务管理 + S194 提问兜底
        local_net_tool,            # 本地网络工具
        read_skill_tool_local,
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
    _TOOL_HOOKS = {
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
        "edit_file_patch_tool_local": edit_file_patch_tool_local, "delete_file_tool_local": delete_file_tool_local,  # 本地精确替换 / S315 删除入 trash
        "glob_files_tool_local": glob_files_tool_local,         # 本地 glob 查找
        "todo_write_tool_local": todo_write_tool_local, "ask_user_question_tool": ask_user_question_tool,  # 本地任务管理 + S194 提问兜底
        "local_net_tool": local_net_tool,                       # 本地网络工具
        "read_skill_tool_local": read_skill_tool_local,         # 本地技能读取

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
    

    if tool_name not in _TOOL_HOOKS:
        # S330（17:21 事故）：本表是 S150 时代副本，S323 后新工具只进主注册表
        # (tool_hooks/server 单一事实源)——审批通过后执行报 "not found"，模型
        # 当轮只收到错误串，误判"没拉起"并连弹两次审批。副本 miss 回退主表。
        _main_hooks = getattr(_srv(), "_TOOL_HOOKS", None) or {}
        _fallback_func = _main_hooks.get(tool_name)
        if _fallback_func is None:
            return {"result": f"Tool {tool_name} not found in backend registry."}
        try:
            return {"result": str(await _fallback_func(**tool_params))}
        except Exception as e:
            return {"result": f"Error executing {tool_name}: {str(e)}"}

    tool_func = _TOOL_HOOKS[tool_name]
    
    try:
        if tool_name in ("shell_tool_local", "docker_sandbox", "shell_tool_wsl"):
            # 异步生成器：调用即返回 AsyncIterator，无需 await
            result = tool_func(**tool_params)
        elif tool_name == "acpx_agent":
            # 常规异步函数：必须 await 才能获得实际结果
            result = await tool_func(**tool_params)
        else:
            # 2. 执行工具
            result = await tool_func(**tool_params)
        
        # 3. 处理流式输出 (AsyncIterator)
        # 如果是流，我们需要将其消耗完合并成字符串返回给前端一次性显示
        # 因为手动执行通常不再支持流式打字机效果（或者前端处理会比较复杂）
        if hasattr(result, "__aiter__"):
            output_buffer = []
            async for chunk in result:
                output_buffer.append(chunk)
            return {"result": "".join(output_buffer)}
        
        return {"result": str(result)}
        
    except Exception as e:
        return {"result": f"Error executing {tool_name}: {str(e)}"}
