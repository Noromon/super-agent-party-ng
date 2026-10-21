# -*- coding: utf-8 -*-
"""faiss 记忆存储层（批 2h2 自 server.py 迁出）。

memory_id → (faiss index, meta dict) 的读写与形状互转；"timetamp" 为
历史拼写的响应键（前端契约），保持原样。
消费方：py/routers/memories.py、server.py 记忆管线。
"""
import os
import pickle
from datetime import datetime
from typing import Any, Dict, List

from fastapi import HTTPException

from py.get_setting import MEMORY_CACHE_DIR


def get_dir(mid: str) -> str:
    return os.path.join(MEMORY_CACHE_DIR, mid)


def get_faiss_path(mid: str) -> str:
    return os.path.join(get_dir(mid), "agent-party.faiss")


def get_pkl_path(mid: str) -> str:
    return os.path.join(get_dir(mid), "agent-party.pkl")


def load_index_and_meta(mid: str):
    import faiss
    fpath, ppath = get_faiss_path(mid), get_pkl_path(mid)
    if not (os.path.exists(fpath) and os.path.exists(ppath)):
        raise HTTPException(status_code=404, detail="memory not found")
    index = faiss.read_index(fpath)
    with open(ppath, "rb") as f:
        raw = pickle.load(f)          # 可能是 tuple 也可能是 dict
    # 兼容旧数据：如果是 tuple 取第 0 个，否则直接用
    meta_dict = raw[0] if isinstance(raw, tuple) else raw
    return index, meta_dict


def save_index_and_meta(mid: str, index, meta: List[Dict[Any, Any]]):
    import faiss
    faiss.write_index(index, get_faiss_path(mid))
    with open(get_pkl_path(mid), "wb") as f:
        pickle.dump(meta, f)


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


def flatten_records(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    flat = []
    for uuid, rec in meta.items():
        flat.append({
            "idx"        : len(flat),
            "uuid"       : uuid,
            "text"       : rec["data"],
            "created_at" : fmt_iso8605_to_local(rec["created_at"]),
            "timetamp"   : rec["timetamp"],
        })
    return flat


def dict_to_list(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    """有序化，保证顺序与 Faiss 索引一致"""
    return [{uuid: rec} for uuid, rec in meta.items()]


def list_to_dict(meta_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """列表再压回 dict"""
    new_meta = {}
    for item in meta_list:
        uuid, rec = next(iter(item.items()))
        new_meta[uuid] = rec
    return new_meta
