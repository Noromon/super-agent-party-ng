# -*- coding: utf-8 -*-
"""S232：日记触发计时器繁忙暂停开关。

覆盖：agent_activity 计数器语义；触发点 busy→挂起(不消费排程/不执行)；
开关关闭保持旧行为；空闲正常触发；chatSummary 门控纳入开关；静态链路。
"""
import asyncio
import os
import pathlib
import sys
import tempfile
import time

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s232_")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_engine as de  # noqa: E402
from py.agent_activity import begin, end, in_flight, is_agent_busy  # noqa: E402

ROOT = _ROOT


# ---------------- agent_activity 语义 ----------------

def test_activity_counter_semantics():
    base = in_flight()
    assert is_agent_busy() == (base > 0)
    begin()
    try:
        assert in_flight() == base + 1
        assert is_agent_busy()
        begin()
        assert in_flight() == base + 2
    finally:
        end()
        end()
    assert in_flight() == base


def test_activity_end_below_zero_clamped():
    base = in_flight()
    end()
    end()
    assert in_flight() == base


# ---------------- 触发点挂起 ----------------

def _mk_engine(monkeypatch, cfg, busy_streams=False, busy_requests=False):
    eng = de.DiaryEngine()  # 单例：显式重置共享状态
    eng._chat_summary_task = None
    eng._busy = False
    base = {"enabled": True, "quietStart": 5, "quietEnd": 5, "minMinutes": 10, "maxMinutes": 60}
    base.update(cfg)
    eng.config = base
    eng._last_chat_summary_check = time.time()  # 跳过总结分支，聚焦触发逻辑
    monkeypatch.setattr(de, "has_live_streams", lambda: busy_streams)
    monkeypatch.setattr(de, "is_agent_busy", lambda: busy_requests)
    fires, scheds = [], []

    async def _fake_run(action):
        fires.append(action)

    eng._run_action = _fake_run
    monkeypatch.setattr(eng, "_pick_action", lambda: "think")
    monkeypatch.setattr(eng, "_schedule_next", lambda: scheds.append(1))
    return eng, fires, scheds


def _fire_now(eng):
    eng.next_run = time.time() - 1


def test_pause_on_stream_busy_defers_without_consuming_schedule(monkeypatch):
    eng, fires, scheds = _mk_engine(monkeypatch, {}, busy_streams=True)
    _fire_now(eng)
    before = time.time()
    asyncio.run(eng._tick())
    assert fires == []
    assert scheds == []  # 排程未被消费：暂停而非跳过
    assert before + 50 <= eng.next_run <= before + 70


def test_pause_on_nonstream_request_busy(monkeypatch):
    eng, fires, scheds = _mk_engine(monkeypatch, {}, busy_requests=True)
    _fire_now(eng)
    asyncio.run(eng._tick())
    assert fires == []
    assert scheds == []
    assert eng.next_run > time.time()


def test_switch_off_keeps_old_behavior_when_busy(monkeypatch):
    eng, fires, scheds = _mk_engine(
        monkeypatch, {"pauseOnBusy": False}, busy_streams=True, busy_requests=True)
    _fire_now(eng)
    asyncio.run(eng._tick())
    assert fires == ["think"]
    assert scheds == [1]


def test_idle_triggers_with_switch_on(monkeypatch):
    eng, fires, scheds = _mk_engine(monkeypatch, {"pauseOnBusy": True})
    _fire_now(eng)
    asyncio.run(eng._tick())
    assert fires == ["think"]
    assert scheds == [1]


def test_not_yet_due_untouched(monkeypatch):
    eng, fires, scheds = _mk_engine(monkeypatch, {}, busy_streams=True)
    eng.next_run = time.time() + 300
    asyncio.run(eng._tick())
    assert fires == []
    assert eng.next_run > time.time() + 200


# ---------------- chatSummary 门控 ----------------

def _summary_setup(monkeypatch, cfg, busy_streams, busy_requests):
    eng = de.DiaryEngine()  # 单例：显式重置共享状态
    eng._chat_summary_task = None
    eng._busy = False
    base = {"enabled": True, "quietStart": 5, "quietEnd": 5}
    base.update(cfg)
    eng.config = base
    eng._last_chat_summary_check = 0.0
    eng.next_run = time.time() + 9999  # 隔离：不触发日记动作
    calls = []

    async def _fake_summarize(*a, **k):
        calls.append(1)

    monkeypatch.setattr(de, "summarize_and_save_buffers", _fake_summarize)
    monkeypatch.setattr(de, "has_live_streams", lambda: busy_streams)
    monkeypatch.setattr(de, "is_agent_busy", lambda: busy_requests)
    return eng, calls


def test_summary_blocked_by_nonstream_busy_when_switch_on(monkeypatch):
    eng, calls = _summary_setup(monkeypatch, {"pauseOnBusy": True}, False, True)
    asyncio.run(eng._tick())
    assert eng._chat_summary_task is None  # 门控拦截，未放行总结任务


def test_summary_runs_when_switch_off_even_if_requests_inflight(monkeypatch):
    eng, calls = _summary_setup(monkeypatch, {"pauseOnBusy": False}, False, True)
    asyncio.run(eng._tick())
    assert eng._chat_summary_task is not None  # 开关关=旧行为，照跑
    eng._chat_summary_task.cancel()


def test_summary_still_blocked_by_live_streams_regardless(monkeypatch):
    eng, calls = _summary_setup(monkeypatch, {"pauseOnBusy": False}, True, False)
    asyncio.run(eng._tick())
    assert eng._chat_summary_task is None


# ---------------- 静态链路 ----------------

def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


def test_server_endpoint_counts_inflight():
    src = _read("server.py")
    assert "from py import agent_activity as _agent_activity" in src
    assert '_counted = (getattr(request, "platform", "") or "") != "diary"' in src
    assert "_agent_activity.begin()" in src
    assert "_agent_activity.end()" in src
    assert "async def _chat_endpoint_impl(request: ChatRequest, fastapi_request: Request)" in src


def test_defaults_and_ui_and_i18n():
    assert '"pauseOnBusy": true' in _read("config", "settings_template.json")
    assert "pauseOnBusy: true" in _read("static", "js", "data", "60_cards_options.js")
    tpl = _read("static", "templates", "page_role.html")
    assert 'v-model="diarySettings.pauseOnBusy"' in tpl
    for loc in ("zh-CN", "en-US"):
        s = _read("static", "js", "locales", f"{loc}.js")
        assert "diaryPauseOnBusy" in s and "diaryPauseOnBusyHint" in s


def test_stamp_s232():
    assert "build=S294" in _read("static", "js", "renderer.js")
