# -*- coding: utf-8 -*-
"""S216: 旁观记忆层（screen_memory）——48h 明细清理 / 30 天摘要 / 本地聚合摘要 / 检索。

纯本地零 LLM 零网络（用源码 import 棘轮钉死）；摘要为确定性规则聚合，
LLM 风格化留给 S217。watcher tick 维护挂钩钉桩：不受 enabled 支配、
每小时节流、失败容错。全部走显式 log_path/out_dir 参数，零真实数据目录触碰。
"""
import asyncio
import datetime
import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import screen_memory as sm  # noqa: E402
from py import screen_watcher as sw  # noqa: E402

_MEM_SRC = (_ROOT / "py" / "screen_memory.py").read_text(encoding="utf-8-sig")


def _ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def _ev(ts, summary="打开了页面", activity="browsing", importance=1, title="Chrome"):
    return {"ts": ts, "iso": "x", "title": title, "summary": summary,
            "activity": activity, "importance": importance, "took_s": 0.3}


def _write_log(path, events):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
                    encoding="utf-8")


class TestLoadEvents:
    def test_missing_file(self, tmp_path):
        assert sm.load_events(log_path=tmp_path / "none.jsonl") == []

    def test_window_and_bad_lines(self, tmp_path):
        p = tmp_path / "screen_log.jsonl"
        p.write_text(
            json.dumps(_ev(_ts(2026, 11, 10, 9))) + "\n"
            "坏行不是json\n"
            + json.dumps([1, 2]) + "\n"
            + json.dumps({"summary": "没有ts"}) + "\n"
            + json.dumps(_ev(_ts(2026, 11, 14, 9))) + "\n",
            encoding="utf-8")
        evs = sm.load_events(log_path=p)
        assert len(evs) == 2
        assert len(sm.load_events(since_ts=_ts(2026, 11, 12, 0), log_path=p)) == 1
        assert sm.load_events(since_ts=_ts(2026, 11, 15, 0), log_path=p) == []
        assert len(sm.load_events(until_ts=_ts(2026, 11, 12, 0), log_path=p)) == 1


class TestPrune:
    def test_prune_keeps_window_drops_bad(self, tmp_path):
        now = _ts(2026, 11, 14, 12)
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(now - 3 * 3600), _ev(now - 60 * 3600)])
        p.write_text(p.read_text(encoding="utf-8") + "坏行\n", encoding="utf-8")
        assert sm.prune_old_events(48, now=now, log_path=p) == 2  # 60h 事件+坏行
        assert len(sm.load_events(log_path=p)) == 1
        assert sm.prune_old_events(48, now=now, log_path=p) == 0  # 幂等
        assert len(sm.load_events(log_path=p)) == 1

    def test_prune_custom_retention(self, tmp_path):
        now = _ts(2026, 11, 14, 12)
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(now - 10 * 3600), _ev(now - 3600)])
        assert sm.prune_old_events(8, now=now, log_path=p) == 1
        assert len(sm.load_events(log_path=p)) == 1

    def test_digest_retention(self, tmp_path):
        now = _ts(2026, 11, 14, 12)
        (tmp_path / "screen_digest_2026-11-13.md").write_text("x", encoding="utf-8")
        (tmp_path / "screen_digest_2026-09-01.md").write_text("x", encoding="utf-8")
        (tmp_path / "screen_digest_垃圾.md").write_text("x", encoding="utf-8")
        (tmp_path / "screen_log.jsonl").write_text("x", encoding="utf-8")
        assert sm.prune_old_digests(30, now=now, out_dir=tmp_path) == 1
        assert (tmp_path / "screen_digest_2026-11-13.md").exists()
        assert (tmp_path / "screen_digest_垃圾.md").exists()  # 坏名不清，宁保守
        assert (tmp_path / "screen_log.jsonl").exists()


class TestDigest:
    def _day_events(self, tmp_path):
        d = _ts(2026, 11, 13, 0)
        _write_log(tmp_path / "screen_log.jsonl", [
            _ev(d + 2 * 3600, summary="深夜挂机", activity="idle"),
            _ev(d + 10 * 3600, summary="写 s216 记忆层", activity="coding", importance=3),
            _ev(d + 11 * 3600, summary="编译错误弹窗", activity="coding",
                importance=5, title="Visual Studio Code"),
            _ev(_ts(2026, 11, 12, 12), summary="不该进摘要", activity="chatting"),
        ])

    def test_digest_sections_and_date_isolation(self, tmp_path):
        self._day_events(tmp_path)
        made = sm.build_daily_digest("2026-11-13", out_dir=tmp_path,
                                     log_path=tmp_path / "screen_log.jsonl")
        assert made and Path(made).name == "screen_digest_2026-11-13.md"
        md = Path(made).read_text(encoding="utf-8")
        assert "2026-11-13" in md and "事件总数: 3" in md
        assert "编译错误弹窗" in md and "importance 5" in md
        assert "活动分布" in md and "时段概览" in md and "高频窗口" in md
        assert "不该进摘要" not in md

    def test_empty_and_idempotent_and_force(self, tmp_path):
        _write_log(tmp_path / "screen_log.jsonl", [_ev(_ts(2026, 11, 13, 9))])
        log = tmp_path / "screen_log.jsonl"
        assert sm.build_daily_digest("2026-10-01", out_dir=tmp_path, log_path=log) is None
        assert sm.build_daily_digest("2026-11-13", out_dir=tmp_path, log_path=log)
        assert sm.build_daily_digest("2026-11-13", out_dir=tmp_path, log_path=log) is None
        assert sm.build_daily_digest("2026-11-13", out_dir=tmp_path,
                                     log_path=log, force=True)


