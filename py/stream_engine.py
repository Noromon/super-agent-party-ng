# -*- coding: utf-8 -*-
"""S302a：流式轮次引擎（首过/二轮/工具轮/DRS 轮/循环 pass/
reasoner 更新与重抓/用量与收尾任务/内容安全终闸），自 server.py 逐字搬移。

纯移动批；文档化改写=_srv() 懒访问（_srv().async_tools(+lock)/t/_role_param——原语义即
server 模块全局调用期读取，逐点等价）。_st 任务态按参数随行（战役纪律：不聚变对象）。
准备域见 py/stream_prep.py；两引擎巨函（stream_generator/generate_stream_response）
属端点编排层，S302b/S304 处置。
"""
import asyncio
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime
from typing import AsyncIterator

from PIL import Image

from py.ask_flow import is_ask_result as ask_flow_is_ask_result
from py.diary_chat_integration import append_to_chat_buffer
from py.diary_system import DEFAULT_BOOK_ID as DIARY_DEFAULT_BOOK
from py.get_setting import UPLOAD_FILES_DIR
from py.guard import check_content_safety
from py.image_draw import draw_action_feedback, draw_grid_on_image, scale_to_fit
from py.llm_recovery import (acreate, attach_retry_note as llm_attach,
                             backoff_sleep as llm_backoff,
                             is_transient_transport_error, llm_retry_cfg,
                             stream_reset_chunk, stream_retry_chunk)
from py.msg_utils import content_append
from py import llm_gate
from py.srv_ref import srv as _srv
from py.stream_prep import (GATE_MAX, _approval_pending_event_chunk,
                            _apply_ctx_guardrail, _ask_channel,
                            _ask_pending_event_chunk, _ask_tool_handle,
                            _bound_tool_output, _breakdown_tokens,
                            _cm_context_enabled, _merge_tool_delta, _robust_cfg,
                            _stream_anchor_inject, _stream_ask_hang,
                            _stream_gate_check, _stream_im_approval_hang,
                            _tcg_display_slice, _tool_notice_chunk,
                            ensure_thinking_fields, get_drs_stage,
                            get_drs_stage_system_message, get_role,
                            parse_tool_arguments, sanitize_tool_chains_logged,
                            truncate_tool_result)
from py.stream_relay import _st_cancelled
from py.token_guard import neutralize as _neutralize
from py.tool_call_guard import neutralize_leaked_blocks as _tcg_neutralize
from py.tool_dispatch import _is_approval_result
from py.tool_hooks import _approval_precheck, dispatch_tool, execute_tool
from py.tool_loop import (NONE_TEXT, TOOL_EXC_TMPL,
                     append_missing_results, arg_error_text)
from py.tool_spiral import SpiralWatch
from py.vision_tools import (_image_magic_ok, _strip_image_parts_from_messages,
                             images_add_in_messages, images_in_messages,
                             message_without_images)

async def _stream_first_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, is_tool_call, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count):
    """First LLM stream: tool_call slot merging + think-tag splitting + SSE."""
    _st["tcg_emit"], _st["tcg_cut"] = len(full_content or ""), -1  # S183 显示拦截基线
    async for chunk in response:
        # S131/F1: 流内 chunk 围栏——在途 LLM 流取消后 ≤5 chunk 内终止，
        # 不依赖 task.cancel() 对 SDK 内部 await 的可达性
        if _chunk_count % 5 == 0 and _st_cancelled(_st):
            logging.getLogger("app").info("[Cancel] 流式输出中被用户取消，终止 LLM 流")
            _st["w1_cancel"] = True
            return
        if not chunk.choices:
            if getattr(chunk, "usage", None):
                usage_info = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else dict(chunk.usage)
                _ctx_peak = max(_ctx_peak, usage_info.get("prompt_tokens") or 0)
            continue
        _chunk_count += 1
        if _chunk_count % 5 == 0:
            await asyncio.sleep(0)  # 定期让出控制权，让事件循环处理WebSocket ping
        choice = chunk.choices[0]
        if choice.delta is None:  # B1(1775d8d3): 末包 delta:null 兼容（少数兼容服务）
            continue
        if choice.delta.tool_calls:  # function_calling
            is_tool_call = True
            # C-20+S85-A: 槽位合并统一走 _merge_tool_delta
            # （index → id 匹配 → 末槽），progress 帧只下发本帧增量。
            for tool in choice.delta.tool_calls:
                current_tool, _frag = _merge_tool_delta(tool_calls, tool)
                _slot = tool_calls.index(current_tool)
                if current_tool.function and current_tool.function.name:
                    progress_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_progress": {  # 新增字段，区别于最终的 tool_content
                                    "name": current_tool.function.name,
                                    "arguments": _frag,
                                    "incremental": True,
                                    "index": _slot,
                                    "id": current_tool.id or f"call_{_slot}"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(progress_chunk)}\n\n"
        else:
            if hasattr(choice.delta, "audio") and choice.delta.audio and is_tool_call == False:
                # 只把 Base64 音频数据留在 delta 里，别动它
                yield f"data: {chunk.model_dump_json()}\n\n"
                continue
            elif hasattr(choice.delta, "audio") and choice.delta.audio and is_tool_call == True:
                continue
            # 创建原始chunk的拷贝
            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0]["delta"]
                        
            # 初始化必要字段
            delta.setdefault("content", "")
            delta.setdefault("reasoning_content", "")
                        
            # 优先处理 reasoning_content
            if delta["reasoning_content"]:
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                continue
            if delta.get("reasoning", ""):
                delta["reasoning_content"] = delta["reasoning"]
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                continue

            # 处理内容
            current_content = delta["content"]
            buffer = current_content
                        
            while buffer:
                if not in_reasoning:
                    # 寻找开始标签
                    start_pos = buffer.find(open_tag)
                    if start_pos != -1:
                        # 处理开始标签前的内容
                        content_buffer.append(buffer[:start_pos])
                        buffer = buffer[start_pos+len(open_tag):]
                        in_reasoning = True
                    else:
                        content_buffer.append(buffer)
                        buffer = ""
                else:
                    # 寻找结束标签
                    end_pos = buffer.find(close_tag)
                    if end_pos != -1:
                        # 处理思考内容
                        reasoning_buffer.append(buffer[:end_pos])
                        buffer = buffer[end_pos+len(close_tag):]
                        in_reasoning = False
                    else:
                        reasoning_buffer.append(buffer)
                        buffer = ""
                        
            # 构造新的delta内容
            new_content = "".join(content_buffer)
            new_reasoning = "".join(reasoning_buffer)
                        
            # 更新chunk内容
            # S183: 流内显示拦截——调用块标记起始处起的正文不流向 UI/IM，
            # 疑似标记前缀先扣住；full_content 仍按原文累积供 TCG 判定与落账。
            _tcg_show, _st["tcg_emit"], _st["tcg_cut"] = _tcg_display_slice(
                full_content, new_content, _st.get("tcg_emit", 0), _st.get("tcg_cut", -1))
            delta["content"] = _tcg_show.strip("\x00")  # 保留未完成内容
            delta["reasoning_content"] = new_reasoning.strip("\x00") or None
                        
            # 重置缓冲区但保留未完成部分
            if in_reasoning:
                content_buffer = [new_content.split(open_tag)[-1]] 
            else:
                content_buffer = []
            reasoning_buffer = []
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            full_content += new_content.strip("\x00")  # S183: 累积原文（非显示截断文）

    _st["usage_info"] = usage_info
    _st["_ctx_peak"] = _ctx_peak
    _st["is_tool_call"] = is_tool_call
    _st["full_content"] = full_content
    _st["in_reasoning"] = in_reasoning
    _st["content_buffer"] = content_buffer
    _st["reasoning_buffer"] = reasoning_buffer
    _st["_chunk_count"] = _chunk_count


