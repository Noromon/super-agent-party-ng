# -*- coding: utf-8 -*-
"""S162: IM /stop 真实停止——跨平台统一的生成流停止账本与回执编排。

各 IM bot 的流循环在 delta 帧上嗅探 stream_id（服务端流首帧 meta 携带，
与 Web 前端同源协议）记账到本模块；/stop 到达时复用 Web 停止键的同一
通道 POST /v1/streams/cancel/{stream_id}，服务端围栏（工具调度与后续
轮次前检查、批准后到达的工具执行拒绝、resume 410）与主会话界面停止键
完全一致地生效。

账本语义：
- track 幂等，新流首帧覆盖同 peer 旧账（异常路径漏 clear 时旧账无害：
  cancel 命中已结束流得 404 → False，且随即被 pop）。
- cancel 无论成败都 pop 账目，避免陈旧账目长期滞留。
"""
import logging

import aiohttp

logger = logging.getLogger("app")


def sniff_stream_id(delta) -> str:
    """从 delta 帧提取 stream_id（服务端首帧 meta；openai SDK 对未知字段
    的透传位置随版本有属性/model_extra 两种形态，双兜底）。"""
    if isinstance(delta, dict):  # qq 系：model_dump 后的 dict delta
        return str(delta.get("stream_id") or "")
    sid = getattr(delta, "stream_id", None) or ""
    if not sid:
        extra = getattr(delta, "model_extra", None) or {}
        if isinstance(extra, dict):
            sid = extra.get("stream_id") or ""
    return str(sid)


class StreamStopLedger:
    def __init__(self):
        self._active = {}  # (platform, peer) -> stream_id

    def track(self, platform: str, peer: str, delta) -> None:
        if not peer:
            return
        sid = sniff_stream_id(delta)
        if not sid:
            return
        key = (platform, peer)
        if self._active.get(key) != sid:
            self._active[key] = sid

    def clear(self, platform: str, peer: str) -> None:
        self._active.pop((platform, peer), None)

    def get(self, platform: str, peer: str) -> str:
        return self._active.get((platform, peer), "")

    def pop(self, platform: str, peer: str) -> str:
        return self._active.pop((platform, peer), "")

    async def cancel(self, platform: str, peer: str) -> bool:
        """经 Web 停止键同一端点取消该 peer 的活跃生成流。无账/流已
        结束/请求失败均返回 False（已 pop 清账）。"""
        sid = self.pop(platform, peer)
        if not sid:
            return False
        from py.get_setting import get_port
        url = f"http://127.0.0.1:{get_port()}/v1/streams/cancel/{sid}"
        try:
            timeout = aiohttp.ClientTimeout(total=3)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url) as resp:
                    if resp.status == 200:
                        logger.info("IM /stop cancelled stream %s (%s/%s)", sid, platform, peer)
                        return True
                    logger.info("stream cancel %s -> HTTP %s (%s/%s)", sid, resp.status, platform, peer)
                    return False
        except Exception as exc:
            logger.warning("stream cancel failed (%s/%s): %s", platform, peer, exc)
            return False


registry = StreamStopLedger()


async def handle_im_stop(platform: str, peer: str, lang: str = "zh") -> str:
    """/stop 统一处置：作废待审批（S150 语义）+ 取消活跃生成流（S162），
    返回回执文本（无实际动作时保持原仅回执文案）。"""
    from py import approval_im, shortcut_commands
    n_pending = 0
    try:
        n_pending = await approval_im.cancel_pending(platform, peer)
    except Exception as exc:
        logger.warning("cancel_pending failed (%s/%s): %s", platform, peer, exc)
    stopped = await registry.cancel(platform, peer)
    parts = []
    if stopped:
        parts.append("已停止正在进行的生成。" if lang != "en" else "Stopped ongoing generation.")
    if n_pending:
        parts.append(f"已作废 {n_pending} 个待审批。" if lang != "en"
                     else f"Discarded {n_pending} pending approval(s).")
    base = shortcut_commands.STOP_MSG_EN if lang == "en" else shortcut_commands.STOP_MSG_ZH
    if not parts:
        return base
    return base + "".join(f"\n{p}" for p in parts)
