# -*- coding: utf-8 -*-
"""S204 工具纪律与能力索引（分层条件注入的渲染器，纯函数）。

设计（审计结论落地）：
- 常驻 T0 零具体工具名：正文写调用块=死块；本轮能力索引=能力全集，索引外的
  名字（历史/记忆里见过的）本轮不存在；缺能力→正文表达或如实说不能，严禁编造。
- 能力索引：类别名 + 本轮实际声明的工具名（权威 schema 在 tools 参数，此处只给
  鸟瞰索引，双事实源零重复）。
- 类别指引块：仅当声明集 ∩ 类别 ≠ ∅ 才注入；不可用类别连类别名都零出现
  （负面清单=粉色大象，弃用）。
- 零工具轮：一行「本回合无工具」。
注入点在 build_llm_tools 之后（stream/ns 两处），不受 CLISettings 开关支配——
授权链（enable_tools→tools 参数）不动，本模块只跟随有效声明集。
"""
from __future__ import annotations

from typing import Dict, List

from py.tool_taxonomy import group, label

MARKER = "<!--sap-tool-discipline-->"

_T0 = (
    "Tool-call markup (<tool_call>, <function=...>, <parameter=...>) "
    "written into the message BODY is never executed and will be intercepted as an error (S183): issue "
    "tool calls only through your native structured tool-call channel. Copy tool names "
    "VERBATIM, one whole name at a time — never compose, concatenate, or blend parts of "
    "different tool names into one. The capability index below lists EVERY tool you have "
    "THIS turn. A name not in the index does not exist for you now — conversation history "
    "or memory may mention others; they are NOT callable. When the capability you want is "
    "missing from the index: express it directly in plain text (write what you would say "
    "or record yourself), or tell the user honestly it is unavailable. Never invent, "
    "rename, or imitate a tool call."
)

_ZERO_LINE = (
    "## Capability index (this turn = full set)\n"
    "(none) — this turn you have NO tools. Output plain text only; any call markup in "
    "the body is an error."
)

# 类别指引块：仅在对应类别可用时注入。键与 tool_taxonomy.CATEGORY_ORDER 对齐。
_BLOCKS: Dict[str, str] = {
    "file_read": "- Read and search before you edit or assert: never guess file contents, paths or APIs.",
    "file_edit": (
        "- Prefer the patch/edit tool over full rewrites; copy oldString EXACTLY from the file. "
        "Batch several changes to one file into one call via its edits array. If a patch fails, "
        "the tool echoes the closest actual snippet with line numbers - "
        "retry the patch directly from that echo; only re-read the file if that still fails, and never re-read-and-"
        "fully-rewrite just because a patch missed."),
    "file_write": (
        "- Use the full-write tool only for creating new files or intentional wholesale "
        "replacement — for targeted changes prefer the editing tool if listed."),
    "shell_exec": (
        "- Use the shell for builds, tests, installs and other commands; prefer a dedicated "
        "tool whenever one exists. For long-running commands start them in the background and "
        "poll; manage spawned processes with the process tools."),
    "web_search": (
        "- Search instead of guessing when facts may be volatile (news, versions, prices, "
        "releases); cite what you used."),
    "browse": (
        "- Browser tools drive a live page: snapshot first, then click/fill; take a screenshot "
        "when visual confirmation matters."),
    "info_query": (
        "- For time, weather, place and encyclopedia facts, query the info tools — memory is "
        "not authoritative for the physical world."),
    "knowledge_diary": (
        "- These are READ tools (recall diaries/knowledge). To persist a thought, write it in "
        "your reply text — the archiving pipeline handles storage; do not fabricate a "
        "write/diary tool call."),
    "todo_plan": (
        "- For multi-step work (3+ steps) maintain the todo list: exactly one item in_progress "
        "at a time; mark an item done only after its work is actually finished and verified, "
        "never merely planned."),
    "ask_user": (
        "- When you need the user's decision, choice, or missing information to proceed: call "
        "ask_user_question_tool with ALL related questions in ONE call (1-4 questions, numbered "
        "options when possible) — this pauses the task cleanly and the answer comes back as the "
        "tool result. Do NOT end the turn with a plain-text question as the pause point, and do "
        "not re-ask what the card already asked. (S194)"),
    "orchestration": (
        "- Subtask/agent tools delegate work: give each subtask clear acceptance criteria, pass "
        "explicit scope/platform parameters, and verify delegated results yourself — never "
        "fabricate their outcomes."),
    "media_analysis": (
        "- Analyze images you received with the media tools before claiming what they contain."),
    "media_gen": (
        "- After generating media, deliver the result URL/markup exactly as the tool contract "
        "requires; tool results alone are not visible to the user."),
    "settings_admin": (
        "- Changing workspace settings alters future behavior: state what you change and why."),
    "external": (
        "- External/MCP capabilities are third-party: check their parameters, mind side effects, "
        "prefer read-only actions when unsure."),
}


def render_tool_discipline(declared: List[str]) -> str:
    """按本轮有效声明集渲染纪律+索引+类别指引。空声明=零工具一行。"""
    names = [n for n in (declared or []) if n]
    if not names:
        return f"{MARKER}\n{_ZERO_LINE}"
    buckets = group(names)
    lines = [MARKER, "## Capability discipline", _T0, "",
             "## Capability index (this turn = full set)"]
    for cat, cat_names in buckets.items():
        lines.append(f"- {label(cat)}: {', '.join(cat_names)}")
    lines.append("")
    for cat in buckets:
        block = _BLOCKS.get(cat)
        if block:
            lines.append(block)
    return "\n".join(lines)
