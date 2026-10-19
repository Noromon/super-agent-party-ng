# -*- coding: utf-8 -*-
"""Global LLM serialization gate.

Background: after each chat turn, mem0 memory extraction (infer=True) fires 1-2 LLM
calls against the SAME backend as the main chat, plus per-memory embeddings. Those
background calls interleave prefixes in the llama.cpp prompt cache slots (reused=0)
and queue up against the live conversation.

This module keeps the backend effectively single-filed:
  - chat streams register enter()/leave() around the whole generation
  - memory extraction jobs are serialized by a dedicated lock and only start while
    no chat request is in flight (bounded wait, stale-job drop)
"""
import threading
import time
from contextlib import asynccontextmanager

_lock = threading.Lock()
_inflight = 0

_mem0_lock = threading.Lock()
_gen_lock = threading.Lock()
_pending = {}

DEFAULT_DEBOUNCE_SECONDS = 20.0

_m0_lock = threading.Lock()
_m0_cache = {}


def enter():
    global _inflight
    with _lock:
        _inflight += 1


def leave():
    global _inflight
    with _lock:
        _inflight = max(0, _inflight - 1)


def inflight():
    with _lock:
        return _inflight


@asynccontextmanager
async def gate():
    """T-5: any LLM exit's one-line gate (exception-safe enter/leave pair).

    Reentrant-safe (plain counter), so calling inside an already-gated
    section only adds a count, never deadlocks.
    """
    enter()
    try:
        yield
    finally:
        leave()


def wait_chat_idle(timeout=600.0, poll=1.5):
    end = time.time() + timeout
    while time.time() < end:
        with _lock:
            if _inflight == 0:
                return True
        time.sleep(poll)
    return False


def submit_memory_job(memory_id, fn, name="mem0-add",
                      debounce=DEFAULT_DEBOUNCE_SECONDS, wait_idle=True):
    """Run fn() (blocking, e.g. m0.add) serialized against the chat.

    Only the newest job per memory_id runs; older queued jobs are dropped
    (their information is stale/redundant relative to the newest turn).
    All memory jobs run one at a time. With debounce/wait_idle enabled the
    job also waits for a quiet period with no chat activity before starting,
    so continuous conversations never interleave memory extraction prefixes
    into the LLM prompt cache.

    debounce: quiet seconds required before starting (0 disables)
    wait_idle: also require zero chat requests in flight at start
    """
    with _gen_lock:
        gen = _pending.get(memory_id, 0) + 1
        _pending[memory_id] = gen

    def runner():
        acquired = _mem0_lock.acquire(timeout=1800)
        if not acquired:
            print(f"[LlmGate] {name}: 互斥锁获取超时，放弃本次记忆提取")
            return
        try:
            if debounce and debounce > 0:
                time.sleep(debounce)
            with _gen_lock:
                if _pending.get(memory_id) != gen:
                    print(f"[LlmGate] {name}: 静默窗内有新回合，本次提取已推迟给新任务")
                    return
            if wait_idle and not wait_chat_idle(timeout=600):
                print(f"[LlmGate] {name}: 等待会话空闲超时(600s)，跳过本次记忆提取")
                return
            print(f"[LlmGate] {name}: 开始记忆提取（会话空闲）")
            t0 = time.time()
            fn()
            print(f"[LlmGate] {name}: 记忆提取完成，耗时 {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"[LlmGate] {name}: 任务异常: {e}")
        finally:
            _mem0_lock.release()

    threading.Thread(target=runner, daemon=True, name=name).start()


def get_mem0_instance(memory_id, cur_memory, settings):
    """Build (and cache by config fingerprint) a mem0 Memory instance.

    Rebuilding Memory.from_config on every request re-loads the FAISS index
    from disk each turn; reuse instead unless any relevant config changed.
    """
    from mem0 import Memory

    key = (
        memory_id,
        cur_memory.get("model"),
        cur_memory.get("base_url"),
        cur_memory.get("api_key"),
        cur_memory.get("embedding_dims", 1024),
        settings.get("model"),
        settings.get("base_url"),
        settings.get("api_key"),
    )
    with _m0_lock:
        cached = _m0_cache.get(memory_id)
        if cached and cached[0] == key:
            return cached[1]

    import os
    from py.get_setting import MEMORY_CACHE_DIR

    config = {
        "embedder": {
            "provider": "openai",
            "config": {
                "model": cur_memory["model"],
                "api_key": cur_memory["api_key"],
                "openai_base_url": cur_memory["base_url"],
                "embedding_dims": cur_memory.get("embedding_dims", 1024),
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": settings["model"],
                "api_key": settings["api_key"],
                "openai_base_url": settings["base_url"],
            },
        },
        "vector_store": {
            "provider": "faiss",
            "config": {
                "collection_name": "agent-party",
                "path": os.path.join(MEMORY_CACHE_DIR, memory_id),
                "distance_strategy": "euclidean",
                "embedding_model_dims": cur_memory.get("embedding_dims", 1024),
            },
        },
    }
    m0 = Memory.from_config(config)
    with _m0_lock:
        _m0_cache[memory_id] = (key, m0)
    return m0
