# S92：主会话流式渲染性能 pins（reasoning 缓冲 + morph 合帧/自适应预算）
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_reasoning_buffered_in_main_stream():
    src = _read("static/js/methods/10_chat_stream.js")
    # delta 处理：reasoning 不再直接 append block，而是写缓冲
    assert "_streamReasoningBuffer" in src
    assert "block.content += delta.reasoning_content" not in src
    # flush 同时消费两种缓冲（定位定义处，非调用点）
    flush_seg = src[src.index("flushStreamTextBuffer() {"):]
    assert "'reasoning'" in flush_seg[:400]


def test_reasoning_buffered_in_resume():
    src = _read("static/js/methods/13_resume_stream.js")
    assert "_streamReasoningBuffer" in src
    assert "block.content += delta.reasoning_content" not in src


def test_cleanup_clears_both_buffers():
    src = _read("static/js/methods/10_chat_stream.js")
    cleanup = src[src.index("// 清理流式缓冲区状态"):]
    assert "_streamReasoningBuffer = ''" in cleanup[:400]


def test_morph_directive_coalescing_and_budget():
    src = _read("static/js/renderer.js")
    assert "el._schedule" in src
    assert "requestAnimationFrame(el._flush)" in src
    # A3 自适应帧预算
    assert "> 50 ? 150 : 0" in src
    # 旧版每变更同步全量渲染的路径已移除
    assert "el._update" not in src
    # 滚动走节流版
    seg = src[src.index("directives:"):]
    assert "requestScrollToBottom" in seg
    assert "unmounted" in seg
