# -*- coding: utf-8 -*-
"""进程级共享状态容器（批 1b）。

放跨 server.py 与 py/routers/*.py 共享的可变运行时状态，作为单一事实源：
消费方一律 `from py import app_state` 后**属性访问**（app_state.X），
不得 `from py.app_state import X`（导入时取值会滞后于 lifespan 的重绑）。

迁移进度（批 1）：MCP 客户端组、MCP/KB 状态、共享 HTTP 客户端、TTS/ASR
缓存已入本容器。`settings`/`client`/`reasoner_client` 暂留 server.py
（触点面大/重绑点多），留批 2 与引擎改造合刀。
"""
import httpx

# ---------- MCP 客户端组（lifespan 建连，system.py 可重建/置空） ----------
HA_client = None
ChromeMCP_client = None
sql_client = None
mcp_client_list = {}

# ---------- 连接状态广播（process_mcp/process_kb 写，memories.py 读） ----------
mcp_status = {}
kb_status = {}

# ---------- 共享 HTTP 连接池（lifespan 创建，语音/媒体路由复用） ----------
global_http_client: httpx.AsyncClient | None = None

# ---------- 语音客户端缓存（media 路由读写） ----------
openai_tts_clients_cache = {}   # 缓存 OpenAI TTS Client
tetos_speakers_cache = {}       # 缓存 Tetos Speaker 对象
openai_asr_clients_cache = {}
