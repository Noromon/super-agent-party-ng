# -*- coding: utf-8 -*-
"""S304：流式响应装配层（stream_generator 轮次编排 + generate_stream_response
SSE 响应装配）——自 server.py 逐字搬移。

纯移动批；文档化改写仅 _srv() 懒访问：_TTFB_T0/current_request_messages
（server 模块全局 ContextVar，须与端点层同一事实源）、_assemble_toolkit/
_inject_tool_discipline/process_extra_params/tools_change_messages/
cli_permission_mode_for（server 侧装配与参数解析）。轮次引擎与准备域函数
直接复用 py/stream_engine.py 与 py/stream_prep.py（S302 同族）。
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import time
import uuid
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse, StreamingResponse

if TYPE_CHECKING:  # S304：注解引用 server 侧模型，仅静态检查期导入（group_memory 同法）
    from server import ChatRequest

from py import interject as _interject, llm_gate, tool_cap as _tool_cap
from py.diary_chat_integration import append_to_chat_buffer, update_buffer_identity
from py.diary_system import DEFAULT_BOOK_ID as DIARY_DEFAULT_BOOK, get_recent_diary_entries
from py.routers.island import notify_island_reply_done
from py.llm_recovery import retry_suffix
from py.model_params import effective_main_params, effective_role_params
from py.msg_utils import _extract_text_content, content_append, accumulate_usage, usage_control_frame  # S309b
from py.task_anchor import anchor_stream_in  # S307：任务锚点（df2f8248 续跑头部残缺修复）
from py import agent_loop_guard as _loop_guard  # S309：工具重复调用熔断
from py.prompt_builders import _inject_screen_context
from py.srv_ref import srv as _srv
from py.stream_engine import (_append_loopcap_hint, _drs_round_cap,
                              _maybe_inject_browser_vision, _stream_drs_loop_round,
                              _stream_drs_round, _stream_final_guard,
                              _stream_finalize_jobs,
                              _stream_first_round_with_recovery, _stream_reasoner_update,
                              _stream_regrab, _stream_second_round,
                              _stream_tool_round, _stream_usage_event)
from py.stream_prep import (_boundary_l1_recheck, _run_context_pipeline,
                            _stream_async_tools, _stream_character_context,
                            _stream_context_compress, _stream_deepsearch_pre,
                            _stream_desktop_capture, _stream_filter_tools,
                            _stream_first_round_leak_note, _stream_kb_before,
                            _stream_reasoner_prep, _stream_web_search_pre,
                            append_resume_nudge, get_drs_stage)
from py.stream_relay import (_current_stream_entry, _st_cancelled,
                             _stream_consumer_generator, _stream_producer_wrapper)
from py.token_guard import apply_eos_guard
from py.token_guard import neutralize as _neutralize
from py.tool_assembly import build_llm_tools
from py.tool_dispatch import pending_approval_at_tail
from py.vision_tools import images_add_in_messages, images_in_messages, message_without_images

logger = logging.getLogger("app")  # S301 同法：setup_logger 即返回 app logger，逐点等价


async def stream_generator(client, reasoner_client, request, settings, fastapi_base_url,
                     enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                     user_prompt, DRS_STAGE, tools, images,
                     chat_vendor, reasoner_vendor, model, extra_params,
                      open_tag, close_tag, source_prompt, m0, memoryId, cur_memory,
                      stream_entry=None):
    from py.know_base import kb_tool
    from py.task_tools import (
        create_subtask_tool,
        query_tasks_tool,
        cancel_subtask_tool,
        finish_task_tool,
    )
    from py.mode_change import mode_change_tool
    # ---------- 统一 SSE 封装 ----------
    def make_sse(tool_data: dict) -> str:
        chunk = {
            "choices": [{
                "delta": {
                    "tool_content": tool_data, # 这里直接传字典
                }
            }]
        }
        return f"data: {json.dumps(chunk)}\n\n"
    try:
        llm_gate.enter()
        _st = {}
        # S131: 显式注入流 entry，取消围栏不再依赖 ContextVar 传播
        _st["_entry"] = stream_entry or _current_stream_entry.get()
        if _st["_entry"] is None and settings.get('enableStreamResume', True):
            logging.getLogger("app").warning("[Cancel-Miss] stream_generator 无法获取流 entry，取消围栏将失效")
        usage_info = _usage_acc = _hold_abort = None  # S309b：_usage_acc 跨轮累计（RA-11 每轮擦 usage_info，acc 只进不出）；S317：_hold_abort=审批/ask 挂起收尾
        _ctx_peak = 0
        extra = {}
        reasoner_extra = {}
        # S206：每模型推理参数（卡片覆盖 > 角色默认；请求级仍由 request.* 优先）
        _eff_main = effective_main_params(settings)
        _eff_reasoner = effective_role_params(settings, settings.get('reasoner') or {})
        if chat_vendor == 'OpenAI':
            extra['max_completion_tokens'] = request.max_tokens or _eff_main.get('max_tokens')
        else:
            extra['max_tokens'] = request.max_tokens or _eff_main.get('max_tokens')
        if settings.get('enableOmniTTS',False) and not request.is_sub_agent:
            extra['modalities'] = ["text", "audio"]
            extra['audio'] ={"voice": settings.get('omniVoice',"Cherry"), "format": "wav"}
        if reasoner_vendor == 'OpenAI':
            reasoner_extra['max_completion_tokens'] = _eff_reasoner.get('max_tokens') or settings['reasoner']['max_tokens']
        else:
            reasoner_extra['max_tokens'] = _eff_reasoner.get('max_tokens') or settings['reasoner']['max_tokens']
        if request.reasoning_effort or _eff_main.get('reasoning_effort'):
            extra['reasoning_effort'] = request.reasoning_effort or _eff_main.get('reasoning_effort')
        if _eff_reasoner.get('reasoning_effort') is not None:
            reasoner_extra['reasoning_effort'] = _eff_reasoner.get('reasoning_effort')
        # S160 L0a：本地推理引擎软压制（eosGuard.enabled 且 base_url 为回环时生效）
        apply_eos_guard(reasoner_extra, settings, str(getattr(reasoner_client, "base_url", "") or ""))
        # 处理传入的异步工具ID查询
        async for _c in _stream_async_tools(request, async_tools_id):
            yield _c
        kb_list = []
        if settings["knowledgeBases"]:
            for kb in settings["knowledgeBases"]:
                if kb["enabled"] and kb["processingStatus"] == "completed":
                    kb_list.append({"kb_id":kb["id"],"name": kb["name"],"introduction":kb["introduction"]})
        async for _c in _stream_kb_before(request, settings, user_prompt, kb_list):
            yield _c
        if settings["KBSettings"]["when"] == "after_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                kb_list_message = f"\n\n可调用的知识库列表：{json.dumps(kb_list, ensure_ascii=False)}"
                content_append(request.messages, 'system', kb_list_message)
        else:
            kb_list = []
        async for _c in _stream_web_search_pre(request, settings, user_prompt, tools, enable_web_search):
            yield _c
        if kb_list:
            tools.append(kb_tool)

        # ==================== 获取权限模式 ====================
        cli_settings = settings.get("CLISettings", {})
        engine = cli_settings.get("engine", "")
                
        # 根据环境类型获取权限模式
        if engine == "local":
            env_settings = settings.get("localEnvSettings", {})
        elif engine == "ds":
            env_settings = settings.get("dsSettings", {})
        elif engine == "wsl":
            env_settings = settings.get("wslSettings", {})
        else:
            env_settings = settings.get("acpSettings", {})

        permission_mode = _srv().cli_permission_mode_for(settings)
        if permission_mode == "cowork" and settings['CLISettings']['enabled'] and not request.is_sub_agent:
            tools = []
            tools.append(create_subtask_tool)
            tools.append(query_tasks_tool)
            tools.append(cancel_subtask_tool)
            if  settings['CLISettings']['mode_change']:
                tools.append(mode_change_tool)

        if request.is_sub_agent:
            tools.append(finish_task_tool)
        # 如果是子智能体调用，或者指定了工具过滤规则
        tools = _stream_filter_tools(request, tools)
            

        logging.getLogger("app").info(tools)

        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            async for _c in _stream_deepsearch_pre(_st, client, model, extra_params, request):
                yield _c
            user_prompt = _st["user_prompt"]
        # 如果启用推理模型
        if settings['reasoner']['enabled'] or enable_thinking:
            async for _c in _stream_reasoner_prep(_st, request, reasoner_client, settings, images, reasoner_extra, open_tag, close_tag, tools, DRS_STAGE, user_prompt, enable_deep_research):
                yield _c
            vendor = _st["vendor"]
        # 状态跟踪变量
        in_reasoning = False
        reasoning_buffer = []
        content_buffer = []
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            content_append(request.messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
            drs_msg = get_drs_stage(DRS_STAGE)
            if drs_msg:
                content_append(request.messages, 'user',  f"\n\n{drs_msg}\n\n")
        # ===== 上下文管理管线：L1 修剪 -> L2 自动摘要（agent 模式），结果下发前端落账 =====
        _compact_event_payload = await _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools)
        if _compact_event_payload:
            yield f"data: {json.dumps(_compact_event_payload, ensure_ascii=False)}\n\n"
        msg = await images_add_in_messages(request.messages, images,settings)
        if request.top_p != 1 or _eff_main.get('top_p') != 1:
            extra['top_p'] = request.top_p or _eff_main.get('top_p')

        if _eff_main.get('temperature') != 1:
            extra['temperature'] = _eff_main.get('temperature')

        if tools:
            extra['tools'] = tools

        if _st_cancelled(_st):
            logging.getLogger("app").info("[Cancel] 流已被用户取消，发起 LLM 调用前终止")
            yield "data: [DONE]\n\n"
            return

        # S207：瞬断恢复→_stream_first_round_with_recovery（同 messages 重发同
        # 一轮推理；重试边界不含工具执行，重发零环境副作用）
        _st["_lr_keep_chars"] = 0
        tool_calls = []
        search_not_done = False
        search_task = ""
        async for _c in _stream_first_round_with_recovery(_st, client, model, msg, extra, extra_params, settings, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, in_reasoning, content_buffer, reasoning_buffer):
            yield _c
        usage_info = _st["usage_info"]
        _usage_acc = accumulate_usage(_usage_acc, usage_info)
        _ctx_peak = _st["_ctx_peak"]
        is_tool_call = _st["is_tool_call"]
        full_content = _st["full_content"]
        in_reasoning = _st["in_reasoning"]
        content_buffer = _st["content_buffer"]
        reasoning_buffer = _st["reasoning_buffer"]
        _chunk_count = _st["_chunk_count"]
        _st["fc"] = full_content
        _st["_lr_keep_chars"] = len(full_content)  # S207：已落账正文基线
        if _st.pop("w1_cancel", False):
            yield "data: [DONE]\n\n"
            return
        async for _c in _stream_final_guard(_st, content_buffer, reasoning_buffer, settings):
            yield _c
        full_content = _st["fc"]
        if not tool_calls:
            # 将响应添加到消息列表
            content_append(request.messages, 'assistant', full_content)
        # 工具和深度搜索
        if tool_calls:
            logging.getLogger("app").debug(f"tool_calls: {tool_calls}")
            pass
        elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            async for _c in _stream_drs_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
                yield _c
            DRS_STAGE = _st["drs"]
            search_not_done = _st["snot"]
            search_task = _st["stask"]

        # S213：首轮正文泄漏（还没进过工具循环）旧版完全没有 TCG——通知、自纠、
        # 闸门三缺，静默终结与 20:48 事故同族。补通知+自纠注记，并借一轮重入
        # 交 second_round 走同一套自纠/闸门（计入同一预算，上限不变）。
        _tcg_reentry = False
        if not tool_calls and full_content and not _st_cancelled(_st):
            _tcg_not = _stream_first_round_leak_note(_st, request, tools, full_content)
            if _tcg_not:
                yield _tcg_not
                _tcg_reentry = True
        reasoner_messages = copy.deepcopy(request.messages)
        _tool_loop_count = 0
        force_no_tools = False
        results = None  # S213：重入轮/纯 DRS 轮不进 tool 分支，先置空（原为潜在未定义引用）
        while tool_calls or search_not_done or _tcg_reentry:
            _tcg_reentry = False
            _tool_loop_count += 1
            _max_tool_iterations = _tool_cap.effective_limit()  # S233：轮边界动态上限（调值/破限即时生效）
            if not _drs_round_cap(_tool_loop_count, _max_tool_iterations, search_not_done, tool_calls, "流式"):
                search_not_done, tool_calls = False, []
                break
            if tool_calls and _tool_loop_count > _max_tool_iterations:
                _append_loopcap_hint(request, "流式")
                tool_calls = []
                force_no_tools = True
            if tool_calls:
                async for _c in _stream_tool_round(_st, request, settings, user_prompt, full_content, tool_calls, reasoner_messages):
                    yield _c
                # RA-11：旧内联压缩段首「逐轮擦除 usage_info」随 helper 化失活，回植旧位（tool round 内顺序执行处）
                usage_info = None
                if _st.pop("w1_cancel", False):
                    return
                if _st.pop("w1_abort", False):
                    _hold_abort = True; break  # S317：挂起收尾=本轮未完（等用户批准/回答），不得触发记忆提取
                for _ij_c in _interject.drain_inject(_st, request):  # S188：轮边界注入插话+ack
                    yield _ij_c
                _boundary_l1_recheck(request, settings, tools)  # S192：轮边界预算复查（仅 L1）
                if (request.is_app_bot and request.platform and request.peer_id
                        and _tool_loop_count % 5 == 0):  # S191：IM 轮内检查点（回合闭合由客户端清除）
                    try:
                        from py.get_setting import save_bot_conv
                        await save_bot_conv(
                            f"bot:{request.platform}:{request.peer_id}#inflight",
                            [m for m in request.messages if m.get("role") != "system"])
                    except Exception as _ik_e:
                        logging.getLogger("app").warning("[Inflight] 检查点写入失败: %r", _ik_e)
                results = _st.get("results")
                if _loop_guard.observe_round(_st, request, tool_calls):  # S309：重复熔断（警告已并入 tool 结果尾部）
                    force_no_tools = True
            # 如果启用推理模型
            if settings['reasoner']['enabled'] or enable_thinking:
                async for _c in _stream_reasoner_update(_st, request, reasoner_client, settings, reasoner_messages, images, reasoner_extra, open_tag, close_tag, tools, vendor):
                    yield _c
                vendor = _st["vendor"]
                    
            vision_control_enabled = settings.get('visionControlSettings', {}).get('enabled', False)
            if vision_control_enabled and (results =='[Getting screenshot]' or settings.get('visionControlSettings', {}).get('desktopVision', False)):
                images = await _stream_regrab(request, settings, results, images, fastapi_base_url)
            images = await _maybe_inject_browser_vision(request, settings, images, fastapi_base_url)  # S228：浏览器截图直注主模型
            msg = await images_add_in_messages(request.messages, images, settings)
            if request.top_p != 1 or _eff_main.get('top_p') != 1:
                extra['top_p'] = request.top_p or _eff_main.get('top_p')

            if _eff_main.get('temperature') != 1:
                extra['temperature'] = _eff_main.get('temperature')

            async for _c in _stream_second_round(_st, client, model, msg, extra, extra_params, settings, request, tools, force_no_tools, usage_info, _ctx_peak, in_reasoning, content_buffer, reasoning_buffer, open_tag, close_tag):
                yield _c
            if _st.pop("tc_round_done", False):
                return  # cancel 路径：helper 已发 DONE
            tool_calls = _st["tc_round"]
            usage_info = _st["usage_info"]
            _usage_acc = accumulate_usage(_usage_acc, usage_info)
            _ctx_peak = _st["_ctx_peak"]
            full_content = _st["fc"]
            in_reasoning = _st["in_reasoning"]
            content_buffer = _st["content_buffer"]
            reasoning_buffer = _st["reasoning_buffer"]
            # 工具和深度搜索
            if tool_calls:
                pass
            elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
                async for _c in _stream_drs_loop_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
                    yield _c
                DRS_STAGE = _st["drs"]
                search_not_done = _st["snot"]
                search_task = _st["stask"]
        async for _c in _stream_usage_event(request, settings, usage_info, _ctx_peak, tools):
            yield _c
        logger.info(f"all msg: {request.messages}")
        if _usage_frame := usage_control_frame(_usage_acc):  # S309b：计费累计帧（前端仪表盘数据源）
            yield _usage_frame
        yield "data: [DONE]\n\n"
        # S139(R6)：灵动岛热力图+1 并通知（上游 5842-5850 语义：非 sub_agent、异常吞）
        await notify_island_reply_done(request.is_sub_agent)
        await _stream_finalize_jobs(request, settings, full_content, user_prompt, m0, memoryId, cur_memory, _hold_abort)  # S317：挂起轮跳过 mem0

        return
    except Exception as e:
        logger.error(f"[StreamError] {type(e).__name__}: {e} | msgs={len(request.messages)}", exc_info=True)
        # 捕获异常并返回结构化错误信息
        error_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {
                        "title": "❎ Error", # 统一标题
                        "content": str(e) + retry_suffix(e),   # 错误详情（S207：自动重试标注）
                        "type": "error"      # 标记类型，方便前端切换样式
                    }
                }
            }]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"  # 确保最终结束
        return
    finally:
        llm_gate.leave()


async def generate_stream_response(client, reasoner_client, request: ChatRequest, settings: dict, 
                                   fastapi_base_url, enable_thinking, enable_deep_research, 
                                   enable_web_search, async_tools_id):
    _tt0 = _srv()._TTFB_T0.get()
    if _tt0:
        logging.getLogger("app").info(f"[TTFBbrk] pre-stream +{int((time.monotonic() - _tt0) * 1000)}ms")
    try:
        # (global decl cleared: migrated to py/app_state.py)
        
        # 设置对话上下文，供 secondhand_review_image 等工具使用
        _srv().current_request_messages.set(request.messages)
        
        DRS_STAGE = 1
        if len(request.messages) > 2:
            DRS_STAGE = 2
            
        vision_cfg = settings.get('vision', {})
        vision_control_enabled = settings.get('visionControlSettings', {}).get('enabled', False)
        user_prompt = request.messages[-1].get('content') or ""
        
        # 1. 只要开启了计算机控制 或者 符合桌面视觉唤醒词条件，就进行初始截图
        await _stream_desktop_capture(request, settings, vision_cfg, vision_control_enabled, user_prompt, fastapi_base_url)

        # =========================================================================
        # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
        # =========================================================================
        _stream_context_compress(request, settings)
        # =========================================================================
        images = await images_in_messages(request.messages,fastapi_base_url)
        request.messages = await message_without_images(request.messages)
        from py.load_files import get_files_content,file_tool,image_tool,analyze_image_tool,review_image_tool,analyze_images_tool,view_images_tool,view_images_tool
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
            duckduckgo_tool, 
            searxng_tool, 
            tavily_tool, 
            bing_tool,
            google_tool,
            brave_tool,
            exa_tool,
            serper_tool,
            bochaai_tool,
            youcom_tool,
            jina_crawler_tool, 
            simple_fetch_tool,
            Crawl4Ai_tool,
            firecrawl_tool,
            markdown_new_tool,
        )
        from py.know_base import kb_tool,query_knowledge_base,rerank_knowledge_base
        from py.agent_tool import get_agent_tool
        from py.a2a_tool import get_a2a_tool
        from py.llm_tool import get_llm_tool
        from py.pollinations import pollinations_image_tool,openai_image_tool,openai_chat_image_tool
        from py.code_interpreter import e2b_code_tool,local_run_code_tool
        from py.utility_tools import (
            time_tool, 
            weather_tool,
            location_tool,
            timer_weather_tool,
            wikipedia_summary_tool,
            wikipedia_section_tool,
            arxiv_tool 
        ) 
        from py.autoBehavior import auto_behavior_tool
        from py.cli_tool import get_tools_for_mode,get_local_tools_for_mode,get_tools_for_permission,get_local_tools_for_permission
        from py.cdp_tool import all_cdp_tools
        from py.random_topic import random_topics_tools
        from py.computer_use_tool import computer_use_tools,mouse_use_tools,keyboard_use_tools,desktopVision_use_tools

        from py.task_tools import (
            create_subtask_tool,
            query_tasks_tool,
            cancel_subtask_tool,
            finish_task_tool,
        )

        from py.mode_change import mode_change_tool
        from py.acpx_tools import acp_agent_tool

        m0 = None
        memoryId = None
        cur_memory = None
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != ""  and not request.is_sub_agent:
            memoryId = settings["memorySettings"]["selectedMemory"]
            cur_memory = None
            for memory in settings["memories"]:
                if memory["id"] == memoryId:
                    cur_memory = memory
                    break
            if cur_memory and cur_memory["providerId"]:
                logging.getLogger("app").info("长期记忆启用")
                m0 = llm_gate.get_mem0_instance(memoryId, cur_memory, settings)
                logging.getLogger("app").info("长期记忆配置加载完成")
        open_tag = "<think>"
        close_tag = "</think>"

        tools = await build_llm_tools(request, settings, _srv()._assemble_toolkit())
        _srv()._inject_tool_discipline(request, tools)  # S204: 纪律随有效声明集（stream/ns 两处）
        
        source_prompt = ""
        if request.fileLinks:
            logging.getLogger("app").debug(f"fileLinks: {request.fileLinks}")
            # 异步获取文件内容
            files_content = await get_files_content(request.fileLinks)
            fileLinks_message = f"\n\n相关文件内容：{files_content}"
            
            # 修复字符串拼接错误
            content_append(request.messages, 'system', fileLinks_message)
            source_prompt += fileLinks_message
        user_prompt = request.messages[-1].get('content') or ""
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != ""  and not request.is_sub_agent:
            await _stream_character_context(request, settings, user_prompt, cur_memory, memoryId, m0)
        # ========== 日记集成：将近期日记注入对话上下文 ==========
        diary_cfg = (settings.get("diarySettings", {}) or {}).get("chatIntegration", {}) or {}
        if diary_cfg.get("enabled", False) and not request.is_sub_agent:
            try:
                ms = (settings or {}).get("memorySettings", {}) or {}
                diary_book_id = DIARY_DEFAULT_BOOK
                if ms.get("is_memory") and ms.get("selectedMemory"):
                    diary_book_id = ms.get("selectedMemory")
                max_entries = max(1, int(diary_cfg.get("maxEntries", 5) or 5))
                recent = await get_recent_diary_entries(diary_book_id, max_entries)
                if recent:
                    diary_lines = []
                    for e in recent:
                        diary_title = e.get("title", "") or e.get("content", "")[:24]
                        diary_lines.append(f"- [{e.get('time', '')[:16]}] ({e.get('type', '')}) {diary_title}: {e.get('content', '')[:200]}")
                    diary_text = _neutralize("\n".join(diary_lines), store="diary-recall")
                    content_append(request.messages, 'system',
                        "\n\n[角色日记 - 近期回忆]\n以下是该角色最近的日记记录，可供你参考其心境和经历：\n" + diary_text + "\n")
                    logging.getLogger("app").info(f"📔 [日记集成] 已注入 {len(recent)} 条日记到对话上下文")
            except Exception as e:
                logging.getLogger("app").info(f"[日记集成] 提取日记失败: {e}")
        # ========== S217 旁观模式：意图命中 → 屏幕观察上下文注入 ==========
        await _inject_screen_context(request, settings, _extract_text_content(user_prompt))
        request = await _srv().tools_change_messages(request, settings)
        # ========== 对话缓冲：记录用户消息用于闲时自动总结 ==========
        try:
            diary_settings = (settings.get("diarySettings", {}) or {})
            if diary_settings.get("enabled", False) and diary_settings.get("chatSummary", {}).get("enabled", True) and not request.is_quarantined \
                    and getattr(request, "platform", "") != "diary":  # S231：同流式侧，diary 自调用不入缓冲
                ms = (settings or {}).get("memorySettings", {}) or {}
                buffer_key = ms.get("selectedMemory") or DIARY_DEFAULT_BOOK
                update_buffer_identity(buffer_key, book_id=buffer_key,
                                       character_name=(ms.get("userName") or ""))
                last_msg = request.messages[-1] if request.messages else None
                if last_msg and last_msg.get("role") == "user" and last_msg.get("name") != "system_note":  # S166：注记不入 DiaryChat 缓冲
                    append_to_chat_buffer(buffer_key, "user", _neutralize(_extract_text_content(last_msg.get("content", "")), store="diary-buffer"))
        except Exception as e:
            logging.getLogger("app").info(f"[DiaryBuffer] 记录对话缓冲失败: {e}")
        # 如果系统消息为空字符串或者仅包含空白符，则将系统消息改成"you are a helpful assistant."
        if request.messages[0]['role'] == 'system' and not request.messages[0]['content'].strip():
            request.messages[0]['content'] = "you are a helpful assistant."
        await anchor_stream_in(request)  # S307: 任务锚点——缺真实 user 消息时回注，防续跑头部残缺致任务失联
        if pending_approval_at_tail(request.messages) is None: append_resume_nudge(request.messages)  # S172: 待批复审批尾部不附继续催办
        chat_vendor = 'OpenAI'
        reasoner_vendor = 'OpenAI'
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['selectedProvider']:
                chat_vendor = modelProvider['vendor']
                break
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['reasoner']['selectedProvider']:
                reasoner_vendor = modelProvider['vendor']
                break
        if chat_vendor == 'Dify':
            try:
                if len(request.messages) >= 3:
                    if request.messages[2]['role'] == 'user':
                        if request.messages[1]['role'] == 'assistant':
                            request.messages[2]['content'] = "你上一次的发言：\n" +request.messages[0]['content'] + "\n你上一次的发言结束\n\n用户：" + request.messages[2]['content']
                        if request.messages[0]['role'] == 'system':
                            request.messages[2]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n" + request.messages[2]['content']
                elif len(request.messages) >= 2:
                    if request.messages[1]['role'] == 'user':
                        if request.messages[0]['role'] == 'system':
                            request.messages[1]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n用户：" + request.messages[1]['content']
            except Exception as e:
                logging.getLogger("app").warning(f"Dify error: {e}")
        model = settings['model']
        extra_params = effective_main_params(settings).get('extra_params') or []  # S206：卡片级覆盖（整体替换角色级）
        # 移除extra_params这个list中"name"不包含非空白符的键值对
        if extra_params:
            for extra_param in extra_params:
                if not extra_param['name'].strip():
                    extra_params.remove(extra_param)
            # 列表转换为字典
            extra_params = _srv().process_extra_params(extra_params)
        else:
            extra_params = {}
        
        # 检查是否启用断点续传
        enable_stream_resume = settings.get('enableStreamResume', True)
        
        if enable_stream_resume:
            # 生产者/消费者解耦模式：客户端断开后生成器继续运行
            stream_id = str(uuid.uuid4())
            _srv()._active_streams[stream_id] = {
                "id": stream_id,  # S151：entry 自带 id（通知中心 pending_key 用）
                "buffer": [],
                "done": False,
                "error": None,
                "cancelled": False,
                "created_at": time.time(),
                "consumer_count": 1,
                "task": None,
            }
            _interject.register_stream(request, stream_id, _srv()._active_streams[stream_id])  # S188
            # 启动生产者后台任务
            # 关键：必须将 task 引用保存到字典中，否则会被 Python GC 回收，
            # 导致 stream_generator 中的 httpx 流式请求中途被中断！
            _srv()._active_streams[stream_id]["task"] = asyncio.create_task(
                _stream_producer_wrapper(
                    stream_id,
                    stream_generator(
                        client, reasoner_client, request, settings, fastapi_base_url,
                        enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                        user_prompt, DRS_STAGE, tools, images,
                        chat_vendor, reasoner_vendor, model, extra_params,
                        open_tag, close_tag, source_prompt, m0, memoryId, cur_memory,
                        stream_entry=_srv()._active_streams[stream_id])
                )
            )

            
            async def _first_frame_consumer():
                """消费者：先发 stream_id 元数据帧，再转发实际内容"""
                meta_chunk = {"choices": [{"delta": {"stream_id": stream_id}}]}
                yield f"data: {json.dumps(meta_chunk)}\n\n"
                async for chunk in _stream_consumer_generator(stream_id, 0):
                    yield chunk
            
            return StreamingResponse(
                _first_frame_consumer(),
                media_type="text/event-stream",
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Stream-Id": stream_id,
                }
            )
        else:
            return StreamingResponse(
                stream_generator(
                    client, reasoner_client, request, settings, fastapi_base_url,
                enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                user_prompt, DRS_STAGE, tools, images,
                chat_vendor, reasoner_vendor, model, extra_params,
                open_tag, close_tag, source_prompt, m0, memoryId, cur_memory),
                media_type="text/event-stream",
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
    except Exception as e:
        logger.error(f"Error occurred: {e}")

        # 如果e.status_code存在，则使用它作为HTTP状态码，否则使用500
        return JSONResponse(
            status_code=getattr(e, "status_code", 500),
            content={"error": str(e)},
        )
