# -*- coding: utf-8 -*-
"""S194: ask_user_question_tool——结构化提问闭环（与审批同构的挂起-续流）。

链路：模型调 ask_user_question_tool（1~4 问一批）→ server 工具轮产 ASK 哨兵并
approval_store.create(kind="ask") 挂起断流 → IM 推编号选项纯文本卡（审批同款
风格，与 AI 正文区分）/ web 走工具卡渲染 → 对端回复=逐题答案：
  · IM：下一条文本消息经解析器逐题落位，解不全→原卡追问（不销账）；
  · web：下一条消息在 tools_change_messages 入口就地替换哨兵（解析不全按
    「未答复」结算，web 无追问卡）。
答案替换哨兵后原位续流（IM 复用 _resume_llm 快照重放；web 天然续跑）。
超时/ /stop 与审批共用 approval_store 生命周期（落盘、跨重启、通知销账）。
通知中心仅收 web 来源的 ask（IM 提问直发对端，不堆面板）。
"""
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

_ASK_PREFIX = '{"__sap_ask_v1__":1,'
ASK_TOOL_NAME = "ask_user_question_tool"
ASK_TTL = 600
MAX_QUESTIONS = 4
MAX_OPTIONS = 6


# ---------------------------------------------------------------- 哨兵

def make_sentinel(ask_id: str, questions: Optional[list] = None) -> str:
    """S195：整体合法 JSON（前端 JSON.parse 可建卡）且保持 _ASK_PREFIX 前缀；
    载荷可携带规范化后的问题列表——web 提问卡渲染直接读哨兵。"""
    payload: Dict[str, Any] = {"__sap_ask_v1__": 1, "type": "ask_pending", "ask_id": ask_id}
    if questions:
        payload["questions"] = questions
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def is_ask_result(res: Any) -> Optional[Dict]:
    """结构化哨兵判定（仿 _is_approval_result）：命中返回 payload，否则 None。"""
    if not isinstance(res, str) or not res.startswith(_ASK_PREFIX):
        return None
    try:
        return json.loads(res)
    except Exception:
        return {}


def humanize_sentinel(payload: dict) -> str:
    return ("[提问卡] 已向用户发出提问，用户尚未答复。不要假设任何一项已获确认；"
            "等待答复或按最保守的合理假设推进并向用户说明假设内容。")


def replace_ask_sentinel(messages: list, result_text: str) -> bool:
    """快照内最后一条 ASK 哨兵 tool 消息 → 答案文本（原位续流核心动作）。"""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "tool" \
                and isinstance(m.get("content"), str) \
                and m["content"].startswith(_ASK_PREFIX):
            m["content"] = result_text
            return True
    return False


# ---------------------------------------------------------------- 问题规范化

