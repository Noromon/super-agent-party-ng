# py/ws_manager.py
# D-11: 每连接串行发送队列。广播/心跳/业务消息统一入队，由 per-connection
# sender 任务串行消费——心跳与业务对同一 socket 的并发 send_json 帧交错消失；
# 慢连接不再"超时即静默丢消息并摘连接"，改为队列缓冲+满时丢最旧保最新。
import asyncio
import logging
from typing import List, Optional
from fastapi import WebSocket

logger = logging.getLogger("app")

_QUEUE_MAX = 256


async def _safe_close(websocket: WebSocket):
    try:
        await websocket.close()
    except Exception:
        pass


class ConnectionManager:
    def __init__(self):
        # 维护所有活跃的 WebSocket 连接
        self.active_connections: List[WebSocket] = []
        self._queues = {}    # id(ws) -> asyncio.Queue
        self._senders = {}   # id(ws) -> asyncio.Task

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        key = id(websocket)
        q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAX)
        self._queues[key] = q
        self._senders[key] = asyncio.create_task(self._sender(websocket, q))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        key = id(websocket)
        self._queues.pop(key, None)
        task = self._senders.pop(key, None)
        if task:
            task.cancel()

    async def _sender(self, websocket: WebSocket, q: asyncio.Queue):
        while True:
            message = await q.get()
            try:
                await websocket.send_json(message)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # S138：warning 级别可见化 + best-effort 关闭 socket。原版只从池中
                # 静默移除，客户端 readyState 仍 OPEN = 僵尸连接（上行被 receive 循环
                # 吞、下行 enqueue 进已死队列），永不自愈。
                logger.warning(f"WS sender 失效，移除并关闭连接: {e}")
                self.disconnect(websocket)
                try:
                    asyncio.create_task(_safe_close(websocket))
                except Exception:
                    pass
                return

    def _enqueue(self, message: dict, websocket: WebSocket) -> bool:
        q = self._queues.get(id(websocket))
        if q is None:
            return False
        try:
            q.put_nowait(message)
        except asyncio.QueueFull:
            # 满=丢最旧保最新（陈旧状态帧对前端无价值）
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                return False
            logger.warning("WS 队列已满，丢弃最旧帧")
        return True

    async def send_json(self, message: dict, websocket: WebSocket, timeout: float = None):
        """向特定连接发送消息（入队串行化，timeout 参数保留兼容旧签名）"""
        self._enqueue(message, websocket)

    async def broadcast(self, message: dict, exclude: Optional[WebSocket] = None, timeout: float = None):
        """向所有连接广播（每连接队列串行，互不阻塞、互不交错）"""
        for conn in self.active_connections[:]:
            if conn != exclude:
                self._enqueue(message, conn)

    async def broadcast_concurrent(self, message: dict, exclude: Optional[WebSocket] = None, timeout: float = None):
        """兼容旧名：语义同上（入队即返回，单个慢连接不拖累其他连接）"""
        await self.broadcast(message, exclude=exclude)

    async def broadcast_settings_update(self, settings: dict, exclude: Optional[WebSocket] = None):
        """快捷函数：广播配置更新"""
        await self.broadcast({
            "type": "settings_update",
            "data": settings
        }, exclude=exclude)

    async def send_heartbeat(self):
        """发送心跳包以维持连接，防止 1006 断开。"""
        await self.broadcast({
            "type": "heartbeat",
            "data": {"status": "still_working"}
        })


# 创建单例对象
ws_manager = ConnectionManager()
