# -*- coding: utf-8 -*-
"""S334: 记忆提取任务——可取消防抖 + 会话级隔离 + 锁外退场。

旧缺陷：防抖 sleep 在全局锁内（作废任务逐个持锁假睡，会话结束后连环
空转、真任务排最后）；作废检查在 sleep 后（防抖有名无实）；generation
仅按 memory_id（多会话共享记忆库互相顶掉、静默丢失提取）。
"""
import sys
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import llm_gate  # noqa: E402


def _wait_until(pred, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(0.02)
    return False


class TestDebounce:
    def test_only_newest_runs_and_fast(self):
        runs = []
        mid, ck = "s334a", "conv1"
        t0 = time.time()
        for i in range(3):
            llm_gate.submit_memory_job(
                mid, lambda: runs.append(time.time()), name="t334",
                debounce=0.4, wait_idle=False, conv_key=ck)
        assert _wait_until(lambda: len(runs) == 1, 6.0)
        assert len(runs) == 1
        # 旧实现=3 个任务串行持锁假睡；现在总时长≈单个 debounce 而非 3×
        assert runs[0] - t0 < 1.6
        time.sleep(0.1)
        assert len(runs) == 1  # 只执行最新一次

    def test_stale_woken_early_not_sleeping_full(self, caplog):
        caplog.set_level("INFO")
        time.sleep(0.05)
        mid, ck = "s334b", "convW"
        llm_gate.submit_memory_job(mid, lambda: None, name="t334w",
                                   debounce=5.0, wait_idle=False, conv_key=ck)
        time.sleep(0.05)
        llm_gate.submit_memory_job(mid, lambda: None, name="t334w2",
                                   debounce=0.2, wait_idle=False, conv_key=ck)

        def _gone():
            return any("作废（未占锁）" in r.getMessage() for r in caplog.records)
        assert _wait_until(_gone, 1.5)  # 5s 防抖被唤醒提前退场

    def test_zero_debounce_runs(self):
        runs = []
        llm_gate.submit_memory_job("s334c", lambda: runs.append(1), name="t334z",
                                   debounce=0, wait_idle=False, conv_key="convZ")
        assert _wait_until(lambda: len(runs) == 1)


class TestSessionIsolation:
    def test_two_conversations_both_extract(self):
        runs = []
        lock = threading.Lock()

        def _fn(tag):
            with lock:
                runs.append(["in", tag])
            time.sleep(0.15)
            with lock:
                runs.append(["out", tag])

        llm_gate.submit_memory_job("s334d", lambda: _fn("A"), name="tA",
                                   debounce=0.1, wait_idle=False, conv_key="cA")
        llm_gate.submit_memory_job("s334d", lambda: _fn("B"), name="tB",
                                   debounce=0.1, wait_idle=False, conv_key="cB")
        assert _wait_until(lambda: len(runs) >= 4)
        assert {r[1] for r in runs} == {"A", "B"}  # 不再互相顶掉
        # 全局执行仍串行：in 出现后必须先 out 才能再有 in
        seq, depth = 0, 0
        for kind, _tag in runs:
            depth += 1 if kind == "in" else -1
            seq = max(seq, depth)
        assert seq == 1


class TestCallSitePins:
    def _src(self, rel):
        return (_ROOT / rel).read_text(encoding="utf-8-sig")

    def test_both_submit_sites_pass_conv_key(self):
        assert "conv_key=_req_key(request)" in self._src("py/stream_engine.py")
        assert "conv_key=_req_key(request)" in self._src("py/complete_engine.py")

    def test_no_locked_sleep_pattern(self):
        s = self._src("py/llm_gate.py")
        seg = s[s.index("def submit_memory_job"):]
        assert "ev.wait(debounce)" in seg and "time.sleep(debounce)" not in seg


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
