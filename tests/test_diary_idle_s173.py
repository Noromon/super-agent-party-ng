# S173: 聊天总结「真空闲」语义。旧语义只随用户消息重置计时——agent 连续执行
# 超过 idleMinutes 的长任务期间（用户沉默、assistant 未 finalize）被误判空闲，
# 在会话最忙碌时触发总结自调用（2026-10-30 事故放大器）。修复：
#   1) last_activity_time 任何 append 刷新，双时间戳双双超时才算空闲；
#   2) 引擎 tick 在途流闸：有未 done/未 cancelled 的流式请求 → 本 tick 跳过。
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import diary_chat_integration as dci  # noqa: E402

_KEY = "_s173_test_book_"


def _mk_buf(key, user_age, act_age):
    buf = dci.get_chat_buffer(key)
    buf["messages"] = [{"role": "user", "content": "hi"},
                       {"role": "assistant", "content": "hello"}]
    buf["last_user_msg_time"] = time.time() - user_age
    buf["last_activity_time"] = time.time() - act_age
    return buf


class TestTrueIdleSemantics:
    def setup_method(self):
        dci._chat_buffers.pop(_KEY, None)

    def teardown_method(self):
        dci._chat_buffers.pop(_KEY, None)

    def test_both_stale_is_idle(self):
        _mk_buf(_KEY, user_age=3600, act_age=3600)
        keys = [k for k, _ in dci.get_idle_buffers(15)]
        assert _KEY in keys

    def test_fresh_assistant_activity_not_idle(self):
        _mk_buf(_KEY, user_age=3600, act_age=10)
        keys = [k for k, _ in dci.get_idle_buffers(15)]
        assert _KEY not in keys

    def test_fresh_user_message_not_idle(self):
        _mk_buf(_KEY, user_age=10, act_age=3600)
        keys = [k for k, _ in dci.get_idle_buffers(15)]
        assert _KEY not in keys

    def test_append_any_role_refreshes_activity(self):
        _mk_buf(_KEY, user_age=3600, act_age=3600)
        dci.append_to_chat_buffer(_KEY, "assistant", "late reply after long task")
        keys = [k for k, _ in dci.get_idle_buffers(15)]
        assert _KEY not in keys

    def test_legacy_buffer_without_activity_key_falls_back(self):
        buf = _mk_buf(_KEY, user_age=3600, act_age=3600)
        del buf["last_activity_time"]
        keys = [k for k, _ in dci.get_idle_buffers(15)]
        assert _KEY in keys

    def test_clear_resets_both_timestamps(self):
        _mk_buf(_KEY, user_age=3600, act_age=3600)
        dci.clear_chat_buffer(_KEY)
        buf = dci.get_chat_buffer(_KEY)
        assert buf["last_user_msg_time"] > time.time() - 5
        assert buf["last_activity_time"] > time.time() - 5


class TestLiveStreamsGate:
    def test_live_stream_blocks_summary_tick(self):
        from py import diary_engine as de
        from py.stream_relay import _active_streams
        _active_streams["_s173_fake"] = {"done": False, "cancelled": False}
        try:
            assert de.has_live_streams() is True
        finally:
            _active_streams.pop("_s173_fake", None)

    def test_done_or_cancelled_stream_does_not_block(self):
        from py import diary_engine as de
        from py.stream_relay import _active_streams
        _active_streams["_s173_done"] = {"done": True}
        _active_streams["_s173_cancel"] = {"done": False, "cancelled": True}
        try:
            assert de.has_live_streams() is False
        finally:
            _active_streams.pop("_s173_done", None)
            _active_streams.pop("_s173_cancel", None)


class TestTickWiring:
    def _engine_src(self):
        with open(os.path.join(_ROOT, "py", "diary_engine.py"), encoding="utf-8") as f:
            return f.read()

    def test_tick_checks_live_streams_before_spawn(self):
        src = self._engine_src()
        assert "and not has_live_streams()):" in src

    def test_helper_defined_at_module_level(self):
        src = self._engine_src()
        assert "def has_live_streams() -> bool:" in src
        assert src.index("def has_live_streams") < src.index("class DiaryEngine")
