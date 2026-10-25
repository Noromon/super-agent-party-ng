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
    assert "renderer build=S1" in rd
# ===== S105: 抓取双通道铁证 + 证据全镜像 + 探针 v3 + 泵耗时帽 =====

def test_s105_capture_and_evidence():
    mj = _read("main.js")
    assert "capture-requested" in mj and "requestCapture" in mj
    assert "const fdiag" in mj and "evidenceAppend" in mj
    rd = _read("static/js/renderer.js")
    assert "capture-requested" in rd
    assert "capture-channels electron=" in rd
    # 探针 v3：scripts top5 带 duration；容器级 DOM 读数
    assert "Math.round(s.duration || 0)" in rd
    assert "msgsDom=" in rd
    # 泵：帧数帽+耗时帽
    sc = _read("static/js/stream_client.js")
    assert sc.count("framesSinceYield >= 6") == 2
# ===== S106: v-memo 行隔离 + 写入节流 + webview 截断网关 + 流式常开 Profiler =====

def test_s106_memo_and_throttle():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        assert 'v-memo="[message._rv || 0' in _read(f"static/templates/{tpl}.html"), tpl
    assert "uiRev: 0" in _read("static/js/data/00_ui_core.js")
    assert "touchUI()" in _read("static/js/methods/68_scroll.js")
    assert "this.touchUI();\n      this.$forceUpdate();" in _read("static/js/methods/60_system_settings.js")
    cs = _read("static/js/methods/10_chat_stream.js")
    assert "_streamLastFlushTs = Date.now()" in cs
    assert "if (__m) __m._rv = (__m._rv || 0) + 1;" in cs
    assert "toolCallStack, currentMsg)" in cs
    assert cs.count("this.streamFlushWait())") >= 2  # 防抖饥饿守卫（S109 起在 streamFlushWait 内）
    rs = _read("static/js/methods/13_resume_stream.js")
    assert "_lastArgsW" in rs and "? 300 : 120" in rs
    assert "currentMsg._rv = (currentMsg._rv || 0) + 1;" in rs  # S107 起带节流包裹
    assert "p.msg._rv = (p.msg._rv || 0) + 1" in rs


def test_s106_wvexec_guest_cap():
    wa = _read("static/js/methods/80_webview_agent.js")
    assert "_wvExec(wv, script)" in wa
    assert "await eval(" in wa and "60000" in wa
    assert wa.count("this._wvExec(wv, ") >= 10


def test_s106_stream_profiler_and_fetch_probe():
    rd = _read("static/js/renderer.js")
    assert "stream-active" in rd and "stream-idle" in rd
    assert "fetch-scheduled" in rd
    mj = _read("main.js")
    assert "startStreamProfile" in mj and "scheduleStreamProfileStop" in mj
    assert "Perf" in mj and "sap-freeze-profile-" in mj
# ===== S107: 侧边栏行 v-memo + tool 帧 bump 节流 + flush 频率普查 =====

def test_s107_sidebar_memo_and_bump_throttle():
    for tpl in ("page_chat_main", "page_home"):
        assert 'v-for="conv in group.conversations" v-memo=' in _read(f"static/templates/{tpl}.html"), tpl
    rs = _read("static/js/methods/13_resume_stream.js")
    assert "_lastRvBump" in rs and "? 240 : 80" in rs
    assert "S107: 流尾终态兜底 bump" in rs
    assert "S107: 流尾终态兜底 bump" in _read("static/js/methods/10_chat_stream.js")
    rd = _read("static/js/renderer.js")
    assert "updates/5s=" in rd
    assert "renderer build=S1" in rd  # 版本戳前缀断言（升版不误炸）
# ===== S108: root 自激侦测+抓栈 / 流式期下线行操作 popper 链 / 翻译流批量 send =====

def test_s108_root_loop_detector_and_batching():
    rd = _read("static/js/renderer.js")
    assert "rootCount > 150" in rd and "root=' + rootCount" in rd
    assert "renderer build=S1" in rd  # 前缀断言（升版不误炸）
    for tpl in ("page_chat_main", "page_home"):
        assert 'class="item-actions" v-if="!isTyping"' in _read(f"static/templates/{tpl}.html"), tpl
    bt = _read("static/js/methods/98_browser_tabs.js")
    assert "tvFlush" in bt and "setTimeout(tvFlush, 80)" in bt
# ===== S109: 消息行 tooltip→原生 title / loop-suspect 探针 / 追赶模式 =====

