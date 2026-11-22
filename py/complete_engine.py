# -*- coding: utf-8 -*-
"""S303：非流式 complete 引擎（上下文压缩/角色上下文/网搜前置/
reasoner 预处理/DRS 步/非流式工具轮与 reasoner pass/绕圈记账/收尾）——
自 server.py 逐字搬移。

纯移动批；文档化改写=_srv() 懒访问（settings=运行期热重载事实源、
_role_param/_main_param=参数解析；原语义即 server 模块全局调用期读取，
逐点等价）。准备域 helper（get_role/parse_tool_arguments/_bound_tool_output
等）来自 py/stream_prep（S302a 同族）；_generate_complete_impl/_chat_endpoint_impl
属端点编排层留 server（与 stream 侧 stream_generator 同等待遇，S304 终评）。
"""
from __future__ import annotations

import asyncio
import copy
import datetime
import json
import logging
import random
import re
import uuid
from typing import TYPE_CHECKING, AsyncIterator

from py import llm_gate, tool_cap as _tool_cap
from fastapi.responses import JSONResponse

if TYPE_CHECKING:  # S304：impl 注解引用 server 侧模型，仅静态检查期导入（group_memory 同法）
    from server import ChatRequest

from py.context_builder import sanitize_tool_chains_logged
from py.llm_recovery import acreate, llm_retry_cfg, retry_suffix
from py.model_params import effective_main_params, effective_role_params
from py.msg_utils import content_append, content_prepend
from py.srv_ref import srv as _srv
from py.stream_engine import (_append_loopcap_hint, _drs_round_cap,
                              _maybe_inject_browser_vision)
from py.stream_prep import (_bound_tool_output, _cm_context_enabled,
                            _run_context_pipeline, append_resume_nudge,
                            ensure_thinking_fields, get_drs_stage,
                            get_drs_stage_system_message, get_role,
                            parse_tool_arguments, truncate_tool_result)
from py.stream_relay import _current_stream_entry
from py.token_guard import apply_eos_guard, neutralize as _neutralize, neutralize_deep
from py.tool_dispatch import _is_approval_result, pending_approval_at_tail
from py.tool_assembly import build_llm_tools
from py.tool_hooks import _im_approval_hangup, dispatch_tool
from py.tool_spiral import SpiralWatch
from py.tool_loop import (NONE_TEXT, TOOL_EXC_TMPL,
                          append_missing_results, arg_error_text)
from py.vision_tools import (_attach_screen_image_for_behavior,
                             images_add_in_messages, images_in_messages,
                             message_without_images)


def _apply_context_compression(request, DRS_STAGE):
    """L1 context window compression (complete channel). (M-3 split)"""
    if len(request.messages) > 2:
        DRS_STAGE = 2

        # =========================================================================
        # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
        # =========================================================================
        max_rounds = 0 if _cm_context_enabled(_srv().settings) else _srv().settings.get("max_rounds", 0)
        chat_messages = request.messages # 这里的 chat_messages 包含 system
        
        if max_rounds > 0:
            
            # 区分系统消息和对话消息
            sys_msgs = [m for m in chat_messages if get_role(m) == "system"]
            dialog_msgs = [m for m in chat_messages if get_role(m) != "system"]
            
            # 设定压缩阈值：当非系统消息超过 max_rounds * 2 + 1 时开始压缩
            if len(dialog_msgs) > (max_rounds * 2 + 1):
                keep_indices = set()
                
                # 1. 总是保留第一条消息 (Anchor User Prompt)
                if len(dialog_msgs) > 0: keep_indices.add(0)
                
                # 2. 保留所有 User 消息 (User 优先策略)
                for i, m in enumerate(dialog_msgs):
                    if get_role(m) == "user": keep_indices.add(i)
                
                # 3. 保留每个 Turn 的最后一个 Assistant 消息 (最终答案)
                for i in range(len(dialog_msgs)):
                    if get_role(dialog_msgs[i]) == "assistant":
                        is_last = True
                        for j in range(i + 1, len(dialog_msgs)):
                            if get_role(dialog_msgs[j]) == "assistant":
                                is_last = False; break
                            if get_role(dialog_msgs[j]) == "user": break
                        if is_last: keep_indices.add(i)
                
                # 4. 保留最近的活跃窗口 (最近 N 条消息，确保当前工具链不被切断)
                tail_start = max(0, len(dialog_msgs) - (max_rounds * 2))
                for i in range(tail_start, len(dialog_msgs)):
                    keep_indices.add(i)
                
                # 构造初步压缩后的列表
                compressed_dialog = [dialog_msgs[i] for i in sorted(list(keep_indices))]
                chat_messages = sys_msgs + compressed_dialog
                logging.getLogger("app").info(f"[Context] Compressed to {len(chat_messages)} msgs.")

        request.messages = sanitize_tool_chains_logged(chat_messages)
        request.messages = ensure_thinking_fields(request.messages)
    return DRS_STAGE


