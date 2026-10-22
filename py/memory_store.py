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
