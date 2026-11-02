# -*- coding: utf-8 -*-
"""S189 观测面：保存通道与 sanitizer 的留痕纪律。

2026-11-01 事故复盘：delta 保存异常被外层吞 + sanitize_tool_chains 不带 log =
上下文"蒸发"一夜零痕迹。本包钉桩：任何丢弃/失败/落盘必须留下可 grep 的一行。
"""
import asyncio
import logging
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

_SRV = None


def srv():
    global _SRV
    if _SRV is None:
        import server
        _SRV = server
    return _SRV


def _cb():
    from py.context_builder import sanitize_tool_chains, sanitize_tool_chains_logged
    return sanitize_tool_chains, sanitize_tool_chains_logged


class _FakeWSManager:
    def __init__(self):
        self.sent = []

    async def send_json(self, obj, websocket):
        self.sent.append(obj)


@pytest.fixture()
def fake_ws(monkeypatch):
    fm = _FakeWSManager()
    monkeypatch.setattr(srv(), "ws_manager", fm)
    return fm


async def _noop_safety(covs):
    return None


def test_delta_failure_returns_save_error_and_logs(monkeypatch, fake_ws, caplog):
    async def _boom(_covs):
        raise RuntimeError("disk on fire")

    async def _empty():
        return {"conversations": []}

    monkeypatch.setattr(srv(), "_sanitize_conversations_safety", _noop_safety)
    monkeypatch.setattr(srv(), "load_covs", _empty)
    monkeypatch.setattr(srv(), "save_covs", _boom)
    with caplog.at_level(logging.INFO):
        asyncio.run(srv()._ws_save_conversations_delta(
            object(), {"correlationId": "cid-1",
                       "data": {"conversations": [{"id": "c1", "messages": []}]}}))
    assert fake_ws.sent[-1]["type"] == "save_error"
    assert fake_ws.sent[-1]["correlationId"] == "cid-1"
    assert "disk on fire" in fake_ws.sent[-1]["error"]
    assert any("[Covs] delta 保存失败" in r.getMessage() for r in caplog.records)


def test_delta_success_returns_ack_and_logs(monkeypatch, fake_ws, caplog):
    saved = {}

    async def _ok(_covs):
        saved["done"] = True

    async def _empty():
        return {"conversations": []}

    monkeypatch.setattr(srv(), "_sanitize_conversations_safety", _noop_safety)
    monkeypatch.setattr(srv(), "load_covs", _empty)
    monkeypatch.setattr(srv(), "save_covs", _ok)
    with caplog.at_level(logging.INFO):
        asyncio.run(srv()._ws_save_conversations_delta(
            object(), {"correlationId": "cid-2",
                       "data": {"conversations": [{"id": "c1", "messages": []}]}}))
    assert saved.get("done") is True
    assert fake_ws.sent[-1]["type"] == "conversations_delta_saved"
    assert any("[Covs] delta 保存 rows=1" in r.getMessage() for r in caplog.records)


def test_sanitizer_logged_matches_plain_and_logs_counts(caplog):
    sanitize_tool_chains, sanitize_tool_chains_logged = _cb()
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "orphan-1", "content": "x"},
        {"role": "assistant", "content": "   "},
        {"role": "assistant", "content": "ok"},
    ]
    expect = sanitize_tool_chains([dict(m) for m in msgs])
    with caplog.at_level(logging.INFO, logger="app"):
        out = sanitize_tool_chains_logged(msgs)
    assert out == expect
    line = [r.getMessage() for r in caplog.records if "Sanitizer 丢弃" in r.getMessage()]
    assert len(line) == 1
    assert "1 孤tool" in line[0] and "1 幽灵assistant" in line[0]
    assert "4 -> 2 条" in line[0]


def test_sanitizer_logged_silent_when_clean(caplog):
    _, sanitize_tool_chains_logged = _cb()
    msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]
    with caplog.at_level(logging.INFO, logger="app"):
        sanitize_tool_chains_logged(msgs)
    assert not [r for r in caplog.records if "Sanitizer" in r.getMessage()]


def test_save_covs_logs_size_and_ms(tmp_path, caplog):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)
    with caplog.at_level(logging.INFO):
        asyncio.run(gs.save_covs({"conversations": [{"id": "c1", "messages": []}]}))
    line = [r.getMessage() for r in caplog.records if "[Covs] save_covs 完成" in r.getMessage()]
    assert line and "rows=1" in line[0] and "KB" in line[0] and "ms" in line[0]


def test_settings_row_write_logs(tmp_path, caplog):
    from test_row_store import load_gs
    gs = load_gs(tmp_path)

    async def _go():
        await gs.init_db()
        await gs._write_settings_row({"model": "m1"})

    with caplog.at_level(logging.INFO):
        asyncio.run(_go())
    line = [r.getMessage() for r in caplog.records if "[Covs] settings 落盘" in r.getMessage()]
    assert line and "ms" in line[0]
