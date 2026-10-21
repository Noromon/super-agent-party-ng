# mcp_client_fixed.py
import json
import asyncio
import logging
import shutil
from typing import Dict, Any, AsyncIterator, Optional

import anyio
from mcp import ClientSession
from mcp.client.stdio   import stdio_client
from mcp.client.sse     import sse_client
from mcp.client.websocket import websocket_client
from mcp.client.streamable_http import streamablehttp_client
from contextlib import AsyncExitStack, asynccontextmanager

# ---------- 超时与日志（S63）----------
DEFAULT_CALL_TIMEOUT = 180   # call_tool 默认超时（秒）；可被 settings['mcpCallTimeout'] 或 server 配置 callTimeout 覆盖
LIST_TOOLS_TIMEOUT = 10      # 装配路径 list_tools 超时：一次工具公告不该挂起整个引擎
MONITOR_LOCK_TIMEOUT = 30    # 重连循环清理拿锁超时：防止被挂死的 call_tool 链成僵尸锁


def _fmt_args(tool_params: Any) -> str:
    """日志用参数摘要：序列化并截断，长命令一行可读。"""
    try:
        s = json.dumps(tool_params, ensure_ascii=False)
    except Exception:
        s = str(tool_params)
    return s if len(s) <= 120 else s[:120] + "..."


# ---------- 工具 ----------
def get_command_path(command_name: str, default_command: str = "uv") -> str:
    path = shutil.which(command_name) or shutil.which(default_command)
    if not path:
        raise FileNotFoundError(f"未找到 {command_name} 或 {default_command}")
    return path

# ---------- 连接管理 ----------
class ConnectionManager:
    def __init__(self) -> None:
        self.session: Optional[ClientSession] = None
        self.tools: list[str] = []

    @asynccontextmanager
    async def connect(self, config: dict) -> AsyncIterator["ConnectionManager"]:
        async with AsyncExitStack() as stack:
            # 1. 建立传输层
            if "command" in config:
                from mcp.client.stdio import StdioServerParameters
                server_params = StdioServerParameters(
                    command=get_command_path(config["command"]),
                    args=config.get("args", []),
                    env=config.get("env"),
                )
                read, write = await stack.enter_async_context(stdio_client(server_params))
            else:
                mcptype = config.get("type", "ws")
                if "streamable" in mcptype:
                    mcptype = "streamablehttp"
                client_map = {
                    "ws": websocket_client,
                    "sse": sse_client,
                    "streamablehttp": streamablehttp_client,
                }
                headers = config.get("headers", {})
                client = client_map[mcptype](
                    config["url"], headers=headers
                ) if headers else client_map[mcptype](config["url"])

                transport = await stack.enter_async_context(client)

                # ---------- END ----------

                if mcptype == "streamablehttp":
                    read, write, _ = transport
                else:
                    read, write = transport
                # ---------- 首包校验（仅 SSE 需要） ----------
                if mcptype == "sse":
                    try:
                        # 非阻塞读 1 条消息，超时 3 秒
                        with anyio.move_on_after(3):
                            await read.receive()
                    except anyio.EndOfStream:
                        # 服务器立刻关闭，说明失败
                        raise RuntimeError("SSE stream closed immediately")
                    except Exception as e:
                        raise RuntimeError(f"SSE initial handshake failed: {e}") from e
            # 2. 建立会话
            self.session = await stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            self.tools = [t.name for t in (await self.session.list_tools()).tools]
            logging.info("Connected to MCP server. Tools: %s", self.tools)

            yield self