class TestSearch:
    def test_query_window_limit(self, tmp_path):
        now = _ts(2026, 11, 14, 12)
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [
            _ev(now - 100 * 3600, summary="很久前的编译", activity="coding"),
            _ev(now - 4 * 3600, summary="Python 报错堆栈", activity="coding"),
            _ev(now - 2 * 3600, summary="聊天窗口", activity="chatting", title="Discord"),
            _ev(now - 3600, summary="python.org 页面", activity="browsing"),
        ])
        assert [e["summary"] for e in
                sm.search_events("python 报错", now=now, log_path=p)] == \
            ["python.org 页面", "Python 报错堆栈"]  # any 命中 + 新→旧
        assert sm.search_events("聊天", now=now, window_hours=1, log_path=p) == []
        assert sm.search_events("编译 browsing", now=now, window_hours=200, log_path=p)
        assert sm.search_events("   ", now=now, log_path=p) == []
        assert len(sm.search_events("e", now=now, window_hours=200, limit=1, log_path=p)) == 1


class TestMaintain:
    def test_full_maintenance_cycle(self, tmp_path):
        now = _ts(2026, 11, 14, 14)
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(now - 100 * 3600, summary="过期明细"),
                       _ev(_ts(2026, 11, 13, 10), summary="昨天的编译", activity="coding",
                           importance=5)])
        (tmp_path / "screen_digest_2026-01-01.md").write_text("x", encoding="utf-8")
        res = sm.maintain({}, now=now, out_dir=tmp_path, log_path=p)
        assert res["pruned"] == 1 and res["digests_pruned"] == 1
        assert res["digest"] == "screen_digest_2026-11-13.md"
        md = (tmp_path / "screen_digest_2026-11-13.md").read_text(encoding="utf-8")
        assert "昨天的编译" in md
        # 幂等：无新料再跑零动作
        res2 = sm.maintain({}, now=now + 3600, out_dir=tmp_path, log_path=p)
        assert res2["pruned"] == 0 and "digest" not in res2

    def test_before_digest_hour_no_digest(self, tmp_path):
        now = _ts(2026, 11, 14, 2)  # 凌晨2点 < digestHour=4：不产昨日摘要
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(_ts(2026, 11, 13, 10), summary="昨天的编译")])
        res = sm.maintain({}, now=now, out_dir=tmp_path, log_path=p)
        assert "digest" not in res and list(tmp_path.iterdir()) == [p]

    def test_custom_digest_hour(self, tmp_path):
        now = _ts(2026, 11, 14, 2)
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(_ts(2026, 11, 13, 10), summary="昨天的编译")])
        res = sm.maintain({"digestHour": 1}, now=now, out_dir=tmp_path, log_path=p)
        assert res["digest"] == "screen_digest_2026-11-13.md"


class TestWatcherHook:
    @pytest.fixture()
    def eng(self, monkeypatch):
        e = sw.global_screen_watcher
        e.update_config({"intervalSeconds": 2})
        e._last_maintain = 0.0
        e._last_capture = 0.0
        e._cooldown_until = 0.0
        calls = []
        monkeypatch.setattr(sw.screen_memory, "maintain",
                            lambda cfg, **kw: calls.append(cfg))
        yield e, calls
        e.update_config({})
        e._last_maintain = 0.0

    def _tick(self, e):
        asyncio.run(e._tick())

    def test_maintain_runs_even_when_disabled(self, eng):
        e, calls = eng  # config 无 enabled：默认关闭
        self._tick(e)
        assert len(calls) == 1 and calls[0].get("intervalSeconds") == 2

    def test_maintain_throttled(self, eng):
        e, calls = eng
        self._tick(e)
        self._tick(e)
        assert len(calls) == 1  # maintainSeconds 节流内不重复

    def test_maintain_failure_swallowed(self, eng, monkeypatch):
        e, _ = eng

        def boom(cfg, **kw):
            raise RuntimeError("disk gone")
        monkeypatch.setattr(sw.screen_memory, "maintain", boom)
        self._tick(e)  # 不抛出即通过；下一小时可再试
        assert e._last_maintain > 0

    def test_capture_gate_still_after_maintain(self, eng):
        e, calls = eng
        e._last_capture = time.time()  # 间隔未到
        self._tick(e)
        assert len(calls) == 1 and e._observe_task is None


class TestPurityPins:
    def test_memory_layer_has_no_network_or_llm(self):
        for banned in ("openai", "acreate", "httpx", "requests", "AsyncOpenAI",
                       "llm_gate", "load_settings"):
            assert banned not in _MEM_SRC, banned

    def test_watcher_wired_to_maintain(self):
        src = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8-sig")
        assert "screen_memory.maintain" in src
        assert "不受 enabled" in src
