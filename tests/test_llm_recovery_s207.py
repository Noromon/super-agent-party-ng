# -*- coding: utf-8 -*-
"""S207：LLM 瞬断故障恢复（引擎推理中途暴毙 terminated 等 → 自动重试）。

语义（用户定稿）：重试预算 2 次退避 1s→2s（agentRobustness.llmRetry* 可配）；
覆盖全部 create 调用点；流中断=同 messages 原样重发本轮推理——重试边界严格
不含工具执行（断流时本轮工具零执行，重发零环境副作用）；4xx 语义错不重试；
耗尽后错误帧标注已自动重试次数。
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx
import openai

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.llm_recovery as lr  # noqa: E402

SERVER = ((_ROOT / "server.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8") + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8")
 + (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
_VT = (_ROOT / "py" / "vision_tools.py").read_text(encoding="utf-8")  # S299：视觉域迁出，计数合并
_GM = (_ROOT / "py" / "group_memory.py").read_text(encoding="utf-8")  # S300：群记忆域迁出，计数合并
CHAT_JS = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
RESUME_JS = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
TEMPLATE = (_ROOT / "config" / "settings_template.json").read_text(encoding="utf-8")
ZH = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
EN = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")


def _req():
    return httpx.Request("POST", "http://x/v1/chat/completions")


class _Status(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code


class TestClassify:
    def test_openai_connection_family(self):
        assert lr.is_transient_transport_error(openai.APIConnectionError(request=_req()))
        assert lr.is_transient_transport_error(openai.APITimeoutError(request=_req()))

    def test_httpx_transport(self):
        assert lr.is_transient_transport_error(httpx.ReadError("terminated"))
        assert lr.is_transient_transport_error(
            httpx.RemoteProtocolError("peer closed connection without sending complete message body"))

    def test_status_codes(self):
        assert lr.is_transient_transport_error(_Status("boom", 503))
        assert lr.is_transient_transport_error(_Status("slow down", 429))
        assert not lr.is_transient_transport_error(_Status("context length exceeded", 400))
        assert not lr.is_transient_transport_error(_Status("no auth", 401))
        assert not lr.is_transient_transport_error(_Status("model not found", 404))

    def test_text_tokens(self):
        assert lr.is_transient_transport_error(RuntimeError("LLM call failed: terminated"))
        assert lr.is_transient_transport_error(
            RuntimeError("incomplete chunked read"))
        assert lr.is_transient_transport_error(
            RuntimeError("[WinError 10054] 远程主机强迫关闭了一个现有的连接"))

    def test_non_transient(self):
        assert not lr.is_transient_transport_error(ValueError("温度参数无效"))
        assert not lr.is_transient_transport_error(KeyError("model"))
        assert not lr.is_transient_transport_error(None)
        assert not lr.is_transient_transport_error(asyncio.CancelledError())


class TestCfg:
    def test_defaults(self):
        assert lr.llm_retry_cfg({}) == (2, 1.0, True)
        assert lr.llm_retry_cfg(None) == (2, 1.0, True)
        assert lr.llm_retry_cfg({"agentRobustness": {}}) == (2, 1.0, True)

    def test_custom_and_clamp(self):
        s = {"agentRobustness": {"llmRetryMax": 5, "llmRetryBaseDelayMs": 500}}
        assert lr.llm_retry_cfg(s) == (5, 0.5, True)
        s = {"agentRobustness": {"llmRetryMax": 99, "llmRetryBaseDelayMs": 1,
                                 "llmRetryMidStream": False}}
        assert lr.llm_retry_cfg(s) == (5, 0.1, False)
        s = {"agentRobustness": {"llmRetryMax": -1}}
        assert lr.llm_retry_cfg(s)[0] == 0

    def test_garbage_falls_back(self):
        s = {"agentRobustness": {"llmRetryMax": "x", "llmRetryBaseDelayMs": None}}
        assert lr.llm_retry_cfg(s) == (2, 1.0, True)


def _rec_sleep(box):
    async def _s(base, attempt, cancelled=None, step=0.2):
        box.append(base * (2 ** attempt))
    return _s


class TestAcreate:
    def _run(self, coro):
        return asyncio.run(coro)

    def test_first_success(self):
        box = []
        orig, lr.backoff_sleep = lr.backoff_sleep, _rec_sleep(box)
        try:
            async def call():
                return "ok"
            assert self._run(lr.acreate(call, attempts=2, base_delay=1.0)) == "ok"
        finally:
            lr.backoff_sleep = orig
        assert box == []

    def test_transient_twice_then_ok(self):
        box = []
        orig, lr.backoff_sleep = lr.backoff_sleep, _rec_sleep(box)
        state = {"n": 0}
        try:
            async def call():
                state["n"] += 1
                if state["n"] <= 2:
                    raise httpx.ReadError("terminated")
                return "ok"
            assert self._run(lr.acreate(call, attempts=2, base_delay=1.0,
                                        label="t")) == "ok"
        finally:
            lr.backoff_sleep = orig
        assert box == [1.0, 2.0]

    def test_non_transient_immediate(self):
        box = []
        orig, lr.backoff_sleep = lr.backoff_sleep, _rec_sleep(box)
        state = {"n": 0}
        try:
            async def call():
                state["n"] += 1
                raise ValueError("温度参数无效")
            try:
                self._run(lr.acreate(call, attempts=2, base_delay=1.0))
                raise AssertionError("should raise")
            except ValueError:
                pass
        finally:
            lr.backoff_sleep = orig
        assert state["n"] == 1 and box == []

    def test_exhausted_carries_note(self):
        orig, lr.backoff_sleep = lr.backoff_sleep, _rec_sleep([])
        try:
            async def call():
                raise httpx.ConnectError("connection refused")
            try:
                self._run(lr.acreate(call, attempts=2, base_delay=0.1))
                raise AssertionError("should raise")
            except httpx.ConnectError as e:
                assert lr.retry_suffix(e) == "（已自动重试 2 次仍失败）"
        finally:
            lr.backoff_sleep = orig

    def test_cancel_during_backoff(self):
        orig, lr.backoff_sleep = lr.backoff_sleep, _rec_sleep([])

        async def sleep_like(base, attempt, cancelled=None, step=0.2):
            raise asyncio.CancelledError()  # 模拟真实退避中检出取消（真实实现同款行为）

        lr.backoff_sleep = sleep_like
        try:
            async def call():
                raise httpx.ReadError("terminated")
            try:
                self._run(lr.acreate(call, attempts=2, base_delay=1.0,
                                     cancelled=lambda: False))
                raise AssertionError("should raise")
            except httpx.ReadError as e:
                # 用户中途取消≠重试耗尽：原异常透传，不挂耗尽标注
                assert lr.retry_suffix(e) == ""
        finally:
            lr.backoff_sleep = orig

    def test_cancel_before_first_attempt(self):
        try:
            self._run(lr.acreate(lambda: None, attempts=2,
                                 cancelled=lambda: True))
            raise AssertionError("should raise")
        except asyncio.CancelledError:
            pass


class TestFrames:
    def test_retry_frame_shape(self):
        f = lr.stream_retry_chunk(1, 2, "x" * 300)
        p = json.loads(f[len("data: "):].strip())
        d = p["choices"][0]["delta"]
        assert d["stream_retry"]["attempt"] == 1
        assert d["stream_retry"]["attempts"] == 2
        assert len(d["stream_retry"]["reason"]) == 160

    def test_reset_frame_shape(self):
        f = lr.stream_reset_chunk(-5)
        p = json.loads(f[len("data: "):].strip())
        assert p["choices"][0]["delta"]["stream_reset"]["keep_text_chars"] == 0
        f = lr.stream_reset_chunk(42)
        p = json.loads(f[len("data: "):].strip())
        assert p["choices"][0]["delta"]["stream_reset"]["keep_text_chars"] == 42


class TestWiring:
    def test_all_creates_wrapped_or_looped(self):
        # 31 处 create：28 机械 acreate + 主链 2 手写重试环 + fast 手写 acreate
        # （S299：视觉域 5 处 acreate 随迁 py/vision_tools.py，计数并入）
        assert SERVER.count("acreate(") + _VT.count("acreate(") + _GM.count("acreate(") >= 28
        assert SERVER.count("_lr_attempt") >= 8  # 两个手写环
        plain = [ln for ln in (SERVER + _VT + _GM).splitlines()
                 if "await " in ln and "chat.completions.create(" in ln
                 and "lambda:" not in ln]
        # 手写环内 create 均为裸调用：全文裸 create 行数必须为 2（first-pass/second_round）
        assert len(plain) == 2, plain

    def test_retry_boundary_excludes_tool_round(self):
        # 重试 except 块内只允许重置累加器/发控制帧——不得出现工具轮执行入口
        for hunk in SERVER.split("except Exception as _lr_e:")[1:]:
            body = hunk.split("\n        usage_info")[0].split("\n                break")[0]
            body = body.split("\n")[0:40]
            seg = "\n".join(body)
            assert "_stream_tool_round" not in seg
            assert "_ns_tool_round" not in seg

    def test_keep_chars_bookkeeping(self):
        assert SERVER.count('_st["_lr_keep_chars"]') >= 3

    def test_error_frames_annotated(self):
        assert "str(e) + retry_suffix(e)" in SERVER  # 主流错误帧
        assert SERVER.count("retry_suffix(e)") >= 2  # ns 错误出口同标注

    def test_template_keys(self):
        d = json.loads(TEMPLATE)
        ar = d["agentRobustness"]
        assert ar["llmRetryMax"] == 2
        assert ar["llmRetryBaseDelayMs"] == 1000
        assert ar["llmRetryMidStream"] is True


class TestFrontendPins:
    def test_control_branches(self):
        for src in (CHAT_JS, RESUME_JS):
            assert "delta.stream_retry" in src
            assert "delta.stream_reset" in src

    def test_consume_hooks(self):
        # 带分号=调用点（定义行无分号）：reasoning/content/tool_progress 三处
        assert CHAT_JS.count("this._consumeStreamReset(currentMsg, toolCallStack);") == 3
        assert RESUME_JS.count("this._consumeStreamReset(currentMsg, toolCallStack);") == 3

    def test_methods_defined(self):
        for m in ("_showStreamRetryNote(", "_armStreamReset(", "_consumeStreamReset("):
            assert m in CHAT_JS

    def test_locale_keys(self):
        assert "streamRetrying" in ZH and "streamRetrying" in EN
