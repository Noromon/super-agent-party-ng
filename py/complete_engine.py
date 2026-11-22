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
import asyncio
import copy
import datetime
import json
import logging
import random
import re
import uuid
from typing import AsyncIterator

from py import llm_gate
from py.context_builder import sanitize_tool_chains_logged
from py.llm_recovery import acreate, llm_retry_cfg
from py.model_params import effective_main_params, effective_role_params
from py.msg_utils import content_append, content_prepend
from py.srv_ref import srv as _srv
from py.stream_prep import (_bound_tool_output, _cm_context_enabled,
                            ensure_thinking_fields, get_drs_stage,
                            get_drs_stage_system_message, get_role,
                            parse_tool_arguments, truncate_tool_result)
from py.stream_relay import _current_stream_entry
from py.token_guard import neutralize as _neutralize, neutralize_deep
from py.tool_dispatch import _is_approval_result
from py.tool_hooks import _im_approval_hangup, dispatch_tool
from py.tool_loop import (NONE_TEXT, TOOL_EXC_TMPL,
                          append_missing_results, arg_error_text)
from py.vision_tools import images_add_in_messages


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
