# -*- coding: utf-8 -*-
"""S150: IM 审批闭环编排——/y /n /a 斜杠审批、approver 门禁、人话化与续跑派发。

链路（xmpp 先行，其余 bot 在 S152 抽 base_bot helper 后接入）：
  工具命中审批哨兵 → server 在工具轮收尾快照内部 messages 并 approval_store.create
  → 本模块注册的 notify（bot 侧）把审批卡文字推给对端 → 对端回 /y /n /a [批语]
  → resolve_and_resume：approver 门禁 → 原子摘除 →（批准则执行工具）→ 平台
  续跑器用快照重放 /v1「原位续流」，结果回推同一会话。
模型面人话化：sanitize_incoming 把历史里残留的审批哨兵 JSON 换成人类可读
说明（事故根之一：哨兵原文随历史回灌本地底模诱发泄漏漂移）；前端审批卡仍
收原始哨兵帧（test_frontend_pins 嗅探不受影响）。
"""
import asyncio
import json
import logging
from typing import Any, Callable, Optional, Tuple

from py.tool_dispatch import _APPROVAL_PREFIX

_APPROVE_ALIASES = {"/y", "/yes", "/批准", "/同意", "/批准"}
_DENY_ALIASES = {"/n", "/no", "/拒绝", "/否决"}
_ALWAYS_ALIASES = {"/a", "/always", "/总是", "/一直允许"}

_EXECUTOR: Optional[Callable] = None  # server 注入：execute_approved_tool


def set_executor(fn: Callable):
    global _EXECUTOR
    _EXECUTOR = fn


def parse_approval_command(text: str):
    """/y /n /a 及其中文化名；返回 (decision, note) 或 None。首 token 精确匹配
    （/yolo 等既有指令不受影响），命令后的整行文字作为批语。"""
    if not text:
        return None
    cmd = text.strip()
    if not cmd.startswith("/"):
        return None
    parts = cmd.split(None, 1)
    first = parts[0].lower()
    note = parts[1].strip() if len(parts) > 1 else ""
    if first in _APPROVE_ALIASES:
        return "approve", note
    if first in _DENY_ALIASES:
        return "deny", note
    if first in _ALWAYS_ALIASES:
        return "always", note
    return None


def _summarize_args(tool_params: Any) -> str:
    try:
        s = tool_params if isinstance(tool_params, str) else json.dumps(
            tool_params, ensure_ascii=False)
    except Exception:
        s = str(tool_params)
    s = " ".join((s or "").split())
    return (s[:800] + " …") if len(s) > 800 else (s or "{}")


