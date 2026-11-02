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
from py.token_guard import neutralize_deep


async def shadow_append(conversation_id, messages, log=None):
    """Record the canonical chain for this conversation (prefix diff).

    S190: the old "history only grows" high-water-mark test (`len(messages)
    <= written`) silently froze the log the first time a chain legitimately
    shrank (sanitize drops / IM per-turn rebuild) - last write stuck at the
    longest chain ever seen. Now we compare element-wise against stored rows:
    common prefix untouched, first divergence onward rewritten (REPLACE) and
    stale tail removed, so the table always mirrors the live chain.
    """
    if not conversation_id or not messages:
        return 0
    def _get(msg, key):
        return msg.get(key) if isinstance(msg, dict) else getattr(msg, key, None)
    try:
        async with aiosqlite.connect(COVS_PATH) as db:
            async with db.execute(
                    "SELECT seq, msg FROM turn_log WHERE conversation_id = ? ORDER BY seq",
                    (conversation_id,)) as cur:
                stored = await cur.fetchall()
            cand = []
            for msg in messages:
                if _get(msg, "role") is None:
                    continue
                cand.append(json.dumps(neutralize_deep(msg, "turn-log"),
                                       ensure_ascii=False, default=str))
            n_common = 0
            while (n_common < len(stored) and n_common < len(cand)
                   and stored[n_common][1] == cand[n_common]):
                n_common += 1
            if n_common == len(stored) and n_common == len(cand):
                return 0
            now = time.time()
            changed = 0
            if n_common < len(stored):
                await db.execute(
                    "DELETE FROM turn_log WHERE conversation_id = ? AND seq >= ?",
                    (conversation_id, stored[n_common][0]))
                changed += len(stored) - n_common
            batch = [(conversation_id, i, cand[i], now) for i in range(n_common, len(cand))]
            if batch:
                await db.executemany(
                    "INSERT OR REPLACE INTO turn_log "
                    "(conversation_id, seq, msg, created_at) VALUES (?, ?, ?, ?)", batch)
                changed += len(batch)
            await db.commit()
            return changed
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
