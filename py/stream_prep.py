# -*- coding: utf-8 -*-
"""S302a：流式请求准备域（DRS 阶段文案/工具参数解析/事件 chunk/
审批-闸门-锚点注入/上下文管线/采集与前置阶段），自 server.py 逐字搬移。

纯移动批；文档化改写=_srv() 懒访问（t=翻译函数/_srv().async_tools(+lock)=运行态注册表/
_role_param=参数解析，原语义均为 server 模块全局调用期读取，逐点等价）。
logger 无引用（域内统一 logging.getLogger("app")，与 server 同对象）。
"""
import asyncio
import copy
import json
import logging
import os
import uuid
from pathlib import Path

from PIL import Image

from py.ask_flow import is_ask_result as ask_flow_is_ask_result
from py.context_builder import sanitize_tool_chains_logged
from py.get_setting import UPLOAD_FILES_DIR
from py.image_draw import draw_grid_on_image, scale_to_fit
from py.llm_recovery import (acreate, llm_retry_cfg)
from py.msg_utils import content_append
from py.srv_ref import srv as _srv
from py.stream_relay import _st_cancelled
from py.tool_dispatch import _is_approval_result
from py.token_guard import neutralize_deep
from py.vision_tools import (images_add_in_messages)

def get_drs_stage(DRS_STAGE):
    if DRS_STAGE == 1:
        drs_msg = "当前阶段为明确用户需求阶段，你需要分析用户的需求，并给出明确的需求描述。如果用户的需求描述不明确，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。"
    elif DRS_STAGE == 2:
        drs_msg = "当前阶段为工具调用阶段，利用你的知识库、互联网搜索、数据库查询、各类MCP等你所有的工具（如果有，这些工具不一定会提供），执行计划中未完成的步骤。每次完成计划中的一个步骤。在工具调用阶段中，你不要完成最终任务，而是尽可能的调用相关的工具，为最后的回答阶段做准备。"
    elif DRS_STAGE == 3:
        drs_msg = "当前阶段为生成结果阶段，根据当前收集到的所有信息，完成任务，给出任务执行结果。如果用户要求你生成一个超过2000字的回答，你可以尝试将该任务拆分成多个部分，每次只完成其中一个部分。"
    else:
        drs_msg = "当前阶段为生成结果阶段，根据当前收集到的所有信息，完成任务，给出任务执行结果。如果用户要求你生成一个超过2000字的回答，你可以尝试将该任务拆分成多个部分，每次只完成其中一个部分。"
    return drs_msg  


def get_drs_stage_name(DRS_STAGE):
    if DRS_STAGE == 1:
        drs_stage_name = "明确用户需求阶段"
    elif DRS_STAGE == 2:
        drs_stage_name = "工具调用阶段"
    elif DRS_STAGE == 3:
        drs_stage_name = "生成结果阶段"
    else:
        drs_stage_name = "生成结果阶段"
    return drs_stage_name


def get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content):
    drs_stage_name = get_drs_stage_name(DRS_STAGE)
    if DRS_STAGE == 1:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 当前阶段，请输出json字符串：

### 如果需要用户明确需求，请输出json字符串（如果你已经在上一轮对话中向用户提出过明确需求，请不要重复使用"need_more_info"，这会导致用户无法快速获取结果）：
{{
    "status": "need_more_info",
    "unfinished_task": ""
}}

### 如果不需要进一步明确需求，进入并进入工具调用阶段，请输出json字符串：
{{
    "status": "need_work",
    "unfinished_task": ""
}}
"""
    elif DRS_STAGE == 2:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 注意！工具调用阶段，是为最后的回答阶段做准备。不需要生成最终的回答，如果已经没有未完成的需要调用工具的步骤，请进入生成结果阶段。

## 当前阶段，请输出json字符串：

### 如果还有计划中的需要调用工具的步骤没有完成，请输出json字符串：
{{
    "status": "need_more_work",
    "unfinished_task": "这里填入未完成的步骤"
}}

### 如果所有计划的需要调用工具的步骤都已完成，进入生成结果阶段，请输出json字符串：
{{
    "status": "answer",
    "unfinished_task": ""
}}
"""    
    else:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 当前阶段，请输出json字符串：

如果初始任务已完成，请输出json字符串：
{{
    "status": "done",
    "unfinished_task": ""
}}

