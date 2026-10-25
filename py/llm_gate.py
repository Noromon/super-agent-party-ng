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

import logging
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
_m0_dims_cache = {}

_bad_ctrl_re = None


def sanitize_card_strings(memory):
    """S77(1c33bc74): 清理角色卡文本字段中的控制字符（保留 \\n \\r \\t），
    防止破坏 API 请求。原地修改，非 dict 容忍直接返回。"""
    global _bad_ctrl_re
    import re
    if not isinstance(memory, dict):
        return
    if _bad_ctrl_re is None:
        _bad_ctrl_re = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]')
    text_keys = ('description', 'personality', 'mesExample', 'systemPrompt',
                 'firstMes', 'name', 'characterBook')
    for key in text_keys:
        val = memory.get(key)
        if isinstance(val, str):
            memory[key] = _bad_ctrl_re.sub('', val)
    alt_gs = memory.get('alternateGreetings')
    if isinstance(alt_gs, list):
        for i in range(len(alt_gs)):
            if isinstance(alt_gs[i], str):
                alt_gs[i] = _bad_ctrl_re.sub('', alt_gs[i])


def effective_dims(memory_id, stored_dims):
    """S77(d8814a90): 以已有 faiss 索引实际维度为准，防止更换 provider/model
    后维度不匹配导致 mem0 静默重建索引、旧数据全部丢失。
    (path, mtime_ns) 缓存，避免每请求全量读大索引。"""
    try:
        import os
        from py.get_setting import MEMORY_CACHE_DIR
        path = os.path.join(MEMORY_CACHE_DIR, memory_id, "agent-party.faiss")
        if not os.path.exists(path):
            return stored_dims
        ck = (path, os.stat(path).st_mtime_ns)
        cached = _m0_dims_cache.get(memory_id)
        if cached and cached[0] == ck:
            return cached[1]
        import faiss
        d = faiss.read_index(path).d
        _m0_dims_cache[memory_id] = (ck, d)
        if d != stored_dims:
            logging.getLogger("app").warning(
                "[LlmGate] stored dims(%s) != faiss actual dims(%s)，以实际维度为准",
                stored_dims, d)
        return d
    except Exception as e:
        logging.getLogger("app").warning("[LlmGate] 无法读取已有 faiss 索引维度: %s", e)
        return stored_dims


def ensure_pkl_compatible(memory_id):
    """S77(75b7a78a): from_config 前把旧 pickle 自动迁移/修复为 mem0 兼容的
    (docstore, idx2id) 元组格式（缺 user_id 一并补齐），否则 mem0 _load 按
    元组解包把 docstore 变成 str，get_all/update/delete 全崩。"""
    import hashlib
    import os
    import pickle
    from py.get_setting import MEMORY_CACHE_DIR
    ppath = os.path.join(MEMORY_CACHE_DIR, memory_id, "agent-party.pkl")
    fpath = os.path.join(MEMORY_CACHE_DIR, memory_id, "agent-party.faiss")
    if not os.path.exists(ppath):
        return
    try:
        with open(ppath, "rb") as f:
            raw = pickle.load(f)
        needs_migration = not (isinstance(raw, tuple) and len(raw) == 2
                               and isinstance(raw[0], dict))
        needs_repair = False
        if not needs_migration and raw[0]:
            first = next(iter(raw[0].values()), {})
            if isinstance(first, dict) and "user_id" not in first:
                needs_repair = True
        if not (needs_migration or needs_repair):
            return
        import faiss
        faiss.read_index(fpath)  # 索引可读性前置校验（上游同法）
        if needs_migration:
            if isinstance(raw, dict):
                meta = raw
            elif isinstance(raw, tuple) and isinstance(raw[0], dict):
                meta = raw[0]
            else:
                meta = {}
        else:
            idx2id_old = raw[1]
            meta = {}
            for _idx in sorted(idx2id_old.keys()):
                vid = idx2id_old[_idx]
                payload = raw[0].get(vid, {})
                meta[vid] = {"data": payload.get("data", ""),
                             "created_at": payload.get("created_at", ""),
                             "timetamp": payload.get("updated_at",
                                                     payload.get("created_at", ""))}
        docstore, idx2id = {}, {}
        for i, (vid, rec) in enumerate(meta.items()):
            data_t = rec.get("data", "") if isinstance(rec, dict) else ""
            docstore[vid] = {
                "data": data_t,
                "hash": hashlib.md5(data_t.encode()).hexdigest(),
                "created_at": rec.get("created_at", "") if isinstance(rec, dict) else "",
                "updated_at": rec.get("timetamp", rec.get("created_at", ""))
                if isinstance(rec, dict) else "",
                "user_id": memory_id,
            }
            idx2id[i] = vid
        with open(ppath, "wb") as f:
            pickle.dump((docstore, idx2id), f)
        logging.getLogger("app").info("[LlmGate] pickle %s: %s",
                                      "已迁移为 mem0 兼容格式" if needs_migration
                                      else "已修复(补充 user_id)", ppath)
    except Exception as e:
        logging.getLogger("app").warning("[LlmGate] pickle 处理失败: %s", e)


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