def test_s109_native_title_and_backlog_mode():
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        s = _read(f"static/templates/{tpl}.html")
        import re as _re
        assert not _re.search(r"<el-tooltip[^>]*>\s*<el-button", s), tpl
    assert ':title="t(\'copy\')"' in _read("static/templates/page_chat_main.html")
    rd = _read("static/js/renderer.js")
    assert "loop-suspect" in rd and "renderer build=S1" in rd
    cs = _read("static/js/methods/10_chat_stream.js")
    assert "streamBacklog()" in cs and "return 240" in cs
    assert "_streamRecvChars = (this._streamRecvChars || 0) + delta.content.length" in cs
    rs = _read("static/js/methods/13_resume_stream.js")
    assert "? 300 : 120" in rs and "? 240 : 80" in rs
    assert "this.streamFlushWait()" in rs and "this.streamFlushWait()" in cs


# ===== S110: storage 页根 v-if 销毁（隐藏页风暴宿主）+ profile hold 120s =====

def test_s110_storage_page_destroy_when_hidden():
    st = _read("static/templates/page_storage.html")
    assert "<div v-if=\"activeMenu === 'storage'\" class=\"page storage-container\">" in st
    assert "v-show=\"activeMenu === 'storage'\"" not in st
    mj = _read("main.js")
    assert "startProfile({ hold: 120000 })" in mj
    assert "renderer build=S1" in _read("static/js/renderer.js")
# ===== S111: 全库 el-tooltip 归零 + loop-suspect 组件链点名 =====

def test_s111_zero_popper_chains():
    import glob as _glob
    for f in _glob.glob("static/templates/*.html"):
        assert "el-tooltip" not in _read(f), f
    home = _read("static/templates/page_home.html")
    assert "clickToSwitchModel" in home and home.count(':title="t(') >= 4
    rd = _read("static/js/renderer.js")
    assert "compChain" in rd and "renderer build=S1" in rd
# ===== S112: 弹层常驻通用解药（persistent=false + destroy-on-close 全量） =====

def test_s112_persistent_off_and_dialog_destroy():
    import glob as _glob
    tp = td = 0
    for f in _glob.glob("static/templates/*.html"):
        s = _read(f)
        tp += s.count(':persistent="false"')
        td += s.count('destroy-on-close')
        assert "el-tooltip" not in s, f
    assert tp >= 203 and td >= 66
    rd = _read("static/js/renderer.js")
    assert "compChain(this) + ' @ ' + ctxOf(this.$el)" in rd
# ===== S113: 七设置页 v-if + outerHTML 点名 + reasoning 因果续写不拆块 =====

def test_s113_pages_vif_and_reasoning_causal():
    for p in ('role', 'model-config', 'toolkit', 'system', 'logo', 'deploy-bot', 'api-group'):
        s = _read(f"static/templates/page_{p}.html").split("\n")[0]
        assert f"v-if=\"activeMenu === '{p}'\"" in s, p
        assert "v-show" not in s, p
    rd = _read("static/js/renderer.js")
    assert "outerHTML" in rd and "renderer build=S1" in rd
    tb = _read("static/js/methods/11_tool_blocks.js")
    assert "b.done = false; return b;" in tb
    assert "b.type === 'text' || b.type === 'tool_result' || b.type === 'error'" in tb
# ===== S114: 热区 el-button 原生刀 + pending 追赶仪表 + 泵预算 6/250 =====

def test_s114_native_buttons_and_pending_meter():
    lines = _read("static/templates/page_home.html").split("\n")
    for i in list(range(184, 200)) + list(range(359, 375)) + list(range(1129, 1160)):
        assert "<el-button" not in lines[i], i + 1
    home = "\n".join(lines)
    assert home.count('<button type="button" class="el-button') >= 16
    rd = _read("static/js/renderer.js")
    assert "pending=" in rd and "_streamRecvChars || 0) - (this.$root._streamFlushChars" in rd
    assert "renderer build=S1" in rd


# ===== S115: chat_main 原生刀镜像 + 扩展卡 el-card→原生 div + LoAF 400ms =====

def test_s115_chat_main_native_hotzone_and_card_div():
    cm = _read("static/templates/page_chat_main.html")
    assert "<el-button :title=\"t('copy')\"" not in cm
    assert "<el-button :title=\"t('unfavorite')\"" not in cm
    for html in (cm, _read("static/templates/page_home.html")):
        assert 'class="el-card is-always-shadow extension-card' in html
        assert html.count('<div class="el-card__body">') >= 4
        assert '<el-card class="extension-card' not in html
        assert '<el-card v-for="ext in' not in html
    rd = _read("static/js/renderer.js")
    assert "durationThreshold: 400" in rd
    assert "typing=" in rd
    assert "renderer build=S1" in rd


# ===== S116: 第三聊天宿主 ai-browser 消息区原生刀（三宿主收口） =====

def test_s116_ai_browser_native_message_row():
    ab = _read("static/templates/page_ai-browser.html")
    assert "<el-button :title=\"t('copy')\"" not in ab
    assert "<el-button :title=\"t('pause')" not in ab
    assert ab.count('<button type="button" class="el-button') >= 12
    rd = _read("static/js/renderer.js")
    assert "renderer build=S116" in rd
