# -*- coding: utf-8 -*-
"""S163: 幻觉工具调用泄漏防御（tool_call_guard）。

背景：推理引擎对「未在请求中声明的工具名」的 <tool_call> 块会降级为纯文本
返回（防御正确），该文本在 SAP 侧被当正文发给用户、写进会话历史（few-shot
污染，会诱导模型复现坏格式），且回合以 stop 终结——任务中断无人自纠。

本模块提供三件纯函数能力：
- detect_leaked_calls(text): 识别正文中的调用块文本并提取模型写的名字；
- build_correction_message(leaked, declared): 生成自纠提示（近似名仅提示，
  绝不改写执行——用户拍板）；
- neutralize_leaked_blocks(text): 落账前把调用块文本替换为占位符，阻断
  历史 few-shot 污染（用户侧流内原文不拦，不骗人）。
"""
import difflib
import re

MAX_TCG_RETRIES = 2
REDACTION = "[malformed tool call redacted]"

# 调用块起始/结束标记（覆盖 Hermes 风格 <tool_call>、ChatML 风格
# <|im_start|>、<function_call>，以及降级文本中残留的块结构）
# S183: 补 <function=/</function> 裸形——Hermes-XML 引擎降级文本常以
# <function=NAME> 直接开块（2026-10-31 nonogram 事故形态），旧表漏检。
_BLOCK_START = (r"<tool_call>|<\|tool_call\|>|<function_call>|<function=|<invoke=|"
                r"</function>|</invoke>|</tool_call>")
_BLOCK_FULL = re.compile(
    r"(?:<tool_call>|<\|tool_call\|>|<function_call>|<function=|<invoke=)[\s\S]*?"
    r"(?:</tool_call>|<\|tool_call\|>|</function_call>|</function>|</invoke>)",
    re.IGNORECASE)
_BLOCK_UNCLOSED = re.compile(
    r"(?:<tool_call>|<\|tool_call\|>|<function_call>|<function=|<invoke=)[\s\S]*$",
    re.IGNORECASE)
_HAS_MARKER = re.compile(_BLOCK_START)
# 名字抽取：XML 属性/等号形态与 JSON 形态；仅在存在调用块标记时启用
_NAME_XML = re.compile(r"<(?:function|invoke)[= ](?:name=\")?([A-Za-z0-9_.:\-]{2,})\"?(?=[>\s]|$)")
_NAME_JSON = re.compile(r"\"name\"\s*:\s*\"([A-Za-z0-9_.:\-]{2,})\"")


def detect_leaked_calls(text):
    """返回正文调用块中出现的工具名列表（去重保序）；无调用块文本返回 []。"""
    if not text or not _HAS_MARKER.search(text):
        return []
    names = []
    for pat in (_NAME_XML, _NAME_JSON):
        for m in pat.finditer(text):
            n = m.group(1)
            if n not in names:
                names.append(n)
    return names


def neutralize_leaked_blocks(text):
    """调用块文本 → 占位符（历史落账专用；无泄漏时原样返回，零开销）。"""
    if not text or not _HAS_MARKER.search(text):
        return text
    out = _BLOCK_FULL.sub(REDACTION, text)
    out = _BLOCK_UNCLOSED.sub(REDACTION, out)
    return out


def declared_tool_names(tools):
    """从 openai tools 声明列表提取名字集合；结构异常一律安全返回空集。"""
    names = set()
    try:
        for t in tools or []:
            fn = t.get("function") if isinstance(t, dict) else getattr(t, "function", None)
            if isinstance(fn, dict):
                n = fn.get("name")
            else:
                n = getattr(fn, "name", None)
            if n:
                names.add(str(n))
    except Exception:
        return set()
    return names


def build_correction_message(leaked_names, declared_names):
    """自纠提示：说明未执行原因+声明清单；近似名以 did-you-mean 提示，
    由模型自己重发结构化调用（不做任何自动改写执行）。"""
    declared_sorted = sorted(declared_names)
    lines = [
        "Your previous message wrote a tool call as PLAIN TEXT "
        "(<tool_call>... markup). It was NOT executed and nothing changed.",
        "Undeclared name(s) in that text: "
        + ", ".join(repr(n) for n in leaked_names) + ".",
        f"Declared tools are exactly: {', '.join(declared_sorted)}.",
        "Copy a tool name VERBATIM from this list - never compose or "
        "concatenate names - and issue the call again in your native "
        "tool-call format, or continue without tools if no call is needed.",
    ]
    hints = []
    for n in leaked_names:
        close = difflib.get_close_matches(n, declared_sorted, n=1, cutoff=0.6)
        if close:
            hints.append(f"Closest declared name for {n!r}: {close[0]!r}.")
    if hints:
        lines.extend(hints)
    return "\n".join(lines)


# ==================== S183: 流内显示拦截（holdback）辅助 ====================
# 目标：调用块标记一旦成型，其起始位置之后的正文不再流向 UI/IM（旧策略
# "流内原文不拦"废止——用户 2026-10-31 明示：展示错误调用块，不展示尸块）。
# 标记跨越流式分块时，尾部"疑似标记前缀"先扣住不发，凑够再判。

_MARKERS = ("<tool_call", "<|tool_call|>", "<function_call>", "<function=", "<invoke=",
            "</function>", "</invoke>", "</tool_call>")
_MAX_MARK = max(len(m) for m in _MARKERS)


def cut_position(text) -> int:
    """最早完整标记下标；无标记返回 -1。"""
    low = text.lower()
    best = -1
    for m in _MARKERS:
        i = low.find(m)
        if i >= 0 and (best < 0 or i < best):
            best = i
    return best


def partial_tail_len(text) -> int:
    """尾部为某标记严格前缀的最大长度（0=无需扣住）。"""
    if not text:
        return 0
    low = text[-_MAX_MARK:].lower()
    for k in range(min(len(low), _MAX_MARK - 1), 0, -1):
        tail = low[-k:]
        for m in _MARKERS:
            if m.startswith(tail):
                return k
    return 0