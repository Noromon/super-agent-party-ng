import asyncio
import base64
import io
import logging
import re
import threading
import time
from typing import Dict, List, Optional, Any

import aiohttp
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from openai import AsyncOpenAI
from pydantic import BaseModel
from py.get_setting import get_port, load_settings

# ------------------ 配置模型 (严格对齐) ------------------
from py import llm_gate
from py.im_empty_guard import EMPTY_REPLY_MSG, log_empty_reply
from py.base_bot import BaseBotManager
from py import stream_stop

class SlackBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    bot_token: str
    app_token: str
    llm_model: str = "super-model"
    memory_limit: int = 30
    separators: List[str] = ["。", "\n", "？", "！"]
    reasoning_visible: bool = True
    quick_restart: bool = True
    enable_tts: bool = False
    wakeWord: str = ""
    # --- 新增：行为规则设置 ---
    behaviorSettings: Optional[Any] = None # 类型为 BehaviorSettings
    # Slack 特定的推送目标 ID 列表 (Channel IDs)
    behaviorTargetChatIds: List[str] = []

# ------------------ Slack 机器人管理器 ------------------
class SlackBotManager(BaseBotManager):
    """批 2 起为 BaseBotManager 的 Slack adapter。

    D2（已批准）：启动异常不再被吞——记入 _startup_error 由 start_bot
    传播；stop_bot 获得统一 join/清理语义。SocketMode 事件驱动、消息处理
    与行为回调为平台私产，保留在本类。
    """
    PLATFORM_LABEL = "Slack"
    THREAD_NAME = "SlackBotThread"
    SETTINGS_KEY = "slackBotConfig"
    TARGET_FIELD = "behaviorTargetChatIds"
    ENGINE_TARGET_KEY = "slack"
    STOP_JOIN_TIMEOUT = 5

    def __init__(self):
        super().__init__()
        self.socket_client: Optional[SocketModeClient] = None
        self.bot_user_id: Optional[str] = None
        # --- 状态存储 ---
        self.memory: Dict[str, List[dict]] = {}
        self.async_tools: Dict[str, List[str]] = {}
        self.file_links: Dict[str, List[str]] = {}

    async def pre_client_setup(self):
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.register_handler("slack", self.execute_behavior_event)

    async def build_client(self, config: SlackBotConfig):
        web_client = AsyncWebClient(token=config.bot_token)

        # 获取机器人 ID 用于防递归
        auth = await web_client.auth_test()
        self.bot_user_id = auth["user_id"]

        socket_client = SocketModeClient(app_token=config.app_token, web_client=web_client)

        async def process_listener(client, req: SocketModeRequest):
            if req.type == "events_api":
                await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
                event = req.payload.get("event", {})
                # 过滤逻辑
                if event.get("user") == self.bot_user_id or event.get("bot_id") or "subtype" in event:
                    return
                if event.get("type") in ["message", "app_mention"]:
                    asyncio.ensure_future(self._handle_message(event, web_client))

        socket_client.socket_mode_request_listeners.append(process_listener)
        self.socket_client = socket_client
        return socket_client

    async def run_client(self):
        await self.socket_client.connect()
        self.is_running = True
        self._ready_complete.set()
        while self.is_running:
            await asyncio.sleep(1)

    def on_stop_requested(self):
        if self.socket_client and self.loop and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(self.socket_client.close(), self.loop)
            except RuntimeError:
                pass

    def get_status(self):
        return {"is_running": self.is_running}

    # ---------- 核心处理：1:1 复刻 Discord 逻辑 ----------
    @llm_gate.gated
    async def _handle_message(self, event: dict, web_client: AsyncWebClient):
        cid = event["channel"]
        text = event.get("text", "").strip()

        if cid not in self.memory:
            self.memory[cid], self.async_tools[cid], self.file_links[cid] = [], [], []

        # --- 新增：上报活跃状态到引擎，用于无输入检测 ---
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.report_activity("slack", cid)

        # --- 新增：/id 指令获取当前频道 ID ---
        if text.lower() == "/id":
            info_msg = (
                f"🤖 *Slack Session Information Identified Successfully*\n\n"
                f"Current Channel ID:\n`{cid}`\n\n"
                f"💡 Note: Please directly copy the ID above and paste it into the 'Autonomous Actions' target list for Slack in the backend."
            )
            await web_client.chat_postMessage(channel=cid, text=info_msg)
            return

        # A11 IM 快捷指令（上游 3e58049f fork 适配：fork 无本地任务表，/stop 仅回执）
        from py import shortcut_commands
        _sub = shortcut_commands.parse_subscribe_action(text)
        if _sub:
            _reply = await shortcut_commands.handle_subscribe_command("slack", cid, _sub == "sub", "en")
            if _reply:
                await web_client.chat_postMessage(channel=cid, text=_reply)
            return

        if await shortcut_commands.im_shortcuts_enabled():
            _act = shortcut_commands.parse_im_action(text)
            if _act:
                if _act == "stop":
                    await web_client.chat_postMessage(channel=cid, text=await stream_stop.handle_im_stop("slack", cid, "en"))
                elif _act == "reset":
                    self.memory[cid].clear()
                    await web_client.chat_postMessage(channel=cid, text=shortcut_commands.RESET_MSG_EN)
                elif _act == "help":
                    await web_client.chat_postMessage(channel=cid, text=shortcut_commands.build_help_text("en"))
                elif _act == "skills":
                    await web_client.chat_postMessage(channel=cid, text=await shortcut_commands.build_skills_text("en"))
                elif _act == "model":
                    await web_client.chat_postMessage(channel=cid, text=await shortcut_commands.handle_model_command(text, "en"))
                elif _act == "personality":
                    await web_client.chat_postMessage(channel=cid, text=await shortcut_commands.handle_personality_command(text, "en"))
                elif _act == "retry":
                    await web_client.chat_postMessage(channel=cid, text=shortcut_commands.retry_hint("en"))
                elif _act == "mode":
                    await web_client.chat_postMessage(channel=cid, text=await shortcut_commands.build_mode_info_text("en"))
                return
        if self.config.wakeWord and self.config.wakeWord not in text: return

        if self.config.quick_restart and text in ["/重启", "/restart"]:
            self.memory[cid].clear()
            await web_client.chat_postMessage(channel=cid, text="对话记录已重置。")
            return

        self.memory[cid].append({"role": "user", "content": text})

        # --- 状态状态机 ---
        state = {
            "text_buffer": "", 
            "image_buffer": "", 
            "image_cache": [],
        }

        # 发送占位消息
        initial_resp = await web_client.chat_postMessage(channel=cid, text="...")
        reply_ts = initial_resp["ts"]

        settings = await load_settings()
        client_ai = AsyncOpenAI(api_key="super-secret-key", base_url=f"http://127.0.0.1:{get_port()}/v1")

        try:
            stream = await client_ai.chat.completions.create(
                model=self.config.llm_model,
                messages=self.memory[cid],
                stream=True,
                extra_body={
                    "asyncToolsID": self.async_tools[cid],
                    "fileLinks": self.file_links[cid],
                    "is_app_bot": True,
                    "platform": "slack",
                },
            )

            full_response = []
            last_update_time = time.time()
            reasoning_chars = 0
            finish_reason = ""

            async for chunk in stream:
                if not chunk.choices: continue
                delta_raw = chunk.choices[0].delta
                stream_stop.registry.track("slack", cid, delta_raw)  # S162：/stop 真实停止记账
                finish_reason = chunk.choices[0].finish_reason or finish_reason

                tool_link = getattr(delta_raw, "tool_link", None)
                if tool_link and settings.get("tools", {}).get("toolMemorandum", {}).get("enabled"):
                    if tool_link not in self.file_links[cid]: self.file_links[cid].append(tool_link)

                async_tool_id = getattr(delta_raw, "async_tool_id", None)
                if async_tool_id:
                    if async_tool_id not in self.async_tools[cid]: self.async_tools[cid].append(async_tool_id)
                    else: self.async_tools[cid].remove(async_tool_id)

                content = delta_raw.content or ""
                reasoning = getattr(delta_raw, "reasoning_content", None) or ""
                reasoning_chars += len(reasoning)
                if reasoning and self.config.reasoning_visible:
                    content = reasoning

                full_response.append(content)
                state["text_buffer"] += content
                state["image_buffer"] += content

                now = time.time()
                if (now - last_update_time > 1.2) or any(sep in content for sep in self.config.separators):
                    seg = self._clean_text(state["text_buffer"])
                    if seg and seg.strip():
                        await web_client.chat_update(channel=cid, ts=reply_ts, text=seg + " ▌")
                        last_update_time = now

            full_content = "".join(full_response)
            final_text = self._clean_text(full_content)
            await web_client.chat_update(channel=cid, ts=reply_ts, text=final_text or "回复完成。")

            self._extract_images(state)
            for img_url in state["image_cache"]:
                await self._send_image(cid, img_url, web_client)

            if not full_content.strip():
                log_empty_reply("slack", cid, reasoning_chars, finish_reason)
                if not state["image_cache"]:
                    await web_client.chat_update(channel=cid, ts=reply_ts, text=EMPTY_REPLY_MSG)
                return
            if self.config.enable_tts:
                await self._send_voice(cid, full_content, web_client)

            self.memory[cid].append({"role": "assistant", "content": full_content})
            if self.config.memory_limit > 0:
                while len(self.memory[cid]) > self.config.memory_limit * 2:
                    self.memory[cid].pop(0)

        except Exception as e:
            logging.error(f"Slack Bot Error: {e}")
            await web_client.chat_update(channel=cid, ts=reply_ts, text=f"❌ 处理消息失败: {e}")
        finally:
            stream_stop.registry.clear("slack", cid)  # S162：流终清账

    # ---------- 工具函数 (1:1 复刻 Discord) ----------
    def _extract_images(self, state: Dict[str, Any]):
        pattern = r'!\[.*?\]\((https?://[^\s)]+)'
        for m in re.finditer(pattern, state["image_buffer"]):
            state["image_cache"].append(m.group(1))

    def _clean_text(self, text: str) -> str:
        # 移除html标签
        text = re.sub(r'<.*?>', '', text)
        return re.sub(r"!\[.*?\]\(.*?\)", "", text).strip()

    async def _send_image(self, cid: str, url: str, web_client: AsyncWebClient):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        data = await r.read()
                        await web_client.files_upload_v2(channel=cid, file=data, filename="image.png")
        except Exception as e:
            logging.error(f"发送图片失败: {e}")

    async def _send_voice(self, cid: str, text: str, web_client: AsyncWebClient):
        try:
            import aiohttp
            settings = await load_settings()
            tts_settings = settings.get("ttsSettings", {})
            
            clean_text = re.sub(r'[*_~`#]|!\[.*?\]\(.*?\)', '', text)
            if not clean_text.strip(): return

            # --- 优化点：针对 Slack 调整 Payload ---
            payload = {
                "text": clean_text[:300],
                "voice": "default",
                "ttsSettings": tts_settings,
                "index": 0,
                # Slack 建议关闭 mobile_optimized 以获取标准 mp3
                "mobile_optimized": False, 
                "format": "mp3" # 👈 改为 mp3，Slack 兼容性更高
            }

            async with aiohttp.ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{get_port()}/tts", json=payload) as r:
                    if r.status == 200:
                        audio = await r.read()
                        
                        # 使用 v2 接口上传
                        await web_client.files_upload_v2(
                            channel=cid, 
                            file=audio, 
                            filename="voice.mp3", # 👈 扩展名改为 mp3
                            title="语音回复",       # 增加标题
                            initial_comment="🔊 语音合成已完成，点击上方文件名可试听。" # 引导用户
                        )
                    else:
                        logging.error(f"TTS 接口返回错误: {r.status}")
        except Exception as e:
            logging.error(f"Slack TTS 发送失败: {e}")

    def update_behavior_config(self, config: SlackBotConfig):
        """
        热更新行为配置，不重启机器人
        """
        # 更新 Manager 的本地记录
        self.config = config
        
        # 更新全局行为引擎
        from py.behavior_engine import global_behavior_engine
        target_map = {
            "slack": config.behaviorTargetChatIds
        }
        
        global_behavior_engine.update_config(
            config.behaviorSettings,
            target_map
        )
        logging.info("Slack 机器人: 行为配置已热更新，计时器已重置")


    @llm_gate.gated
    async def execute_behavior_event(self, chat_id: str, behavior_item: Any):
        """
        回调函数：响应行为引擎的主动触发指令
        """
        if not self.socket_client or not self.socket_client.web_client:
            return
            
        logging.info(f"[SlackBot] 行为触发! 目标: {chat_id}, 动作类型: {behavior_item.action.type}")
        
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content: return

        cid = chat_id
        if cid not in self.memory:
            self.memory[cid] = []
        
        # 构造上下文
        messages = self.memory[cid].copy()
        system_instruction = f"[system]: {prompt_content}"
        messages.append({"role": "user", "content": system_instruction})
        self.memory[cid].append({"role": "user", "content": system_instruction})

        try:
            client_ai = AsyncOpenAI(
                api_key="super-secret-key",
                base_url=f"http://127.0.0.1:{get_port()}/v1"
            )
            
            # 使用非流式请求处理主动行为
            response = await client_ai.chat.completions.create(
                model=self.config.llm_model,
                messages=messages,
                stream=False, 
                extra_body={
                    "is_app_bot": True,
                    "behavior_trigger": True,
                    "platform": "slack",
                    **behavior_item.tools_override(),
                }
            )
            
            reply_content = response.choices[0].message.content
            if reply_content:
                # 1. 发送文本
                await self.socket_client.web_client.chat_postMessage(channel=cid, text=reply_content)
                self.memory[cid].append({"role": "assistant", "content": reply_content})
                
                # 2. 如果开启了 TTS，则发送语音
                if self.config.enable_tts:
                    await self._send_voice(cid, reply_content, self.socket_client.web_client)
            
        except Exception as e:
            logging.error(f"[SlackBot] 执行行为 API 调用失败: {e}")

    async def _resolve_behavior_prompt(self, behavior: Any) -> Optional[str]:
        """解析行为配置，生成具体的 Prompt 指令"""
        import random
        action = behavior.action
        
        if action.type == "prompt":
            return action.prompt
            
        elif action.type == "random":
            if not action.random or not action.random.events:
                return None
            events = action.random.events
            if action.random.type == "random":
                return random.choice(events)
            elif action.random.type == "order":
                idx = action.random.orderIndex
                if idx >= len(events): idx = 0
                selected = events[idx]
                action.random.orderIndex = idx + 1 # 内存更新
                return selected
        return None