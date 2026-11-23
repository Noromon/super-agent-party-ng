# -*- coding: utf-8 -*-
"""S308：瞬断韧性加宽（llmRetryMax 默认 4+抖动）+ 网关 HTML 错误摘要 + 手动重试按钮。

事故（2026-11-24 00:54）：中转网关（Node/Express）自身崩溃返回 HTML 500，
S207 分类正确但默认 2 次重试 ≈5.5s 窗耗尽，15 分钟 agent 长跑终止；且重试
日志/展示帧原样倾倒整页 HTML；失败后无手动重试入口只能手打"继续"。
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import openai
import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.llm_recovery as lr  # noqa: E402

ROOT = _ROOT
SE = (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
LR = (ROOT / "py" / "llm_recovery.py").read_text(encoding="utf-8")
TPL_HTML = (ROOT / "static" / "templates" / "page_chat_main.html").read_text(encoding="utf-8")
TB = (ROOT / "static" / "js" / "methods" / "11_tool_blocks.js").read_text(encoding="utf-8")
ZH = (ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")

_HTML500 = ('<!DOCTYPE html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<title>Error</title>\n</head>\n<body>\n<pre>Internal Server Error</pre>\n'
            '</body>\n</html>\n')


def _ie500():
    req = httpx.Request("POST", "http://gw.local/v1/chat/completions")
    resp = httpx.Response(500, request=req)
    return openai.InternalServerError(_HTML500, response=resp, body=None)


class TestBriefLlmError:
    def test_gateway_html_folded(self):
        s = lr.brief_llm_error(_ie500())
        assert s.startswith("网关500(HTML响应,~")
        assert "DOCTYPE" not in s and "\n" not in s

    def test_html_without_status(self):
        s = lr.brief_llm_error(Exception(_HTML500))
        assert s.startswith("网关500(HTML响应,~")  # 文本含 internal server error → 500

    def test_plain_untouched(self):
        assert lr.brief_llm_error(RuntimeError("connection reset by peer")) == \
            "connection reset by peer"

    def test_long_plain_truncated(self):
        s = lr.brief_llm_error(RuntimeError("x" * 900))
        assert len(s) <= 300

    def test_transient_classification_survives(self):
        # 摘要只用于展示/日志，瞬断判定必须仍基于原异常（500→瞬断）
        assert lr.is_transient_transport_error(_ie500())


class TestBackoffJitter:
    def _collect(self, monkeypatch, base, attempt, rnd):
        box = []
        clock = {"t": 1000.0}

        async def fake_sleep(x):
            box.append(x)
            clock["t"] += x  # 假时钟同步推进：退避循环以时间判断，不真睡
        monkeypatch.setattr(lr.asyncio, "sleep", fake_sleep)
        monkeypatch.setattr(lr.time, "monotonic", lambda: clock["t"])
        monkeypatch.setattr(lr.random, "random", rnd)
        asyncio.run(lr.backoff_sleep(base, attempt))
        return sum(box)

    def test_jitter_within_bounds(self, monkeypatch):
        monkeypatch.setattr(lr.random, "random", lambda: 0.0)
        lo = self._collect(monkeypatch, 1.0, 0, lambda: 0.0)
        assert lo == pytest.approx(1.0)
        hi = self._collect(monkeypatch, 1.0, 0, lambda: 0.99999)
        assert hi == pytest.approx(1.3, abs=1e-3)

    def test_mid_value(self, monkeypatch):
        got = self._collect(monkeypatch, 1.0, 0, lambda: 0.5)
        assert got == pytest.approx(1.15, abs=1e-9)

    def test_cap_holds_after_jitter(self, monkeypatch):
        got = self._collect(monkeypatch, 1.0, 5, lambda: 0.9)
        assert got == pytest.approx(10.0)

    def test_cancel_raises(self, monkeypatch):
        async def fake_sleep(x):
            return None
        monkeypatch.setattr(lr.asyncio, "sleep", fake_sleep)

        async def body():
            with pytest.raises(asyncio.CancelledError):
                await lr.backoff_sleep(5.0, 0, cancelled=lambda: True)
        asyncio.run(body())


class TestPolicyDefaults:
    def test_cfg_default_is_4(self):
        assert lr.llm_retry_cfg(None) == (4, 1.0, True)
        assert lr.llm_retry_cfg({"agentRobustness": {}}) == (4, 1.0, True)

    def test_template_default_4(self):
        d = json.loads((ROOT / "config" / "settings_template.json").read_text(encoding="utf-8"))
        assert d["agentRobustness"]["llmRetryMax"] == 4

    def test_wire_pins(self):
        # 两条流路径：日志+展示帧都走摘要（2 路径 × 2 处）
        assert SE.count("brief_llm_error(_lr_e)") == 4
        assert LR.count("brief_llm_error(exc)") >= 1
        # 完整 traceback 出口保留（S207 语义不变）
        assert "raise llm_attach(_lr_e, _lr_attempt) from None" in SE


class TestManualRetryButton:
    def test_method_defined(self):
        assert "async retryLastRound()" in TB
        assert "this._retryRoundInFlight" in TB
        # 复用 isResume 续跑：已执行工具副作用不重放
        assert "generateAIResponse(this.mainAgent, last.agentName || undefined, true)" in TB
        # 空闲守卫：发送/打字中不触发
        assert "if (this.isSending || this.isTyping) return;" in TB
        # S199 同族自备件：controller 必须在续跑调用之前建好
        seg = TB[TB.index("async retryLastRound()"):]
        assert seg.index("this.abortController = new AbortController();") < \
            seg.index("await this.generateAIResponse")

    def test_template_binding(self):
        assert "@click=\"retryLastRound()\"" in TPL_HTML
        assert "t('retryRound')" in TPL_HTML
        assert "index === messages.length - 1 && !isSending" in TPL_HTML

    def test_locale_keys_clean(self):
        # zh 值必须是干净中文（防编码管道 '?' 回归——S308 踩过的坑）
        assert "'retryRound': '重试本轮'" in ZH
        assert "'retryRound': 'Retry round'" in EN
