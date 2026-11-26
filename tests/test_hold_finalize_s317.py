# S317: 审批/ask 挂起收尾轮不得提交 mem0 记忆提取（半截提取 + 打穿本地网关 KV 前缀缓存）；
# 日记空闲总结在审批挂起期推迟；idleMinutes 下限 5→1。
import pathlib
import sys
from types import SimpleNamespace

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SR = (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8")
SE = (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")


def _req():
    return SimpleNamespace(conversation_id="c1", messages=[], is_sub_agent=False,
                           is_quarantined=False, platform="")


def _fake_m0():
    class M0:
        def __init__(self):
            self.added = []

        def add(self, msgs, **kw):
            self.added.append(msgs)
    return M0()


@pytest.fixture
def submitted(monkeypatch):
    import py.stream_engine as se
    calls = []
    monkeypatch.setattr(se.llm_gate, "submit_memory_job",
                        lambda mid, fn, name="", debounce=0.0, wait_idle=False,
                        conv_key=None:
                        calls.append((name, debounce, wait_idle)) or True)
    return calls


def test_hold_abort_skips_mem0(submitted):
    import py.stream_engine as se
    import asyncio
    m0 = _fake_m0()
    asyncio.run(se._stream_finalize_jobs(_req(), {}, "partial reply", "hi", m0, "mid", {}, True))
    assert submitted == []


def test_normal_turn_still_submits(submitted):
    import py.stream_engine as se
    import asyncio
    m0 = _fake_m0()
    asyncio.run(se._stream_finalize_jobs(_req(), {}, "full reply", "hi", m0, "mid", {}))
    assert len(submitted) == 1 and submitted[0][0] == "mem0-add"


class TestPins:
    def test_stream_response_wiring(self):
        assert "_usage_acc = _hold_abort = None" in SR
        assert "_hold_abort = True; break" in SR
        assert "cur_memory, _hold_abort)" in SR

    def test_engine_gate(self):
        assert "cur_memory, hold_abort=False" in SE
        assert "m0 and not hold_abort and not request.is_sub_agent" in SE
        assert "审批/ask 挂起收尾：本轮跳过记忆提取提交" in SE

    def test_diary_holds_on_pending_approval(self):
        de = (_ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
        assert "from py.approval_store import pending_count" in de
        i = de.index("_appr_held = bool(_apc())")
        assert "has_live_streams() or _appr_held" in de[i:i + 300]

    def test_idle_minutes_floor_one(self):
        pr = (_ROOT / "static" / "templates" / "page_role.html").read_text(encoding="utf-8")
        assert 'chatSummary.idleMinutes" :min="1"' in pr
        de = (_ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
        assert 'idle_min = max(1, int(summary_cfg.get("idleMinutes", 15) or 15))' in de
