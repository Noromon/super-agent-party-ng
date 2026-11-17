# -*- coding: utf-8 -*-
"""S232：在途请求活动计数——「对话/长任务进行中」的服务器侧信号。

流式任务由 stream_relay._active_streams（has_live_streams）覆盖全生命周期；
但非流式请求（IM bot、子代理、complete 路径，stream=False）不在其中注册，
上层引擎（日记触发计时器等）会探测不到这些长任务。本模块在
/v1/chat/completions 端点入口/出口做进出计数，覆盖所有非流式请求的
完整 handler 生命周期（工具循环亦在请求生命周期内）。

日记系统自身的自调用（platform="diary"）不计入，避免触发暂停逻辑自锁。
"""

_inflight = 0


def begin() -> None:
    global _inflight
    _inflight += 1


def end() -> None:
    global _inflight
    _inflight = max(0, _inflight - 1)


def in_flight() -> int:
    return _inflight


def is_agent_busy() -> bool:
    """是否存在进行中的用户对话/长任务（不含日记自调用与流式——后者用 has_live_streams）。"""
    return _inflight > 0
