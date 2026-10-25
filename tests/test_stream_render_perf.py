# S92：主会话流式渲染性能 pins（reasoning 缓冲 + morph 合帧/自适应预算）
import subprocess
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

def test_s96_cache_layer_rolled_back():
    # S93-F1 缓存层已回滚：响应式实例上的 Map 在渲染表达式里 delete/set
    # = 渲染期响应式写入 → render effect 自我触发死循环（[WinUnresponsive] 实测）。
    # 防死循环回归：任何实例级缓存不得再出现。
    src = _read("static/js/methods/08_message_render.js")
    assert "_fmtCache" not in src
    assert "_formatMessageUncached" not in src
    src2 = _read("static/js/methods/96_table_a2ui.js")
    assert "_segCache" not in src2


def test_s93_dom_hooks_throttled():
    src = _read("static/js/methods/08_message_render.js")
    assert "this.scheduleDomHooks()" in src
    assert "$nextTick(() => {" not in src[src.index("formatMessage(content, index)"):]
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


# ===== S97: 模块级纯读缓存（命中零写入、FIFO、活跃只读） =====

def test_s97_module_cache_pins():
    src = _read("static/js/methods/08_message_render.js")
    assert "const SAP_FMT_CACHE = new Map();" in src
    # 命中 = 纯读直接返回，无任何写回（LRU touch 是 S96 死循环根因）
    assert "if (hit !== undefined) return hit;" in src
    # 活跃流式消息不写缓存（逐帧变化的内容写进去只会冲刷历史条目）
    assert "if (!active) {\n        bucket.set(content, out);" in src
    assert "bucket.size > 300" in src
    src2 = _read("static/js/methods/96_table_a2ui.js")
    assert "const SAP_SEG_CACHE = new Map();" in src2
    assert "hit.map(s => ({ ...s }))" in src2
    # S96 回滚地雷防回归：裸 cache 标识符（声明已被删）不得再出现
    assert " cache.set(" not in src2
    assert " cache.size" not in src2


def test_s97_split_runtime(tmp_path):
    # node 真跑：miss 解析正确、命中返回纯拷贝、空输入安全
    src = _read("static/js/methods/96_table_a2ui.js")
    harness = tmp_path / "seg_harness.js"
    harness.write_text(
        "globalThis.vue_methods = {};\n" + src + "\n"
        "const f = vue_methods.splitMessageContent;\n"
        "const c = 'before\\n```a2ui\\n{\"a\":1}\\n```\\nafter';\n"
        "const r1 = f(c); const r2 = f(c);\n"
        "if (r1.length !== 3 || r1.map(x=>x.type).join(',') !== 'text,ui,text') throw new Error('miss-parse wrong');\n"
        "if (JSON.stringify(r2) !== JSON.stringify(r1)) throw new Error('hit mismatch');\n"
        "if (r1 === r2 || r1[0] === r2[0]) throw new Error('hit must return fresh copies');\n"
        "if (f('').length !== 0) throw new Error('empty input');\n"
        "console.log('SEG_OK');\n",
        encoding="utf-8",
    )
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=60)
    assert "SEG_OK" in out.stdout, out.stderr
# ===== S102: 流式期纯文本直出 + args 写时预计算 + 日志自动落盘 =====

def test_s102_streaming_plain_and_args_precompute():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        src = _read(f"static/templates/{tpl}.html")
        # reasoning(S93, 带 !block.done 前缀) + text(S102) 两处流式纯文本分支
        assert src.count("isTyping && index === messages.length - 1") >= 2, tpl
        assert "block.displayArgs ?? block.args" in src, tpl
        assert "block.args.replace(/\\\\n" not in src, tpl
    tb = _read("static/js/methods/11_tool_blocks.js")
    assert "_setToolArgs(block, args)" in tb
    rs = _read("static/js/methods/13_resume_stream.js")
    assert rs.count("this._setToolArgs(") >= 2


def test_s102_logs_auto_land():
    assert "SAP_LOG_DIR" in _read("py/log_setup.py")
    assert "SAP_LOG_DIR" in _read("一键启动(start).bat")
    src = _read("main.js")
    assert "frontend-evidence.log" in src
# ===== S103: 第二条跑步机（旧架构兼容路径）拆除 + 广播 toRaw + setTimeout 归因探针 =====

def test_s103_legacy_path_treadmill_removed():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        src = _read(f"static/templates/{tpl}.html")
        # 旧架构兼容路径的流式纯文本分支（class 含 streaming 光标态）
        assert 'class="stream-content streaming"' in src, tpl
        # :class 内联 splitMessageContent(message.content).length 已去除
        assert "segIndex === splitMessageContent(message.content).length" not in src, tpl
        # 三处流式纯文本分支：reasoning(S93) + displayBlocks text(S102) + 旧路径(S103)
        assert src.count("isTyping && index === messages.length - 1") >= 3, tpl


def test_s103_broadcast_toraw_and_skip():
    src = _read("static/js/methods/63_extension_bridge.js")
    assert "Vue.toRaw(this.messages)" in src
    assert "if (!wsOpen && this._pendingExtensionMessage) return;" in src


def test_s103_settimeout_attribution_probe():
    src = _read("static/js/renderer.js")
    assert "window.__lateTimers" in src
    assert "timers[' + window.__lateTimers.slice(-2)" in src
    assert "[Probe] renderer build=S1" in src  # 版本号随升级变，前缀恒定
# ===== S104: 显示窗口切片 + 饥饿自报抓栈 + 探针 v2 帧相位 =====

def test_s104_message_window():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        src = _read(f"static/templates/{tpl}.html")
        assert '<template v-for="(message, index) in messages" :key="index">' in src, tpl
        assert 'v-if="index >= msgWindowStart()"' in src, tpl
    sc = _read("static/js/methods/68_scroll.js")
    assert "msgWindowStart()" in sc and "expandMsgWindow()" in sc
    assert "msgWindowOffset: null" in _read("static/js/data/00_ui_core.js")


def test_s104_capture_channel():
    assert "requestFreezeCapture" in _read("static/js/preload.js")
    mj = _read("main.js")
    assert "sap-freeze-capture" in mj
    assert "win.__freezeProbeOn" in mj  # 幂等守卫（历史双份回显修复）
    rd = _read("static/js/renderer.js")
    assert "window.electron.requestFreezeCapture()" in rd


def test_s104_probe_v2_phases():
    rd = _read("static/js/renderer.js")
    assert "phases[script=" in rd
    assert "forcedStyleAndLayoutDuration" in rd
    assert "renderer build=S104" in rd
