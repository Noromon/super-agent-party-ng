# build=S295
# S290：观察退避自愈。日志裁决：400 'Model unloaded' → 300s 退避；但①update_config
# 不清退避（拨开关无效）；②hash 在 VLM 前已更新，退避到期后静止画面被场景门控吞掉，
# 永不重试。本文件锁三条自愈路径 + 静态接线。
import asyncio
import sys
import time
from pathlib import Path

import pytest
from PIL import Image

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import screen_watcher as sw  # noqa: E402


def _img(color=(10, 20, 30), size=(64, 64)):
    return Image.new("RGB", size, color)


def _mk_settings():
    async def fake():
        return {"vision": {"enabled": True, "api_key": "k",
                           "base_url": "http://x/v1", "model": "m"}}
    return fake


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    e = sw.global_screen_watcher
    e.update_config({"enabled": True, "intervalSeconds": 2, "warmupEnabled": False})
    e._last_capture = 0.0
    e._last_hash = None
    e._last_rgb = None
    e._cooldown_until = 0.0
    e._observe_task = None
    e._last_maintain = time.time()
    monkeypatch.setattr(sw, "GUI_AVAILABLE", True)
    monkeypatch.setattr(sw, "SCREEN_WATCH_DIR", str(tmp_path))
    monkeypatch.setattr(sw, "load_settings", _mk_settings())
    calls = {"grab": 0, "vlm": 0}

    def _grab():
        calls["grab"] += 1
        return _img()
    e._grab = _grab
    e._title = lambda: "记事本 - note.txt"

    def bad():
        async def _v(vision, data_uri, extra_body=None):
            calls["vlm"] += 1
            raise RuntimeError("400 Model unloaded by user or API request.")
        return _v

    def good():
        async def _v(vision, data_uri, extra_body=None):
            calls["vlm"] += 1
            return '{"summary": "s", "activity": "coding", "importance": 1}'
        return _v

    e.bad_vlm, e.good_vlm = bad(), good()
    e._vlm = e.good_vlm
    yield e, calls
    e._vlm = e.good_vlm
    e.update_config({})
    e._observe_task = None
    e._cooldown_until = 0.0


def _drive(e):
    async def go():
        await e._tick()
        if e._observe_task is not None and not e._observe_task.done():
            await e._observe_task
    asyncio.run(go())


def test_fail_sets_cooldown_then_config_save_clears(eng):
    e, calls = eng
    e._vlm = e.bad_vlm
    _drive(e)
    assert calls["vlm"] == 1
    assert e._cooldown_until > time.time()  # 300s 退避挂起
    _drive(e)
    assert calls["vlm"] == 1  # 退避期内确实不再打
    e.update_config({"enabled": True, "intervalSeconds": 2, "warmupEnabled": False})
    assert e._cooldown_until == 0.0  # 保存配置=立即重试


def test_cooldown_survives_disabled_save(eng):
    e, _ = eng
    e._cooldown_until = time.time() + 100
    e.update_config({"enabled": False, "intervalSeconds": 2})
    assert e._cooldown_until > time.time()  # 关着保存不清退避（没有观察在等）


def test_fail_rolls_back_scene_watermark_and_retries(eng):
    e, calls = eng
    e._vlm = e.bad_vlm
    _drive(e)
    assert e._last_hash is None and e._last_rgb is None  # 快照回滚（静止画面不再吞重试）
    e._cooldown_until = 0.0
    e._last_capture = 0.0
    e._vlm = e.good_vlm
    _drive(e)  # 画面一模一样也必须再进 VLM
    assert calls["vlm"] == 2
    assert e._cooldown_until == 0.0  # 成功后退避复位
    assert calls["grab"] == 2


def test_cooldown_expiry_resumes_after_static_gap(eng):
    e, calls = eng
    e._vlm = e.bad_vlm
    _drive(e)
    assert e._cooldown_until > time.time()
    e._cooldown_until = time.time() - 1  # 模拟退避到期（不靠 sleep）
    e._last_capture = 0.0
    e._vlm = e.good_vlm
    _drive(e)
    assert e._cooldown_until == 0.0
    assert calls["vlm"] == 2  # 到期即恢复尝试，且有 INFO 留痕（见静态接线锁）


class TestStaticWiring:
    def test_self_heal_hooks(self):
        src = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8-sig")
        assert 'if self.config.get("enabled") and self._cooldown_until:' in src
        assert "_prev_pair = (self._last_hash, self._last_rgb)" in src
        assert "self._last_hash, self._last_rgb = _prev_pair" in src
        assert "[ScreenWatcher] 退避到期，恢复观察尝试" in src
