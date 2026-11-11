# -*- coding: utf-8 -*-
"""S208：日记时间感知修复。

根因（实锤）：注入只有 24h 字符串，本地模型换算失守且 11-11 的日期「11」与
分钟拼成 11:29/11:46（21:29→「快11点半」、22:46→「11点快四十五分」）；种子
引子再把上一篇的（错误）时刻行喂回下一篇自复制。
方案：三处注入点改双格式（24h + cn_clock_time 中文 12h）；种子剥离首行时间头。
"""
import asyncio
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_system as ds  # noqa: E402
import py.diary_engine as de  # noqa: E402

ENGINE = (_ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
CHAT = (_ROOT / "py" / "diary_chat_integration.py").read_text(encoding="utf-8")
UTIL = (_ROOT / "py" / "utility_tools.py").read_text(encoding="utf-8")


def _dt(h, m):
    return datetime(2026, 11, 11, h, m)


class TestCnClock:
    def test_all_periods(self):
        assert ds.cn_clock_time(_dt(0, 30)) == "凌晨十二点半"
        assert ds.cn_clock_time(_dt(0, 5)) == "凌晨十二点五分"
        assert ds.cn_clock_time(_dt(6, 0)) == "早上六点整"
        assert ds.cn_clock_time(_dt(9, 15)) == "上午九点一刻"
        assert ds.cn_clock_time(_dt(12, 45)) == "中午十二点四十五分"
        assert ds.cn_clock_time(_dt(13, 0)) == "下午一点整"
        assert ds.cn_clock_time(_dt(16, 59)) == "下午四点五十九分"
        assert ds.cn_clock_time(_dt(17, 30)) == "傍晚五点半"
        assert ds.cn_clock_time(_dt(18, 30)) == "傍晚六点半"
        assert ds.cn_clock_time(_dt(19, 18)) == "晚上七点十八分"
        assert ds.cn_clock_time(_dt(20, 15)) == "晚上八点一刻"
        assert ds.cn_clock_time(_dt(21, 29)) == "晚上九点二十九分"
        assert ds.cn_clock_time(_dt(22, 0)) == "晚上十点整"
        assert ds.cn_clock_time(_dt(23, 59)) == "晚上十一点五十九分"

    def test_minute_edges(self):
        assert ds.cn_clock_time(_dt(20, 10)) == "晚上八点十分"
        assert ds.cn_clock_time(_dt(20, 11)) == "晚上八点十一分"
        assert ds.cn_clock_time(_dt(20, 5)) == "晚上八点五分"


class TestTimeHead:
    def test_headers_detected(self):
        for line in ("11月11日晚，快11点半了。", "晚上十点一刻，屋里很静。",
                     "2026-11-11 星期三 · 晨间独白", "2026-11-11，深夜。",
                     "11月11日 晴", "下午四点差两分",
                     "2026年11月11日 星期三 · 午后补记"):
            assert de._looks_like_time_head(line), line

    def test_non_headers(self):
        for line in ("今天下午发呆的时候，我顺着激光往下摸，",
                     "今天学到一点新东西，觉得有意思",
                     "x" * 41 + " 晚上八点", "。", ""):
            assert not de._looks_like_time_head(line), line


class TestSeed:
    def test_time_head_stripped(self, monkeypatch):
        async def fake_recent(book_id, n=5):
            return [{"content": "11月11日晚，快11点半了。\n\n"
                                "下午主人问起 Qwen4 的消息，我晚上特意又搜了一圈。"}]
        monkeypatch.setattr(de, "get_recent_diary_entries", fake_recent)
        monkeypatch.setattr(de.random, "random", lambda: 0.1)
        seed = asyncio.run(de.build_recall_seed("x"))
        assert "快11点半" not in seed
        assert "下午主人问起" in seed
        assert "旧篇当时" in seed

    def test_no_head_kept_as_is(self, monkeypatch):
        async def fake_recent(book_id, n=5):
            return [{"content": "今天下午发呆的时候，我顺着激光往下摸。"}]
        monkeypatch.setattr(de, "get_recent_diary_entries", fake_recent)
        monkeypatch.setattr(de.random, "random", lambda: 0.1)
        seed = asyncio.run(de.build_recall_seed("x"))
        assert "激光" in seed

    def test_word_pool_fallback(self, monkeypatch):
        monkeypatch.setattr(de.random, "random", lambda: 0.9)
        seed = asyncio.run(de.build_recall_seed("x"))
        assert "「" not in seed


class TestInjectionPins:
    def test_engine_dual_format(self):
        assert "cn_clock_time(now)" in ENGINE
        assert "不要自行换算" in ENGINE

    def test_chat_summary_dual_format(self):
        assert "cn_clock_time(now_dt)" in CHAT

    def test_time_tool_dual_format(self):
        assert "cn_clock_time(now)" in UTIL
