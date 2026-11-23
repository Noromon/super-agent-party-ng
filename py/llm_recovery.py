# -*- coding: utf-8 -*-
"""S207：LLM 瞬断故障恢复。

引擎（LM Studio 等）推理中途被杀/重载时，SDK 在 create() 或读流阶段抛
传输族异常（terminated / peer closed connection / incomplete chunked read
等）。本模块提供：
  - is_transient_transport_error: 瞬断判定（4xx 语义错不重试）
  - acreate:      非流式/首字节前的退避重试（重试只重发 create 本身，
                  重试边界严格不含工具执行——已执行副作用永不重放）
  - backoff_sleep: 可取消的分段退避
  - llm_retry_cfg: 读取 agentRobustness.llmRetry* 配置
  - stream_retry_chunk / stream_reset_chunk: 流中断恢复控制帧
  - retry_suffix:  耗尽后错误标注
  - brief_llm_error: S308 错误一句话摘要（网关 HTML 错误页折叠）
"""
import asyncio
import json
import logging
import random
import time

import httpx

_TRANSIENT_TYPE_NAMES = (
    "APIConnectionError", "APITimeoutError", "InternalServerError",
    "RateLimitError", "ServiceUnavailableError", "APIStatusError",
    "TransportError", "TimeoutException", "ConnectError", "ReadError",
    "WriteError", "RemoteProtocolError", "ProtocolError",
)

# 传输族错误词表（引擎侧断连多以纯文本形态出现在异常里）
_TRANSIENT_TOKENS = (
    "terminated", "incomplete chunked read", "peer closed connection",
    "server disconnected", "connection reset", "connection refused",
    "connection aborted", "remote end closed", "remote protocol",
    "bad gateway", "service unavailable", "too many requests",
    "timed out", "timeout", "eof occurred", "network error",
    "getaddrinfo failed", "unable to connect", "winerror 10054",
    "winerror 10061", "winerror 10053",
)

_NOT_TRANSIENT_STATUS = {400, 401, 403, 404, 405, 406, 413, 422}
_TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}


def is_transient_transport_error(exc):
    """瞬断判定：传输族类型/状态码/错误词表命中 → True；确定性语义错 → False。"""
    if exc is None:
        return False
    if isinstance(exc, (asyncio.CancelledError, GeneratorExit, KeyboardInterrupt,
                        SystemExit)):
        return False
    if isinstance(exc, httpx.TransportError):
        return True
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if status in _NOT_TRANSIENT_STATUS:
            return False
        if status in _TRANSIENT_STATUS:
            return True
    name = type(exc).__name__
    for base in type(exc).__mro__:
        if base.__name__ in _TRANSIENT_TYPE_NAMES:
            name = base.__name__
            break
    if name in _TRANSIENT_TYPE_NAMES:
        # 状态码缺失的 APIStatusError 兜底走文本判定（下面统一判词表）
        if name != "APIStatusError":
            return True
    text = str(exc).lower()
    for tok in _TRANSIENT_TOKENS:
        if tok in text:
            return True
    return False


def brief_llm_error(exc):
    """S308：错误一句话摘要（日志/展示帧用）。中转网关 5xx 多以 Express/nginx
    默认 HTML 页形态出现，整页倾倒既刷日志又吓用户——折叠为
    「网关{status}(HTML,~{len}B)」；纯文本异常原样返回（截 300）。
    完整 traceback 仍由外层 StreamError ERROR 级日志保留。"""
    text = str(exc) if exc is not None else ""
    head = text.lstrip()[:200].lower()
    if head.startswith("<") or "<!doctype" in head or "<html" in head:
        status = getattr(exc, "status_code", None)
        if not isinstance(status, int):
            status = 500 if any(t in head for t in ("500", "internal server error")) else None
        return "网关%s(HTML响应,~%dB)" % (status if status else "?", len(text))
    return text[:300]


