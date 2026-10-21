# -*- coding: utf-8 -*-
"""断点续传：活跃流缓存与生产者/消费者中继（批 1 自 server.py 迁出）。

纯 asyncio 模块：零 server 私产依赖。生产者（stream/complete 引擎）把每个
SSE chunk 写入 buffer；消费者（首次连接与 resume 端点）按下标读取并可从任意
下标重放；T-4 的释放计数、延迟清理与 TTL 兜底清扫都在本模块内闭环。
消费方：server.py 引擎与端点注册、py/routers/tasks.py（resume/cancel/status）。
"""
import asyncio
import contextvars
import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("app")

# ==================== 断点续传：活跃流缓存 ====================
# 结构: {stream_id: {"buffer": [str, ...], "done": bool, "error": str|None, "new_data": asyncio.Event, "created_at": float, "consumer_count": int}}
_active_streams: Dict[str, dict] = {}
_active_streams_lock = asyncio.Lock()

# 生产者任务通过该 ContextVar 携带自身 stream entry，供 stream_generator
# 在每次工具调度/新一轮 LLM 调用前检查用户是否已点击停止（围栏：
# 取消后不得再产生任何工具副作用）
_current_stream_entry: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "_current_stream_entry", default=None
)


def _stream_cancelled() -> bool:
    entry = _current_stream_entry.get()
    return bool(entry and entry.get("cancelled"))


async def _stream_producer_wrapper(stream_id: str, gen):
    """
    包装原始 stream_generator，作为生产者：
    - 将每个 yield 的 SSE 字符串写入 buffer
    - 生成结束/出错时标记 done/error
    - 捕获 GeneratorExit，确保消费者断开不会终止生产者
    """
    entry = _active_streams[stream_id]
    _current_stream_entry.set(entry)
    try:
        async for sse_chunk in gen:
            entry["buffer"].append(sse_chunk)
            await asyncio.sleep(0)
        entry["done"] = True
    except GeneratorExit:
        # 消费者断开不应终止生产者，标记完成即可
        entry["done"] = True
        logger.info(f"Stream producer {stream_id} received GeneratorExit, marking done")
    except asyncio.CancelledError:
        # 生产者被显式取消（如清理），标记完成
        entry["done"] = True
        raise
    except Exception as e:
        entry["error"] = str(e)
        entry["done"] = True
        logger.error(f"Stream producer {stream_id} error: {e}")
    finally:
        entry["done"] = True
        # T-4: 生产者退出统一排程兜底（消费者已全退时 30s 后清理；仍有消费者则由
        # _release_consumer 归零时触发，TTL sweeper 为最终兜底）
        if entry.get("consumer_count", 0) <= 0:
            try:
                asyncio.create_task(_cleanup_stream(stream_id, delay=30.0))
            except RuntimeError:
                pass


async def _stream_consumer_generator(stream_id: str, from_index: int = 0):
    """
    消费者生成器：从 buffer[from_index] 开始读取并 yield。
    使用轮询方式等待生产者产出新数据，避免 Event 引用失效问题。
    在等待新数据时定期发送 SSE 心跳注释，保持连接活跃。
    """
    entry = _active_streams[stream_id]
    idx = from_index
    _heartbeat_counter = 0
    try:
        while True:
            buf = entry["buffer"]
            # 消费所有已缓存但未读的 chunk
            while idx < len(buf):
                yield buf[idx]
                idx += 1
                await asyncio.sleep(0)
            # 如果生产者已完成且无更多数据，退出
            if entry["done"]:
                break
            # 短暂等待后重新检查（轮询，50ms 间隔）
            await asyncio.sleep(0.05)
            # 每 3 秒发送一次 SSE 心跳注释，防止浏览器/代理超时关闭连接
            _heartbeat_counter += 1
            if _heartbeat_counter >= 60:  # 60 * 0.05s = 3s
                _heartbeat_counter = 0
                yield ": heartbeat\n\n"
        # 最终确保消费完所有
        buf = entry["buffer"]
        while idx < len(buf):
            yield buf[idx]
            idx += 1
    except asyncio.CancelledError:
        # 消费者被取消（客户端断开），不删除缓存，生产者继续
        pass
    finally:
        # T-4: 正常结束/断开/取消均释放本消费者的计数（初始 1 由此释放）
        _release_consumer(stream_id)



def _release_consumer(stream_id: str) -> None:
    """T-4: 消费者退出统一释放（含 entry 创建时的初始计数）。
    done 且计数归零 → 排程延迟清理（留重连窗口）。"""
    entry = _active_streams.get(stream_id)
    if not entry:
        return
    entry["consumer_count"] = max(0, entry.get("consumer_count", 0) - 1)
    if entry.get("done") and entry["consumer_count"] <= 0:
        try:
            asyncio.create_task(_cleanup_stream(stream_id, delay=5.0))
        except RuntimeError:
            pass


# T-4: 流缓存 TTL 兜底（created_at 此前写了没人读 = 无 TTL，长挂机线性泄漏）
_STREAM_TTL_DONE = 1800.0
_STREAM_TTL_HARD = 21600.0
_STREAM_TTL_INTERVAL = 300.0


def _stream_ttl_sweep(now: float = None, done_ttl: float = _STREAM_TTL_DONE,
                      hard_ttl: float = _STREAM_TTL_HARD) -> list:
    """TTL 清扫纯函数：done 且超过 done_ttl、或任意流超过 hard_ttl → 移除并取消生产者任务。"""
    now = time.time() if now is None else now
    reaped = []
    for sid, entry in list(_active_streams.items()):
        age = now - entry.get("created_at", now)
        if (entry.get("done") and age > done_ttl) or age > hard_ttl:
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            _active_streams.pop(sid, None)
            reaped.append(sid)
    return reaped


async def _stream_ttl_loop():
    while True:
        await asyncio.sleep(_STREAM_TTL_INTERVAL)
        try:
            reaped = _stream_ttl_sweep()
            if reaped:
                logger.warning(f"[T-4] TTL reaped {len(reaped)} stale streams: {reaped[:5]}")
        except Exception as e:
            logger.error(f"T-4 TTL sweep error: {e}")


async def _cleanup_stream(stream_id: str, delay: float = 30.0):
    """延迟清理已完成的流缓存，给客户端足够的重连时间"""
    await asyncio.sleep(delay)

    async with _active_streams_lock:
        entry = _active_streams.get(stream_id)
        if entry and entry.get("consumer_count", 0) <= 0:
            # 取消可能仍在运行的生产者任务
            task = entry.get("task")
            if task and not task.done():
                task.cancel()
            _active_streams.pop(stream_id, None)
            logger.info(f"Stream {stream_id} cache cleaned up")
