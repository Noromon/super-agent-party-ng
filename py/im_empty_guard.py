# -*- coding: utf-8 -*-
"""S68：IM 家族统一空回复防线。

背景：thinking 系模型可能仅输出 reasoning_content；当平台 reasoningVisible=False
时正文收集结果为空。旧行为 = 对用户完全沉默 + 空 assistant 写回会话历史
（下轮历史含空 assistant，污染自我强化）。

防线三件套（各 bot 流式收集点引用本模块）：
  ① log_empty_reply —— 一行 [IM-empty] 观测日志（reasoning_len/finish_reason/audio）
  ② EMPTY_REPLY_MSG —— 非音频回合的兜底提示文案
  ③ 调用方负责不将空 assistant 写入 memoryList（防污染由调用点守卫）
"""
import logging

EMPTY_REPLY_MSG = "⚠️ 模型本轮未返回正文（可能只完成了思考）。请重试。"


def error_from_delta(delta) -> str:
    """S89-B：识别服务端流内错误帧（delta.tool_content type=error）。

    server 流 handler 的兜底 except 会把异常塞进 tool_content 帧发给前端；
    IM 侧此前静默丢弃该帧 → 用户只见「未返回正文」，真实异常两头不可见。
    返回错误摘要（截 300 字符）；非错误帧返回 ''。"""
    tc = None
    if isinstance(delta, dict):
        tc = delta.get("tool_content")
    if tc is None:
        tc = getattr(delta, "tool_content", None)
    if isinstance(tc, dict):
        if (tc.get("type") or "") == "error":
            return str(tc.get("content") or tc.get("title") or "unknown")[:300]
    elif tc is not None:
        if (getattr(tc, "type", "") or "") == "error":
            return str(getattr(tc, "content", "") or getattr(tc, "title", "") or "unknown")[:300]
    return ""


def empty_reply_msg(error_text: str = "") -> str:
    """空回复兜底文案：有流内错误摘要时如实告知，不再只报「未返回正文」。"""
    if error_text:
        return f"⚠️ 本轮内部错误：{error_text}\n（已记录服务端日志，请排查后重试，无需重复发送问题）"
    return EMPTY_REPLY_MSG


def log_empty_reply(platform: str, chat_id, reasoning_len: int = 0,
                    finish_reason: str = "", audio: bool = False) -> None:
    logging.getLogger("app").info(
        "[IM-empty] platform=%s chat=%s reasoning_len=%d finish=%s audio=%s",
        platform, chat_id, reasoning_len, finish_reason or "?", audio)