def gated(fn):
    """T-5: decorator form of gate() for whole-coroutine coverage.

    One-line opt-in above an `async def` that talks to the LLM backend;
    zero-indent surgery. NOT for async generator functions (use gate()).
    """
    import functools
    import inspect
    if inspect.isasyncgenfunction(fn):
        raise TypeError(f"llm_gate.gated cannot wrap async generator: {fn.__name__}")

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        enter()
        try:
            return await fn(*args, **kwargs)
        finally:
            leave()

    return wrapper


def wait_chat_idle(timeout=600.0, poll=1.5):
    end = time.time() + timeout
    while time.time() < end:
        with _lock:
            if _inflight == 0:
                return True
        time.sleep(poll)
    return False


def _lower_thread_priority():
    """S123: 提取线程降 Windows 优先级至 IDLE——mem0-add 实测最长 41.6s，
    运行期不与聊天请求/渲染抢核（闸门只保证启动时机，运行中无法让路）。"""
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.SetThreadPriority(
            ctypes.windll.kernel32.GetCurrentThread(), -1)  # THREAD_PRIORITY_IDLE
    except Exception:
        pass


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
        _lower_thread_priority()
        acquired = _mem0_lock.acquire(timeout=1800)
        if not acquired:
            logging.getLogger("app").info(f"[LlmGate] {name}: 互斥锁获取超时，放弃本次记忆提取")
            return
        try:
            if debounce and debounce > 0:
                time.sleep(debounce)
            with _gen_lock:
                if _pending.get(memory_id) != gen:
                    logging.getLogger("app").info(f"[LlmGate] {name}: 静默窗内有新回合，本次提取已推迟给新任务")
                    return
            if wait_idle and not wait_chat_idle(timeout=600):
                logging.getLogger("app").info(f"[LlmGate] {name}: 等待会话空闲超时(600s)，跳过本次记忆提取")
                return
            logging.getLogger("app").info(f"[LlmGate] {name}: 开始记忆提取（会话空闲）")
            t0 = time.time()
            fn()
            logging.getLogger("app").info(f"[LlmGate] {name}: 记忆提取完成，耗时 {time.time() - t0:.1f}s")
        except Exception as e:
            logging.getLogger("app").info(f"[LlmGate] {name}: 任务异常: {e}")
        finally:
            _mem0_lock.release()

    threading.Thread(target=runner, daemon=True, name=name).start()


def get_mem0_instance(memory_id, cur_memory, settings):
    """Build (and cache by config fingerprint) a mem0 Memory instance.

    Rebuilding Memory.from_config on every request re-loads the FAISS index
    from disk each turn; reuse instead unless any relevant config changed.

    S77 单点：角色卡清洗 + dims 实际值护栏 + pkl 兼容迁移在每次真实构建前
    执行（聊天两路与 CRUD 端点全走此处，优于上游三份拷贝）。
    """
    from mem0 import Memory

    sanitize_card_strings(cur_memory)
    eff_dims = effective_dims(memory_id, cur_memory.get("embedding_dims", 1024))
    key = (
        memory_id,
        cur_memory.get("model"),
        cur_memory.get("base_url"),
        cur_memory.get("api_key"),
        eff_dims,
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
                "embedding_dims": eff_dims,
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
                "embedding_model_dims": eff_dims,
            },
        },
    }
    ensure_pkl_compatible(memory_id)
    m0 = Memory.from_config(config)
    with _m0_lock:
        _m0_cache[memory_id] = (key, m0)
    return m0
