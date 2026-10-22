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


def log_empty_reply(platform: str, chat_id, reasoning_len: int = 0,
                    finish_reason: str = "", audio: bool = False) -> None:
    logging.getLogger("app").info(
        "[IM-empty] platform=%s chat=%s reasoning_len=%d finish=%s audio=%s",
        platform, chat_id, reasoning_len, finish_reason or "?", audio)