def build_notice(record: dict, lang: str = "zh") -> str:
    mins = max(1, int((record.get("expires_at", 0) - record.get("created_at", 0)) // 60))
    lines = [
        f"⚠️ 需要审批：工具 `{record.get('tool_name', '?')}` 已挂起，输出暂停（{mins} 分钟无响应自动超时）。",
        f"参数：{_summarize_args(record.get('tool_params'))}",
    ]
    mode = record.get("permission_mode")
    if mode:
        lines.append(f"权限模式：{mode}")
    lines.append("回复 /y 批准本次 · /a 批准并加入白名单 · /n 拒绝；指令后可附批语（仅记入日志与模型上下文）。")
    return "\n".join(lines)


def denied_text(tool_name: str, note: str = "") -> str:
    extra = f"（批语：{note}）" if note else ""
    return f"用户拒绝执行工具 '{tool_name}'。请不要再重试该操作，改用其他方式或与用户确认。{extra}"


def timeout_text(tool_name: str) -> str:
    return (f"审批超时（用户未在时限内响应），工具 '{tool_name}' 未执行。"
            "请不要再次触发该审批，直接向用户说明情况或调整方案。")


def stopped_text(tool_name: str) -> str:
    return f"用户已取消任务，工具 '{tool_name}' 未执行。"


def humanize_sentinel(payload: dict) -> str:
    name = (payload or {}).get("tool_name") or "工具"
    return (f"[待审批] 工具 {name} 需要用户批准才能执行；用户尚未响应审批请求，"
            "该工具未执行。不要假设其已产生任何效果。")


def sanitize_incoming(messages: list) -> int:
    """历史回灌防线：把 tool 消息里的审批哨兵 JSON 换成人类可读说明。
    返回替换条数。前端/续跑重放都以替换后内容发送，这里只兜底第三方/迟到路径。"""
    n = 0
    if not isinstance(messages, list):
        return 0
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "tool":
            continue
        c = m.get("content")
        if isinstance(c, str) and c.startswith(_APPROVAL_PREFIX):
            try:
                payload = json.loads(c)
            except Exception:
                payload = {}
            m["content"] = humanize_sentinel(payload)
            n += 1
    return n


def strip_system_messages(messages: list) -> list:
    """快照预处理：剔除注入类 system 消息（重放时由 tools_change_messages 重新
    注入，避免双重 system/权限行）。返回浅拷贝新列表。"""
    return [m for m in (messages or [])
            if not (isinstance(m, dict) and m.get("role") == "system")]


def replace_sentinel_content(messages: list, result_text: str) -> bool:
    """把快照中最后一条哨兵 tool 消息换成审批结果文本（原位续流的核心动作）。"""
    for m in reversed(messages or []):
        if isinstance(m, dict) and m.get("role") == "tool" \
                and isinstance(m.get("content"), str) \
                and m["content"].startswith(_APPROVAL_PREFIX):
            m["content"] = result_text
            return True
    return False


async def approver_gate(platform: str, peer_id: str) -> Tuple[bool, str]:
    """名录含 approver 时启用门禁（未配置=向后兼容，任何对端可批复）。"""
    try:
        from py.get_setting import load_settings
        settings = await load_settings()
    except Exception:
        return True, ""
    roster = ((settings or {}).get("imPeerSettings") or {}).get("roster") or {}
    plat = roster.get(platform) or {}
    approvers = [pid for pid, e in plat.items()
                 if isinstance(e, dict) and e.get("approver")]
    if not approvers:
        return True, ""
    if peer_id in approvers:
        return True, ""
    return False, "ℹ️ 你不在该机器人的审批人名录中，本次审批需由审批人回复（/y /n /a）。"


def _log_note(record: dict, decision: str, note: str, actor: str = "peer"):
    try:
        logging.getLogger("app").info(
            "[Approval] %s by %s: %s peer=%s id=%s note=%s",
            decision, actor, record.get("tool_name"), record.get("peer_id"),
            record.get("approval_id"), (note or "")[:200])
    except Exception:
        pass


async def resolve_and_resume(platform: str, peer_id: str, decision: str,
                             note: str = "") -> str:
    """对端批复入口：门禁 → 原子摘除 →（批准则执行工具）→ 派发育续跑器。
    返回给 IM 的即时回执文本；续流在后台任务中完成。"""
    from py import approval_store
    ok, reason = await approver_gate(platform, peer_id)
    if not ok:
        return reason
    record, err = await approval_store.resolve(platform, peer_id, decision, note)
    if record is None:
        return "ℹ️ 当前没有待审批的任务。（/y 批准 · /n 拒绝 · /a 批准并加白名单）"
    tool = record.get("tool_name", "?")
    result_text = ""
    reply = ""
    if decision in ("approve", "always"):
        if _EXECUTOR is None:
            return "⚠️ 审批执行器未就绪（服务未完成初始化），请稍后重试。"
        try:
            res = await _EXECUTOR(tool, record.get("tool_params") or {}, decision, None)
        except Exception as e:
            res = {"result": f"Error executing {tool}: {e}"}
        result_text = str((res or {}).get("result", res))
        reply = (f"✅ 已按批准执行 `{tool}`，继续任务…" if decision == "approve"
                 else f"✅ 已执行 `{tool}` 并将其加入项目白名单，继续任务…")
    elif decision == "deny":
        result_text = denied_text(tool, note)
        reply = "🚫 已拒绝，正在告知模型并继续收尾…"
    else:
        result_text = stopped_text(tool)
    _log_note(record, decision, note)
    asyncio.create_task(approval_store._fire(record, decision, note, result_text))
    return reply


async def cancel_pending(platform: str, peer_id: str) -> int:
    from py import approval_store
    return await approval_store.cancel_all(platform, peer_id)
