# -*- coding: utf-8 -*-
"""S215: 旁观者内核（screen_watcher）——门控采集→vision 卡 VLM→事件 jsonl。

钉桩：aHash 门控（场景未变不调 VLM=成本命门）、隐私黑名单跳帧（不进 VLM）、
vision 未配置退避不回退主卡、VLM 失败冷却、默认关闭零动作、单飞、热更新、
事件记录字段契约。真机接缝（_grab/_title/_vlm）整体替换，零真机零网络。
"""
import asyncio
import base64
import io
import json
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import screen_watcher as sw  # noqa: E402

_SERVER_SRC = (_ROOT / "server.py").read_text(encoding="utf-8-sig")
_SCHEMA_SRC = (_ROOT / "static" / "js" / "settings_schema.js").read_text(encoding="utf-8-sig")


def _img(color, size=(64, 64)):
    return Image.new("RGB", size, color)


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    e = sw.global_screen_watcher
    e.update_config({"enabled": True, "intervalSeconds": 2,
                     "changeThreshold": 6, "maxImageWidth": 300})
    e._last_capture = 0.0
    e._last_hash = None
    e._last_rgb = None
    e._cooldown_until = 0.0
    e._observe_task = None
    monkeypatch.setattr(sw, "SCREEN_WATCH_DIR", str(tmp_path))
    monkeypatch.setattr(sw, "load_settings", _mk_settings(True))
    yield e
    e.update_config({})
    e._last_hash = None
    e._last_rgb = None
    e._cooldown_until = 0.0
    e._observe_task = None


def _mk_settings(vision_on):
    async def fake():
        return {"vision": {"enabled": vision_on, "api_key": "k",
                           "base_url": "http://x/v1", "model": "m"}}
    return fake


def _stub(e, shot=None, title="记事本 - note.txt", vlm_ret=None, calls=None):
    e._grab = lambda: shot if shot is not None else _img((10, 20, 30))
    e._title = lambda: title
    n = calls if calls is not None else {"vlm": 0}

    async def fake_vlm(vision, data_uri):
        n["vlm"] += 1
        if vlm_ret is None:
            return '{"summary": "打开着记事本", "activity": "coding", "importance": 2}'
        if isinstance(vlm_ret, Exception):
            raise vlm_ret
        return vlm_ret
    e._vlm = fake_vlm
    return n


def _events(tmp_path):
    f = tmp_path / "screen_log.jsonl"
    if not f.exists():
        return []
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


def _run(fn):
    return asyncio.run(fn())


class TestPureHelpers:
    def test_ahash_identical_zero_diff(self):
        assert sw.hamming(sw.compute_ahash(_img((0, 0, 0))),
                          sw.compute_ahash(_img((0, 0, 0)))) == 0

    def test_ahash_stable_across_sizes(self):
        a = sw.compute_ahash(_img((0, 0, 0), (64, 64)))
        b = sw.compute_ahash(_img((0, 0, 0), (1024, 768)))
        assert a == b

    def test_privacy_blocked(self):
        kws = list(sw.DEFAULT_PRIVACY_KEYWORDS)
        assert sw.privacy_blocked("1Password – Chrome", kws)
        assert sw.privacy_blocked("KeePass 2.0", kws)
        assert sw.privacy_blocked("密码管理器 - Edge", kws)
        assert not sw.privacy_blocked("main.py - Notepad", kws)
        assert not sw.privacy_blocked(None, kws)
        assert not sw.privacy_blocked("1Password", [])

    def test_parse_vlm_json_variants(self):
        ok = sw.parse_vlm_json('{"summary": "浏览器", "activity": "browsing", "importance": 3}')
        assert ok == {"summary": "浏览器", "activity": "browsing", "importance": 3}
        fenced = sw.parse_vlm_json('```json\n{"summary": "a", "activity": "idle", "importance": 1}\n```')
        assert fenced["activity"] == "idle"
        noisy = sw.parse_vlm_json('好的：{"summary": "b", "activity": "chatting", "importance": 4}')
        assert noisy["summary"] == "b"
        junk = sw.parse_vlm_json("完全不是JSON的中文描述。")
        assert junk["summary"].startswith("完全不是") and junk["importance"] is None
        bad_imp = sw.parse_vlm_json('{"summary": "c", "importance": 9}')
        assert bad_imp["importance"] is None

    def test_encode_jpeg_downscale_and_uri(self):
        uri = sw.encode_jpeg_data_uri(_img((1, 2, 3), (1600, 900)), 300)
        assert uri.startswith("data:image/jpeg;base64,")
        raw = base64.b64decode(uri.split(",", 1)[1])
        with Image.open(io.BytesIO(raw)) as im:
            assert im.width == 300 and im.height == int(900 * 300 / 1600)

    def test_scene_changed_covers_solid_color_blindspot(self):
        # 纯色帧 aHash 恒 0：黑→橙必须靠 RGB 均值漂移放行，否则永远漏检
        assert sw.scene_changed(0, (0, 0, 0), 0, (200, 30, 90), 6, 24)
        assert not sw.scene_changed(0, (0, 0, 0), 0, (3, 3, 3), 6, 24)
        assert sw.scene_changed(None, None, 0, (0, 0, 0), 6, 24)  # 首帧必采


