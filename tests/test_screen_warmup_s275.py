# build=S276
# S275：窥屏预热冷静期——开启后前 N 秒整帧跳过（不截图/不评估/不发言）；
# start、enabled 上升沿、warmupEnabled 上升沿均重置计时；关闭期间不计时。
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
    e.update_config({"enabled": True, "intervalSeconds": 2, "warmupEnabled": True,
                     "warmupSeconds": 60})
    e._last_capture = 0.0
    e._last_hash = None
    e._last_rgb = None
    e._cooldown_until = 0.0
    e._observe_task = None
    e._last_maintain = time.time()  # 隔离维护分支
    e._warmup_since = 0.0
    e._warmup_last_on = False
    e._enabled_last_on = False
    monkeypatch.setattr(sw, "GUI_AVAILABLE", True)
    monkeypatch.setattr(sw, "SCREEN_WATCH_DIR", str(tmp_path))
    monkeypatch.setattr(sw, "load_settings", _mk_settings())
    calls = {"grab": 0}

    def _grab():
        calls["grab"] += 1
        return _img()
    e._grab = _grab
    e._title = lambda: "记事本 - note.txt"

    async def fake_vlm(vision, data_uri, extra_body=None):
        return '{"summary": "s", "activity": "coding", "importance": 1}'
    e._vlm = fake_vlm
    yield e, calls
    e.update_config({})
    e._observe_task = None
    e._cooldown_until = 0.0


def _drive(e):
    # 仿 s215：tick 与 observe 同 loop 内驱动（asyncio.run 关 loop 会作废任务）
    async def go():
        await e._tick()
        if e._observe_task is not None and not e._observe_task.done():
            await e._observe_task
    asyncio.run(go())


def test_warmup_blocks_entire_frame(eng):
    e, calls = eng
    _drive(e)  # 上升沿：重置计时并整帧跳过
    assert e._observe_task is None
    assert e._last_capture == 0.0
    assert calls["grab"] == 0  # 连截图都没发生


def test_warmup_expiry_resumes_capture(eng):
    e, calls = eng
    _drive(e)
    e._warmup_since = time.time() - 61
    _drive(e)
    assert e._observe_task is not None
    assert calls["grab"] == 1


def test_warmup_off_is_transparent(eng):
    e, calls = eng
    e.update_config({"enabled": True, "intervalSeconds": 2, "warmupEnabled": False})
    _drive(e)
    assert e._observe_task is not None
    assert calls["grab"] == 1


def test_reenable_restarts_cooloff(eng):
    e, calls = eng
    _drive(e)                        # 上升沿 → 冷静期中
    e._warmup_since = time.time() - 61
    _drive(e)                        # 到期 → 观察一帧
    assert calls["grab"] == 1
    e.update_config({"enabled": False, "intervalSeconds": 2,
                     "warmupEnabled": True, "warmupSeconds": 60})
    _drive(e)                        # 关闭期间不计时
    e.update_config({"enabled": True, "intervalSeconds": 2,
                     "warmupEnabled": True, "warmupSeconds": 60})
    e._last_capture = 0.0            # 绕开 interval，纯测冷静期重置
    _drive(e)                        # enabled 上升沿 → 重新计时并跳过
    assert calls["grab"] == 1        # 没有第二帧


def test_warmup_seconds_clamp(eng):
    e, _ = eng
    e.update_config({"warmupSeconds": 99999})
    assert e._warmup_seconds() == 600
    e.update_config({"warmupSeconds": -5})
    assert e._warmup_seconds() == 0
    e.update_config({"warmupSeconds": "abc"})
    assert e._warmup_seconds() == 30
    e.update_config({})
    assert e._warmup_seconds() == 30


class TestStaticWiring:
    def test_backend_hooks(self):
        src = (_ROOT / "py" / "screen_watcher.py").read_text(encoding="utf-8-sig")
        assert "self._warmup_since = time.time()" in src                       # start 重置
        assert "not self._warmup_last_on or not self._enabled_last_on" in src  # 双上升沿
        assert "now - self._warmup_since < self._warmup_seconds()" in src      # 整帧门控

    def test_defaults_both_frontends(self):
        for p in ("static/js/settings_schema.js", "static/js/data/60_cards_options.js"):
            s = (_ROOT / p).read_text(encoding="utf-8-sig")
            assert "warmupEnabled: false," in s, p
            assert "warmupSeconds: 30," in s, p

    def test_ui_and_i18n(self):
        role = (_ROOT / "static/templates/page_role.html").read_text(encoding="utf-8-sig")
        assert 'v-model="screenWatchSettings.warmupEnabled"' in role
        assert 'v-model="screenWatchSettings.warmupSeconds"' in role
        # S276：该行必须位于「采集与隐私」卡内（间隔滑条下方），且在「主动发言」卡之前，
        # 并常显（无 v-if）——S275 首版误藏发言卡内导致用户在设置页找不到。
        i_cap = role.index("t('screenWatchCapture')")
        i_warm = role.index("'screenWatchWarmup'")
        i_speak = role.index("t('screenWatchSpeak')")
        assert i_cap < i_warm < i_speak, "预热行应在采集与隐私卡内、主动发言卡之前"
        line = role[role.rindex("<el-form-item", 0, i_warm):role.index(">", i_warm) + 1]
        assert "v-if" not in line, "预热行必须常显（不依赖窥屏/speak 开关）"
        for p in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
            s = (_ROOT / p).read_text(encoding="utf-8-sig")
            assert "'screenWatchWarmup'" in s and "'screenWatchWarmupNotice'" in s, p