def normalize_questions(args: Any) -> Tuple[List[Dict], str]:
    """校验并规范化 {"questions":[{"question","options"}]}。返回 (questions, 错误)。
    错误非空时 questions 无意义（模型按错误文本自纠）。"""
    if not isinstance(args, dict):
        return [], "[Error] ask_user_question_tool expects an object with 'questions'."
    raw = args.get("questions")
    _bad_json = False
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = None
            _bad_json = True  # S196：模型把 questions 传成 JSON 字符串但串本身非法
    # 容错：模型常见单问平铺 {"question": ..., "options": [...]}
    if raw is None and isinstance(args.get("question"), str):
        raw = [{"question": args.get("question"), "options": args.get("options") or []}]
    if _bad_json:
        return [], ("[Error] 'questions' was given as a string that is not valid JSON; "
                    "pass a real JSON array: [{\"question\": \"...\", \"options\": [\"...\"]}].")
    if not isinstance(raw, list) or not raw:
        return [], ("[Error] 'questions' must be a non-empty array of "
                    "{question, options?} objects (1-4 questions per call).")
    if len(raw) > MAX_QUESTIONS:
        return [], (f"[Error] too many questions ({len(raw)}); ask at most "
                    f"{MAX_QUESTIONS} per call - merge or split across turns.")
    out: List[Dict] = []
    for i, q in enumerate(raw, 1):
        if isinstance(q, str):
            q = {"question": q}
        if not isinstance(q, dict):
            return [], f"[Error] question #{i} must be an object {{question, options?}}."
        text = str(q.get("question") or "").strip()
        if not text:
            return [], f"[Error] question #{i} has empty 'question' text."
        opts_raw = q.get("options") or []
        if isinstance(opts_raw, str):
            # S313：模型常把数组字符串化（"[...]"）或用分隔符并排多个选项——
            # 直接 splitlines 会把 N 个选项合并成 1 个按钮（用户报"选项合并/只剩一个"）。
            s = opts_raw.strip()
            parsed = None
            if s.startswith("["):
                try:
                    parsed = json.loads(s)
                except Exception:
                    parsed = None
            if isinstance(parsed, list):
                opts_raw = parsed
            else:
                parts = [p for p in s.splitlines() if p.strip()]
                if len(parts) == 1 and s:
                    for sep in ("、", "；", ";"):
                        cand = [p.strip() for p in s.split(sep) if p.strip()]
                        if len(cand) > 1:
                            parts = cand
                            break
                opts_raw = parts
        if not isinstance(opts_raw, list):
            return [], f"[Error] question #{i} 'options' must be an array of strings."
        opts = [str(o).strip()[:200] for o in opts_raw if str(o).strip()][:MAX_OPTIONS]
        out.append({"question": text[:500], "options": opts})
    return out, ""


# ---------------------------------------------------------------- 卡片

def _fmt_question(qi: int, q: Dict) -> List[str]:
    lines = [f"Q{qi}. {q['question']}"]
    for oi, opt in enumerate(q.get("options") or [], 1):
        lines.append(f"   {oi}. {opt}")
    return lines


