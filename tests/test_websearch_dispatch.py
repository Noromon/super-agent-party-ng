# -*- coding: utf-8 -*-
"""搜索引擎/爬虫公告分发 pin（上游 dbaccbf7 并入后回归，S65.1）。"""
import io
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_S = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()


def test_engine_tools_announced_by_engine_key():
    # serper/bochaai/youcom 是 engine 值，公告必须挂 engine==（crawler UI 无这三个值）
    for v in ("serper", "bochaai", "youcom"):
        assert "settings['webSearch']['crawler'] == '%s'" % v not in _S, v
        assert _S.count("settings['webSearch']['engine'] == '%s'" % v) == 4, v  # 2 检索 + 2 公告


def test_real_crawlers_stay_on_crawler_key():
    for v in ("jina", "crawl4ai", "firecrawl"):
        assert "settings['webSearch']['crawler'] == '%s'" % v in _S, v