class TestObservePipeline:
    def test_event_written_with_fields(self, eng, tmp_path):
        n = _stub(eng)
        _run(lambda: eng._observe_once())
        evs = _events(tmp_path)
        assert len(evs) == 1 and n["vlm"] == 1
        ev = evs[0]
        assert ev["summary"] == "打开着记事本" and ev["activity"] == "coding"
        assert ev["importance"] == 2 and ev["title"] == "记事本 - note.txt"
        assert "ts" in ev and "iso" in ev and "took_s" in ev

    def test_unchanged_scene_skips_vlm(self, eng, tmp_path):
        shot = _img((5, 5, 5))
        n = _stub(eng, shot=shot)
        _run(lambda: eng._observe_once())
        _run(lambda: eng._observe_once())          # 同帧：门控跳过
        assert n["vlm"] == 1 and len(_events(tmp_path)) == 1
        eng._grab = lambda: _img((200, 30, 90))     # 场景变化：放行
        _run(lambda: eng._observe_once())
        assert n["vlm"] == 2 and len(_events(tmp_path)) == 2

    def test_privacy_frame_never_reaches_vlm(self, eng, tmp_path):
        n = _stub(eng, title="1Password – Chrome")
        _run(lambda: eng._observe_once())
        assert n["vlm"] == 0 and _events(tmp_path) == []

    def test_vision_off_backs_off_no_fallback(self, eng, tmp_path, monkeypatch):
        monkeypatch.setattr(sw, "load_settings", _mk_settings(False))
        n = _stub(eng)
        _run(lambda: eng._observe_once())
        assert n["vlm"] == 0 and _events(tmp_path) == []
        assert eng._cooldown_until > time.time() and eng._vlm_missing_warned

    def test_vlm_error_sets_cooldown(self, eng, tmp_path):
        _stub(eng, vlm_ret=RuntimeError("boom"))
        _run(lambda: eng._observe_once())          # 不抛出
        assert _events(tmp_path) == []
        assert eng._cooldown_until > time.time()

    def test_vlm_garbage_falls_back_to_summary(self, eng, tmp_path):
        _stub(eng, vlm_ret="这就一屏代码，没什么结构。")
        _run(lambda: eng._observe_once())
        evs = _events(tmp_path)
        assert evs and evs[0]["importance"] is None and "代码" in evs[0]["summary"]


class TestTickGating:
    def _drive(self, e):
        async def go():
            await e._tick()
            if e._observe_task is not None and not e._observe_task.done():
                await e._observe_task
        return asyncio.run(go())

    def test_disabled_zero_action(self, eng):
        eng.update_config({"enabled": False})
        _stub(eng)
        self._drive(eng)
        assert eng._observe_task is None and eng._last_capture == 0.0

    def test_cooldown_blocks_tick(self, eng):
        _stub(eng)
        eng._cooldown_until = time.time() + 60
        self._drive(eng)
        assert eng._observe_task is None

    def test_interval_blocks_tick(self, eng):
        _stub(eng)
        eng._last_capture = time.time()
        self._drive(eng)
        assert eng._observe_task is None

    def test_tick_runs_and_marks_capture(self, eng, tmp_path):
        _stub(eng)
        self._drive(eng)
        assert eng._last_capture > 0 and len(_events(tmp_path)) == 1

    def test_hot_update_config(self, eng):
        eng.update_config(None)
        assert eng.config == {} and not eng.config.get("enabled", False)
        eng.update_config({"enabled": True, "intervalSeconds": "junk"})
        assert eng._interval() == 5  # 非法值回落默认


class TestWiringPins:
    def test_server_wiring_points(self):
        assert "screen_watcher_task = None" in _SERVER_SRC
        assert "diary_engine_task, screen_watcher_task" in _SERVER_SRC
        assert "def _boot_background_engines" in _SERVER_SRC
        assert "diary_engine_task, screen_watcher_task = _boot_background_engines(settings)" in _SERVER_SRC
        assert 'global_screen_watcher.update_config((settings or {}).get("screenWatchSettings"))' in _SERVER_SRC
        assert "_shutdown_background_engines(diary_engine_task, screen_watcher_task)" in _SERVER_SRC
        assert 'global_screen_watcher.update_config(current.get("screenWatchSettings"))' in _SERVER_SRC

    def test_vlm_exit_is_llm_gated(self):
        # engine-parity 棘轮：py/ 下所有 chat.completions 出口必须在 gate 链上
        eng_src = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8-sig")
        assert "@llm_gate.gated" in eng_src
        assert hasattr(sw.ScreenWatcher.__dict__["_vlm"], "__wrapped__")

    def test_schema_wire_key(self):
        assert "['screenWatchSettings', 'screenWatchSettings']" in _SCHEMA_SRC

    def test_data_dir_constant(self):
        gs = (_ROOT / "py" / "get_setting.py").read_text(encoding="utf-8-sig")
        assert "SCREEN_WATCH_DIR = os.path.join(USER_DATA_DIR, 'screen_watch')" in gs
