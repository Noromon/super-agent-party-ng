# -*- coding: utf-8 -*-
"""S218: 旁观主动发言——防骚扰闸门纯函数 + behavior 平台通道投递（全 mock 零真机）。

钉：五道闸门（enabled/importance/冷却/日限额跨天归零/静默时段跨夜支持）、
平台求交、合成事件 S73 无工具安全钉与空回复吞掉出口、状态持久化损坏容错、
watcher 投递集成（handler 契约空 chat_id=平台展开用户目标；冷却生效；
无平台不计额度；发言失败不炸观察链路）。
"""
import asyncio
import datetime
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import screen_speak as sp  # noqa: E402
from py import screen_watcher as sw  # noqa: E402

_WATCHER_SRC = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8-sig")


def _ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def _ev(imp=5, summary="编译错误弹窗"):
    return {"ts": _ts(2026, 11, 14, 10), "iso": "x", "title": "VS Code",
            "summary": summary, "activity": "coding", "importance": imp, "took_s": 0.4}


class TestShouldSpeak:
    CFG = {"enabled": True}

    def test_master_switch(self):
        ok, why = sp.should_speak({}, _ev(), {}, _ts(2026, 11, 14, 10))
        assert not ok and why == "speak 未启用"

    def test_importance_threshold(self):
        now = _ts(2026, 11, 14, 10)
        ok, why = sp.should_speak(self.CFG, _ev(3), {}, now)
        assert not ok and "阈值" in why
        ok, _ = sp.should_speak(self.CFG, _ev(None), {}, now)
        assert not ok
        ok, _ = sp.should_speak({"enabled": True, "minImportance": 3}, _ev(3), {}, now)
        assert ok

    def test_cooldown_and_daily_limit_with_day_rollover(self):
        now = _ts(2026, 11, 14, 10)
        st = {"date": "2026-11-14", "count": 0, "last_ts": now - 300}
        ok, why = sp.should_speak(self.CFG, _ev(), st, now)  # 默认冷却 600s
        assert not ok and why == "冷却中"
        st["last_ts"] = now - 700
        assert sp.should_speak(self.CFG, _ev(), st, now)[0]
        st["count"] = 5
        ok, why = sp.should_speak(self.CFG, _ev(), st, now)
        assert not ok and "额度" in why
        st["date"] = "2026-11-13"  # 跨天：原地归零后放行
        assert sp.should_speak(self.CFG, _ev(), st, now)[0]
        assert st["count"] == 0 and st["date"] == "2026-11-14"

    def test_quiet_window_including_overnight(self):
        cfg_q = {"enabled": True}
        assert not sp.should_speak(cfg_q, _ev(), {}, _ts(2026, 11, 14, 2))[0]  # 默认 0-8
        assert sp.should_speak(cfg_q, _ev(), {}, _ts(2026, 11, 14, 9))[0]
        overnight = {"enabled": True, "quietStart": 22, "quietEnd": 8}
        assert not sp.should_speak(overnight, _ev(), {}, _ts(2026, 11, 14, 23))[0]
        assert not sp.should_speak(overnight, _ev(), {}, _ts(2026, 11, 14, 3))[0]
        assert sp.should_speak(overnight, _ev(), {}, _ts(2026, 11, 14, 12))[0]
        off = {"enabled": True, "quietStart": 8, "quietEnd": 8}  # 相等=关闭静默
        assert sp.should_speak(off, _ev(), {}, _ts(2026, 11, 14, 3))[0]

    def test_record_sent(self):
        now = _ts(2026, 11, 14, 10)
        st = {}
        sp.record_sent(st, now)
        sp.record_sent(st, now + 1)
        assert st == {"date": "2026-11-14", "count": 2, "last_ts": now + 1}


