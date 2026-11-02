# -*- coding: utf-8 -*-
"""S192: contextWindow="auto" 探测——引擎 /props → /models 兼容读取真实上下文
窗口（llama.cpp 及其派生引擎），结果按 base_url|model 缓存到数据目录，重启复用；
探测失败回退 32000 并告警一次（不反复打引擎）。"""
import json
import logging
import os
import threading
import time
import urllib.request

_PROBE_TIMEOUT = 1.5
_CACHE_TTL = 7 * 86400
_FALLBACK = 32000
_CTX_KEYS = {"n_ctx", "n_ctx_actual", "context_window", "max_context", "n_ctx_train"}

_mem_cache = {}
_lock = threading.Lock()
_warned = set()


def _cache_path():
    from py.get_setting import USER_DATA_DIR
    return os.path.join(USER_DATA_DIR, "context_window_probe.json")


def _load_file_cache():
    try:
        with open(_cache_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save_file_cache(d):
    try:
        p = _cache_path()
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def _http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sap-ctx-probe/1"})
    with urllib.request.urlopen(req, timeout=_PROBE_TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _scan_n_ctx(node, depth=0):
    """递归搜上下文窗口字段（不同引擎层级不一：顶层 n_ctx / general.n_ctx 等）。"""
    if depth > 6:
        return 0
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _CTX_KEYS and isinstance(v, int) and not isinstance(v, bool) and v > 0:
                return v
        for v in node.values():
            got = _scan_n_ctx(v, depth + 1)
            if got:
                return got
    elif isinstance(node, list):
        for v in node:
            got = _scan_n_ctx(v, depth + 1)
            if got:
                return got
    return 0


def _engine_root(base_url):
    u = str(base_url or "").rstrip("/")
    if u.endswith("/v1"):
        u = u[:-3]
    return u


def probe_window(base_url):
    """/props → /models 依次探测；拿不到返回 0。"""
    root = _engine_root(base_url)
    for path in ("/props", "/models"):
        try:
            got = _scan_n_ctx(_http_json(root + path))
            if got:
                return got
        except Exception:
            continue
    return 0


def resolve_auto_window(settings):
    """get_context_settings 的 auto 解析入口（同步；命中缓存零网络）。"""
    base_url = str(settings.get("base_url") or "")
    key = f"{base_url}|{settings.get('model', '')}"
    now = time.time()
    with _lock:
        hit = _mem_cache.get(key)
        if hit and now - hit[1] < _CACHE_TTL:
            return hit[0]
    win = probe_window(base_url)
    if win:
        with _lock:
            _mem_cache[key] = (win, now)
        d = _load_file_cache()
        d[key] = {"n": win, "ts": now}
        _save_file_cache(d)
        logging.getLogger("app").info("[Context] auto 探测窗口=%d (%s)", win, base_url)
        return win
    d = _load_file_cache()
    stale = d.get(key)
    if isinstance(stale, dict) and isinstance(stale.get("n"), int) and stale["n"] > 0:
        logging.getLogger("app").info("[Context] auto 探测失败，沿用上次缓存窗口=%d", stale["n"])
        with _lock:
            _mem_cache[key] = (stale["n"], now)  # 避免每请求重试打引擎
        return stale["n"]
    with _lock:
        first = key not in _warned
        _warned.add(key)
        _mem_cache[key] = (_FALLBACK, now)
    if first:
        logging.getLogger("app").warning(
            "[Context] contextWindow=auto 探测失败（/props//models 均不可达），回退 %d；"
            "可在设置里手配真实窗口", _FALLBACK)
    return _FALLBACK


def reset_for_tests():
    with _lock:
        _mem_cache.clear()
        _warned.clear()