# ---------- 客户端 ----------
class McpClient:
    def __init__(self) -> None:
        self._conn: Optional[ConnectionManager] = None
        self._config: Optional[dict] = None
        self._lock = asyncio.Lock()
        self._monitor_task: Optional[asyncio.Task] = None
        self._shutdown = False
        self._on_failure_callback: Optional[callable] = None  # 新增：失败回调
        self._tools: list[str] = []
        self._tools_list = []
        self._name: str = "?"  # 日志标识（initialize 时记录 server_name）

    async def initialize(self, server_name: str, server_config: dict, on_failure_callback: Optional[callable] = None) -> None:
        """非阻塞初始化：拉起连接监控协程"""
        self._name = server_name
        self._config = server_config
        self._on_failure_callback = on_failure_callback  # 设置回调
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._connection_monitor())

    async def close(self) -> None:
        self._shutdown = True
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def _connection_monitor(self) -> None:
        """持续重连逻辑：仅在一个协程里管理 AsyncExitStack"""
        while not self._shutdown:
            try:
                async with ConnectionManager().connect(self._config) as conn:
                    async with self._lock:
                        self._conn = conn
                    # 心跳检测
                    while not self._shutdown:
                        try:
                            await asyncio.wait_for(self._conn.session.send_ping(), timeout=3)
                        except Exception:
                            break  # 断线，跳出 inner loop
                        await asyncio.sleep(30)
            except Exception as e:
                logging.exception("Connection failed, will retry: %s", e)
                if self._on_failure_callback:
                    await self._on_failure_callback(str(e))  # 调用回调
            finally:
                # 拿锁带超时（S63）：即便上一个 call_tool 处于挂死边缘，
                # 重连循环也不被链成永久僵尸锁；超时则强制重置连接引用。
                try:
                    await asyncio.wait_for(self._lock.acquire(), MONITOR_LOCK_TIMEOUT)
                except asyncio.TimeoutError:
                    logging.getLogger("app").warning(
                        "MCP %s 重连清理拿锁超时(%ss)，强制重置连接", self._name, MONITOR_LOCK_TIMEOUT)
                    self._conn = None
                else:
                    self._conn = None
                    self._lock.release()
            if not self._shutdown:
                await asyncio.sleep(5)

    # ---------- 外部 API ----------
    async def get_openai_functions(self,disable_tools=[]):
        async with self._lock:
            if not self._conn or not self._conn.session:
                return []
            try:
                listed = await asyncio.wait_for(self._conn.session.list_tools(), LIST_TOOLS_TIMEOUT)
            except asyncio.TimeoutError:
                logging.getLogger("app").warning("MCP list_tools 超时(>%ss): %s", LIST_TOOLS_TIMEOUT, self._name)
                return []
            tools = listed.tools
            self._tools = [t.name for t in tools]
            self._tools_list = [{"name": t.name, "description": t.description,"enabled":True} for t in tools]
            tools_list = []
            for t in tools:
                if t.name not in disable_tools:
                    tools_list.append(
                        {
                            "type": "function",
                            "function": {
                                "name": t.name,
                                "description": t.description,
                                "parameters": t.inputSchema,
                            },
                        }
                    )

            return tools_list

    async def call_tool(self, tool_name: str, tool_params: Dict[str, Any],
                        timeout: Optional[float] = None) -> Any:
        """调用工具。timeout 解析优先级（S63）：入参（dispatch 已按 settings 解析）
        → 本 server 配置 callTimeout → DEFAULT_CALL_TIMEOUT。
        超时返回 [Error] 字符串给 LLM（回合继续走），不再无限悬挂并僵尸化 _lock。
        """
        cfg_timeout = (self._config or {}).get("callTimeout")
        timeout = timeout or cfg_timeout or DEFAULT_CALL_TIMEOUT
        async with self._lock:
            if not self._conn or not self._conn.session:
                return None
            log = logging.getLogger("app")
            log.info("MCP 调用 %s.%s (timeout=%ss) 参数: %s",
                     self._name, tool_name, timeout, _fmt_args(tool_params))
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            try:
                result = await asyncio.wait_for(
                    self._conn.session.call_tool(tool_name, tool_params), timeout)
                log.info("MCP 调用完成 %s.%s 耗时 %.1fs", self._name, tool_name, loop.time() - t0)
                return result
            except asyncio.TimeoutError:
                log.error("MCP 调用超时 %s.%s (>%ss)，server 可能未返回响应",
                          self._name, tool_name, timeout)
                return "[Error] MCP call %s.%s timed out after %ss" % (self._name, tool_name, timeout)
            except Exception as e:
                logging.error("Failed to call tool %s: %s", tool_name, e)
                return "Failed to call tool %s: %s" % (tool_name, e)


# ---------- 使用示例 ----------
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    async def main():
        client = McpClient()
        await client.initialize(
            "example",
            {
                "type": "sse",
                "url": "http://127.0.0.1:8000/mcp",
            },
        )
        await asyncio.sleep(2)
        funcs = await client.get_openai_functions()
        print("OpenAI functions:", funcs)
        await asyncio.sleep(30)  # 保持连接
        await client.close()

    asyncio.run(main())