如果初始任务未完成，请输出json字符串：
{{
    "status": "not_done",
    "unfinished_task": "这里填入未完成的任务"
}}
"""    
    return search_prompt


def get_role(m): return m.get("role") if isinstance(m, dict) else m.role


def get_tcs(m): 
    if get_role(m) != "assistant": return None
    return m.get("tool_calls") if isinstance(m, dict) else getattr(m, "tool_calls", None)


_ARG_SHELL_KEYS = ("arguments", "params", "input", "tool_arguments")


def _unwrap_arg_shell(data, depth=3):
    """S85-A：单键壳解包。llama 系本地模型常输出 {"arguments": {...}} 双层包裹
    （内层还可能是字符串化 JSON），直接 **dict 会得到 unexpected keyword 'arguments'。"""
    while depth > 0 and isinstance(data, dict) and len(data) == 1:
        key = next(iter(data)).lower()
        if key not in _ARG_SHELL_KEYS:
            break
        val = data[next(iter(data))]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                break
        if not isinstance(val, dict):
            break
        data, depth = val, depth - 1
    return data


def _merge_tool_delta(tool_calls, tool):
    """S85-A(C-20 扩展)：流式 tool_call delta 槽位合并。返回 (槽对象, 本帧参数片段)。
    槽位定位优先级：协议 tool.index → 既有槽中 id 匹配 → 末槽（无 index 旧模型）。
    修复顺序多 call 无 index 时后一 call 的参数拼进前一 buffer（'}{' 拼接串）。"""
    _slot = getattr(tool, "index", None)
    if _slot is None:
        _slot = None
        tc_id = getattr(tool, "id", None)
        if tc_id:
            for i, ex in enumerate(tool_calls):
                if getattr(ex, "id", None) == tc_id:
                    _slot = i
                    break
            if _slot is None:
                _slot = len(tool_calls)  # 带 id 但无匹配 = 无 index provider 的新调用
            elif (getattr(tool, "function", None)
                  and getattr(tool.function, "name", None)
                  and tool_calls[_slot].function
                  and getattr(tool_calls[_slot].function, "arguments", "")):
                # id 跨轮复用：带 name 且旧槽已有参数 → 新一轮调用，开新槽
                _slot = len(tool_calls)
        if _slot is None:
            _slot = max(len(tool_calls) - 1, 0)  # 无 index 无 id 旧模型：回退末槽
    while len(tool_calls) <= _slot:
        _fill = copy.deepcopy(tool)
        if _fill.function is not None:
            _fill.function.arguments = ""
        tool_calls.append(_fill)
    current = tool_calls[_slot]
    if getattr(tool, "id", None) and not current.id:
        current.id = tool.id
    frag = ""
    if tool.function:
        if tool.function.name and not current.function.name:
            current.function.name = tool.function.name
        if tool.function.arguments:
            current.function.arguments = (current.function.arguments or "") + tool.function.arguments
            frag = tool.function.arguments
    return current, frag


def parse_tool_arguments(raw):
    """解析工具调用参数。返回 (args_dict, error_msg)。
    先直接 JSON 解析（含单键壳解包）；失败则回退 '}{ 拼接拆分，取首个非空片段
    再解壳；仍失败返回错误供模型自愈，不炸流。"""
    raw = (raw or "").strip()
    if not raw:
        return {}, None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _unwrap_arg_shell(data), None
        if isinstance(data, list):
            return _unwrap_arg_shell(data[0] if data and isinstance(data[0], dict) else {}), None
        return {}, None
    except Exception:
        pass
    try:
        data_list = json.loads('[' + raw.replace('}{', '},{') + ']')
        if isinstance(data_list, list):
            for item in data_list:
                if isinstance(item, dict) and item:
                    return _unwrap_arg_shell(item), None
            return {}, None
        return {}, None
    except Exception as e:
        return None, (
            f"Invalid JSON arguments: {e}. "
            "Arguments must be ONE JSON object like {\"path\": \"src/main.py\"} — "
            "double-quoted keys/strings, no trailing commas, no markdown fences, no comments. "
            f"Raw (truncated): {raw[:200]!r}"
        )


def truncate_tool_result(text, limit: int = 32000):
    """纯截断（头 2/3 + 尾 1/3，不落盘）。S184 后仅用于 reasoner 摘要通道；
    agent 历史落账统一走 _bound_tool_output（可恢复截断）。"""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text
    head = int(limit * 2 / 3)
    tail = limit - head
    omitted = len(text) - limit
    return (text[:head]
            + f"\n\n...[结果过长，已截断中间 {omitted} 个字符。如需完整内容请缩小查询范围或写文件后读取]...\n\n"
            + text[-tail:])


def _tcg_display_slice(full_acc, new_content, emitted, cut):
    """S183 流内显示拦截（纯函数）：调用块标记成型后其起始位置起的正文
    不流向展示端；标记未成型时先扣住"疑似标记前缀"尾部待判。
    返回（可见增量, 累计可见长度, 标记位置）。历史落账与 TCG 判定用原文，
    不经此截断。"""
    from py.tool_call_guard import cut_position, partial_tail_len
    cand = full_acc + new_content
    if cut < 0:
        cut = cut_position(cand)
    allow = cut if cut >= 0 else len(cand) - partial_tail_len(cand)
    keep = max(0, allow - emitted)
    show = new_content[:keep]
    return show, emitted + len(show), cut


def _robust_cfg(settings):
    """S183：agentRobustness 设置 -> (再锚间隔轮数 0~50, 塌方返工上限 0~5)。
    0=关闭对应机制；缺省 6/2。"""
    ar = (settings or {}).get("agentRobustness") or {}
    try:
        n = int(ar.get("reanchorEveryToolRounds", 6))
    except (TypeError, ValueError):
        n = 6
    try:
        m = int(ar.get("malformedCallRepairMax", 2))
    except (TypeError, ValueError):
        m = 2
    return max(0, min(50, n)), max(0, min(5, m))


def _tool_notice_chunk(title, content):
    """S183：工具样式提示块 SSE（type=error → UI 错误调用块；
    IM 侧由 ToolProgressLedger 按 progressMode 桥接裁决）。"""
    _chunk = {"choices": [{"delta": {"tool_content": {
        "title": title, "content": content, "type": "error"}}}]}
    return f"data: {json.dumps(_chunk)}\n\n"


def _approval_pending_event_chunk(request):
    """S186：真-pending 活卡宣告（唯一 approval_pending SSE 事件）。
    前端流收尾据此只保留被点名 tool_call_id 的审批卡可操作，其余折叠为
    已失效结果块——asyncTools 期间被模型越过的孤儿哨兵不再可点。"""
    try:
        for _m in reversed(getattr(request, "messages", None) or []):
            _c = _m.get("content") if isinstance(_m, dict) else getattr(_m, "content", None)
            _ap = _is_approval_result(_c)
            if _ap is not None:
                _tid = _m.get("tool_call_id", "") if isinstance(_m, dict) else getattr(_m, "tool_call_id", "")
                _chunk = {"choices": [{"delta": {"approval_pending": {
                    "tool_call_id": _tid, "tool_name": _ap.get("tool_name", "")}}}]}
                return f"data: {json.dumps(_chunk, ensure_ascii=False)}\n\n"
    except Exception:
        return None
    return None


def _ask_pending_event_chunk(request):
    """S195：提问卡活卡宣告（仿 S186 审批版）：前端流收尾据此只保留被点名
    提问卡可操作，其余折叠为已失效——历史里的旧 ask 哨兵不再可点。"""
    try:
        for _m in reversed(getattr(request, "messages", None) or []):
            _c = _m.get("content") if isinstance(_m, dict) else getattr(_m, "content", None)
            _ak = ask_flow_is_ask_result(_c)
            if _ak is not None:
                _tid = _m.get("tool_call_id", "") if isinstance(_m, dict) else getattr(_m, "tool_call_id", "")
                _chunk = {"choices": [{"delta": {"ask_pending": {
                    "tool_call_id": _tid, "ask_id": _ak.get("ask_id", "")}}}]}
                return f"data: {json.dumps(_chunk, ensure_ascii=False)}\n\n"
    except Exception:
        return None
    return None


GATE_MAX = 2  # S183 完成闸门注入上限（固定值，非设置项——用户拍板）


def _gate_note_text(open_items, nth):
    """完成闸门注记（回注模型，name=system_note 元频道）。"""
    ids = ", ".join(f"#{t.get('id')}[{t.get('status', '?')}]" for t in open_items[:8])
    return (f"【完成闸门 {nth}/{GATE_MAX}】todo 列表仍有 {len(open_items)} 项未完成：{ids}。"
            "若确有未做完的步骤：立即继续调用工具执行；若某项实际已完成：现在更新其状态。"
            "本轮回复只针对当前任务，不得复述已回答过的旧话题。")


def _anchor_note_text(todos):
    """S183(T-A) 再锚注记（回注模型，name=system_note 元频道）。"""
    from py.cli_tool import format_todo_snapshot_line
    return ("【系统再锚】当前以工具推进中的任务进度快照：" + (format_todo_snapshot_line(todos) or "(空)")
            + "。纪律：只汇报当前任务；已回答过的旧话题不得复述；"
              "存在 pending/in_progress 项时不得结束回合。")


def _todo_open_items(todos):
    """未完成项（pending/in_progress）；结构异常项忽略。"""
    return [t for t in (todos or [])
            if isinstance(t, dict) and t.get("status") in ("pending", "in_progress")]


async def _stream_anchor_inject(request, settings, _st, pending_abort):
    """S183(T-A)：每 N 个工具轮把 todo 进度与任务纪律重新推到近端。
    仅在 todo 激活、非审批挂起（不得污染批复尾检）、非取消时注入。"""
    _rn = _robust_cfg(settings)[0]
    if not _rn or pending_abort or _st_cancelled(_st):
        return
    _st["anchor_rounds"] = _st.get("anchor_rounds", 0) + 1
    if _st["anchor_rounds"] % _rn != 0:
        return
    try:
        from py.cli_tool import read_todo_snapshot
        _snap_now = await read_todo_snapshot()
    except Exception:
        _snap_now = []
    if _snap_now:
        request.messages.append({
            "role": "user",
            "content": _anchor_note_text(_snap_now),
            "name": "system_note",  # S166：元频道注记
        })


def _ask_channel(request):
    """提问卡挂起的会话键：IM 用 (platform, peer_id)，其余归一为 web+conversation。"""
    if (getattr(request, "is_app_bot", False) and getattr(request, "platform", "")
            and getattr(request, "peer_id", "")):
        return request.platform, request.peer_id
    return "web", str(getattr(request, "conversation_id", None) or "web-default")


async def _ask_tool_handle(request, args_dict, tool_calls, cur_id, state):
    """S194：ask_user_question_tool 在工具轮内的处理——校验+同轮合并，产占位哨兵。
    挂起记录在轮末 _stream_ask_hang 落账（那时快照才含完整 tool 结果链）。"""
    from py import ask_flow
    qs, err = ask_flow.normalize_questions(args_dict)
    if err:
        return err  # 参数不合法：不挂起，模型按错误文本自纠
    if state.get("ask_done"):
        return "（本题已并入本轮提问卡，无需重复发出；等待主人答复后继续。）"
    all_q = list(qs)
    for tc in tool_calls:
        try:
            fn = getattr(tc, "function", None)
            if getattr(fn, "name", "") != ask_flow.ASK_TOOL_NAME:
                continue
            if (getattr(tc, "id", "") or "") == (cur_id or ""):
                continue
            more, err2 = ask_flow.normalize_questions(json.loads(fn.arguments or "{}"))
            if not err2:
                for q in more:
                    if len(all_q) >= ask_flow.MAX_QUESTIONS:
                        break
                    if q not in all_q:
                        all_q.append(q)
        except Exception:
            continue
    state["ask_done"] = True
    state["ask_qs"] = all_q
    return ask_flow.make_sentinel("pending", all_q)


async def _stream_ask_hang(request, _st, state):
    """S194：轮末提问卡挂起登记——快照此刻已含哨兵与补全的 tool 结果对；
    同会话旧提问卡作废旧卡；通知/续跑复用 approval_store 生命周期（kind=ask）。"""
    from py import approval_store, approval_im, ask_flow
    plat, key = _ask_channel(request)
    try:
        old = approval_store.latest_pending_ask(plat, key)
        if old is not None:
            popped, _e = await approval_store.resolve(plat, key, "stop", kind="ask")
            if popped is not None:
                logging.getLogger("app").info("[Ask] 旧提问卡被新提问取代: %s/%s id=%s",
                                              plat, key, old.get("approval_id"))
                asyncio.create_task(approval_store._fire(popped, "stop", "", ""))
        snap = approval_im.strip_system_messages(copy.deepcopy(request.messages))
        await approval_store.create(
            platform=plat, peer_id=key, tool_name=ask_flow.ASK_TOOL_NAME,
            tool_params={"questions": state["ask_qs"]}, messages=snap,
            kind="ask", questions=state["ask_qs"], ttl=ask_flow.ASK_TTL)
        _st["ask_hit"] = True
        logging.getLogger("app").info("[Ask] 提问卡挂起: %s/%s（%d 问）",
                                      plat, key, len(state["ask_qs"]))
    except Exception as e:
        logging.getLogger("app").warning("[Ask] 提问卡挂起登记失败（降级为文本结果）: %r", e)


async def _stream_im_approval_hang(request, _st):
    """S150：IM 渠道审批挂起——快照内部 messages（tool_calls 成对闭合后）登记挂起表，
    由 bot 通知对端斜杠批复并「原位续流」；前端哨兵帧与审批卡流程原样不动。
    （S183-M3：自 _stream_tool_round 抽出，行为不变。）"""
    try:
        from py import approval_im, approval_store
        _ap = _is_approval_result(_st.get("results"))
        if _ap and approval_store.has_handlers(request.platform):
            _hit_id = ""
            for _m in reversed(request.messages):
                if _m.get("role") == "tool" and _is_approval_result(_m.get("content")) is not None:
                    _hit_id = _m.get("tool_call_id", "")
                    break
            await approval_store.create(
                platform=request.platform, peer_id=request.peer_id,
                tool_name=_ap.get("tool_name", ""), tool_params=_ap.get("tool_params"),
                tool_call_id=_hit_id, permission_mode=_ap.get("permission_mode", ""),
                cwd=_ap.get("cwd", ""),
                messages=approval_im.strip_system_messages(copy.deepcopy(request.messages)))
    except Exception as _ape:
        logging.getLogger("app").warning("[Approval] 挂起审批登记失败（降级为仅前端流程）: %r", _ape)


async def _stream_gate_check(_st, tools_now):
    """S183(T-C) 完成闸门判定（M3：纯决策，注记/放行由调用方执行）。
    返回 ("pass"|"block"|"exhaust", payload)。放行条件：无声明工具、todo 空、
    无未完成项、或本轮既未用 todo 也无 in_progress 佐证。"""
    if not tools_now or _st_cancelled(_st):
        return "pass", None
    from py.cli_tool import read_todo_snapshot
    try:
        open_items = _todo_open_items(await read_todo_snapshot())
    except Exception:
        return "pass", None
    if not open_items or not (any(_t.get("status") == "in_progress" for _t in open_items)
                              or _st.get("turn_used_todo")):
        return "pass", None
    if _st.get("ask_hit"):
        # S194：本轮已挂起提问卡——todo 未开是「等主人拍板」的合法暂停态，结构放行
        logging.getLogger("app").info("[Gate] 提问卡挂起中，完成闸门结构放行")
        return "pass", None
    nth = _st.get("gate_retries", 0) + 1
    if nth > GATE_MAX:
        return "exhaust", open_items
    _st["gate_retries"] = nth
    return "block", _gate_note_text(open_items, nth)


def _stream_first_round_leak_note(_st, request, tools, full_content):
    """S213：首轮正文泄漏工具调用（还没进过工具循环）→通知体+自纠注记+预算记账。
    注入时返回通知 chunk（调用方 yield 并做自纠重入），否则 None。"""
    from py.tool_call_guard import (build_correction_message,
                                    declared_tool_names, detect_leaked_calls)
    _fl, _fd = detect_leaked_calls(full_content), declared_tool_names(tools)
    if not (_fl and _fd) or _st_cancelled(_st):
        return None
    request.messages.append({"role": "user", "content": build_correction_message(_fl, _fd),
                             "name": "system_note"})
    _st["tcg_retries"] = _st.get("tcg_retries", 0) + 1
    logging.getLogger("app").info("[TCG] 首轮正文泄漏未声明工具调用，自纠重入: %s", _fl)
    return _tool_notice_chunk(
        "⚠️ 畸形工具调用（已拦截，未执行）",
        "模型把调用块以纯文本写入正文：%s。已要求改用结构化调用重发。" % ", ".join(map(str, _fl[:6])))


RESUME_NUDGE_TEXT = (
    "【系统提示】上面的工具结果已收到。工具的“成功”仅代表这一处操作完成，"
    "不代表用户的原始任务已全部完成。如果任务仍有未完成的步骤（继续修改、读回验证、运行测试等），"
    "请立即继续调用工具执行；只有在确认全部完成并验证后，才向用户做最终总结。"
)


def append_resume_nudge(messages):
    """恢复续跑 nudge：当请求历史以 tool 结果结尾（审批通过后手动执行工具再恢复的典型场景）时，
    追加一条“继续推进”指令，防止模型把成功的工具结果当成最终报告直接收尾。

    S307(F3)：nudge 合并进尾部 tool 结果文本，不再新增 user 角色消息——
    df2f8248 事故中链内仅剩的 user-role 注入被模型当成用户发言。
    tool content 非字符串（多模态等罕见形态）时退回旧的元频道注记。"""
    if messages and get_role(messages[-1]) == "tool":
        last = messages[-1]
        c = last.get("content") if isinstance(last, dict) else getattr(last, "content", None)
        if isinstance(c, str):
            if RESUME_NUDGE_TEXT not in c:
                new_c = c + "\n\n" + RESUME_NUDGE_TEXT
                if isinstance(last, dict):
                    last["content"] = new_c
                else:
                    last.content = new_c
        else:
            messages.append({"role": "user", "content": RESUME_NUDGE_TEXT, "name": "system_note"})  # S166：元频道注记，不进前端时间线/m
    return messages


def ensure_thinking_fields(messages):
    """
    为所有 assistant 消息强制添加 reasoning_content: ""（空字符串）
    """
    if not messages:
        return messages
    
    for msg in messages:
        role = get_role(msg)
        
        if role == "assistant":
            # 处理字典格式
            if isinstance(msg, dict):
                # 强制设置为空字符串
                msg["reasoning_content"] = ""
            
            # 处理对象格式
            else:
                setattr(msg, "reasoning_content", "")
    
    return messages


def _cm_context_enabled(settings: dict) -> bool:
    from py.context_manager import get_context_settings
    try:
        return bool(get_context_settings(settings)["enabled"])
    except Exception:
        return False


def _write_context_state(settings: dict, request, res: dict):
    """L3: 把压缩产生的结构化摘要落盘为任务检查点（按会话）"""
    try:
        cwd = settings.get("CLISettings", {}).get("cc_path")
        if not cwd or not Path(cwd).exists():
            return
        state_dir = Path(cwd) / ".agent"
        state_dir.mkdir(parents=True, exist_ok=True)
        import time as _time
        data = {
            "conversation_id": request.conversation_id,
            "updated_at": int(_time.time()),
            "task_mode": res.get("task_mode"),
            "summary": (res.get("summary") or "")[:6000],
        }
        (state_dir / "context_state.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.getLogger("app").info("[Context] 任务检查点已写入 .agent/context_state.json")
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 检查点写入失败: {e}")


async def _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools=None):
    """上下文管线：L1 工具结果修剪 -> L2 自动摘要（仅 agent 模式）。
    执行了 L2 时返回 context_compact 事件 dict（供前端落账），否则 None。"""
    try:
        from py.context_manager import (get_context_settings, estimate_tokens, prune_tool_results,
                                        compact_messages, detect_task_mode)
        cm = get_context_settings(settings)
        if not cm["enabled"]:
            return None
        budget = int(cm["context_window"] * cm["compact_ratio"])
        est = estimate_tokens(request.messages, tools)
        if est <= budget:
            return None
        request.messages, pruned_n = prune_tool_results(request.messages, cm["keep_recent_tools"], cm["tool_output_budget"])
        est2 = estimate_tokens(request.messages, tools)
        logging.getLogger("app").info(f"[Context] L1 修剪旧工具结果 {pruned_n} 条: est {est} -> {est2} (budget {budget})")
        if est2 <= budget:
            return None
        mode = detect_task_mode(request.messages)
        if not (mode == "agent" and cm["auto_agent_compact"]):
            logging.getLogger("app").info(f"[Context] 超预算但模式={mode}，仅修剪不摘要")
            return None
        r_cli = reasoner_client if settings.get("reasoner", {}).get("enabled") else None
        r_model = settings["reasoner"]["model"] if r_cli else None
        res = await compact_messages(client, model, request.messages, task_mode="agent",
                                     keep_recent_dialog=cm["keep_recent_dialog"],
                                     extra_params=extra_params,
                                     reasoner_client=r_cli, reasoner_model=r_model)
        if not res:
            return None
        request.messages = res["messages"]
        _write_context_state(settings, request, res)
        logging.getLogger("app").info(f"[Context] L2 自动摘要完成，压缩 {res['compacted_count']} 条消息")
        return {"type": "context_compact", "reason": "auto", "summary": res["summary"],
                "task_mode": res["task_mode"], "compacted_count": res["compacted_count"]}
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 上下文管线异常（跳过）: {e}")
        return None


def _boundary_l1_recheck(request, settings, tools=None):
    """S192（对齐 opencode compaction 轮边界复查）：工具轮边界复查预算，超限
    仅做 L1 修剪（L2 摘要仍只在 turn 入口，避免打断进行中的工具链）。"""
    try:
        from py.context_manager import (get_context_settings, estimate_tokens,
                                        prune_tool_results)
        cm = get_context_settings(settings)
        if not cm["enabled"]:
            return 0
        budget = int(cm["context_window"] * cm["compact_ratio"])
        est = estimate_tokens(request.messages, tools)
        if est <= budget:
            return 0
        request.messages, n = prune_tool_results(
            request.messages, cm["keep_recent_tools"], cm["tool_output_budget"])
        if n:
            logging.getLogger("app").info(
                f"[Context] L1 轮边界复查: 修剪 {n} 条 est {est} -> "
                f"{estimate_tokens(request.messages, tools)} (budget {budget})")
        return n
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 轮边界复查异常（跳过）: {e}")
        return 0


def _bound_tool_output(result, settings):
    """S184：工具输出落历史单一入口（替代旧 15000 字符盲切）。
    限额内原样返回（幂等）；超限全文落盘 <工作区>/.agent/tool_output/ 并回
    头尾预览 + 真实路径 marker，模型可用 search_files_local /
    read_file_range_local 无损续查——对齐 opencode ToolOutputStore。"""
    from py.tool_output_store import bound_output
    try:
        cwd = (settings or {}).get("CLISettings", {}).get("cc_path") or ""
    except Exception:
        cwd = ""
    text = result if isinstance(result, str) else str(result)
    out = bound_output(text, cwd, settings)
    if out is not text:
        logging.getLogger("app").info("[Context] 工具输出超限已落盘预览: %d -> %d 字符", len(text), len(out))
    # S244: 落历史前剥离孤立代理项——脏源含页面截断残留与本地推理引擎 CESU-8
    # 破碎代理对输出；带病进 messages 会让后续请求 json 序列化整轮炸。
    return out.encode("utf-8", "ignore").decode("utf-8")


async def _bound_tool_output_async(result):
    """无 settings 上下文时的变体（异步工具回注等）。"""
    from py.get_setting import load_settings
    return _bound_tool_output(result, await load_settings())


def _apply_ctx_guardrail(extra, messages, settings):
    """防 Strata 400：max_tokens 不得超过 window - prompt估算 - 512。"""
    try:
        from py.context_manager import get_context_settings, estimate_tokens
        window = get_context_settings(settings)["context_window"]
        est = estimate_tokens(messages)
        mt = extra.get('max_completion_tokens') or extra.get('max_tokens')
        if mt:
            guard = window - est - 512
            if mt > guard:
                key = 'max_completion_tokens' if 'max_completion_tokens' in extra else 'max_tokens'
                extra = dict(extra)
                extra[key] = max(512, guard)
                logging.getLogger("app").info(f"[Context] 护栏: max_tokens {mt} -> {extra[key]} (估算 prompt {est}, window {window})")
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 护栏检查异常（跳过）: {e}")
    return extra


def _breakdown_tokens(messages, tools=None):
    """上下文分段估算：system/历史user/历史assistant/工具结果/tools schema/本轮user。"""
    from py.context_manager import estimate_text_tokens
    seg = {"system": 0, "history_user": 0, "history_assistant": 0,
           "tool_results": 0, "tools_schema": 0, "current_user": 0}
    try:
        import json as _json
        role_of = lambda m: (m.get('role') if isinstance(m, dict) else getattr(m, 'role', None))
        last_user = max((i for i, m in enumerate(messages) if role_of(m) == 'user'), default=-1)
        for i, m in enumerate(messages):
            role = role_of(m)
            if role is None:
                continue
            c = m.get('content') if isinstance(m, dict) else getattr(m, 'content', None)
            t = estimate_text_tokens(c if isinstance(c, str) else _json.dumps(c or "", ensure_ascii=False))
            for tc in (m.get('tool_calls') or [] if isinstance(m, dict) else []):
                fn = tc.get('function') or {}
                t += estimate_text_tokens(str(fn.get('name', '')) + str(fn.get('arguments', '')))
            if role == 'system':
                seg["system"] += t
            elif role == 'user':
                seg["current_user" if i == last_user else "history_user"] += t
            elif role == 'tool':
                seg["tool_results"] += t
            elif role == 'assistant':
                seg["history_assistant"] += t
        if tools:
            seg["tools_schema"] = estimate_text_tokens(_json.dumps(tools, ensure_ascii=False)) // 2
    except Exception:
        pass
    return seg


async def _stream_desktop_capture(request, settings, vision_cfg, vision_control_enabled, user_prompt, fastapi_base_url):
    """Desktop-vision wake/vision-control capture pipeline + injection. (M-3 split)"""
    should_capture = False
    if vision_control_enabled and settings.get('visionControlSettings', {}).get('desktopVision', False):
        should_capture = True
    elif vision_cfg.get('desktopVision'):
        # 检查唤醒词
        if vision_cfg.get('enableWakeWord'):
            wake_words = [w.strip() for w in vision_cfg.get('wakeWord', "").split('\n') if w.strip()]
            if any(word in user_prompt for word in wake_words):
                should_capture = True
        else:
            # 未开启唤醒词则默认每次捕获（或根据需求调整）
            should_capture = True
        
    if should_capture:
        try:
            import pyautogui
            # 引入我们刚才写的设置区域的方法
            from py.computer_use_tool import set_screen_region
                
            # 获取配置
            v_settings = settings.get('visionControlSettings', {})
            is_full_screen = v_settings.get('isFullScreen', True)
            screen_size = v_settings.get('ScreenSize', [0, 0, 1280, 720])
            is_grid_enabled = vision_control_enabled and v_settings.get('isEnableGrid', False)

            logging.getLogger("app").info(f"正在执行桌面截图 (全屏: {is_full_screen}, 网格: {is_grid_enabled})...")
                
            # 1. 根据全屏配置决定截取范围，并同步给鼠标工具
            if not is_full_screen and len(screen_size) == 4:
                x, y, w, h = map(int, screen_size)
                # 截取指定区域
                screenshot = await asyncio.to_thread(pyautogui.screenshot, region=(x, y, w, h))
                logical_width, logical_height = w, h
                # 通知计算机工具，接下来的鼠标操作要基于这个区域
                set_screen_region((x, y, w, h))
            else:
                # 全屏截图
                logical_width, logical_height = pyautogui.size()
                screenshot = await asyncio.to_thread(pyautogui.screenshot)
                # 恢复全屏鼠标映射
                set_screen_region(None)
                
            # 2. 统一缩放到逻辑坐标系 (解决 Windows DPI 缩放偏移)
            if screenshot.width != logical_width or screenshot.height != logical_height:
                screenshot = await asyncio.to_thread(
                    screenshot.resize, (logical_width, logical_height), Image.Resampling.LANCZOS
                )
                
            # 3. 缩放到传输尺寸 (1280x720 左右，平衡清晰度与 Token 消耗)
            target_w, target_h = scale_to_fit(logical_width, logical_height, 1280, 720)
                
            if screenshot.width > target_w or screenshot.height > target_h:
                logging.getLogger("app").info(f"检测到高分辨率屏幕，正在从 {screenshot.size} 缩放到 {(target_w, target_h)}")
                screenshot = await asyncio.to_thread(
                    screenshot.resize, (target_w, target_h), Image.Resampling.LANCZOS
                )

            # 4. 根据设置决定是否绘制网格
            if is_grid_enabled:
                # 在副本上绘制网格
                display_image = await asyncio.to_thread(draw_grid_on_image, screenshot.copy(), grid_spacing=10)
                if not is_full_screen:
                    grid_hint = "\n\n【system info】Current partial screen region screenshot with coordinate grid (0-1000) is injected. Use coordinates for precise clicking."
                else:
                    grid_hint = "\n\n【system info】Current desktop screenshot with coordinate grid (0-1000) is injected. Use coordinates for precise clicking."
            else:
                display_image = screenshot
                grid_hint = "\n\n【system info】Current desktop screenshot is injected."

            # 5. 保存图片
            file_prefix = "desktop_grid" if is_grid_enabled else "desktop_plain"
            desktop_img_name = f"{file_prefix}_{uuid.uuid4().hex}.png"
            desktop_img_path = os.path.join(UPLOAD_FILES_DIR, desktop_img_name)
                
            await asyncio.to_thread(display_image.save, desktop_img_path, optimize=True)
            desktop_url = f"{fastapi_base_url}uploaded_files/{desktop_img_name}"
                
            # 6. 注入到当前消息
            current_user_msg = request.messages[-1]
            if isinstance(current_user_msg['content'], str):
                original_text = current_user_msg['content']
                current_user_msg['content'] = [
                    {"type": "text", "text": original_text + grid_hint},
                    {"type": "image_url", "image_url": {"url": desktop_url}}
                ]
            elif isinstance(current_user_msg['content'], list):
                current_user_msg['content'].append(
                    {"type": "image_url", "image_url": {"url": desktop_url}}
                )
                
            # 7. 清理历史截图 (如果开启了 onlyNewScreen)
            if settings.get('visionControlSettings', {}).get('onlyNewScreen', False):
                for msg in request.messages[:-1]: # 不处理最后一条刚刚添加的消息
                    if isinstance(msg.get('content'), list):
                        # 过滤掉 image_url，只保留 text
                        new_content = [item for item in msg['content'] if item.get('type') != 'image_url']
                        # 如果 list 里只剩文本，简化为字符串提高处理效率
                        if len(new_content) == 1 and new_content[0].get('type') == 'text':
                            msg['content'] = new_content[0]['text']
                        else:
                            msg['content'] = new_content
                logging.getLogger("app").info("已清理历史上下文中的旧截图。")

            logging.getLogger("app").info(f"桌面截图已注入: {desktop_url}")

        except Exception as e:
            logging.getLogger("app").info(f"后端桌面截图失败: {e}")


def _stream_context_compress(request, settings):
    """L1 context window compression (stream channel; dead-neutral inits kept)."""
    max_rounds = 0 if _cm_context_enabled(settings) else settings.get("max_rounds", 0)
    chat_messages = request.messages # 这里的 chat_messages 包含 system
    usage_info = None
    _ctx_peak = 0
        
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


async def _stream_character_context(request, settings, user_prompt, cur_memory, memoryId, m0):
    """Character-book lore + persona fields + mem0 recall (stream wording)."""
    if settings["memorySettings"]["userName"]:
        logging.getLogger("app").info("添加用户名：\n\n" + settings["memorySettings"]["userName"] + "\n\n用户名结束\n\n")
        content_append(request.messages, 'system', "与你交流的默认用户名为：\n\n" + settings["memorySettings"]["userName"] + "\n\n注意！除非用户消息中提到了是其他用户发送，否则视为默认用户发送的消息\n\n")
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
        content_append(request.messages, 'system', "\n\n" + cur_memory["systemPrompt"] + "\n\n")
    if settings["memorySettings"]["genericSystemPrompt"]:
        if settings["memorySettings"]["userName"]:
            # 替换settings["memorySettings"]["genericSystemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
            settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
        settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{char}}", cur_memory["name"])
        content_append(request.messages, 'system', "\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n")
    if m0 and not request.is_sub_agent and getattr(request, "platform", "") != "diary":  # S172: 日记总结自调用跳过记忆检索
        memoryLimit = settings["memorySettings"]["memoryLimit"]
        try:
            # 【核心修改】：使用 asyncio.to_thread 将同步的 search 方法放入线程池运行
            # 这样主线程（Event Loop）会被释放，可以去处理 /minilm/embeddings 请求，从而避免死锁
            relevant_memories = await asyncio.to_thread(
                m0.search, 
                query=(getattr(request, "recall_query", None) or user_prompt),
                user_id=memoryId, 
                limit=memoryLimit
            )
            relevant_memories = json.dumps(neutralize_deep(relevant_memories, "recall"), ensure_ascii=False)
        except Exception as e:
            logging.getLogger("app").warning(f"m0.search error: {e}")
            relevant_memories = ""
        logging.getLogger("app").info("添加相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")
        content_append(request.messages, 'system', "之前的相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")                   


async def _stream_async_tools(request, async_tools_id):
    """Async-tool result harvesting + SSE tool_result chunks. (M-3 split)

    Delegation pattern: the caller re-yields every chunk so SSE ordering and
    backpressure stay identical to the original inline code.
    """
    if async_tools_id:
        responses_to_send = []
        responses_to_wait = []
        async with _srv().async_tools_lock:
            # 收集已完成的结果并删除条目
            for tid in list(_srv().async_tools.keys()):  # 转成list避免字典修改异常
                if tid in async_tools_id:
                    if _srv().async_tools[tid]["status"] in ("completed", "error"):
                        responses_to_send.append({
                            "tool_id": tid,
                            **_srv().async_tools.pop(tid)  # 移除已处理的条目
                        })
                    elif _srv().async_tools[tid]["status"] == "pending":
                        responses_to_wait.append({
                            "tool_id": tid,
                            "name":_srv().async_tools[tid]["name"],
                            "parameters": _srv().async_tools[tid]["parameters"]
                        })
        for response in responses_to_send:
            tid = response["tool_id"]
            if response["status"] == "completed":
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": response["name"], "content": str(response["result"]), "type": "tool_result"},
                            "async_tool_id": tid,
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
                request.messages.insert(-1, 
                    {
                        "tool_calls": [
                            {
                                "id": "agentParty",
                                "function": {
                                    "arguments": json.dumps(response["parameters"]),
                                    "name": response["name"],
                                },
                                "type": "function",
                            }
                        ],
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "",
                    }
                )
                request.messages.insert(-1, 
                    {
                        "role": "tool",
                        "tool_call_id": "agentParty",
                        "name": response["name"],
                        "content": f"之前调用的异步工具（{tid}）的结果：\n\n{await _bound_tool_output_async(response['result'])}\n\n====结果结束====\n\n你必须根据工具结果回复未回复的问题或需求。请不要重复调用该工具！"
                    }
                )
            if response["status"] == "error":
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": f"{tid}{await _srv().t('tool_result')}", "content": f"Error: {str(response['result'])}"},
                            "async_tool_id": tid
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
                request.messages.append({
                    "role": "system",
                    "content": f"之前调用的异步工具（{tid}）发生错误：\n\n{response['result']}\n\n====错误结束====\n\n"
                }) 
        for response in responses_to_wait:
            # 在request.messages倒数第一个元素之前的位置插入一个新元素
            request.messages.insert(-1, 
                {
                    "tool_calls": [
                        {
                            "id": "agentParty",
                            "function": {
                                "arguments": json.dumps(response["parameters"]),
                                "name": response["name"],
                            },
                            "type": "function",
                        }
                    ],
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "",
                }
            )
            results = f"{response["name"]}工具已成功启动，获取结果需要花费很久的时间。请不要再次调用该工具，因为工具结果将生成后自动发送，再次调用也不能更快的获取到结果。请直接告诉用户，你会在获得结果后回答他的问题。"
            request.messages.insert(-1, 
                {
                    "role": "tool",
                    "tool_call_id": "agentParty",
                    "name": response["name"],
                    "content": str(results),
                }
            )


async def _stream_kb_before(request, settings, user_prompt, kb_list):
    """before_thinking knowledge-base query with call/result SSE notices."""
    from py.know_base import query_knowledge_base, rerank_knowledge_base
    if settings["KBSettings"]["when"] == "before_thinking" or settings["KBSettings"]["when"] == "both":
        if kb_list:
            chunk_dict = {
                "id": "webSearch",
                "choices": [
                    {
                        "finish_reason": None,
                        "index": 0,
                        "delta": {
                            "role":"assistant",
                            "content": "",
                            "tool_content": {"title": "query_knowledge_base", "content": "", "type": "call"},
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            all_kb_content = []
            # 用query_knowledge_base函数查询kb_list中所有的知识库
            for kb in kb_list:
                kb_content = await query_knowledge_base(kb["kb_id"],user_prompt)
                all_kb_content.extend(kb_content)
                if settings["KBSettings"]["is_rerank"]:
                    all_kb_content = await rerank_knowledge_base(user_prompt,all_kb_content)
            if all_kb_content:
                all_kb_content = json.dumps(all_kb_content, ensure_ascii=False, indent=4)
                kb_message = f"\n\n可参考的知识库内容：{all_kb_content}"
                content_append(request.messages, 'user',  f"{kb_message}\n\n用户：{user_prompt}")
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": "query_knowledge_base", "content": str(all_kb_content), "type": "tool_result"},
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"


async def _stream_web_search_pre(request, settings, user_prompt, tools, enable_web_search):
    """Web search before-thinking injection + after-thinking announcements."""
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
            chunk_dict = {
                "id": "webSearch",
                "choices": [
                    {
                        "finish_reason": None,
                        "index": 0,
                        "delta": {
                            "role":"assistant",
                            "content": "",
                            "tool_content": {"title": "web_search", "content": "", "type": "call"},
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            # S90：统一入口——配置引擎失败自动走内置浏览器兜底
            results = await websearch_with_fallback(
                settings['webSearch']['engine'], user_prompt)
            if results:
                content_append(request.messages, 'user',  f"\n\n联网搜索结果：{results}\n\n请根据联网搜索结果组织你的回答，并确保你的回答是准确的。")
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": "web_search", "content": str(results), "type": "tool_result"},
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
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


def _stream_filter_tools(request, tools):
    """enable/disable whitelist-blacklist filter + subagent safety policy.

    S73: 显式空列表（[] 而非 None）= 有效指令：enable_tools=[] -> 0 工具。
    旧语义把 [] 当“未指定”导致日记总结的无工具意图被静默忽略（全量工具）。
    """
    _has_enable = request.enable_tools is not None
    _has_disable = request.disable_tools is not None
    if request.is_sub_agent or _has_enable or _has_disable:
        original_tool_count = len(tools)
                    
        # 1. Enable Tools 过滤（白名单模式）
        if _has_enable:
            # 只保留白名单中的工具（空名单 -> 无工具）
            filtered_tools = []
            enable_set = set(request.enable_tools)
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name in enable_set:
                    filtered_tools.append(tool)
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[Tool Filter] Enable mode: {original_tool_count} -> {len(tools)} tools (enabled: {request.enable_tools})")
                    
        # 2. Disable Tools 过滤（黑名单模式）
        elif _has_disable and len(request.disable_tools) > 0:
            # 移除黑名单中的工具
            disable_set = set(request.disable_tools)
            filtered_tools = []
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name not in disable_set:
                    filtered_tools.append(tool)
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[Tool Filter] Disable mode: {original_tool_count} -> {len(tools)} tools (disabled: {request.disable_tools})")
                    
        # 3. 子智能体默认策略（如果没有指定 enable/disable）
        elif request.is_sub_agent:
            # 子智能体默认只保留安全的工具，移除高风险操作
            SUBAGENT_BLOCKED_TOOLS = [
                            
                # 阻止子智能体管理进程/端口
                "list_processes_tool",
                "get_process_logs_tool",
                "kill_process_tool",
                "docker_manage_ports_tool",
                "local_net_tool",
                            
                # 阻止子智能体创建子任务（防止递归）
                "create_subtask",
                            
                # 阻止高风险的浏览器操作
                "new_page",
                "close_page",
                "evaluate_script",
                            
                # 阻止子智能体使用 Agent 调用（防止复杂的嵌套）
                "agent_tool_call",
                "todo_write_tool",
            ]
                        
            filtered_tools = []
            blocked_count = 0
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name not in SUBAGENT_BLOCKED_TOOLS:
                    filtered_tools.append(tool)
                else:
                    blocked_count += 1
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[SubAgent Safety] Blocked {blocked_count} dangerous tools: {original_tool_count} -> {len(tools)} tools")
    return tools


async def _stream_deepsearch_pre(_st, client, model, extra_params, request):
    """Deep-research step planning streamed to the client as tool_progress.

    Mutable results cross the generator boundary via _st (yield delegation
    cannot carry a return value). (M-3 split)
    """
    deepsearch_messages = copy.deepcopy(request.messages)
    content_append(deepsearch_messages, 'user',  "\n\n将用户提出的问题或给出的当前任务拆分成多个步骤，每一个步骤用一句简短的话概括即可，无需回答或执行这些内容，直接返回总结即可，但不能省略问题或任务的细节。如果用户输入的只是闲聊或者不包含任务和问题，直接把用户输入重复输出一遍即可。如果是非常简单的问题，也可以只给出一个步骤即可。一般情况下都是需要拆分成多个步骤的。")
                    
    # 1. 开启 stream=True 进行流式请求
    response = await acreate(
        lambda: client.chat.completions.create(
        model=model,
        messages=deepsearch_messages,
        stream=True,  # 新增
        extra_body = extra_params, # 其他参数
    ), attempts=2, base_delay=1.0, label="s207-_stream_deepsearch_pre")
                    
    user_prompt = ""
    # 生成一个唯一的 ID，用于让前端锁定同一个 UI 块进行内容更新
    deepsearch_id = f"ds_{uuid.uuid4().hex[:8]}"
                    
    # 2. 遍历流式响应并实时推给前端
    async for chunk in response:
        if not chunk.choices:
            continue
                        
        # 兼容不同版本的 openai 响应对象
        chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
        delta = chunk_dict["choices"][0].get("delta", {})
        content = delta.get("content", "")
                        
        if content:
            user_prompt += content
                            
            # 3. 借用前端原有的 tool_progress 渲染机制
            # 前端会自动创建类似 "调用deep_research工具" 的动态刷新框
            progress_chunk = {
                "choices": [{
                    "delta": {
                        "tool_progress": {
                            "name": "deep_research",
                            "arguments": user_prompt, # 传入不断累加的内容
                            "tool_call_id": deepsearch_id
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(progress_chunk)}\n\n"
                    
    content_append(request.messages, 'user',  f"\n\n如果用户没有提出问题或者任务，直接闲聊即可，如果用户提出了问题或者任务，任务描述不清晰或者你需要进一步了解用户的真实需求，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。")

    _st["user_prompt"] = user_prompt


async def _stream_reasoner_prep(_st, request, reasoner_client, settings, images, reasoner_extra, open_tag, close_tag, tools, DRS_STAGE, user_prompt, enable_deep_research):
    """First reasoner pass (streamed reasoning deltas) + vendor resolution."""
    reasoner_messages = copy.deepcopy(request.messages)
    if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
        content_append(reasoner_messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
        drs_msg = get_drs_stage(DRS_STAGE)
        if drs_msg:
            content_append(reasoner_messages, 'user',  f"\n\n{drs_msg}\n\n")
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
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_stream_reasoner_prep")
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
        ), attempts=llm_retry_cfg(settings)[0], base_delay=llm_retry_cfg(settings)[1], label="s207-_stream_reasoner_prep")
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
    content_append(request.messages, 'assistant', f"<think>\n{full_reasoning}\n</think>")  # 可参考的推理过程

    _st["vendor"] = vendor
