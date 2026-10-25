# -*- coding: utf-8 -*-
"""S123: TTFB 分段锚点 + mem0 启动预热 + 提取线程 idle 优先级（存在性）。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_ttfb_anchors_present():
    sp = _read("server.py")
    assert "_TTFB_T0 = contextvars.ContextVar" in sp
    assert "[TTFBbrk] endpoint-enter +" in sp
    assert "[TTFBbrk] pre-stream +" in sp
    # 中间件在 call_next 之前 set（内层 task 继承 context）
    assert "if request.url.path.endswith(\"/chat/completions\"):\n        _TTFB_T0.set(_tt0)\n    response = await call_next(request)" in sp


def test_mem0_prewarm_wired():
    sp = _read("server.py")
    assert "def _mem0_prewarm_loop():" in sp
    assert "_start_mem0_prewarm()  # S123" in sp  # lifespan 一行零膨胀
    assert 'emb.embed("warmup", "search")' in sp


def test_extract_thread_idle_priority():
    lg = _read("py/llm_gate.py")
    assert "def _lower_thread_priority():" in lg
    assert "THREAD_PRIORITY_IDLE" in lg
    assert "runner():\n        _lower_thread_priority()" in lg
