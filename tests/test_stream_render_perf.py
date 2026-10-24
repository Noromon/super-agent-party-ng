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


# ===== S93: 渲染放大/CoT 纯文本流式/工具流封顶 pins =====

def test_s93_format_message_lru_cache():
    src = _read("static/js/methods/08_message_render.js")
    assert "_fmtCache" in src
    assert "_formatMessageUncached" in src
    # 活跃消息旁路缓存、语言分桶
    assert "this._formatMessageUncached(content, index)" in src


def test_s93_split_content_cache():
    src = _read("static/js/methods/96_table_a2ui.js")
    assert "_segCache" in src
    assert "hit.map(s => ({ ...s }))" in src


def test_s93_dom_hooks_throttled():
    src = _read("static/js/methods/08_message_render.js")
    assert "this.scheduleDomHooks()" in src
    assert "$nextTick(() => {" not in src[src.index("_formatMessageUncached"):]
    src2 = _read("static/js/methods/66_render_preview.js")
    assert "scheduleDomHooks()" in src2
    assert "300" in src2[src2.index("scheduleDomHooks"):src2.index("scheduleDomHooks") + 320]


def test_s93_reasoning_plain_text_while_streaming():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        src = _read(f"static/templates/{tpl}.html")
        assert "v-if=\"!block.done && isTyping && index === messages.length - 1\"" in src, tpl
        assert "white-space: pre-wrap" in src, tpl
    src = _read("static/js/methods/11_tool_blocks.js")
    assert "_markReasoningDone(msg)" in src
    src = _read("static/js/methods/13_resume_stream.js")
    assert "this._markReasoningDone(currentMsg)" in src
    assert "this._markReasoningDone(this._streamTargetMsg)" in src


def test_s93_tool_stream_capped_and_buffered():
    src = _read("static/js/methods/13_resume_stream.js")
    assert "_toolStreamPending" in src
    assert "_flushToolStream()" in src
    assert "targetBlock.content = this.smartMergeTerminal" not in src
    assert "50000" in src
    assert "131072" in src
    src = _read("static/js/methods/10_chat_stream.js")
    assert src.count("this._flushToolStream();") >= 3


def test_s93_server_display_frame_capped():
    src = _read("server.py")
    assert "_disp_chunk" in src
    assert "16384" in src
    assert '"content": _disp_chunk,' in src
    # LLM 全文链不受影响
    assert "buffer.append(chunk)" in src