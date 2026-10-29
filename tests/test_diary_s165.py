# -*- coding: utf-8 -*-
"""S165: 日记场景注入消歧义（做减法）。

事故（diary 7fb41746 2026-10-29）：①18:53 think 把 18 点后写成「深夜」
（时间锚点被旧日记语料压倒）；②「用户正在使用 diary 软件与你交流」注入与
「用户并没有主动与你说话」正面矛盾，模型消歧为「主人在通过日记跟我对话」；
③「当前与你交流的人的名字为」配置行被缝合杜撰成「宇宙当前与你交流的人的
名字为：」并连续三篇冥想。修复方向=删源+清痕，不加叠句。
"""
import asyncio
import datetime
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import diary_engine  # noqa: E402

_SRC_SERVER = (_ROOT / "server.py").read_text(encoding="utf-8-sig")


class TestStripTraces:
    def test_name_line_variants_stripped(self):
        s = '2026年10月29日 晴 顺着"宇宙当前与你交流的人的名字为：主人"这句话我又发了会儿呆。'
        out = diary_engine._strip_injection_traces(s)
        assert "当前与你交流的人的名字" not in out
        assert "发了会儿呆" in out  # 正文其余保留

    def test_platform_line_stripped(self):
        s = "用户正在使用 diary 软件与你交流（当前对端：主人 <a@b>）然后继续想别的"
        out = diary_engine._strip_injection_traces(s)
        assert "软件与你交流" not in out

    def test_system_notice_stripped(self):
        out = diary_engine._strip_injection_traces("【系统提示】上面的工具结果已收到。尾巴")
        assert "【系统提示】" not in out

    def test_normal_prose_untouched(self):
        for s in ("下午三点，主人大概忙去了，我还在琢磨那行字。",
                  "主人今天会想知道这个的，我等会儿讲给他听。",
                  "风把窗帘吹起来一点点，又放下了。"):
            assert diary_engine._strip_injection_traces(s) == s

    def test_empty_safe(self):
        assert diary_engine._strip_injection_traces("") == ""
        assert diary_engine._strip_injection_traces(None) is None


class TestSeedFallback:
    def test_pure_injection_prev_entry_falls_back_to_pool(self, monkeypatch):
        async def fake_recent(book_id, n=1):
            return [{"content": "当前与你交流的人的名字为：主人", "time": "2026-10-29T20:00:00"}]

        monkeypatch.setattr(diary_engine, "get_recent_diary_entries", fake_recent)
        seed = asyncio.run(diary_engine.build_recall_seed("b", prev_ratio=1.0))
        assert seed in diary_engine.RECALL_SEEDS

    def test_normal_prev_entry_still_quoted(self, monkeypatch):
        async def fake_recent(book_id, n=1):
            return [{"content": "风把窗帘吹起来一点点，又放下了。就这样吧。",
                     "time": "2026-10-29T20:00:00"}]

        monkeypatch.setattr(diary_engine, "get_recent_diary_entries", fake_recent)
        seed = asyncio.run(diary_engine.build_recall_seed("b", prev_ratio=1.0))
        assert seed.startswith("上一篇日记你写到「风把窗帘吹起来")


class TestTodayContextFilter:
    def test_entry_head_filtered_before_injection(self, monkeypatch):
        async def fake_recent(book_id, n=40):
            return [{"type": "chatSummary", "time": "2026-10-29T18:52:46",
                     "content": "用户正在使用 diary 软件与你交流 主人来聊了生图的事"},
                    {"type": "think", "time": "2026-10-29T18:53:09",
                     "content": "当前与你交流的人的名字为：主人 于是我开始发呆"}]

        async def no_mem():
            return []

        monkeypatch.setattr(diary_engine, "get_recent_diary_entries", fake_recent)
        monkeypatch.setattr(diary_engine, "_fetch_today_new_memories", no_mem)
        block = asyncio.run(diary_engine.build_today_context(
            "b", now=datetime.datetime(2026, 10, 29, 18, 55)))
        assert "软件与你交流" not in block
        assert "当前与你交流的人的名字" not in block
        assert "主人来聊了生图的事" in block  # 真实互动内容保留


class TestServerWiringPins:
    def test_diary_skips_platform_dialogue_block(self):
        assert 'if request.is_app_bot and request.platform and request.platform != "diary":' in _SRC_SERVER

    def test_diary_skips_name_line(self):
        assert ('if settings["memorySettings"]["userName"] and '
                'settings["memorySettings"]["userName"] != "user" and '
                'getattr(request, "platform", "") != "diary"') in _SRC_SERVER

    def test_daynight_clause_in_diary_system(self):
        eng = (_ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
        assert "日夜晨昏的判断只以当前时间为准" in eng
