# -*- coding: utf-8 -*-
"""S307：任务锚点（df2f8248 事故修复，F1+F2）。

事故实证：审批续跑 POST 头部残缺（[assistant 问候, user 任务原文] 整对消失），
服务端 sanitizer 零丢弃日志（S189 必留痕）⇒ 残缺来自前端负载；而服务端链条
从未持有任务原文（turn_log seq0 即 assistant），任务一旦离链即永久失联，模型
被注入 nudge/first-hand + 陈旧记忆召回带跑，思维链涣散。

防线：
- F1 upsert：链上存在真实 user 消息时，把其文本持久化为该会话的任务锚点；
- F2 repair：续跑请求缺真实 user 消息（审批续跑头部残缺）→ 把锚点以 user
  消息回注到 system 头部之后，留 [ResumeRepair] 痕迹。

注入消息（name=system_note/browser_vision）不算真实用户消息。
"""
import logging
import time

import aiosqlite

from py.get_setting import COVS_PATH
from py.msg_utils import _extract_text_content

logger = logging.getLogger("app")

INJECT_NAMES = ("system_note", "browser_vision")

_CREATE_SQL = ("CREATE TABLE IF NOT EXISTS task_anchor ("
               "conv_id TEXT PRIMARY KEY, text TEXT NOT NULL, updated_at REAL)")


def is_genuine_user_msg(m):
    if not isinstance(m, dict):
        return False
    if m.get("role") != "user" or m.get("name") in INJECT_NAMES:
        return False
    text = _extract_text_content(m.get("content"))
    return bool(text and text.strip())


def last_genuine_user_text(messages):
    for m in reversed(messages or []):
        if is_genuine_user_msg(m):
            text = _extract_text_content(m.get("content"))
            if text and text.strip():
                return text.strip()
    return None


def insert_anchor(messages, text):
    """锚点以 user 角色回注到 system 头部之后（它是用户原话，恢复合法）。

    链内已有真实 user 消息则不动，返回 False。
    """
    if any(is_genuine_user_msg(m) for m in messages or []):
        return False
    pos = 1 if (messages and isinstance(messages[0], dict)
                and messages[0].get("role") == "system") else 0
    messages.insert(pos, {"role": "user", "content": text})
    return True


async def remember_anchor(conversation_id, text):
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(_CREATE_SQL)
        await db.execute(
            "INSERT OR REPLACE INTO task_anchor (conv_id, text, updated_at) VALUES (?, ?, ?)",
            (str(conversation_id), text, time.time()))
        await db.commit()


async def fetch_anchor(conversation_id):
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(_CREATE_SQL)
        async with db.execute(
                "SELECT text FROM task_anchor WHERE conv_id=?",
                (str(conversation_id),)) as cur:
            row = await cur.fetchone()
    return row[0] if row else None


async def anchor_stream_in(request):
    """流入口挂点：有真实 user 消息→持久化锚点；缺→回注锚点。绝不抛出。"""
    try:
        cid = getattr(request, "conversation_id", None)
        if not cid:
            return
        msgs = getattr(request, "messages", None)
        if not isinstance(msgs, list) or not msgs:
            return
        live = last_genuine_user_text(msgs)
        if live:
            await remember_anchor(cid, live)
            return
        anchor = await fetch_anchor(cid)
        if not anchor:
            return
        if insert_anchor(msgs, anchor):
            logger.info("[ResumeRepair] 任务锚点已回注 conv=%s len=%d", cid, len(anchor))
    except Exception as e:
        logger.info("[ResumeRepair] 锚点处理失败（忽略）: %r", e)