def llm_retry_cfg(settings):
    """返回 (max_retries, base_delay_seconds, mid_stream_enabled)。

    S308 策略变更：默认 2→4（00:54 事故：网关崩溃 ~30s 才恢复，5s 重试窗
    耗尽导致 15 分钟 agent 长跑终止；1/2/4/8s 指数退避+抖动 ≈15s 窗口，
    配置可 5 ≈25s）。"""
    ar = {}
    try:
        ar = (settings or {}).get("agentRobustness") or {}
    except AttributeError:
        ar = {}
    try:
        maxr = int(ar.get("llmRetryMax", 4))
    except (TypeError, ValueError):
        maxr = 4
    maxr = min(max(maxr, 0), 5)
    try:
        delay = float(ar.get("llmRetryBaseDelayMs", 1000))
    except (TypeError, ValueError):
        delay = 1000.0
    delay = min(max(delay / 1000.0, 0.1), 10.0)
    mid = bool(ar.get("llmRetryMidStream", True))
    return maxr, delay, mid


async def backoff_sleep(base_delay, attempt, cancelled=None, step=0.2):
    """指数退避 base*2**attempt（封顶 10s），分段睡眠并每段检查取消。
    S308：加 0–30% 随机抖动，防多路会话同步重试打踩刚恢复的网关。"""
    total = min(base_delay * (2 ** attempt) * (1.0 + random.random() * 0.3), 10.0)
    deadline = time.monotonic() + total
    while True:
        remain = deadline - time.monotonic()
        if remain <= 0:
            return
        await asyncio.sleep(min(step, remain))
        if cancelled is not None and cancelled():
            raise asyncio.CancelledError()


def attach_retry_note(exc, attempts):
    """把已重试次数挂到异常上，供外层错误帧标注。返回 exc。"""
    try:
        if attempts:
            setattr(exc, "sap_llm_retries", int(attempts))
    except Exception:
        pass
    return exc


def retry_suffix(exc):
    """外层错误帧用的中文标注后缀；未发生过重试则为空串。"""
    n = getattr(exc, "sap_llm_retries", 0) if exc is not None else 0
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = 0
    return f"（已自动重试 {n} 次仍失败）" if n > 0 else ""


async def acreate(make_call, *, attempts=2, base_delay=1.0, label="",
                  cancelled=None, log=None):
    """重发 create 本身（不含任何流消费/工具执行）。瞬断→退避重试；
    耗尽或非瞬断→重抛原异常（已挂重试计数）。"""
    _log = log or logging.getLogger("app")
    last = None
    for i in range(attempts + 1):
        if cancelled is not None and cancelled():
            raise asyncio.CancelledError()
        try:
            return await make_call()
        except Exception as exc:  # noqa: BLE001 — 判定后决定重抛或退避
            if not is_transient_transport_error(exc):
                raise attach_retry_note(exc, i) from None
            last = exc
            if i >= attempts:
                break
            _log.warning("[LLMRetry] %s 瞬断重试 %d/%d: %s",
                         label or "llm", i + 1, attempts, brief_llm_error(exc))
            try:
                await backoff_sleep(base_delay, i, cancelled=cancelled)
            except asyncio.CancelledError:
                raise attach_retry_note(last, i) from None
    raise attach_retry_note(last, attempts) from None


def _sse(obj):
    return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"


def stream_retry_chunk(attempt, attempts, reason=""):
    """瞬断重试状态帧：前端展示临时提示，下一个正常 chunk 到达自动消失。"""
    return _sse({"choices": [{"delta": {"stream_retry": {
        "attempt": int(attempt), "attempts": int(attempts),
        "reason": ("" if reason is None else str(reason))[:160]}}}]})


def stream_reset_chunk(keep_text_chars=0):
    """整轮重发控制帧：前端保留前 keep_text_chars 个字符（此前各轮已落账
    正文），新输出到达时清掉失败轮半截文本/思考与在途工具块后接流。"""
    return _sse({"choices": [{"delta": {"stream_reset": {
        "keep_text_chars": max(0, int(keep_text_chars))}}}]})
