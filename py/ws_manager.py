# py/ws_manager.py
import asyncio
import json
import logging
from typing import List, Optional
from fastapi import WebSocket

logger = logging.getLogger("app")

class ConnectionManager:
    def __init__(self):
        # 维护所有活跃的 WebSocket 连接
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def send_json(self, message: dict, websocket: WebSocket, timeout: float = 5.0):
        """向特定连接发送消息，带超时防止阻塞事件循环"""
        try:
            await asyncio.wait_for(websocket.send_json(message), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"发送消息超时({timeout}s)，移除连接")
            self.disconnect(websocket)
        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict, exclude: Optional[WebSocket] = None, timeout: float = 5.0):
        """向所有连接并发广播消息，可选排除某个连接。使用并发发送防止单个慢连接阻塞事件循环。"""
        targets = [c for c in self.active_connections[:] if c != exclude]
        if not targets:
            return

        async def _safe_send(conn: WebSocket):
            try:
                await asyncio.wait_for(conn.send_json(message), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"广播超时({timeout}s)，移除连接")
                self.disconnect(conn)
            except Exception as e:
                logger.error(f"广播失败，移除失效连接: {e}")
                self.disconnect(conn)

        # 并发发送，单个连接阻塞不会卡住其他连接
        await asyncio.gather(*[_safe_send(conn) for conn in targets], return_exceptions=True)

    async def broadcast_concurrent(self, message: dict, exclude: Optional[WebSocket] = None, timeout: float = 5.0):
        """
        非阻塞并发广播：所有连接同时发送，单个连接阻塞不影响其他连接。
        用于心跳等关键消息，防止事件循环饥饿导致 1006 断开。
        """
        targets = [c for c in self.active_connections[:] if c != exclude]
        if not targets:
            return

        async def _safe_send(conn: WebSocket):
            try:
                await asyncio.wait_for(conn.send_json(message), timeout=timeout)
            except asyncio.TimeoutError:
                logger.warning(f"并发广播超时({timeout}s)，移除连接")
                self.disconnect(conn)
            except Exception as e:
                logger.error(f"并发广播失败，移除失效连接: {e}")
                self.disconnect(conn)

        # 并发发送，单个连接阻塞不会卡住其他连接
        await asyncio.gather(*[_safe_send(conn) for conn in targets], return_exceptions=True)

    async def broadcast_settings_update(self, settings: dict, exclude: Optional[WebSocket] = None):
        """快捷函数：广播配置更新"""
        await self.broadcast({
            "type": "settings_update",
            "data": settings
        }, exclude=exclude)

    async def send_heartbeat(self):
        """
        发送心跳包以维持连接，防止 1006 断开。
        使用并发广播，避免单个慢连接阻塞所有心跳发送。
        """
        await self.broadcast_concurrent({
            "type": "heartbeat",
            "data": {"status": "still_working"}
        })

# 创建单例对象
ws_manager = ConnectionManager()