def build_notice(record: Dict, lang: str = "zh", only: Optional[List[int]] = None) -> str:
    """IM 纯文本提问卡（系统卡风格，与 AI 正文区分）。only=追问时限定题号。"""
    qs = record.get("questions") or []
    mins = max(1, int((record.get("expires_at", 0) - record.get("created_at", 0)) // 60))
    idxs = only if only else list(range(1, len(qs) + 1))
    lines = [f"🙋 需要主人拍板（共 {len(idxs)} 问，{mins} 分钟内有效，未答将自动收尾）："]
    for i in idxs:
        if 1 <= i <= len(qs):
            lines.extend(_fmt_question(i, qs[i - 1]))
    lines.append("回复格式：每题一行「题号. 选项号」（如 1.2）；单题可直接回选项号或自由文本；"
                 "多题也可按顺序每行一条自由回答。/stop 作废提问。")
    return "\n".join(lines)


def build_reask_notice(record: Dict, missing: List[int]) -> str:
    miss_txt = "、".join(f"Q{i}" for i in missing)
    return (f"⚠️ {miss_txt} 还没收到能对上号的答复，请再答一次（本题卡未失效，倒计时继续）：\n"
            + build_notice(record, only=missing))


# ---------------------------------------------------------------- 答案解析

_LINE_RE = None


def _match_option(spec: Dict, val: str) -> str:
    opts = spec.get("options") or []
    v = val.strip()
    if opts:
        if v.isdigit() and 1 <= int(v) <= len(opts):
            return opts[int(v) - 1]
        low = v.lower()
        for o in opts:
            if o.lower() == low:
                return o
    return v


def parse_answers(record: Dict, text: str) -> Tuple[Dict[int, str], List[int]]:
    """对端文本 → (题号→答案, 未落位题号列表)。

    规则：显式「题号. 值」行优先；单题裸文本直接落位；无显式行且行数==题数按行序
    映射；选项数字映射为选项文本，其余原样作为自定义答案（Other 语义）。
    """
    import re as _re
    global _LINE_RE
    qs = record.get("questions") or []
    n = len(qs)
    answers: Dict[int, str] = {}
    if n == 0 or not (text or "").strip():
        return {}, list(range(1, n + 1))
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if _LINE_RE is None:
        _LINE_RE = _re.compile(r"^(\d{1,2})\s*[\.、:：)）]\s*(.+)$")
    rest: List[str] = []
    explicit_any = False
    for ln in lines:
        m = _LINE_RE.match(ln)
        if m and 1 <= int(m.group(1)) <= n and int(m.group(1)) not in answers:
            answers[int(m.group(1))] = _match_option(qs[int(m.group(1)) - 1], m.group(2).strip())
            explicit_any = True
        else:
            rest.append(ln)
    if not answers and n == 1:
        answers[1] = _match_option(qs[0], text.strip())
    elif rest and len(rest) == n - len(answers):
        free = [i for i in range(1, n + 1) if i not in answers]
        for i, ln in zip(free, rest):
            answers[i] = _match_option(qs[i - 1], ln)
    elif not explicit_any and n > 1 and len(lines) == n:
        for i, ln in enumerate(lines, 1):
            answers[i] = _match_option(qs[i - 1], ln)
    missing = [i for i in range(1, n + 1) if i not in answers]
    return answers, missing


# ---------------------------------------------------------------- 结算文本

def format_result_text(record: Dict, answers: Dict[int, str]) -> str:
    qs = record.get("questions") or []
    lines = [f"【提问卡答复】（共 {len(qs)} 问）"]
    for i, q in enumerate(qs, 1):
        a = answers.get(i)
        lines.append(f"{i}. {q['question']} → {a if a else '（未答复）'}")
    if any(not answers.get(i) for i in range(1, len(qs) + 1)):
        lines.append("（未答复项：按最合理的默认假设继续推进，并在最终答复中向用户说明该假设。）")
    else:
        lines.append("（答复已确认，按所选继续任务，无需重复追问。若当前处于 Plan/只读模式且"
                 "答复已补齐全部待定项：立刻输出最终计划正文供用户确认，禁止再探索文件、"
                 "反复权衡或尝试越权执行。）")
    return "\n".join(lines)


def timeout_result_text(record: Dict) -> str:
    return format_result_text(record, {})


# ---------------------------------------------------------------- web 入口拦截

def _last_user_text(request) -> str:
    for m in reversed(getattr(request, "messages", None) or []):
        if not isinstance(m, dict) or m.get("role") != "user":
            continue
        c = m.get("content")
        if isinstance(c, str):
            return c.strip()
        if isinstance(c, list):
            parts = [p.get("text", "") for p in c
                     if isinstance(p, dict) and p.get("type") == "text"]
            return "\n".join(p for p in parts if p).strip()
        return ""
    return ""


async def web_resolve_incoming(request) -> bool:
    """web 主对话入口拦截：本会话存在待答提问卡时，本条消息即答案——就地替换
    哨兵并销账（解析不全按「未答复」结算；web 不做追问卡）。bot 重放不受影响。
    """
    if getattr(request, "is_app_bot", False):
        return False
    cid = getattr(request, "conversation_id", None)
    if not cid:
        return False
    from py import approval_store
    rec = approval_store.latest_pending_ask("web", str(cid))
    if rec is None:
        return False
    answers, missing = parse_answers(rec, _last_user_text(request))
    popped, _err = await approval_store.resolve("web", str(cid), "answers", kind="ask")
    if popped is None:
        return False  # 已被其它路径（超时/停止）销账，哨兵留给 sanitize 人话化
    import asyncio
    from py import approval_store as _st_mod
    asyncio.create_task(_st_mod._fire(popped, "answers", "",
                                      format_result_text(rec, answers)))
    logging.getLogger("app").info(
        "[Ask] web 答案注入: conv=%s id=%s 已答=%d 未答=%d",
        cid, rec.get("approval_id"), len(answers), len(missing))
    return replace_ask_sentinel(getattr(request, "messages", None) or [],
                                format_result_text(rec, answers))
