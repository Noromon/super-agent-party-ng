# S309b: 消息级计费累计帧 + Token 仪表盘（总token恒0/首token错时/无tok/s 修复）。
# 后端 stream_usage 控制帧（DONE 前、跨轮累计）+ 前端 guarded-once first_token、
# 实时 tok/s（80ms flush 节流）、无 usage 时字符估算兜底、footer 分项展示。
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # site-packages py.py shim 让位给仓库包

from py.msg_utils import accumulate_usage, usage_control_frame  # noqa: E402

STREAM_RESPONSE = (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8")
CHAT_JS = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
TEMPLATE = (_ROOT / "static" / "templates" / "page_chat_main.html").read_text(encoding="utf-8")
ZH = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")


class TestAccumulate:
    def test_cross_round_sum(self):
        acc = accumulate_usage(None, {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110})
        acc = accumulate_usage(acc, {"prompt_tokens": 150, "completion_tokens": 5, "total_tokens": 155})
        assert acc == {"prompt_tokens": 250, "completion_tokens": 15, "total_tokens": 265}

    def test_none_and_junk_passthrough(self):
        assert accumulate_usage(None, None) is None
        acc = {"prompt_tokens": 1, "completion_tokens": 0, "total_tokens": 1}
        assert accumulate_usage(acc, {"completion_tokens": "x", "prompt_tokens": True}) == acc
        assert accumulate_usage(acc, {"completion_tokens": 2})["completion_tokens"] == 2

    def test_frame_shape(self):
        frame = usage_control_frame({"prompt_tokens": 250, "completion_tokens": 15, "total_tokens": 265})
        assert frame.startswith("data: ") and frame.endswith("\n\n")
        obj = json.loads(frame[len("data: "):])
        assert obj["type"] == "stream_usage"
        assert obj["prompt_tokens"] == 250 and obj["completion_tokens"] == 15 and obj["total_tokens"] == 265

    def test_frame_absent_when_empty(self):
        assert usage_control_frame(None) is None
        assert usage_control_frame({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}) is None


class TestBackendWiring:
    def test_init_and_two_accum_sites(self):
        assert "_usage_acc = None" in STREAM_RESPONSE
        assert STREAM_RESPONSE.count("accumulate_usage(_usage_acc, usage_info)") == 2

    def test_frame_emitted_before_done(self):
        i = STREAM_RESPONSE.index("usage_control_frame(_usage_acc)")
        j = STREAM_RESPONSE.index('yield "data: [DONE]\\n\\n"', i)
        assert 0 < j - i < 300

    def test_ra11_wipe_not_resetting_acc(self):
        site = '                usage_info = None\n                if _st.pop("w1_cancel"'
        assert site in STREAM_RESPONSE  # 轮内擦除处不得误插 _usage_acc 复位


class TestFrontendPins:
    def test_stream_usage_branch(self):
        assert "parsed.type === 'stream_usage'" in CHAT_JS
        assert "_applyStreamUsage(currentMsg, parsed)" in CHAT_JS

    def test_first_token_guarded_once(self):
        assert "if (!currentMsg.first_token_latency)" in CHAT_JS
        assert "currentMsg.content === '' && !isResume" not in CHAT_JS

    def test_live_tok_per_sec_flush(self):
        i = CHAT_JS.index("flushStreamTextBuffer() {")
        seg = CHAT_JS[i:i + 2660]  # S316：守卫块变长，窗扩至函数尾
        assert "_usageFinal" in seg and "_streamT0" in seg and "tok_per_sec" in seg

    def test_est_finalize_fallback(self):
        assert "_finalizeUsage(currentMsg)" in CHAT_JS
        assert CHAT_JS.count("this._finalizeUsage(currentMsg)") == 2
        assert "/ 1.8" in CHAT_JS

    def test_msg_fields_and_t0(self):
        for k in ("completion_tokens: 0", "context_tokens: 0", "tok_per_sec: 0", "usage_est: false"):
            assert k in CHAT_JS
        assert "this._streamT0 = Date.now()" in CHAT_JS

    def test_template_footer(self):
        for key in ("completion_tokens", "context_tokens", "tokens_per_sec", "usage_est"):
            assert key in TEMPLATE[TEMPLATE.index("msg-status"):TEMPLATE.index("msg-status") + 1200]

    def test_locale_keys(self):
        for src in (ZH, EN):
            for key in ("'completion_tokens'", "'context_tokens'", "'tokens_per_sec'"):
                assert key in src


class TestS310LiveBadge:
    DATA = (_ROOT / "static" / "js" / "data" / "00_ui_core.js").read_text(encoding="utf-8")
    CSS = (_ROOT / "static" / "css" / "stream_live_badge.css").read_text(encoding="utf-8")  # S316: 独立文件（CSS 棘轮）

    def test_flush_updates_live_totals(self):
        i = CHAT_JS.index("flushStreamTextBuffer() {")
        seg = CHAT_JS[i:i + 2660]  # S316：窗扩至函数尾
        assert "this.streamLiveStats = { tok: _tps, out: _est, total: _est }" in seg
        assert "__m.usage_est = true" in seg
        assert "__m.completion_tokens = _est" in seg
        assert "__m.total_tokens = _est" in seg

    def test_stream_start_resets_badge(self):
        i = CHAT_JS.index("this._streamT0 = Date.now()")
        assert "this.streamLiveStats = null" in CHAT_JS[i:i + 220]

    def test_badge_template_and_gate(self):
        # S314：徽章改 DOM 直连——模板必须已无 Teleport/徽章节点（模板链路弃用）
        assert "<Teleport" not in TEMPLATE
        assert "stream-live-badge" not in TEMPLATE
        assert "streamLiveStats" not in TEMPLATE

    def test_data_key_and_css(self):
        assert "streamLiveStats: null" in self.DATA
        assert ".stream-live-badge" in self.CSS and "position: fixed" in self.CSS

    def test_s314_dom_direct_badge(self):
        assert "_liveBadgePaint" in CHAT_JS
        paint = CHAT_JS[CHAT_JS.index("_liveBadgePaint(stats)"):]
        paint = paint[:paint.index("_applyStreamUsage")]
        assert "document.body.appendChild" in paint
        assert "sap-live-badge" in paint and 'className = "stream-live-badge"'.replace('"', "'") in paint
        assert "b.remove()" in paint and "clearInterval" in paint
        assert "this._liveBadgePaint(this.streamLiveStats)" in CHAT_JS
        assert "z-index: 9999" in self.CSS
        assert 'href="css/stream_live_badge.css"' in (_ROOT / "static" / "index.html").read_text(encoding="utf-8")
        assert ".stream-live-badge" not in (_ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8")

    def test_s316_instant_rate(self):
        i = CHAT_JS.index("flushStreamTextBuffer() {")
        seg = CHAT_JS[i:i + 2660]
        assert "_flowTs" in seg and "_flowChars" in seg  # 滚动窗口 Δchars/Δt
        assert "_tokEma" in seg and "0.55" in seg and "0.45" in seg  # EMA 平滑
        assert "_dt >= 0.4" in seg  # 窗口最小间隔，防噪声
        j = CHAT_JS.index("this._streamT0 = Date.now()")
        assert "this._flowTs = 0; this._flowChars = 0; this._tokEma = 0;" in CHAT_JS[j:j + 400]

    def test_s316_badge_frosted_pill_left(self):
        blk = self.CSS[self.CSS.index(".stream-live-badge {"):]
        blk = blk[:blk.index("}")]
        assert "left: 22px" in blk and "right" not in blk
        assert "backdrop-filter: blur" in blk and "border-radius: 999px" in blk
        assert "var(--el-bg-color" in blk and "rgba(0, 0, 0, 0.62)" not in blk
        assert "fa-gauge-high" in CHAT_JS
