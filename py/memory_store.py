# -*- coding: utf-8 -*-
"""faiss 记忆存储层（批 2h2 自 server.py 迁出）。

S77 后 CRUD 已改走 mem0 API（py/llm_gate.get_mem0_instance 单点），本模块
保留路径工具与时间格式化的响应键（前端契约），保持原样。
"timetamp" 为历史拼写的响应键（前端契约），保持原样。
"""
import os
from datetime import datetime

from py.get_setting import MEMORY_CACHE_DIR


def get_dir(mid: str) -> str:
    return os.path.join(MEMORY_CACHE_DIR, mid)


def get_faiss_path(mid: str) -> str:
    return os.path.join(get_dir(mid), "agent-party.faiss")


def get_pkl_path(mid: str) -> str:
    return os.path.join(get_dir(mid), "agent-party.pkl")


def idx2id_health(ntotal: int, docstore_len: int, mapped_len: int) -> dict:
    """S133：faiss 索引 / docstore / idx2id 三方一致性体检（纯函数，可测）。

    mem0 faiss provider 检索时经 idx2id 反查 uuid，查不到即静默丢弃；
    delete 只删 docstore/idx2id 不删 faiss 向量，且 insert 用
    starting_idx=len(idx2id) 分配 int id —— 一旦漂移，后续写入互相
    覆盖映射，大量记忆对检索隐形（日志表现为召回恒为同一两条）。
    """
    orphan = ntotal - mapped_len
    ratio = (orphan / ntotal) if ntotal else 0.0
    return {
        "ntotal": ntotal,
        "docstore": docstore_len,
        "mapped": mapped_len,
        "orphan": orphan,
        "orphan_ratio": ratio,
        "ok": orphan <= max(64, int(ntotal * 0.05)),
    }


def rebuild_idx2id(index_vecs, docstore_keys, query_vecs, tau: float = 0.995):
    """S133：按「向量最近邻匹配」重建 int_pos -> uuid 映射（纯函数，可测）。

    index_vecs: (ntotal, d) float32，faiss 位置序向量；
    docstore_keys: docstore 插入序 uuid 列表；
    query_vecs: (len(docstore_keys), d) 对 docstore 文本重新 embed 的向量；
    返回 (mapping, scores)：贪心一对一（分数降序、位置与 uuid 均不复用），
    cos 相似度 < tau 不建映射（宁可少召回，不可错归因）。
    """
    import numpy as np

    iv = np.asarray(index_vecs, dtype=np.float32)
    qv = np.asarray(query_vecs, dtype=np.float32)
    if iv.ndim != 2 or qv.ndim != 2 or iv.shape[1] != qv.shape[1]:
        raise ValueError("index_vecs/query_vecs must be 2-D with equal dims")
    if qv.shape[0] != len(docstore_keys):
        raise ValueError("query_vecs rows must match docstore_keys length")
    n_iv = np.linalg.norm(iv, axis=1, keepdims=True)
    n_qv = np.linalg.norm(qv, axis=1, keepdims=True)
    iv = iv / np.maximum(n_iv, 1e-9)
    qv = qv / np.maximum(n_qv, 1e-9)

    candidates = []
    chunk = 64
    for start in range(0, qv.shape[0], chunk):
        sim = qv[start:start + chunk] @ iv.T
        k = min(4, iv.shape[0])
        if iv.shape[0] > 1:
            top_i = np.argpartition(sim, sim.shape[1] - k, axis=1)[:, sim.shape[1] - k:]
            top_s = np.take_along_axis(sim, top_i, axis=1)
            order = np.argsort(-top_s, axis=1)
            top_s = np.take_along_axis(top_s, order, axis=1)
            top_i = np.take_along_axis(top_i, order, axis=1)
        else:
            top_s, top_i = sim, np.zeros_like(sim, dtype=np.int64)
        for r in range(top_s.shape[0]):
            ui = start + r
            for s, p in zip(top_s[r], top_i[r]):
                candidates.append((float(s), int(p), ui))

    candidates.sort(key=lambda t: -t[0])
    mapping: dict = {}
    scores: dict = {}
    used_uuid = set()
    for score, pos, ui in candidates:
        if score < tau:
            break
        if pos in mapping or ui in used_uuid:
            continue
        mapping[pos] = docstore_keys[ui]
        scores[docstore_keys[ui]] = score
        used_uuid.add(ui)
    return mapping, scores


def fmt_iso8605_to_local(iso: str) -> str:
    """
    ISO-8601 -> 服务器本地时区 yyyy-MM-dd HH:mm:ss
    """
    try:
        dt = datetime.fromisoformat(iso)      # 读入（可能带时区）
        dt = dt.astimezone()                  # 落到服务器当前时区
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return iso        # 解析失败就原样返回
