# -*- coding: utf-8 -*-
"""S71：日记主动推送目标解析（activity 主会话/配置回退/显式目标/黑洞移除）+ 结构 pins。"""
import asyncio
import io
import os
import sys
import tempfile
from pathlib import Path

# Must precede any py.get_setting import: keep paths out of the production dir.
os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_diary_targets_")

# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py.behavior_engine import global_behavior_engine as gbe  # noqa: E402
from py.diary_engine import global_diary_engine as engine  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def _make_handler(sink):
    async def _h(chat_id, behavior_item):
        sink.append(chat_id)
    return _h


def _run_push(chat_id, monkeypatch, activity=None, targets=None, sink=None):
    sink = sink if sink is not None else []
    monkeypatch.setitem(gbe.handlers, "xmpp", _make_handler(sink))
    monkeypatch.setattr(gbe, "platform_activity", activity or {}, raising=False)
    monkeypatch.setattr(gbe, "platform_targets", targets or {}, raising=False)

    async def _go():
        ok = await engine._push_to_im("xmpp", chat_id, "内容")
        await asyncio.sleep(0.05)
        return ok
    return asyncio.run(_go()), sink


def test_auto_target_uses_most_recent_activity(monkeypatch):
    ok, sink = _run_push(None, monkeypatch,
                         activity={"xmpp": {"a@b": 1.0, "c@d": 9.0, "e@f": 5.0}})
    assert ok is True
    assert sink == ["c@d"]


def test_auto_falls_back_to_configured_targets(monkeypatch):
    ok, sink = _run_push(None, monkeypatch, activity={}, targets={"xmpp": ["t1", "t2"]})
    assert ok is True
    assert sorted(sink) == ["t1", "t2"]


def test_no_target_returns_false_and_no_blackhole(monkeypatch):
    ok, sink = _run_push(None, monkeypatch, activity={}, targets={})
    assert ok is False
    assert sink == []


def test_explicit_single_and_list(monkeypatch):
    ok, sink = _run_push("solo@x", monkeypatch, activity={"xmpp": {"lurker@y": 100.0}})
    assert ok is True and sink == ["solo@x"]
    ok, sink = _run_push(["p@1", "p@2"], monkeypatch)
    assert ok is True and sorted(sink) == ["p@1", "p@2"]


# ---------------------------------------------------------------- pins

def test_engine_pins():
    src = _read("py/diary_engine.py")
    assert '"imTargetMap"' in src
    assert 'handler("", behavior)' not in src
    assert "platform_activity" in src


def test_xmpp_behavior_pins():
    src = _read("py/xmpp_client.py")
    assert "run_coroutine_threadsafe" in src
    assert '"xmpp-behavior"' in src
    assert "behaviorTargetJids" in src
    assert 'logging.getLogger("app").error(f"XMPP 行为事件失败' in src
    assert 'logging.getLogger("app").error(f"XMPP 发送失败' in src
    assert "logging.error(f\"XMPP 行为事件失败" not in src


def test_server_ws_endpoint_pins():
    src = _read("server.py")
    assert '"get_diary_im_targets"' in src
    assert '"diary_im_targets"' in src


def test_frontend_pins():
    role = _read("static/templates/page_role.html")
    assert "'diaryTargets-' + p" in role
    assert "onDiaryImTargetsChange" in role
    assert "diaryImTargetOptionLabel" in role
    m = _read("static/js/methods/44_diary.js")
    assert "onDiaryImTargetChange" in m and "requestDiaryImTargets" in m
    w = _read("static/js/methods/14_ws_client.js")
    assert "diary_im_targets" in w


@pytest.mark.parametrize("rel", ["static/js/locales/zh-CN.js", "static/js/locales/en-US.js"])
@pytest.mark.parametrize("key", ["diaryImTargetPick", "diaryImTargetAutoHint",
                                 "diaryImTargetMainSuffix"])
def test_i18n_keys_parity(rel, key):
    assert key in _read(rel)


def test_settings_template_has_map():
    assert '"imTargetMap": {}' in _read("config/settings_template.json")
