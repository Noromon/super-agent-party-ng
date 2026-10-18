# -*- coding: utf-8 -*-
"""Shadow turn log: server-side canonical LLM-chain store (M1 ownership groundwork).

Every successful round appends the canonical OpenAI messages it produced into
turn_log (conversations DB), keyed by conversation_id. Shadow mode: nothing
reads it yet; M4 migration and the headless API will. Best-effort by design -
never breaks a live conversation.
"""
import json
import time

import aiosqlite

from py.get_setting import COVS_PATH


async def shadow_append(conversation_id, messages, log=None):
    """Append messages not yet recorded for this conversation. Idempotent per (id, seq)."""
    if not conversation_id or not messages:
        return 0
    def _get(msg, key):
        return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)
    try:
        async with aiosqlite.connect(COVS_PATH) as db:
            cur = await db.execute(
                "SELECT COALESCE(MAX(seq), -1) FROM turn_log WHERE conversation_id = ?",
                (conversation_id,))
            written = (await cur.fetchone())[0] + 1
            if len(messages) <= written:
                return 0
            now = time.time()
            batch = []
            for offset, msg in enumerate(messages[written:]):
                if _get(msg, "role") is None:
                    continue
                batch.append((conversation_id, written + offset,
                              json.dumps(msg, ensure_ascii=False, default=str), now))
            if batch:
                await db.executemany(
                    "INSERT OR REPLACE INTO turn_log "
                    "(conversation_id, seq, msg, created_at) VALUES (?, ?, ?, ?)", batch)
                await db.commit()
            return len(batch)
    except Exception as e:  # shadow must never kill the conversation
        if log:
            log(f"[TurnLog] shadow_append failed: {e}")
        return 0


async def read_chain(conversation_id):
    async with aiosqlite.connect(COVS_PATH) as db:
        cur = await db.execute(
            "SELECT msg FROM turn_log WHERE conversation_id = ? ORDER BY seq",
            (conversation_id,))
        return [json.loads(r[0]) for r in await cur.fetchall()]