def _diary_recall_sample(payload, memory_limit):
    """S83：日记（自主触发，query 变化有限）长期记忆召回抽样。

    m0.search 为确定性语义 top-k，固定/近固定提示词永远召回同一批条目；
    这里从扩大召回的候选集中随机抽 memory_limit 条制造多样性。
    仅日记平台调用；候选不足或结构异常时原样返回。
    """
    try:
        results = payload.get("results")
        if not isinstance(results, list) or memory_limit <= 0 or len(results) <= memory_limit:
            return payload
        return {**payload, "results": random.sample(results, memory_limit)}
    except Exception:
        return payload


async def _complete_character_context(request, settings, user_prompt, cur_memory, memoryId, m0):
    """Character-book lore + persona fields + mem0 relevant-memory recall."""
    if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
        if settings["memorySettings"]["userName"] and settings["memorySettings"]["userName"] != "user" and getattr(request, "platform", "") != "diary":  # S165：diary 独处无「当前交流者」，名字行是认知扭曲原料
            logging.getLogger("app").info("添加用户名：\n\n" + settings["memorySettings"]["userName"] + "\n\n用户名结束\n\n")
            content_append(request.messages, 'system', "当前与你交流的人的名字为：\n\n" + settings["memorySettings"]["userName"] + "\n\n")
        lore_content = ""
        assistant_reply = ""
        # 找出request.messages中上次的assistant回复
        for i in range(len(request.messages)-1, -1, -1):
            if request.messages[i]['role'] == 'assistant':
                assistant_reply = request.messages[i]['content']
                break
        if cur_memory["characterBook"]:
            for lore in cur_memory["characterBook"]:
                # lore['keysRaw'] 按照换行符分割，并去除空字符串
                lore_keys = lore["keysRaw"].split("\n")
                lore_keys = [key for key in lore_keys if key != ""]
                logging.getLogger("app").info(lore_keys)
                # 如果lore_keys不为空，并且lore_keys的任意一个元素在user_prompt或者assistant_reply中，则添加lore['content']到lore_content中
                if lore_keys != [] and any(key in user_prompt or key in assistant_reply for key in lore_keys):
                    lore_content += lore['content'] + "\n\n"
        if lore_content:
            if settings["memorySettings"]["userName"]:
                # 替换lore_content中的{{user}}为settings["memorySettings"]["userName"]
                lore_content = lore_content.replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换lore_content中的{{char}}为cur_memory["name"]
            lore_content = lore_content.replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
            content_append(request.messages, 'system', "世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
        if cur_memory["description"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["description"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["description"] = cur_memory["description"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["description"]中的{{char}}为cur_memory["name"]
            cur_memory["description"] = cur_memory["description"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
            content_append(request.messages, 'system', "角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
        if cur_memory["personality"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["personality"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["personality"] = cur_memory["personality"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["personality"]中的{{char}}为cur_memory["name"]
            cur_memory["personality"] = cur_memory["personality"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n")
            content_append(request.messages, 'system', "性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n") 
        if cur_memory['mesExample']:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["mesExample"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["mesExample"]中的{{char}}为cur_memory["name"]
            cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
            content_append(request.messages, 'system', "对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
        if cur_memory["systemPrompt"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["systemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
            cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加系统提示：\n\n" + cur_memory["systemPrompt"] + "\n\n系统提示结束\n\n")
            content_append(request.messages, 'system', "系统提示：\n\n" + cur_memory["systemPrompt"] + "\n\n系统提示结束\n\n")
        if settings["memorySettings"]["genericSystemPrompt"]:
            if settings["memorySettings"]["userName"]:
                # 替换settings["memorySettings"]["genericSystemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
                settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
            settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加系统提示：\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n系统提示结束\n\n")
            content_append(request.messages, 'system', "系统提示：\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n系统提示结束\n\n")
                    
        if m0:
            memoryLimit = settings["memorySettings"]["memoryLimit"]
            # S83：日记平台扩大召回×3（下限 6）后随机抽样，主对话行为不变
            is_diary = getattr(request, "platform", "") == "diary"
            search_limit = max(memoryLimit * 3, 6) if is_diary else memoryLimit
            try:
                # 【核心修改】：使用 asyncio.to_thread 将同步的 search 方法放入线程池运行
                # 这样主线程（Event Loop）会被释放，可以去处理 /minilm/embeddings 请求，从而避免死锁
                relevant_memories = await asyncio.to_thread(
                    m0.search, 
                    query=(getattr(request, "recall_query", None) or user_prompt),
                    user_id=memoryId, 
                    limit=search_limit
                )
                if is_diary:
                    relevant_memories = _diary_recall_sample(relevant_memories, memoryLimit)
                relevant_memories = json.dumps(neutralize_deep(relevant_memories, "recall"), ensure_ascii=False)
            except Exception as e:
                logging.getLogger("app").warning(f"m0.search error: {e}")
                relevant_memories = ""
            logging.getLogger("app").info("添加相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")
            content_append(request.messages, 'system', "之前的相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n") 


async def _complete_web_search_setup(request, settings, user_prompt, tools, enable_web_search):
    """before_thinking search execution + after_thinking tool announcements."""
    from py.web_search import (
        DDGsearch, searxng, Tavily_search, Bing_search, Google_search,
        Brave_search, Exa_search, Serper_search, bochaai_search, youcom_search,
        duckduckgo_tool, searxng_tool, tavily_tool, bing_tool, google_tool,
        brave_tool, exa_tool, serper_tool, bochaai_tool, youcom_tool, jina_crawler_tool,
        simple_fetch_tool, Crawl4Ai_tool, firecrawl_tool, markdown_new_tool,
        websearch_with_fallback, browser_search_tool,
    )
    if settings['webSearch']['enabled'] or enable_web_search:
        if settings['webSearch']['when'] == 'before_thinking' or settings['webSearch']['when'] == 'both':
            # S90：统一入口——配置引擎失败自动走内置浏览器兜底
            results = await websearch_with_fallback(
                settings['webSearch']['engine'], user_prompt)
            if results:
                content_append(request.messages, 'user',  f"\n\n联网搜索结果：{results}")
        if settings['webSearch']['when'] == 'after_thinking' or settings['webSearch']['when'] == 'both':
            if settings['webSearch']['engine'] == 'duckduckgo':
                tools.append(duckduckgo_tool)
            elif settings['webSearch']['engine'] == 'searxng':
                tools.append(searxng_tool)
            elif settings['webSearch']['engine'] == 'tavily':
                tools.append(tavily_tool)
            elif settings['webSearch']['engine'] == 'bing':
                tools.append(bing_tool)
            elif settings['webSearch']['engine'] == 'google':
                tools.append(google_tool)
            elif settings['webSearch']['engine'] == 'brave':
                tools.append(brave_tool)
            elif settings['webSearch']['engine'] == 'exa':
                tools.append(exa_tool)
            elif settings['webSearch']['engine'] == 'serper':
                tools.append(serper_tool)
            elif settings['webSearch']['engine'] == 'bochaai':
                tools.append(bochaai_tool)
            elif settings['webSearch']['engine'] == 'youcom':
                tools.append(youcom_tool)
            elif settings['webSearch']['engine'] == 'browser':
                tools.append(browser_search_tool)

            if settings['webSearch']['crawler'] == 'jina':
                tools.append(jina_crawler_tool)
            elif settings['webSearch']['crawler'] == 'crawl4ai':
                tools.append(Crawl4Ai_tool)
            elif settings['webSearch']['crawler'] == 'firecrawl':
                tools.append(firecrawl_tool)
            elif settings['webSearch']['crawler'] == 'simpleRequest':
                tools.append(simple_fetch_tool)
            elif settings['webSearch']['crawler'] == 'mdnew':
                tools.append(markdown_new_tool)


async def _complete_reasoner_prep(request, reasoner_client, settings, chat_vendor, reasoner_vendor, images, tools, extra, reasoner_extra, open_tag, close_tag, enable_deep_research, enable_thinking, DRS_STAGE, user_prompt):
    """First reasoner pass: build reasoner_messages, fetch reasoning, prepend."""
    reasoner_messages = copy.deepcopy(request.messages)
    if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
        drs_msg = get_drs_stage(DRS_STAGE)
        if drs_msg:
            content_append(reasoner_messages, 'user',  f"\n\n{drs_msg}\n\n")
        content_append(reasoner_messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)   
    # S206：每模型推理参数（卡片覆盖 > 角色默认）
    _eff_main = effective_main_params(settings)
    _eff_reasoner = effective_role_params(settings, settings.get('reasoner') or {})
    if chat_vendor == 'OpenAI':
        extra['max_completion_tokens'] = request.max_tokens or _eff_main.get('max_tokens')
    else:
        extra['max_tokens'] = request.max_tokens or _eff_main.get('max_tokens')
    if reasoner_vendor == 'OpenAI':
        reasoner_extra['max_completion_tokens'] = _eff_reasoner.get('max_tokens') or settings['reasoner']['max_tokens']
    else:
        reasoner_extra['max_tokens'] = _eff_reasoner.get('max_tokens') or settings['reasoner']['max_tokens']
    if request.reasoning_effort or _eff_main.get('reasoning_effort'):
        extra['reasoning_effort'] = request.reasoning_effort or _eff_main.get('reasoning_effort')
    if _eff_reasoner.get('reasoning_effort') is not None:
        reasoner_extra['reasoning_effort'] = _eff_reasoner.get('reasoning_effort') 
    if vendor == 'Ollama':
        reasoner_response = await acreate(
            lambda: reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            temperature=_srv()._role_param(settings, 'reasoner', 'temperature'),
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_complete_reasoner_prep")
        reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']
        if reasoning_buffer:
            content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
        else:
            reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning']
            if reasoning_buffer:
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
            else:
                # 将推理结果中的思考内容提取出来
                reasoning_content = reasoner_response.model_dump()['choices'][0]['message']['content']
                # open_tag和close_tag之间的内容
                start_index = reasoning_content.find(open_tag) + len(open_tag)
                end_index = reasoning_content.find(close_tag)
                if start_index != -1 and end_index != -1:
                    reasoning_content = reasoning_content[start_index:end_index]
                else:
                    reasoning_content = ""
                content_prepend(request.messages, 'assistant', reasoning_content) # 可参考的推理过程
    else:
        reasoner_response = await acreate(
            lambda: reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            stop=settings['reasoner']['stop_words'],
            temperature=_srv()._role_param(settings, 'reasoner', 'temperature'),
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_complete_reasoner_prep")
        reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']
        if reasoning_buffer:
            content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
        else:
            reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning']
            if reasoning_buffer:
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
            else:
                reasoning_buffer = ""
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
    return vendor


async def _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty):
    """Deep-research stage machine shared by the pre-loop and in-loop copies.
    none_to_empty=True preserves the pre-loop copy's None guard; the in-loop
    copy never had one (raw behaviour kept)."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,response.choices[0].message.content)
    research_response = await acreate(
        lambda: client.chat.completions.create(
        model=model,
        messages=[
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        temperature=0.5,
        extra_body = extra_params, # 其他参数
    ), attempts=2, base_delay=1.0, label="s207-_complete_drs_step")
    response_content = research_response.choices[0].message.content
    if none_to_empty and response_content is None:
        response_content = ""

    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    response_content = json.loads(response_content)
    if response_content["status"] == "done":
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "need_more_info":
        DRS_STAGE = 2
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )
    elif response_content["status"] == "need_more_work":
        DRS_STAGE = 2
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "answer":
        DRS_STAGE = 3
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )
    return DRS_STAGE, search_not_done, search_task


def _spiral_observe_ns(spiral, name, args_dict, hints):
    """S296：非流式绕圈记账（watch 由 impl 任务态传入）。"""
    _hint = spiral.observe(name, args_dict)
    if _hint:
        hints.append(_hint)


def _spiral_drain_ns(request, hints):
    """S296：非流式绕圈警示注入（元频道 system_note，同流式路径）。"""
    for _sp_hint in hints:
        request.messages.append({"role": "user", "content": _sp_hint, "name": "system_note"})


async def _ns_tool_round(request, reasoner_messages, settings, user_prompt, response, spiral=None):
    """Non-stream tool_calls round: dispatch, ack, approval abort. Returns abort."""
    from py.know_base import rerank_knowledge_base
    assistant_message = response.choices[0].message
    ns_tool_calls_meta = []
    for _tc in assistant_message.tool_calls:
        ns_tool_calls_meta.append({
            "id": _tc.id or f"call_{uuid.uuid4().hex[:12]}",
            "function": {
                "arguments": _tc.function.arguments or "",
                "name": _tc.function.name,
            },
            "type": getattr(_tc, "type", None) or "function",
        })
    request.messages.append({
        "role": "assistant",
        "content": assistant_message.content or "",
        "tool_calls": ns_tool_calls_meta,
        "reasoning_content": "",
    })
    ns_pending_abort = False
    ns_acked_ids = set()
    _sp_hints = []  # S296：本绕圈提示收集，对闭合后注入
    for _ti, _tc in enumerate(assistant_message.tool_calls):
        # T-8: 取消围栏——取消后不再调度任何工具
        _cur_entry = _current_stream_entry.get()
        if _cur_entry and _cur_entry.get("cancelled"):
            ns_pending_abort = True
            break
        tool_call_id = ns_tool_calls_meta[_ti]["id"]
        response_content = _tc.function
        logging.getLogger("app").info(response_content.name)
        args_dict, arg_err = parse_tool_arguments(_tc.function.arguments)
        if arg_err is not None:
            err_text = arg_error_text(arg_err)
            ns_acked_ids.add(tool_call_id)
            reasoner_messages.append({
                "role": "assistant",
                "content": f"{response_content.name}({_tc.function.arguments})",
                "reasoning_content": "",
            })
            reasoner_messages.append({
                "role": "user",
                "content": f"{response_content.name}工具结果：" + truncate_tool_result(err_text, 8000),
            })
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": err_text,
            })
            continue
        try:
            results = await dispatch_tool(response_content.name, args_dict, settings)
        except Exception as e:
            results = TOOL_EXC_TMPL.format(type=type(e).__name__, exc=e)
        if isinstance(results, AsyncIterator):
            buffer = []
            async for chunk in results:
                buffer.append(chunk)
            results = "".join(buffer)
        if results is None:
            ns_acked_ids.add(tool_call_id)
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": NONE_TEXT,
            })
            ns_pending_abort = True
            break
        if response_content.name in ["query_knowledge_base"] and isinstance(results, list):
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt, results)
            results = json.dumps(results, ensure_ascii=False, indent=4)
        tool_result_text = str(results)
        ns_acked_ids.add(tool_call_id)
        request.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": response_content.name,
            "content": _bound_tool_output(tool_result_text, settings),  # S184
        })
        reasoner_messages.append({
            "role": "assistant",
            "content": f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})",
            "reasoning_content": "",
        })
        reasoner_messages.append({
            "role": "user",
            "content": f"{response_content.name}工具结果：" + truncate_tool_result(tool_result_text, 8000),
        })
        # S296：绕圈熔断观测（与流式路径同源；轮末注入）
        if spiral is not None:
            _spiral_observe_ns(spiral, str(response_content.name), args_dict, _sp_hints)
        # T-9: 结构化哨兵判定（与 stream 路径同源）
        if _is_approval_result(results) is not None:
            ns_pending_abort = True
            break
    # 为未执行的调用补上说明性 tool 结果，保证成对闭合
    append_missing_results(request.messages, ns_tool_calls_meta, ns_acked_ids)
    _spiral_drain_ns(request, _sp_hints)  # S296：绕圈警示（对闭合后注入，同流式）
    if ns_pending_abort:
        # S172：非流式审批中断同样走 IM 挂起登记（与流式路径对齐；非 IM 渠道自动跳过）
        _tail_m = next((m for m in reversed(request.messages) if get_role(m) == "tool"), None)
        if _tail_m is not None and _is_approval_result(_tail_m.get("content")) is not None:
            await _im_approval_hangup(request, request.messages, _tail_m.get("content"))
        return True
    return False


async def _ns_reasoner_pass(request, reasoner_client, reasoner_messages, settings, images, reasoner_extra, open_tag, close_tag, tools, vendor):
    """In-loop reasoner refresh: re-run reasoner, prepend its reasoning."""
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)
    if vendor == 'Ollama':
        reasoner_response = await acreate(
            lambda: reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            temperature=_srv()._role_param(settings, 'reasoner', 'temperature'),
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_ns_reasoner_pass")
        # 将推理结果中的思考内容提取出来
        reasoning_content = reasoner_response.model_dump()['choices'][0]['message']['content']
        # open_tag和close_tag之间的内容
        start_index = reasoning_content.find(open_tag) + len(open_tag)
        end_index = reasoning_content.find(close_tag)
        if start_index != -1 and end_index != -1:
            reasoning_content = reasoning_content[start_index:end_index]
        else:
            reasoning_content = ""
        content_prepend(request.messages, 'assistant', reasoning_content) # 可参考的推理过程
    else:
        reasoner_response = await acreate(
            lambda: reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            stop=settings['reasoner']['stop_words'],
            temperature=_srv()._role_param(settings, 'reasoner', 'temperature'),
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_ns_reasoner_pass")
        content_prepend(request.messages, 'assistant', reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']) # 可参考的推理过程
    return vendor


async def _complete_finalize(request, settings, response, m0, memoryId, cur_memory, user_prompt, open_tag, close_tag):
    """response_dict normalization + mem0 write job + turn-log shadow append."""
    response_dict = response.model_dump()
    content = response_dict["choices"][0]['message']['content']
    if response_dict["choices"][0]['message'].get('reasoning_content',""):
        pass
    else:
        response_dict["choices"][0]['message']['reasoning_content'] = response_dict["choices"][0]['message'].get('reasoning',"")
    if open_tag in content and close_tag in content:
        reasoning_content = re.search(fr'{open_tag}(.*?)\{close_tag}', content, re.DOTALL)
        if reasoning_content:
            # 存储到 reasoning_content 字段
            response_dict["choices"][0]['message']['reasoning_content'] = reasoning_content.group(1).strip()
            # 移除原内容中的标签部分
            response_dict["choices"][0]['message']['content'] = re.sub(fr'{open_tag}(.*?)\{close_tag}', '', content, flags=re.DOTALL).strip()
    if m0 and not request.is_sub_agent and not request.is_quarantined and getattr(request, "platform", "") != "diary":  # S172: 日记自调用跳过记忆检索
        _reply_txt = response_dict["choices"][0]['message']['content'] or ""
        # S231：结构化传角色，防记忆角色漂移（同流式路径 mem0-add）。
        messages = [
            {"role": "user", "content": _neutralize(user_prompt or "", store="mem0-add-complete")},
            {"role": "assistant", "content": _neutralize(_reply_txt, store="mem0-add-complete")},
        ]
        infer = cur_memory.get('infer') or False
        _m0_job = m0
        _mid = memoryId
        _job_msgs = messages

        def _mem_job():
            metadata = {
                "timetamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _m0_job.add(_job_msgs, user_id=_mid, metadata=metadata, infer=infer)
            logging.getLogger("app").info("知识库更新完成")

        llm_gate.submit_memory_job(
            _mid, _mem_job, name="mem0-add-complete",
            debounce=float((settings.get('llmGuardSettings') or {}).get('debounceSeconds', 20) or 0)
                     if (settings.get('llmGuardSettings') or {}).get('enabled', True) else 0.0,
            wait_idle=(settings.get('llmGuardSettings') or {}).get('enabled', True))
    try:
        from py.turn_log import shadow_append as _shadow_append
        await _shadow_append(request.conversation_id, request.messages, log=print)
    except Exception as _tle:
        logging.getLogger("app").info(f"[TurnLog] complete shadow skip: {_tle}")
    return response_dict


def _ns_behavior_sanitize(response_dict):
    """S203 兜底：行为/主动外发轮正文漏网调用块——中和剥除后直发文本不得残留
    尸块与占位符（该通道无拦截展示语义，剥空则空串，各 IM manager 空回复不发）。"""
    try:
        from py.tool_call_guard import REDACTION, detect_leaked_calls, neutralize_leaked_blocks
        message = response_dict["choices"][0]["message"]
        content = message.get("content") or ""
        leaked = detect_leaked_calls(content)
        if leaked:
            cleaned = neutralize_leaked_blocks(content).replace(REDACTION, " ")
            cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
            logging.getLogger("app").info(
                "[TCG] 直发/行为轮正文泄漏调用块已中和剥除: %s（剩余 %d 字符）",
                leaked, len(cleaned))
            message["content"] = cleaned
    except Exception:
        pass
    return response_dict


async def _generate_complete_impl(client,reasoner_client, request: ChatRequest, settings: dict,fastapi_base_url,enable_thinking,enable_deep_research,enable_web_search):
    # (global decl cleared: migrated to py/app_state.py)
    
    # 设置对话上下文，供 secondhand_review_image 等工具使用
    _srv().current_request_messages.set(request.messages)
    
    DRS_STAGE = 1 # 1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段
    DRS_STAGE = _apply_context_compression(request, DRS_STAGE)
        # =========================================================================

    from py.load_files import get_files_content,file_tool,image_tool,analyze_image_tool,review_image_tool,analyze_images_tool,view_images_tool
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
    from py.utility_tools import time_tool
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
    
    from py.mode_change import mode_change_tool
    from py.acpx_tools import acp_agent_tool
    m0 = None
    memoryId = None
    cur_memory = None
    if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
        memoryId = settings["memorySettings"]["selectedMemory"]
        cur_memory = None
        for memory in settings["memories"]:
            if memory["id"] == memoryId:
                cur_memory = memory
                break
        if cur_memory and cur_memory["providerId"]:
            logging.getLogger("app").info("长期记忆启用")
            m0 = llm_gate.get_mem0_instance(memoryId, cur_memory, settings)
    images = await images_in_messages(request.messages,fastapi_base_url)
    request.messages = await message_without_images(request.messages)
    open_tag = "<think>"
    close_tag = "</think>"
    tools = await build_llm_tools(request, settings, _srv()._assemble_toolkit())
    _srv()._inject_tool_discipline(request, tools)  # S204: 纪律随有效声明集（stream/ns 两处）
    extra = {}
    reasoner_extra = {}
    # S160 L0a：本地推理引擎软压制（eosGuard.enabled 且 base_url 为回环时生效）
    apply_eos_guard(reasoner_extra, settings, str(getattr(reasoner_client, "base_url", "") or ""))
    search_not_done = False
    search_task = ""
    try:
        model = settings['model']
        _eff_main = effective_main_params(settings)  # S206：每模型推理参数（卡片覆盖 > 角色默认）
        extra_params = _eff_main.get('extra_params') or []
        # 移除extra_params这个list中"name"不包含非空白符的键值对
        if extra_params:
            for extra_param in extra_params:
                if not extra_param['name'].strip():
                    extra_params.remove(extra_param)
            # 列表转换为字典
            extra_params = _srv().process_extra_params(extra_params)
        else:
            extra_params = {}
        if request.fileLinks:
            # 异步获取文件内容
            files_content = await get_files_content(request.fileLinks)
            system_message = f"\n\n相关文件内容：{files_content}"
            
            # 修复字符串拼接错误
            content_append(request.messages, 'system', system_message)
        kb_list = []
        user_prompt = request.messages[-1].get('content') or ""
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
            await _complete_character_context(request, settings, user_prompt, cur_memory, memoryId, m0)
        if settings["knowledgeBases"]:
            for kb in settings["knowledgeBases"]:
                if kb["enabled"] and kb["processingStatus"] == "completed":
                    kb_list.append({"kb_id":kb["id"],"name": kb["name"],"introduction":kb["introduction"]})
        if settings["KBSettings"]["when"] == "before_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                all_kb_content = []
                # 用query_knowledge_base函数查询kb_list中所有的知识库
                for kb in kb_list:
                    kb_content = await query_knowledge_base(kb["kb_id"],user_prompt)
                    all_kb_content.extend(kb_content)
                    if settings["KBSettings"]["is_rerank"]:
                        all_kb_content = await rerank_knowledge_base(user_prompt,all_kb_content)
                if all_kb_content:
                    kb_message = f"\n\n可参考的知识库内容：{all_kb_content}"
                    content_append(request.messages, 'user',  f"{kb_message}\n\n用户：{user_prompt}")
        if settings["KBSettings"]["when"] == "after_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                kb_list_message = f"\n\n可调用的知识库列表：{json.dumps(kb_list, ensure_ascii=False)}"
                content_append(request.messages, 'system', kb_list_message)
        else:
            kb_list = []
        request = await _srv().tools_change_messages(request, settings)
        # 如果系统消息为空字符串或者仅包含空白符，则将系统消息改成"you are a helpful assistant."
        if request.messages[0]['role'] == 'system' and not request.messages[0]['content'].strip():
            request.messages[0]['content'] = "you are a helpful assistant."
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
        await _complete_web_search_setup(request, settings, user_prompt, tools, enable_web_search)
        if kb_list:
            tools.append(kb_tool)
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            deepsearch_messages = copy.deepcopy(request.messages)
            content_append(deepsearch_messages, 'user',  "\n\n将用户提出的问题或给出的当前任务拆分成多个步骤，每一个步骤用一句简短的话概括即可，无需回答或执行这些内容，直接返回总结即可，但不能省略问题或任务的细节。如果用户输入的只是闲聊或者不包含任务和问题，直接把用户输入重复输出一遍即可。如果是非常简单的问题，也可以只给出一个步骤即可。一般情况下都是需要拆分成多个步骤的。")
            response = await acreate(
                lambda: client.chat.completions.create(
                model=model,
                messages=deepsearch_messages,
                temperature=0.5, 
                extra_body = extra_params, # 其他参数
            ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_generate_complete_impl")
            user_prompt = response.choices[0].message.content
            content_append(request.messages, 'user',  f"\n\n如果用户没有提出问题或者任务，直接闲聊即可，如果用户提出了问题或者任务，任务描述不清晰或者你需要进一步了解用户的真实需求，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。")
        if settings['reasoner']['enabled'] or enable_thinking:
            vendor = await _complete_reasoner_prep(request, reasoner_client, settings, chat_vendor, reasoner_vendor, images, tools, extra, reasoner_extra, open_tag, close_tag, enable_deep_research, enable_thinking, DRS_STAGE, user_prompt)
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            content_append(request.messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
            drs_msg = get_drs_stage(DRS_STAGE)
            if drs_msg:
                content_append(request.messages, 'user',  f"\n\n{drs_msg}\n\n")
        # ===== 上下文管理管线：L1 修剪 -> L2 自动摘要（agent 模式；非流式通道不下发事件） =====
        await _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools)
        # S203：行为/主动外发轮（8 个 IM manager 的 execute_behavior_event 通道）——产出
        # 将原样送 IM 对端，声明工具只会诱导模型把调用块写进正文被整块发出（ns 尸块事故）。
        # 此轮强制零工具并注记只输出 plain 文本；_ns_behavior_sanitize 兜底中和漏网尸块。
        if getattr(request, "behavior_trigger", False):
            tools = []
            request.messages.append({
                "role": "user", "name": "system_note",
                "content": ("本轮为计划外主动外发：你的输出会被原样转达给 IM 对端，"
                            "只输出要对 TA 说的 plain 文本，不要调用任何工具，"
                            "也不要在正文里书写任何形式的工具调用标记。"),
            })
        msg = await images_add_in_messages(request.messages, images,settings)
        _attach_screen_image_for_behavior(msg, request, settings)  # S225：旁观发言附截图（仅改 deepcopy，主模型原生读图，不入 request.messages/落盘）
        if request.top_p != 1 or _eff_main.get('top_p') != 1:
            extra['top_p'] = request.top_p or _eff_main.get('top_p')
        if tools:
            response = await acreate(
                lambda: client.chat.completions.create(
                model=model,
                messages=msg,  # 添加图片信息到消息
                temperature=request.temperature or _eff_main.get('temperature'),
                tools=tools,
                stream=False,
                extra_body = extra_params, # 其他参数
                **extra
            ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_generate_complete_impl")
        else:
            response = await acreate(
                lambda: client.chat.completions.create(
                model=model,
                messages=msg,  # 添加图片信息到消息
                temperature=request.temperature or _eff_main.get('temperature'),
                stream=False,
                extra_body = extra_params, # 其他参数
                **extra
            ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_generate_complete_impl")
        if response.choices[0].message and response.choices[0].message.tool_calls:  # B1: message 可能为 None
            pass
        elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            DRS_STAGE, search_not_done, search_task = await _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty=True)
        reasoner_messages = copy.deepcopy(request.messages)
        _ns_loop_count = 0
        ns_force_no_tools = False
        _ns_spiral = SpiralWatch()  # S296：绕圈熔断（任务态，与流式 _st._spiral 对位）
        while response.choices[0].message and (response.choices[0].message.tool_calls or search_not_done):  # B1: None 守卫
            _ns_loop_count += 1
            _ns_max_iterations = _tool_cap.effective_limit()  # S233：轮边界动态上限（调值/破限即时生效）
            # T-8: 取消围栏——后续 LLM 轮次前检查（cancel 端点可停不可停工具链的漏洞封堵）
            _cur_entry = _current_stream_entry.get()
            if _cur_entry and _cur_entry.get("cancelled"):
                break
            if not _drs_round_cap(_ns_loop_count, _ns_max_iterations, search_not_done, response.choices[0].message.tool_calls, "非流式"):
                search_not_done = False
                response.choices[0].message.tool_calls = None
                break
            if response.choices[0].message.tool_calls and _ns_loop_count > _ns_max_iterations:
                _append_loopcap_hint(request, "非流式")
                ns_force_no_tools = True
                response.choices[0].message.tool_calls = None
            if response.choices[0].message.tool_calls:
                abort = await _ns_tool_round(request, reasoner_messages, settings, user_prompt, response, spiral=_ns_spiral)
                if abort:
                    break
            if settings['webSearch']['when'] == 'after_thinking' or settings['webSearch']['when'] == 'both':
                content_append(request.messages, 'user',  f"\n对于联网搜索的结果，如果联网搜索的信息不足以回答问题时，你可以进一步使用联网搜索查询还未给出的必要信息。如果已经足够回答问题，请直接回答问题。")
            if settings['reasoner']['enabled'] or enable_thinking:
                vendor = await _ns_reasoner_pass(request, reasoner_client, reasoner_messages, settings, images, reasoner_extra, open_tag, close_tag, tools, vendor)
            images = await _maybe_inject_browser_vision(request, settings, images, fastapi_base_url)  # S228：浏览器截图直注主模型
            msg = await images_add_in_messages(request.messages, images,settings)
            if request.top_p != 1 or _eff_main.get('top_p') != 1:
                extra['top_p'] = request.top_p or _eff_main.get('top_p')
            if tools and not ns_force_no_tools:
                response = await acreate(
                    lambda: client.chat.completions.create(
                    model=model,
                    messages=msg,  # 添加图片信息到消息
                    temperature=request.temperature or _eff_main.get('temperature'),
                    tools=tools,
                    stream=False,
                    extra_body = extra_params, # 其他参数
                    **extra
                ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_generate_complete_impl")
            else:
                response = await acreate(
                    lambda: client.chat.completions.create(
                    model=model,
                    messages=msg,  # 添加图片信息到消息
                    temperature=request.temperature or _eff_main.get('temperature'),
                    stream=False,
                    extra_body = extra_params, # 其他参数
                    **extra
                ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_generate_complete_impl")
            if response.choices[0].message and response.choices[0].message.tool_calls:  # B1: 再生成后 message 可能为 None
                pass
            elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
                DRS_STAGE, search_not_done, search_task = await _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty=False)
       # 处理响应内容
        response_dict = await _complete_finalize(request, settings, response, m0, memoryId, cur_memory, user_prompt, open_tag, close_tag)
        if getattr(request, "behavior_trigger", False) or getattr(request, "sanitize_plain_output", False):
            response_dict = _ns_behavior_sanitize(response_dict)  # S203/S204 兜底：尸块剥除
        return JSONResponse(content=response_dict)
    except Exception as e:
        return JSONResponse(
            content={"error": {"message": str(e) + retry_suffix(e), "type": "api_error"}}
        )