class TestTargetsAndItem:
    def test_target_platforms(self):
        assert sp.target_platforms({}, ["xmpp", "telegram"]) == ["xmpp", "telegram"]
        assert sp.target_platforms({"platforms": ["xmpp", "line"]},
                                   ["xmpp"]) == ["xmpp"]
        assert sp.target_platforms({"platforms": "垃圾"}, ["xmpp"]) == ["xmpp"]
        assert sp.target_platforms({"platforms": ["line"]}, ["xmpp"]) == []

    def test_behavior_item_safety_pins(self):
        item = sp.build_behavior_item(_ev())
        assert item.tools_override() == {"enable_tools": []}  # S73：旁观发言无工具
        p = item.action.prompt
        assert "VS Code" in p and "编译错误弹窗" in p and "重要度 5" in p
        assert "只回复一个空格" in p  # 空回复吞掉=模型静默出口

    def test_state_io_roundtrip_and_corrupt(self, tmp_path):
        p = tmp_path / "speak_state.json"
        assert sp.load_state(p) == {}
        sp.save_state({"count": 2}, p)
        assert sp.load_state(p) == {"count": 2}
        p.write_text("{坏文件", encoding="utf-8")
        assert sp.load_state(p) == {}


class TestWatcherDispatch:
    @pytest.fixture()
    def wired(self, tmp_path, monkeypatch):
        from py.behavior_engine import global_behavior_engine
        e = sw.global_screen_watcher
        e.update_config({"speak": {"enabled": True, "minImportance": 4}})
        monkeypatch.setattr(sp, "SCREEN_WATCH_DIR", str(tmp_path))
        calls = []

        async def spy(chat_id, item):
            calls.append((chat_id, item))
        monkeypatch.setattr(global_behavior_engine, "handlers", {"xmpp": spy})
        yield e, calls, tmp_path
        e.update_config({})

    def _run(self, e, ev):
        async def go():
            await e._maybe_speak(ev)
            await asyncio.sleep(0.05)
        asyncio.run(go())

    def test_high_importance_dispatches_with_empty_chat_id(self, wired):
        e, calls, tmp_path = wired
        self._run(e, _ev())
        assert len(calls) == 1
        chat_id, item = calls[0]
        assert chat_id == ""  # 空目标=平台展开用户配置行为目标（S71 语义）
        assert "编译错误弹窗" in item.action.prompt
        state = json.loads((tmp_path / "speak_state.json").read_text(encoding="utf-8"))
        assert state["count"] == 1

    def test_second_event_blocked_by_cooldown(self, wired):
        e, calls, _ = wired
        self._run(e, _ev())
        self._run(e, _ev(5, "又一个错误"))
        assert len(calls) == 1

    def test_low_importance_and_disabled_silent(self, wired):
        e, calls, _ = wired
        self._run(e, _ev(2))
        e.update_config({"speak": {"enabled": False}})
        self._run(e, _ev())
        assert calls == []

    def test_no_platform_no_quota_consumed(self, wired, monkeypatch):
        from py.behavior_engine import global_behavior_engine
        e, calls, tmp_path = wired
        monkeypatch.setattr(global_behavior_engine, "handlers", {})
        self._run(e, _ev())
        assert calls == []
        assert not (tmp_path / "speak_state.json").exists()  # 未投递不记额度

    def test_handler_boom_does_not_reach_caller(self, wired, monkeypatch):
        from py.behavior_engine import global_behavior_engine
        e, _, _ = wired

        async def boom(chat_id, item):
            raise RuntimeError("bot down")
        monkeypatch.setattr(global_behavior_engine, "handlers", {"xmpp": boom})
        self._run(e, _ev())  # 不抛出即通过


class TestPins:
    def test_watcher_wired(self):
        # S225：附截图后调用带 attach_b64 形参；钉死观察链路仍接线发言
        assert "await self._maybe_speak(ev, attach_b64)" in _WATCHER_SRC

    def test_state_persisted_survives_restart(self):
        src = (_ROOT / "py" / "screen_speak.py").read_text(encoding="utf-8-sig")
        assert "speak_state.json" in src