async def _stream_drs_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
    """Post-first-pass deep-research status machine with per-status SSE notices."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content)
    response = await acreate(
        lambda: client.chat.completions.create(
        model=model,
        messages=[
            {
            "role": "system",
            "content": source_prompt,
            },
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        extra_body = extra_params, # 其他参数
    ), attempts=2, base_delay=1.0, label="s207-_stream_drs_round")
    response_content = response.choices[0].message.content
    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    try:
        response_content = json.loads(response_content)
    except json.JSONDecodeError:
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❌{await _srv().t('task_error')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
    if response_content["status"] == "done":
        search_chunk = {
            "choices": [{
                "delta": {
                   "tool_content": {"title": f"✅{await _srv().t('task_done')}", "content": ""},
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❎{await _srv().t('task_not_done')}", "content": ""},
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
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
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❓{await _srv().t('task_need_more_info')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await _srv().t('enter_search_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
                "reasoning_content": "",
            }
        )
    elif response_content["status"] == "need_more_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await _srv().t('need_more_work')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
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
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"⭐{await _srv().t('enter_answer_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
                "reasoning_content": "",
            }
        )

    _st["drs"] = DRS_STAGE
    _st["snot"] = search_not_done
    _st["stask"] = search_task


def _stream_round_compress(request, settings, _st):
    """L1 context compression after a tool round (W1 copy). (M-3 split)"""
    max_rounds = 0 if _cm_context_enabled(settings) else settings.get("max_rounds", 0)
    chat_messages = request.messages # 这里的 chat_messages 包含 system
    _st.setdefault("_ctx_peak", 0)
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


def _notify_web_approval_pending(_st):
    """S151：Web 会话审批挂起落通知中心（M3 棘轮：逻辑移出巨函数体）。"""
    try:
        from py import notification_center
        _ap = _is_approval_result(_st.get("results"))
        if not _ap:
            return
        _ent = _st.get("_entry")
        _sid = _ent.get("id") if isinstance(_ent, dict) else None
        notification_center.emit(
            "approval", f"工具 {_ap.get('tool_name', '?')} 等待审批（Web 会话）", level="warn",
            extra={"pending_key": _sid or "web-anon", "source": "web",
                   "stream_id": _sid, "tool_name": _ap.get("tool_name", ""),
                   "tool_params": _ap.get("tool_params") or {}, "status": "pending"})
    except Exception:
        pass


async def _stream_first_round_with_recovery(_st, client, model, msg, extra, extra_params,
                                            settings, open_tag, close_tag, tool_calls,
                                            usage_info, _ctx_peak, in_reasoning,
                                            content_buffer, reasoning_buffer):
    """S207：首轮 create+读流，瞬断则同 messages 原样重发本轮推理。

    重试边界不含工具执行——断流时本轮工具零执行、半截正文未落历史，重发
    零环境副作用；已流出半截时下发 stream_reset（前端保留前 keep_text_chars
    个已落账字符，新输出到达才替换）+ stream_retry 状态帧。写回协议同
    _stream_first_pass（累加器经 _st）。
    """
    _lr_max, _lr_delay, _lr_mid = llm_retry_cfg(settings)
    _lr_attempt = 0
    while True:
        _lr_delivered = False  # 累加器轮末才写回，以实际下发帧判定半截产出
        try:
            response = await client.chat.completions.create(
                user="sap-main",  # S191-N2：主通道流量标记（引擎侧与 reasoner 区分）
                model=model,
                messages=msg,  # 添加图片信息到消息
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra_params,  # 其他参数
                **_apply_ctx_guardrail(extra, msg, settings)
            )
            full_content = ""
            is_tool_call = False
            _chunk_count = 0  # 流式让出计数器，防止事件循环饥饿
            async for _c in _stream_first_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, is_tool_call, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count):
                if isinstance(_c, str) and '"delta"' in _c:
                    _lr_delivered = True
                yield _c
            return
        except Exception as _lr_e:
            if (_lr_attempt >= _lr_max or _st_cancelled(_st)
                    or not is_transient_transport_error(_lr_e)):
                raise llm_attach(_lr_e, _lr_attempt) from None
            _lr_partial = _lr_delivered or bool(tool_calls)
            logging.getLogger("app").warning(
                "[LLMRetry] 主流首轮瞬断重试 %d/%d: %s",
                _lr_attempt + 1, _lr_max, str(_lr_e)[:200])
            if _lr_partial and _lr_mid:
                yield stream_reset_chunk(_st.get("_lr_keep_chars", 0))
            yield stream_retry_chunk(_lr_attempt + 1, _lr_max, str(_lr_e))
            _st["full_content"] = ""
            _st["content_buffer"] = []
            _st["reasoning_buffer"] = []
            _st["in_reasoning"] = False
            await llm_backoff(_lr_delay, _lr_attempt,
                              cancelled=lambda: _st_cancelled(_st))
            _lr_attempt += 1


async def _stream_second_round(_st, client, model, msg, extra, extra_params, settings, request,
                               tools, force_no_tools, usage_info, _ctx_peak, in_reasoning,
                               content_buffer, reasoning_buffer, open_tag, close_tag):
    """工具循环轮：create + 消费（_stream_loop_pass）+ 终守卫 + 闭合落账。

    S163：正文泄漏幻觉调用块（引擎把未声明名的调用降级回文本）且本轮声明了
    工具时——中和落账 + 注入自纠消息重发（上限 MAX_TCG_RETRIES），新轮产出
    结构化 tool_calls 即由外层走既有工具循环真实执行；只提示不改写执行。
    写回 _st：tc_round / fc / usage_info / _ctx_peak / in_reasoning /
    content_buffer / reasoning_buffer；cancel 路径置 tc_round_done 并终结。
    """
    from py.tool_call_guard import (build_correction_message,
                                    declared_tool_names, detect_leaked_calls)
    _tools_now = []
    if tools and not force_no_tools:
        extra['tools'] = tools
        _tools_now = tools
    _lr_max, _lr_delay, _lr_mid = llm_retry_cfg(settings)  # S207
    _lr_attempt = 0
    while True:
        full_content = ""
        if _st_cancelled(_st):
            logging.getLogger("app").info("[Cancel] 流已被用户取消，工具后续轮次终止")
            yield "data: [DONE]\n\n"
            _st["tc_round"] = []
            _st["tc_round_done"] = True
            return
        tool_calls = []
        _chunk_count2 = 0  # 流式让出计数器（工具调用循环内）
        _lr_delivered = False  # 累加器轮末才写回，以实际下发帧判定半截产出
        try:
            response = await client.chat.completions.create(
                user="sap-main",  # S191-N2：主通道流量标记（引擎侧与 reasoner 区分）
                model=model,
                messages=msg,  # 添加图片信息到消息
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra_params,  # 其他参数
                **_apply_ctx_guardrail(extra, msg, settings)
            )
            async for _c in _stream_loop_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count2):
                if isinstance(_c, str) and '"delta"' in _c:
                    _lr_delivered = True
                yield _c
            _lr_attempt = 0
        except Exception as _lr_e:
            # S207：本轮瞬断→同 messages 重发本轮推理（工具执行在边界外，
            # 已执行副作用永不重放）；半截轮正文/思考从未落账，清后重生成
            # S252: 引擎加载图像失败类 400（伪装图/AVIF 等不支持字节）非瞬态，原样重发必再炸——
            # 剥离全部图像降级为纯文本请求重试一次（一次性标志），图像问题不再拖垮整轮
            _et252 = str(_lr_e).lower()
            if (not _st.get("img_strip_retried")
                    and ("failed to load image" in _et252 or "image or audio" in _et252
                         or "load image" in _et252
                         # S264: 格式拒收类 400（本地服务器不认 webp/avif 实证文案）同样剥图降级
                         or "base64 encoded image" in _et252)
                    and _strip_image_parts_from_messages(request.messages)):
                _st["img_strip_retried"] = True
                logging.getLogger("app").warning(
                    "[S252] 引擎图像加载失败(400)，已剥离图像降级重试: %s", str(_lr_e)[:160])
                yield stream_retry_chunk(_lr_attempt + 1, _lr_max, "图像加载失败：已剥离图像降级为纯文本重试")
                content_buffer = []
                reasoning_buffer = []
                in_reasoning = False
                _st["full_content"] = ""
                _st["content_buffer"] = []
                _st["reasoning_buffer"] = []
                _st["in_reasoning"] = False
                _lr_attempt += 1
                await llm_backoff(0, _lr_attempt, cancelled=lambda: _st_cancelled(_st))
                continue
            if (_lr_attempt >= _lr_max or _st_cancelled(_st)
                    or not is_transient_transport_error(_lr_e)):
                raise llm_attach(_lr_e, _lr_attempt) from None
            _lr_partial = _lr_delivered or bool(tool_calls)
            logging.getLogger("app").warning(
                "[LLMRetry] 工具轮瞬断重试 %d/%d: %s",
                _lr_attempt + 1, _lr_max, str(_lr_e)[:200])
            if _lr_partial and _lr_mid:
                yield stream_reset_chunk(_st.get("_lr_keep_chars", 0))
            yield stream_retry_chunk(_lr_attempt + 1, _lr_max, str(_lr_e))
            content_buffer = []
            reasoning_buffer = []
            in_reasoning = False
            _st["full_content"] = ""
            _st["content_buffer"] = []
            _st["reasoning_buffer"] = []
            _st["in_reasoning"] = False
            await llm_backoff(_lr_delay, _lr_attempt,
                              cancelled=lambda: _st_cancelled(_st))
            _lr_attempt += 1
            continue
        usage_info = _st["usage_info"]
        _ctx_peak = _st["_ctx_peak"]
        full_content = _st["full_content"]
        in_reasoning = _st["in_reasoning"]
        content_buffer = _st["content_buffer"]
        reasoning_buffer = _st["reasoning_buffer"]
        _st["fc"] = full_content
        async for _c in _stream_final_guard(_st, content_buffer, reasoning_buffer, settings):
            yield _c
        full_content = _st["fc"]
        if not tool_calls and full_content:
            _leaked = detect_leaked_calls(full_content)
            _declared = declared_tool_names(_tools_now)
            _retries = _st.get("tcg_retries", 0)
            _repair_max = _robust_cfg(settings)[1]  # S183 可配置（旧：常量 MAX_TCG_RETRIES）
            _will_retry = bool(_leaked and _declared and _retries < _repair_max
                               and not _st_cancelled(_st))
            if _leaked:
                # S183: 可见错误调用块——正文已在流内截断不展示尸块；
                # IM 侧由 ToolProgressLedger 按工具块桥接设置裁决
                yield _tool_notice_chunk(
                    "⚠️ 畸形工具调用（已拦截，未执行）",
                    "模型把调用块以纯文本写入正文：%s。%s" % (
                        ", ".join(map(str, _leaked[:6])),
                        "已要求改用结构化调用重发。" if _will_retry
                        else "返工已达上限或本轮无声明工具，按正文收尾。"))
            if _will_retry:
                _st["tcg_retries"] = _retries + 1
                content_append(request.messages, 'assistant', full_content)  # 已含 S163 中和
                _st["_lr_keep_chars"] = _st.get("_lr_keep_chars", 0) + len(full_content)  # S207
                request.messages.append({
                    "role": "user",
                    "content": build_correction_message(_leaked, _declared),
                    "name": "system_note",  # S166：元频道注记
                })
                # S213：重发轮必须携带刚注入的自纠注记。旧版 create 用的 msg 是
                # 本轮入口处的 deepcopy——注记只落了 request.messages，重试请求
                # 永远看不见 did-you-mean（S163 安慰剂缺陷，e2e 实锤 2026-11-13）
                msg = request.messages
                logging.getLogger("app").info(
                    "[TCG] 正文泄漏未声明工具调用，自纠重试 %d/%d: %s",
                    _retries + 1, _repair_max, _leaked)
                continue
            if _leaked:
                logging.getLogger("app").warning(
                    "[TCG] 泄漏调用已拦截显示，未返工（retries=%d max=%d declared=%d）: %s",
                    _retries, _repair_max, len(_declared), _leaked)
            # 将响应添加到消息列表（S68：空生成不写历史；S163：泄漏块经
            # content_append 中和后落账，防 few-shot 污染）
            content_append(request.messages, 'assistant', full_content)
            _st["_lr_keep_chars"] = _st.get("_lr_keep_chars", 0) + len(full_content)  # S207
            # S183(T-C) 完成闸门：todo 未清即收尾 → 打回续跑（上限 GATE_MAX）
            # S213：泄漏终结也过闸门——旧版 if not _leaked 让泄漏成为唯一绕过闸门的
            # 收尾路径：todo 未清照样静默终结（长任务事故实证 2026-11-13 20:48）。
            # 打回时把 did-you-mean 一并附上，模型重发时手里就有正确名。
            _g_act, _g_payload = await _stream_gate_check(_st, _tools_now)
            if _g_act == "block":
                if _leaked:
                    _g_payload = build_correction_message(_leaked, _declared) + "\n" + _g_payload
                request.messages.append({"role": "user", "content": _g_payload,
                                         "name": "system_note"})
                msg = request.messages  # S213：闸门注记必须进重发轮（同上）
                logging.getLogger("app").info("[Gate] todo 未清即收尾，完成闸门打回: %s (leaked=%s)",
                                              _g_payload[:40], bool(_leaked))
                continue
            if _g_act == "exhaust":
                yield _tool_notice_chunk(
                    "⚠️ 任务未完结即收尾",
                    f"todo 仍有 {len(_g_payload)} 项未收口，闸门返工上限已达，按收尾放行。"
                    + ("（工具调用连续畸形后最终收尾；回复「继续」可再推进。）" if _leaked else ""))
                logging.getLogger("app").warning(
                    "[Gate] todo 未清收尾放行（闸门 %d 用尽, leaked=%s）：%d 项",
                    GATE_MAX, bool(_leaked), len(_g_payload))
        if tool_calls and _st.get("tcg_retries"):
            # S213：泄漏后经结构化调用恢复推进，旧账减一——只惩罚连续泄漏，
            # 不惩罚隔了长时间正常推进后的新事故（20:48 事故：额度被 4 分钟前的
            # 两次泄漏烧光，期间几十次成功调用视而不见）
            _st["tcg_retries"] = _st["tcg_retries"] - 1
        _st["tc_round"] = tool_calls
        return


async def _todo_stats_event_chunk():
    """S183：todo 记账后推送 todo_stats 事件供前端画进度条。返回 SSE 字符串或
    None。S194 从 _stream_tool_round 抽出（守 M-3 300 行线，逻辑不变）。"""
    try:
        from py.cli_tool import read_todo_snapshot
        _td = await read_todo_snapshot()
        _td_done = sum(1 for _t in _td if isinstance(_t, dict) and _t.get("status") == "done")
        _td_evt = {"type": "todo_stats",
                   "items": [{k: _t.get(k) for k in ("id", "content", "status", "priority")} for _t in _td if isinstance(_t, dict)],
                   "done": _td_done, "total": len(_td)}
        return f"data: {json.dumps(_td_evt, ensure_ascii=False)}\n\n"
    except Exception as _te:
        logging.getLogger("app").info(f"[Todo] todo_stats 事件推送异常（跳过）: {_te}")
        return None


def _spiral_observe(_st, name, args_dict):
    """S296：绕圈记账（任务态挂 _st）；命中收集提示，轮末对闭合后统一注入。"""
    _sp = _st.get("_spiral") or _st.setdefault("_spiral", SpiralWatch())
    _hint = _sp.observe(name, args_dict)
    if _hint:
        _st.setdefault("_spiral_hints", []).append(_hint)


def _spiral_drain(request, _st):
    """S296：绕圈警示注入（必须在 tool_calls 对闭合后调用；元频道 system_note 不进时间线）。"""
    for _sp_hint in _st.pop("_spiral_hints", None) or []:
        request.messages.append({"role": "user", "content": _sp_hint, "name": "system_note"})


async def _stream_tool_round(_st, request, settings, user_prompt, full_content, tool_calls, reasoner_messages):
    """While-loop tool round: ack, dispatch, SSE results, abort/cancel signals.

    w1_cancel = user cancelled mid-round (generator must terminate);
    w1_abort  = approval gate hit (while must break). (M-3 split)
    """
    from py.know_base import rerank_knowledge_base
    # 将本轮全部 tool_calls 连同伴随的叙述文本一次性 append 为 assistant 消息
    assistant_tool_calls = []
    for _tc in tool_calls:
        _fn = _tc.function
        assistant_tool_calls.append({
            "id": _tc.id or f"call_{uuid.uuid4().hex[:12]}",
            "function": {
                "arguments": _fn.arguments or "",
                "name": _fn.name,
            },
            "type": getattr(_tc, "type", None) or "function",
        })
    request.messages.append({
        "role": "assistant",
        "content": _tcg_neutralize(full_content) or "",  # S163：防泄漏块入历史
        "tool_calls": assistant_tool_calls,
        "reasoning_content": "",
    })
    pending_abort = False
    _ask_state = {}  # S194：本轮提问卡状态（同轮多调用合并、轮末挂起登记）
    acked_ids = set()
    reasoner_tool_events = []
    for _ti, _tc in enumerate(tool_calls):
        tool_call_id = assistant_tool_calls[_ti]["id"]
        response_content = _tc.function
        logging.getLogger("app").info(response_content)
        args_dict, arg_err = parse_tool_arguments(response_content.arguments)
        if arg_err is not None:
            err_text = arg_error_text(arg_err)
            acked_ids.add(tool_call_id)
            reasoner_tool_events.append((f"{response_content.name}({response_content.arguments})", err_text))
            err_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": err_text,
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(err_chunk)}\n\n"
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": err_text,
            })
            continue

        # 显式发送 "call" 事件，锁定 UI 状态并同步 ID（参数接收完毕，确认调用，绑定 ID）
        call_confirm_chunk = {
            "choices": [{
                "delta": {
                    "tool_call_id": tool_call_id,
                    "tool_content": {
                        "title": response_content.name,
                        "content": json.dumps(args_dict, ensure_ascii=False),
                        "type": "call"
                    }
                }
            }]
        }
        yield f"data: {json.dumps(call_confirm_chunk)}\n\n"

        if response_content.name == "ask_user_question_tool":
            # S194：结构化提问——在审批预检/异步管道之前拦截，产占位哨兵，
            # 轮末 _stream_ask_hang 落挂起记录并断流等待主人答复
            results = await _ask_tool_handle(request, args_dict, tool_calls, tool_call_id, _ask_state)
        elif settings['tools']['asyncTools']['enabled']:
            # S172：审批/路径门同步预检——命中则本轮直接产哨兵走既有审批编排，
            # 绝不进异步管道（哨兵一旦被吞进结果表，断流/登记/送审全部失联）
            _pre_ap = _approval_precheck(response_content.name, args_dict, settings)
            if _pre_ap is not None:
                results = _pre_ap
            else:
                tool_id = uuid.uuid4()
                async_tool_id = f"{response_content.name}_{tool_id}"
                chunk_dict = {
                    "id": "agentParty",
                    "choices": [
                        {
                            "finish_reason": None,
                            "index": 0,
                            "delta": {
                                "role":"assistant",
                                "content": "",
                                "async_tool_id": async_tool_id
                            }
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                asyncio.create_task(
                    execute_tool(
                        async_tool_id,
                        response_content.name,
                        args_dict,
                        settings,
                        user_prompt
                    )
                )
                async with _srv().async_tools_lock:
                    _srv().async_tools[async_tool_id] = {
                        "status": "pending",
                        "result": None,
                        "name":response_content.name,
                        "parameters":args_dict
                    }
                results = f"{response_content.name}tool has been successfully launched. It will take some time to run, and the results will be provided in the next round of conversation."
        else:
            if _st_cancelled(_st):
                logging.getLogger("app").info(f"[Cancel] 流已被用户取消，跳过工具 {response_content.name} 并终止本轮")
                _st["w1_cancel"] = True
                yield "data: [DONE]\n\n"
                return
            try:
                await asyncio.sleep(0)  # 让出控制权，确保心跳/ping能及时发送
                results = await dispatch_tool(response_content.name, args_dict, settings)
                await asyncio.sleep(0)  # 工具调用完成后再次让出，防止事件循环饥饿
            except Exception as e:
                results = TOOL_EXC_TMPL.format(type=type(e).__name__, exc=e)

        if results is None:
            none_text = NONE_TEXT
            none_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": none_text,
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(none_chunk)}\n\n"
            acked_ids.add(tool_call_id)
            reasoner_tool_events.append((f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})", none_text))
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": none_text,
            })
            pending_abort = True
            break

        if response_content.name in ["query_knowledge_base"] and type(results) == list:
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt, results)
            results = json.dumps(results, ensure_ascii=False, indent=4)

        # 发送结果，带上匹配的 tool_call_id
        if not isinstance(results, AsyncIterator):
            results = _bound_tool_output(results, settings)  # S184: 超限落盘+预览
            result_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": str(results),
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(result_chunk)}\n\n"
            if str(response_content.name).startswith("todo_write_tool"):
                _ts_chunk = await _todo_stats_event_chunk()  # S183（S194：抽 helper 守 300 行线）
                if _ts_chunk:
                    yield _ts_chunk
        else:
            # 流式工具结果处理 (AsyncIterator)
            buffer = []
            first = True
            async for chunk in results:
                buffer.append(chunk)
                # S93(F4): 显示帧单帧封顶 16KB（buffer 全文进 LLM 不受影响），防 MB 级 chunk 打爆渲染端
                _disp_chunk = chunk if isinstance(chunk, str) else str(chunk)
                if len(_disp_chunk) > 16384:
                    _disp_chunk = _disp_chunk[:16384] + "\n... [frame truncated for display]"
                if first:
                    # 第一帧带 title
                    stream_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_call_id": tool_call_id,
                                "tool_content": {
                                    "title": response_content.name,
                                    "content": _disp_chunk,
                                    "type": "tool_result_stream"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(stream_chunk)}\n\n"
                    first = False
                else:
                    # 后续帧
                    stream_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_call_id": tool_call_id,
                                "tool_content": {
                                    "title": "tool_result_stream",
                                    "content": _disp_chunk,
                                    "type": "tool_result_stream"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(stream_chunk)}\n\n"
            results = "".join(buffer)

        tool_result_text = str("".join(results))
        _st["results"] = results
        acked_ids.add(tool_call_id)
        reasoner_tool_events.append((f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})", tool_result_text))
        request.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": _bound_tool_output(tool_result_text, settings),  # S184 (幂等: 上步已 bound 则原样)
            }
        )

        if "todo_write" in str(getattr(response_content, "name", "") or ""):  # S183(T-C) todo 记账轮
            _st["turn_used_todo"] = True
        _spiral_observe(_st, str(response_content.name), args_dict)  # S296：绕圈熔断观测
        # 如果工具返回审批请求：停止执行本轮后续调用并跳出循环，等待前端手动调用恢复
        # T-9: 结构化哨兵判定（非子串嗅探），命中即断
        if _is_approval_result(results) is not None or ask_flow_is_ask_result(results) is not None:
            # S194：提问哨兵与审批哨兵同构断流（ask 记录在轮末登记）
            pending_abort = True
            break

    # 为未执行的调用补上说明性 tool 结果，保证 tool_calls 与 tool 消息成对闭合
    append_missing_results(request.messages, assistant_tool_calls, acked_ids)
    _spiral_drain(request, _st)  # S296：绕圈警示（对闭合后注入）

    # S194：提问卡轮末挂起登记（快照已含哨兵+补全对）；ask 轮不走审批登记面
    if pending_abort and _ask_state.get("ask_qs") is not None:
        await _stream_ask_hang(request, _st, _ask_state)
        # S195：web 渠道宣告活提问卡（IM 走 bot 通知，无前端卡）
        if _st.get("ask_hit") and _ask_channel(request)[0] == "web":
            _ask_ev_chunk = _ask_pending_event_chunk(request)
            if _ask_ev_chunk:
                yield _ask_ev_chunk

    # S150：IM 渠道审批挂起登记（S183-M3：主体抽至 _stream_im_approval_hang）
    if (pending_abort and _ask_state.get("ask_qs") is None
            and request.is_app_bot and request.platform and request.peer_id):
        await _stream_im_approval_hang(request, _st)

    # S151：web 侧审批挂起落通知中心（面板引导回会话卡处理）；IM 来源已经 approval_store 登记
    if (pending_abort and _ask_state.get("ask_qs") is None
            and not (request.is_app_bot and request.platform and request.peer_id)):
        _notify_web_approval_pending(_st)
        _ap_ev_chunk = _approval_pending_event_chunk(request)  # S186：真-pending 活卡宣告
        if _ap_ev_chunk:
            yield _ap_ev_chunk

    await _stream_anchor_inject(request, settings, _st, pending_abort)  # S183(T-A)

    # =========================================================================
    # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
    # =========================================================================
    _stream_round_compress(request, settings, _st)

    # 将本轮工具事件喂给推理模型上下文
    for _r_call, _r_result in reasoner_tool_events:
        reasoner_messages.append(
            {
                "role": "assistant",
                "content": _r_call,
                "reasoning_content": "",
            }
        )
        reasoner_messages.append(
            {
                "role": "user",
                "content": f"工具结果：" + truncate_tool_result(str(_r_result), 8000),
                "reasoning_content": "",
            }
        )

    _st["w1_abort"] = pending_abort


async def _stream_reasoner_update(_st, request, reasoner_client, settings, reasoner_messages, images, reasoner_extra, open_tag, close_tag, tools, vendor):
    """While-loop reasoner refresh (streamed) + vendor resolution."""
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)
    if vendor == 'Ollama':
        if _srv()._role_param(settings, 'reasoner', 'temperature') !=1:
            reasoner_extra['temperature'] = _srv()._role_param(settings, 'reasoner', 'temperature')
        # 流式调用推理模型
        reasoner_stream = await acreate(
            lambda: reasoner_client.chat.completions.create(
                user="sap-reasoner",  # S191-N2：压缩视图流量标记
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_stream_reasoner_update")
        full_reasoning = ""
        buffer = ""  # 跨chunk的内容缓冲区
        in_reasoning = False  # 是否在标签内
                            
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue
            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                current_content = delta.get("content", "")
                buffer += current_content  # 累积到缓冲区
                                    
                # 实时处理缓冲区内容
                while True:
                    reasoning_content = delta.get("reasoning_content", "")
                    if reasoning_content:
                        full_reasoning += reasoning_content
                    else:
                        reasoning_content = delta.get("reasoning", "")
                        if reasoning_content:
                            delta['reasoning_content'] = reasoning_content
                            full_reasoning += reasoning_content
                    if reasoning_content:
                        yield f"data: {json.dumps(chunk_dict)}\n\n"
                        break
                    if not in_reasoning:
                        # 寻找开放标签
                        start_pos = buffer.find(open_tag)
                        if start_pos != -1:
                            # 开放标签前的内容（非思考内容）
                            non_reasoning = buffer[:start_pos]
                            buffer = buffer[start_pos+len(open_tag):]
                            in_reasoning = True
                        else:
                            break  # 无开放标签，保留后续处理
                    else:
                        # 寻找闭合标签
                        end_pos = buffer.find(close_tag)
                        if end_pos != -1:
                            # 提取思考内容并构造响应
                            reasoning_part = buffer[:end_pos]
                            chunk_dict["choices"][0]["delta"] = {
                                "reasoning_content": reasoning_part,
                                "content": ""  # 清除非思考内容
                            }
                            yield f"data: {json.dumps(chunk_dict)}\n\n"
                            full_reasoning += reasoning_part
                            buffer = buffer[end_pos+len(close_tag):]
                            in_reasoning = False
                        else:
                            # 发送未闭合的中间内容
                            if buffer:
                                chunk_dict["choices"][0]["delta"] = {
                                    "reasoning_content": buffer,
                                    "content": ""
                                }
                                yield f"data: {json.dumps(chunk_dict)}\n\n"
                                full_reasoning += buffer
                                buffer = ""
                            break  # 等待更多内容
    else:
        if _srv()._role_param(settings, 'reasoner', 'temperature') !=1:
            reasoner_extra['temperature'] = _srv()._role_param(settings, 'reasoner', 'temperature')

        # 流式调用推理模型
        reasoner_stream = await acreate(
            lambda: reasoner_client.chat.completions.create(
                user="sap-reasoner",  # S191-N2：压缩视图流量标记
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            stop=settings['reasoner']['stop_words'],
            **reasoner_extra
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_stream_reasoner_update")
        full_reasoning = ""
        # 处理推理模型的流式响应
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue

            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                reasoning_content = delta.get("reasoning_content", "")
                if reasoning_content:
                    full_reasoning += reasoning_content
                else:
                    reasoning_content = delta.get("reasoning", "")
                    if reasoning_content:
                        delta['reasoning_content'] = reasoning_content
                        full_reasoning += reasoning_content
                # 移除content字段，确保yield的内容中不包含content
                if 'content' in delta:
                    del delta['content']
            yield f"data: {json.dumps(chunk_dict)}\n\n"

    # 在推理结束后添加完整推理内容到消息
    content_append(request.messages, 'user', f"\n\n可参考的推理过程：{full_reasoning}") # 可参考的推理过程

    _st["vendor"] = vendor


async def _stream_regrab(request, settings, results, images, fastapi_base_url):
    """Post-tool desktop re-grab with action feedback + grid."""
    try:
        import pyautogui
        # 必须从你的工具类中引入设置区域的方法
        from py.computer_use_tool import set_screen_region
                            
        v_settings = settings.get('visionControlSettings', {})
        is_grid_enabled = v_settings.get('isEnableGrid', False)
        is_full_screen = v_settings.get('isFullScreen', True)
        # ScreenSize 格式为 [x, y, width, height]
        screen_size = v_settings.get('ScreenSize', [0, 0, 1920, 1080])
        time.sleep(0.5) # 等待一下，确保截图工具已经准备好
        logging.getLogger("app").info(f"正在执行桌面截图 (全屏: {is_full_screen}, 网格: {is_grid_enabled})...")
                            
        # --- 1. 区域判定与捕获 ---
        if not is_full_screen and len(screen_size) == 4:
            # 局部截图模式
            rx, ry, rw, rh = map(int, screen_size)
            # 关键：告诉鼠标工具，接下来的 0-1000 坐标要映射到这个局部矩形
            set_screen_region((rx, ry, rw, rh))
                                
            # 逻辑尺寸即为选区尺寸
            logical_width, logical_height = rw, rh
            # 捕获指定区域
            screenshot = await asyncio.to_thread(pyautogui.screenshot, region=(rx, ry, rw, rh))
        else:
            # 全屏截图模式
            set_screen_region(None) # 恢复全屏映射
            logical_width, logical_height = pyautogui.size()
            screenshot = await asyncio.to_thread(pyautogui.screenshot)
                            
        # --- 2. 强制 Resize 到逻辑坐标系 (解决 Windows 缩放偏移) ---
        if screenshot.width != logical_width or screenshot.height != logical_height:
            screenshot = await asyncio.to_thread(
                screenshot.resize, (logical_width, logical_height), Image.Resampling.LANCZOS
            )
                            
        # 限制传输图片大小，平衡 Token 消耗
        target_w, target_h = scale_to_fit(logical_width, logical_height, 1280, 720)
        if screenshot.width > target_w or screenshot.height > target_h:
            screenshot = await asyncio.to_thread(
                screenshot.resize, (target_w, target_h), Image.Resampling.LANCZOS
            )

        # --- 3. 绘制视觉反馈 (红点/线) ---
        action_feedback_hint = ""
        if results and "[LAST_ACTION:" in str(results):
            screenshot = await asyncio.to_thread(draw_action_feedback, screenshot, str(results))
            action_feedback_hint = (
                " Notice: The colored markers show your PREVIOUS actions relative to this view. "
                "Cyan = Click. Blue = Double Click. Green-Yellow = Drag."
            )

        # --- 4. 绘制网格辅助 ---
        if is_grid_enabled:
            display_image = await asyncio.to_thread(draw_grid_on_image, screenshot.copy(), grid_spacing=10)
            region_text = "partial region" if not is_full_screen else "full desktop"
            grid_hint = f"\n\n【system info】Screenshot of {region_text} with coordinate grid (0-1000) injected. Use coordinates for precise clicking within this view.\n{action_feedback_hint}"
        else:
            display_image = screenshot
            grid_hint = f"\n\n【system info】Current screenshot injected.\n{action_feedback_hint}"
                            
        # --- 5. 保存并注入消息 ---
        desktop_img_name = f"desktop_view_{uuid.uuid4().hex}.png"
        desktop_img_path = os.path.join(UPLOAD_FILES_DIR, desktop_img_name)
        await asyncio.to_thread(display_image.save, desktop_img_path, optimize=True)
                            
        desktop_url = f"{fastapi_base_url}uploaded_files/{desktop_img_name}"
                            
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": '[Getting screenshot]' + grid_hint},
                {"type": "image_url", "image_url": {"url": desktop_url}}
            ]
        }
        request.messages.append(current_user_msg)
                            
        # --- 6. 清理旧截图 ---
        if v_settings.get('onlyNewScreen', False):
            for msg in request.messages[:-1]:
                if isinstance(msg.get('content'), list):
                    msg['content'] = [item for item in msg['content'] if item.get('type') != 'image_url']
                    if len(msg['content']) == 1 and msg['content'][0].get('type') == 'text':
                        msg['content'] = msg['content'][0]['text']
                    elif len(msg['content']) == 0:
                        msg['content'] = ""

    except Exception as e:
        logging.getLogger("app").info(f"后端桌面截图失败: {e}")
                            
    images = await images_in_messages(request.messages, fastapi_base_url)
    request.messages = await message_without_images(request.messages)

    return images


_BROWSER_VISION_TOOLS = {"take_screenshot", "view_images"}  # S228 截图 / S243 一手直看，结果含可注入 URL


def _collect_new_vision_requests(messages):
    """S243：本轮新产生、尚未注入过的 (url, 来源工具) 列表。
    以「最近一条真实 user 消息」为本轮下界（排除历史轮），再以「最近一条 browser_vision 标记」
    为本轮内已注入界，避免跨轮/同轮多轮重复注入。view_images 结果可含空格分隔的多图 URL。"""
    turn_start = 0
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") == "user" and m.get("name") not in ("browser_vision", "system_note"):
            turn_start = i
            break
    last = turn_start
    for i in range(len(messages) - 1, turn_start, -1):
        m = messages[i]
        if m.get("role") == "user" and m.get("name") == "browser_vision":
            last = i
            break
    out = []
    for i in range(last + 1, len(messages)):
        m = messages[i]
        if m.get("role") == "tool" and m.get("name") in _BROWSER_VISION_TOOLS:
            c = m.get("content")
            if isinstance(c, str):
                for u in re.findall(r"https?://\S+", c):
                    u = u.rstrip("\"'(),;，。；>")
                    if 'uploaded_files' in u or 'tool_temp' in u or re.search(
                            r"\.(?:png|jpe?g|gif|webp|bmp)(?:\?|$)", u, re.I):
                        out.append((u, m.get("name")))
    return out


def _collect_new_browser_screenshots(messages):
    """S228：本轮 take_screenshot 新截、且尚未注入过的浏览器画面 URL。"""
    return [u for u, _src in _collect_new_vision_requests(messages)]


async def _maybe_inject_browser_vision(request, settings, images, fastapi_base_url):
    """S228/S243：把本轮 take_screenshot 画面或 view_images 请求的图片作为图像直注本次模型调用——
    unifiedModel/视觉原生时主模型一手读像素，配独立 vision 时由既有路由自动转描述（均免手动
    转述工具）。与桌面 _stream_regrab 同管线，但只定向注入新图（不全局剥离历史图，回归安全）。"""
    try:
        reqs = _collect_new_vision_requests(request.messages)
    except Exception:
        reqs = []
    if not reqs:
        return images
    reqs = reqs[:3]
    inj0 = len(request.messages)
    for u, _src in reqs:
        _txt = ("[Browser screenshot] 内置浏览器截图的实际画面，请据图判断。" if _src == "take_screenshot" else
                "[First-hand image] 这是你用 view_images 请求亲自查看的图片，原图像素已附上，"
                "请直接看图并据此作答，无需再调用 secondhand_* 转述工具。")
        request.messages.append({
            "role": "user",
            "name": "browser_vision",
            "content": [
                {"type": "text", "text": _txt},
                {"type": "image_url", "image_url": {"url": u}},
            ],
        })
    try:
        new_imgs = await images_in_messages(request.messages[inj0:], fastapi_base_url)
        for e in new_imgs:
            e["index"] = e["index"] + inj0
    except Exception as _bv_e:
        # S245: 转换失败=整段回滚，绝不把带裸 http url 的注入消息留给请求体
        # （本地推理服务器不拉远程图，残留必 400 炸整轮；18:16 实证）
        del request.messages[inj0:]
        logging.getLogger("app").info("[S228] 浏览器截图注入失败，已回滚: %r", _bv_e)
        return images
    # S245 二线：漏网的「url 仍为 http / base64 为空」注入行（内部文件被删/0字节等）整行剔除
    # S252: 新增毒字节判定——base64 有效但非图像魔数（HTML 伪装图实证会引擎 400 炸整轮），
    # 此类不删行而是改写为纯文本注记，让模型知情（否则静默丢图模型会瞎猜）
    import base64 as _b64s
    bad, poisoned = [], []
    for off in range(len(request.messages) - inj0):
        m = request.messages[inj0 + off]
        if isinstance(m.get("content"), list):
            for it in m["content"]:
                if isinstance(it, dict) and it.get("type") in ("image_url", "video_url"):
                    uu = (it.get(it["type"]) or {}).get("url") or ""
                    if uu.startswith("http") or (uu.startswith("data:") and not uu.split("base64,", 1)[-1]):
                        bad.append(off)
                        break
                    b64p = uu.split("base64,", 1)[-1] if uu.startswith("data:") else ""
                    if b64p:
                        try:
                            _h = _b64s.b64decode(b64p[:32])
                        except Exception:
                            _h = b""
                        if not _image_magic_ok(_h):
                            poisoned.append(off)
                            break
    for off in poisoned:
        request.messages[inj0 + off]["content"] = [{"type": "text", "text":
            "[vision dropped] 登记的图片字节无效（非图像魔数，常见为防盗链/反爬 HTML 伪装成图片），已被框架剔除以保护本轮。"
            "如仍需该图：用 new_page 打开原始页面 + wait_for 等待渲染后 take_screenshot 查看，或换图片来源；勿反复重试同一 URL。"}]
        logging.getLogger("app").info("[S252] 注入图像魔数无效，已剔图留注记 (msg %d)", inj0 + off)
    if bad or poisoned:
        drop_entries = set(bad) | set(poisoned)
        kept = []
        for e in new_imgs:
            off = e["index"] - inj0
            if off in drop_entries:
                continue
            # 位移只算删行（bad）；poisoned 行仍在 messages 原位（已改纯文本）
            e["index"] = inj0 + off - sum(1 for b in bad if b < off)
            kept.append(e)
        new_imgs = kept
        for off in sorted(bad, reverse=True):
            del request.messages[inj0 + off]
        logging.getLogger("app").info("[S245/S252] 注入剔除 bad=%d 行 poisoned=%d 图", len(bad), len(poisoned))
    for m in request.messages[inj0:]:
        if isinstance(m.get("content"), list):
            m["content"] = next((it["text"] for it in m["content"] if it.get("type") == "text"), "")
    return (images or []) + new_imgs


async def _stream_loop_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count2):
    """While-loop LLM re-request chunk stream (slot merge + think tags)."""
    _st["tcg_emit"], _st["tcg_cut"] = len(full_content or ""), -1  # S183 显示拦截基线
    async for chunk in response:
        if not chunk.choices:
            if getattr(chunk, "usage", None):
                usage_info = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else dict(chunk.usage)
                _ctx_peak = max(_ctx_peak, usage_info.get("prompt_tokens") or 0)
            continue
        _chunk_count2 += 1
        if _chunk_count2 % 5 == 0:
            await asyncio.sleep(0)  # 定期让出控制权，防止事件循环饥饿导致1006断开
        if chunk.choices:
            choice = chunk.choices[0]
            if choice.delta is None:  # B1(1775d8d3): 末包 delta:null 兼容
                continue
            if hasattr(choice.delta, "audio") and choice.delta.audio:
                # 只把 Base64 音频数据留在 delta 里，别动它
                yield f"data: {chunk.model_dump_json()}\n\n"
                continue
            if choice.delta.tool_calls:  # function_calling
                current_tool, _frag = None, ""
                for tool in choice.delta.tool_calls:
                    current_tool, _frag = _merge_tool_delta(tool_calls, tool)
                _idx = tool_calls.index(current_tool)
                if current_tool.function and current_tool.function.name:
                    progress_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_progress": {  # 新增字段，区别于最终的 tool_content
                                    "name": current_tool.function.name,
                                    # S85-A：本帧只下发增量片段（incremental=true），
                                    # 旧实现每帧下发全量累积串 → 前端拼接 O(n²) 膨胀
                                    "arguments": _frag,
                                    "incremental": True,
                                    "index": _idx,
                                    "id": current_tool.id or f"call_{_idx}"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(progress_chunk)}\n\n"
            else:
                # 创建原始chunk的拷贝
                chunk_dict = chunk.model_dump()
                delta = chunk_dict["choices"][0]["delta"]
                                
                # 初始化必要字段
                delta.setdefault("content", "")
                delta.setdefault("reasoning_content", "")

                # 优先处理 reasoning_content
                if delta["reasoning_content"]:
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                    continue
                if delta.get("reasoning", ""):
                    delta["reasoning_content"] = delta["reasoning"]
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                    continue
                # 处理内容
                current_content = delta["content"]
                buffer = current_content
                                
                while buffer:
                    if not in_reasoning:
                        # 寻找开始标签
                        start_pos = buffer.find(open_tag)
                        if start_pos != -1:
                            # 处理开始标签前的内容
                            content_buffer.append(buffer[:start_pos])
                            buffer = buffer[start_pos+len(open_tag):]
                            in_reasoning = True
                        else:
                            content_buffer.append(buffer)
                            buffer = ""
                    else:
                        # 寻找结束标签
                        end_pos = buffer.find(close_tag)
                        if end_pos != -1:
                            # 处理思考内容
                            reasoning_buffer.append(buffer[:end_pos])
                            buffer = buffer[end_pos+len(close_tag):]
                            in_reasoning = False
                        else:
                            reasoning_buffer.append(buffer)
                            buffer = ""
                                
                # 构造新的delta内容
                new_content = "".join(content_buffer)
                new_reasoning = "".join(reasoning_buffer)
                                
                # 更新chunk内容
                # S183: 流内显示拦截（与 first_pass 同构，full_content 累积原文）
                _tcg_show, _st["tcg_emit"], _st["tcg_cut"] = _tcg_display_slice(
                    full_content, new_content, _st.get("tcg_emit", 0), _st.get("tcg_cut", -1))
                delta["content"] = _tcg_show.strip("\x00")  # 保留未完成内容
                delta["reasoning_content"] = new_reasoning.strip("\x00") or None
                                
                # 重置缓冲区但保留未完成部分
                if in_reasoning:
                    content_buffer = [new_content.split(open_tag)[-1]] 
                else:
                    content_buffer = []
                reasoning_buffer = []
                                
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                full_content += new_content.strip("\x00")  # S183: 累积原文（非显示截断文）

    _st["usage_info"] = usage_info
    _st["_ctx_peak"] = _ctx_peak
    _st["full_content"] = full_content
    _st["in_reasoning"] = in_reasoning
    _st["content_buffer"] = content_buffer
    _st["reasoning_buffer"] = reasoning_buffer
    _st["_chunk_count2"] = _chunk_count2


async def _stream_drs_loop_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
    """While-loop deep-research status machine (stream SSE notices)."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content)
    response = await acreate(
        lambda: client.chat.completions.create(
        model=model,
        messages=[                        
            {
            "role": "system",
            "content": source_prompt,
            },
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        extra_body = extra_params, # 其他参数
    ), attempts=2, base_delay=1.0, label="s207-_stream_drs_loop_round")
    response_content = response.choices[0].message.content
    if response_content is None:
        response_content = ""
    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    try:
        response_content = json.loads(response_content)
    except json.JSONDecodeError:
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❌{await _srv().t('task_error')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
    if response_content["status"] == "done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"✅{await _srv().t('task_done')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❎{await _srv().t('task_not_done')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
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
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❓{await _srv().t('task_need_more_info')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await _srv().t('enter_search_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
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
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await _srv().t('need_more_work')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
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
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"⭐{await _srv().t('enter_answer_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": _tcg_neutralize(full_content),  # S183: 泄漏块不落历史
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )

    _st["drs"] = DRS_STAGE
    _st["snot"] = search_not_done
    _st["stask"] = search_task


async def _stream_usage_event(request, settings, usage_info, _ctx_peak, tools):
    """context_usage SSE event generation + log line. (M-3 split)"""
    try:
        from py.context_manager import get_context_settings as _gcs, estimate_tokens as _esttok
        _cm_u = _gcs(settings)
        _usage_evt = {
            "type": "context_usage",
            "prompt_tokens": (usage_info or {}).get("prompt_tokens"),
            "completion_tokens": (usage_info or {}).get("completion_tokens"),
            "peak_prompt_tokens": _ctx_peak or None,
            "window": _cm_u["context_window"],
            "budget": int(_cm_u["context_window"] * _cm_u["compact_ratio"]),
            "est_total": _esttok(request.messages, tools),
            "breakdown": _breakdown_tokens(request.messages, tools),
            # S191-N2：标注本轮是否另有 reasoner 压缩视图流量（引擎历史读数的
            # 锯齿多来自双通道交错，此字段供前端/排障甄别）
            "reasoner_enabled": bool(settings.get("reasoner", {}).get("enabled")),
            "reasoner_model": settings.get("reasoner", {}).get("model", "") if settings.get("reasoner", {}).get("enabled") else "",
        }
        yield f"data: {json.dumps(_usage_evt, ensure_ascii=False)}\n\n"
        logging.getLogger("app").info(f"[Context] usage: prompt={_usage_evt['prompt_tokens']} peak={_usage_evt['peak_prompt_tokens']} est_total={_usage_evt['est_total']} window={_usage_evt['window']}")
    except Exception as _ue:
        logging.getLogger("app").info(f"[Context] usage 事件生成异常（跳过）: {_ue}")


async def _stream_finalize_jobs(request, settings, full_content, user_prompt, m0, memoryId, cur_memory):
    """turn-log shadow append + affection extraction + mem0 submit job."""
    try:
        from py.turn_log import shadow_append as _shadow_append
        await _shadow_append(request.conversation_id, request.messages, log=print)
    except Exception as _tle:
        logging.getLogger("app").info(f"[TurnLog] stream shadow skip: {_tle}")
    if settings.get('loveSettings', {}).get('enabled', False) and not request.is_sub_agent:
        try:
            from py.affection_system import extract_and_update_affection
            # full_content 是当前轮次 AI 的完整回复文本
            await extract_and_update_affection(full_content)
        except Exception as e:
            logging.getLogger("app").info(f"解析好感度标签出错: {e}")
    # ========== 对话缓冲：记录助手回复用于闲时自动总结 ==========
    try:
        diary_settings_inner = (settings.get("diarySettings", {}) or {})
        if diary_settings_inner.get("enabled", False) and diary_settings_inner.get("chatSummary", {}).get("enabled", True) and not request.is_quarantined \
                and getattr(request, "platform", "") != "diary":  # S231：日记自调用(含校对 pass)不回灌对话摘要缓冲，防自证回路
            ms = (settings or {}).get("memorySettings", {}) or {}
            buffer_key = ms.get("selectedMemory") or DIARY_DEFAULT_BOOK
            if full_content:
                append_to_chat_buffer(buffer_key, "assistant", _neutralize(full_content, store="diary-buffer"))
    except Exception as e:
        logging.getLogger("app").info(f"[DiaryBuffer] 记录助手回复失败: {e}")
    if m0 and not request.is_sub_agent and not request.is_quarantined and getattr(request, "platform", "") != "diary":  # S172: 日记自调用跳过记忆检索
        logging.getLogger("app").info("记忆更新任务开始提交")
        # S231：结构化传角色（user/assistant 各自 sanitize），不再压平成单条 user 文本——
        # 压平会让 mem0 把「你说」段当用户话语提取，造成记忆角色漂移/反转。
        messages = [
            {"role": "user", "content": _neutralize(user_prompt or "", store="mem0-add")},
            {"role": "assistant", "content": _neutralize(full_content or "", store="mem0-add")},
        ]
        infer = cur_memory.get('infer', False) or False
        _m0_job = m0
        _mid = memoryId
        _job_msgs = messages

        def _mem_job():
            metadata = {
                "timetamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _m0_job.add(_job_msgs, user_id=_mid, metadata=metadata, infer=infer)

        llm_gate.submit_memory_job(
            _mid, _mem_job, name="mem0-add",
            debounce=float((settings.get('llmGuardSettings') or {}).get('debounceSeconds', 20) or 0)
                     if (settings.get('llmGuardSettings') or {}).get('enabled', True) else 0.0,
            wait_idle=(settings.get('llmGuardSettings') or {}).get('enabled', True))
        logging.getLogger("app").info("记忆更新任务已提交到后台线程")


def _append_loopcap_hint(request, tag):
    """S78(B2-2/T-8 单点): 工具迭代上限后的收尾提示——强制模型基于已有
    工作向用户总结（流式与非流式共用）。"""
    logging.getLogger("app").info(f"[LoopCap] {tag}工具调用迭代上限已达，强制模型收尾")
    request.messages.append({
        "role": "user",
        "content": "[系统提示] 你已达到本轮工具调用迭代上限，工具已不可用。请基于已完成的工作向用户总结当前进展与剩余步骤。",
    })


def _drs_round_cap(loop_count, max_iters, search_not_done, tool_calls, tag):
    """S78(B2-2 16f079d4 fork 侧补强): 纯深度研究轮（无 tool_calls）也须有
    出口。返回 False=轮数超限且非可收尾工具轮，调用方应结束循环。"""
    if loop_count <= max_iters:
        return True
    if tool_calls and not search_not_done:
        return True  # 纯工具轮交给迭代上限收尾提示路径
    logging.getLogger("app").info(f"[LoopCap] {tag}迭代上限({max_iters})已达，强制结束循环")
    return False


SAFETY_REPLACEMENT_TEXT = "[该回复已被内容安全策略自动替换]"


async def _stream_final_guard(_st, content_buffer, reasoning_buffer, settings):
    """S120(上游 guard 族)：流式终态前置——残留 buffer flush + 内容安全整体替换
    （S68 双 pass 共用；产出 SSE 帧，_st["fc"] 回写最终 full_content）。"""
    full_content = _st["fc"]
    if content_buffer or reasoning_buffer:
        final_chunk = {
            "choices": [{
                "delta": {
                    "content": "".join(content_buffer),
                    "reasoning_content": "".join(reasoning_buffer)
                }
            }]
        }
        yield f"data: {json.dumps(final_chunk)}\n\n"
        full_content += final_chunk["choices"][0]["delta"].get("content", "")
    if settings.get("systemSettings", {}).get("contentSafety", False) and full_content:
        is_safe, matched = await check_content_safety(full_content, min_cjk_chars=3)
        if not is_safe:
            logging.getLogger("app").warning(f"[content_safety] output blocked words: {matched}")
            correction = {"choices": [{"delta": {"content": SAFETY_REPLACEMENT_TEXT, "_safety_filtered": True}}]}
            yield f"data: {json.dumps(correction)}\n\n"
            full_content = SAFETY_REPLACEMENT_TEXT
    _st["fc"] = full_content
