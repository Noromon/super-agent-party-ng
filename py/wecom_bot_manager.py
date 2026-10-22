# py/wecom_bot_manager.py
import asyncio
import json
import random
import threading
from typing import Optional, List
import weakref
import aiohttp
import io
import base64
import logging
import time
import re
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from py.get_setting import convert_to_amr_simple, get_port, load_settings
from py.behavior_engine import BehaviorItem, global_behavior_engine, BehaviorSettings
from aibot import WSClient, WSClientOptions, generate_req_id

# 企业微信机器人配置模型
from py import llm_gate
from py.base_bot import BaseBotManager

class WeComBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    WeComAgent: str           # LLM模型名
    memoryLimit: int          # 记忆条数限制
    bot_id: str               # 企微机器人BotID (Webhook Key)
    secret: str               # 企微长连接专用Secret
    reasoningVisible: bool    # 是否显示推理过程
    quickRestart: bool        # 快速重启指令开关
    enableTTS: bool           # 是否启用TTS
    wakeWord: str             # 唤醒词
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class WeComBotManager(BaseBotManager):
    """批 2 起为 BaseBotManager 的 WeCom adapter；WS 长连接编排、消息与
    行为回调为平台私产，保留在 WeComClient。"""
    PLATFORM_LABEL = "企业微信"
    THREAD_NAME = "WeComBotThread"
    SETTINGS_KEY = "weComBotConfig"
    TARGET_FIELD = "behaviorTargetChatIds"
    ENGINE_TARGET_KEY = "wecom"
    SYNC_CONFIG_WRITEBACK = False  # RA-07：旧 wecom 行为同步仅 update_config，不回写 config
    STOP_JOIN_TIMEOUT = 3
    AUTO_START_ENGINE = False    # 原语义：run_client 内 stop+restart 编排

    def build_client(self, config: WeComBotConfig):
        client = WeComClient()
        client.WeComAgent = config.WeComAgent
        client.memoryLimit = config.memoryLimit
        client.reasoningVisible = config.reasoningVisible
        client.quickRestart = config.quickRestart
        client.wakeWord = config.wakeWord
        return client

    async def run_client(self):
        from py.behavior_engine import global_behavior_engine
        try:
            options = WSClientOptions(bot_id=self.config.bot_id, secret=self.config.secret)
            self.bot_client.ws_client = WSClient(options)
            self.bot_client.register_events()

            if global_behavior_engine.is_running:
                global_behavior_engine.stop()
                await asyncio.sleep(0.5)
            asyncio.create_task(global_behavior_engine.start())

            # 标记状态（企微原语义：建连前即乐观标记，startup 与 ready 同步置位）
            self.is_running = True
            self._startup_complete.set()
            self._ready_complete.set()
            logging.info("[WeComManager] 状态已标记为 True，建立连接并进入保活...")

            # 建立连接并保活
            await self.bot_client.ws_client.connect()
            while not self._stop_requested:
                await asyncio.sleep(1.0)

        except Exception as e:
            self.is_running = False
            if not self._stop_requested:
                logging.error(f"企微长连接崩溃: {e}")
                self._startup_error = str(e)
            raise

    def _cleanup(self):
        if self.bot_client and self.bot_client.ws_client:
            try:
                self.bot_client.ws_client.disconnect()
            except Exception:
                pass
        super()._cleanup()

    def get_status(self):
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "config": self.config.model_dump() if self.config else None,
            "startup_error": self._startup_error,
        }

    def apply_live_fields(self, client, config: WeComBotConfig):
        client.WeComAgent = config.WeComAgent
        client.wakeWord = config.wakeWord
        client.config = config


class WeComClient:
    def __init__(self):
        self.WeComAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList = {}
        self.reasoningVisible = False
        self.quickRestart = True
        self.port = get_port()
        self.ws_client: WSClient = None
        self._manager_ref = None
        self.wakeWord = None
        
        global_behavior_engine.register_handler("wecom", self.execute_behavior_event)

    def register_events(self):
        @self.ws_client.on('message.text')
        async def on_text(frame): await self.handle_message(frame, "text")
        @self.ws_client.on('message.image')
        async def on_image(frame): await self.handle_message(frame, "image")
        @self.ws_client.on('message.voice')
        async def on_voice(frame): await self.handle_message(frame, "voice")

    @llm_gate.gated
    async def handle_message(self, frame, msg_type) -> None:
        body = frame.get('body', {})
        chat_id = body.get('chatid', body.get('from', {}).get('userid', ''))
        global_behavior_engine.report_activity("wecom", chat_id)
        
        client = AsyncOpenAI(api_key="sk", base_url=f"http://127.0.0.1:{self.port}/v1")
        if chat_id not in self.memoryList: self.memoryList[chat_id] = []
        
        user_text = ""
        user_content = []
        has_image = False
        
        # 1. 解析多种消息类型
        if msg_type == "text":
            user_text = body.get('text', {}).get('content', '')
            if "/id" in user_text.lower():
                await self.ws_client.reply_stream(frame, generate_req_id('stream'), f"ID: `{chat_id}`", True)
                return
            # A11 IM 快捷指令（上游 3e58049f fork 适配：fork 无本地任务表，/stop 仅回执）
            from py import shortcut_commands
            _sub = shortcut_commands.parse_subscribe_action(user_text)
            if _sub:
                _reply = await shortcut_commands.handle_subscribe_command("wecom", chat_id, _sub == "sub", "zh")
                if _reply:
                    await self.ws_client.reply_stream(frame, generate_req_id('stream'), _reply, True)
                return

            if await shortcut_commands.im_shortcuts_enabled():
                _act = shortcut_commands.parse_im_action(user_text)
                if _act:
                    if _act == "stop":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), shortcut_commands.STOP_MSG_ZH, True)
                    elif _act == "reset":
                        self.memoryList[chat_id] = []
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), shortcut_commands.RESET_MSG_ZH, True)
                    elif _act == "help":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), shortcut_commands.build_help_text("zh"), True)
                    elif _act == "skills":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), await shortcut_commands.build_skills_text("zh"), True)
                    elif _act == "model":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), await shortcut_commands.handle_model_command(user_text, "zh"), True)
                    elif _act == "personality":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), await shortcut_commands.handle_personality_command(user_text, "zh"), True)
                    elif _act == "retry":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), shortcut_commands.retry_hint("zh"), True)
                    elif _act == "mode":
                        await self.ws_client.reply_stream(frame, generate_req_id('stream'), await shortcut_commands.build_mode_info_text("zh"), True)
                    return
            if self.quickRestart and ("/重启" in user_text or "/restart" in user_text):
                self.memoryList[chat_id] = []
                await self.ws_client.reply_stream(frame, generate_req_id('stream'), "对话已重置。", True)
                return
            if self.wakeWord and self.wakeWord not in user_text: return

        elif msg_type == "image":
            image = body.get('image', {})
            if image.get('url'):
                # 企业微信图片需要 AES 解密，SDK 内置了 download_file 处理此逻辑
                buffer, _ = await self.ws_client.download_file(image.get('url'), image.get('aeskey'))
                base64_data = base64.b64encode(buffer).decode("utf-8")
                has_image = True
                user_content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_data}"}})

        elif msg_type == "voice":
            voice = body.get('voice', {})
            if voice.get('url'):
                # 语音也需要解密下载
                buffer, _ = await self.ws_client.download_file(voice.get('url'), voice.get('aeskey'))
                # 调用本地 ASR 接口
                transcribed = await self._transcribe_audio(buffer)
                if transcribed:
                    user_text = transcribed
                    if self.wakeWord and self.wakeWord not in user_text: return
                else:
                    await self.ws_client.reply_stream(frame, generate_req_id('stream'), "语音识别失败", True)
                    return

        # 2. 构造 OpenAI 多模态消息
        if has_image:
            if user_text: user_content.append({"type": "text", "text": user_text})
            self.memoryList[chat_id].append({"role": "user", "content": user_content})
        else:
            if user_text: self.memoryList[chat_id].append({"role": "user", "content": user_text})
            else: return

        # 3. LLM 响应与流式回传
        stream_id = generate_req_id('stream')
        full_response_text = ""
        try:
            stream = await client.chat.completions.create(
                model=self.WeComAgent,
                messages=self.memoryList[chat_id],
                stream=True,
                extra_body={
                    "is_app_bot": True,
                    "platform": "wecom",
                }
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                content = delta.content or ""
                reasoning = getattr(delta, "reasoning_content", "") or ""
                full_response_text += (reasoning if self.reasoningVisible and reasoning else content)
                
                if content:
                    # 控制发送频率，避免企微接口限流
                    await self.ws_client.reply_stream(frame, stream_id, full_response_text, False)
            
            await self.ws_client.reply_stream(frame, stream_id, full_response_text, True)
            self.memoryList[chat_id].append({"role": "assistant", "content": full_response_text})
            
            # # 4. 如果开启了 TTS，异步发送语音气泡
            # config = self._manager_ref().config if self._manager_ref else None
            # if config and config.enableTTS:
            #     asyncio.create_task(self._send_voice(chat_id, full_response_text))
                
        except Exception as e:
            logging.error(f"回复异常: {e}")
            await self.ws_client.reply_stream(frame, stream_id, f"机器人异常: {e}", True)

    @llm_gate.gated
    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """行为引擎触发主动发送"""
        logging.info(f"[WeComClient] 行为触发 -> {chat_id}")
        prompt = behavior_item.action.prompt
        if behavior_item.action.type == "random":
            prompt = random.choice(behavior_item.action.random.events)
        if not prompt: return

        if chat_id not in self.memoryList: self.memoryList[chat_id] = []
        messages = self.memoryList[chat_id] + [{"role": "user", "content": f"[system]: {prompt}"}]

        try:
            client = AsyncOpenAI(api_key="sk", base_url=f"http://127.0.0.1:{self.port}/v1")
            response = await client.chat.completions.create(
                model=self.WeComAgent, messages=messages, stream=False, 
                extra_body={
                    "is_app_bot": True,
                    "platform": "wecom",
                    "behavior_trigger": True
                }
            )
            reply = response.choices[0].message.content
            if reply:
                await self.ws_client.send_message(chat_id, {
                    'msgtype': 'markdown',
                    'markdown': {'content': reply}
                })
                self.memoryList[chat_id].append({"role": "assistant", "content": reply})
                
                # config = self._manager_ref().config if self._manager_ref else None
                # TTS备用，暂时未启用
                # if config and config.enableTTS:
                #     asyncio.create_task(self._send_voice(chat_id, reply))
        except Exception as e:
            logging.error(f"主动推送失败: {e}")

    # ------------------ 工具方法 ------------------

    async def _transcribe_audio(self, audio_data: bytes) -> str:
        """调用本地 ASR 处理收到的音频"""
        try:
            form = aiohttp.FormData()
            form.add_field('audio', io.BytesIO(audio_data), filename="voice.amr", content_type='audio/amr')
            async with aiohttp.ClientSession() as session:
                async with session.post(f"http://127.0.0.1:{self.port}/asr", data=form) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        return res.get("text", "")
            return ""
        except: return ""

    async def _send_voice(self, chat_id: str, text: str):
        try:
            # 【深度修复 Key 获取】
            # 尝试从多个渠道获取 bot_id，确保不为空
            manager = self._manager_ref()
            bot_key = None
            if manager and manager.config:
                bot_key = manager.config.bot_id
            
            # 如果还是没有，尝试从 settings 紧急加载
            if not bot_key:
                try:
                    settings = await load_settings()
                    bot_key = settings.get("weComBotConfig", {}).get("bot_id")
                except: pass

            if not bot_key:
                logging.error("[WeComClient] 关键错误：未找到企微 bot_id，无法发送语音")
                return

            # 1. 清理文本
            clean_text = re.sub(r'[*_#`~>]', '', text)
            if not clean_text.strip(): return
            
            async with aiohttp.ClientSession() as session:
                # 2. 请求 MP3
                payload = {"text": clean_text, "voice": "default", "format": "mp3"} 
                async with session.post(f"http://127.0.0.1:{self.port}/tts", json=payload) as r:
                    if r.status != 200: return
                    mp3_data = await r.read()

                # 3. 转码
                amr_data = await asyncio.to_thread(convert_to_amr_simple, mp3_data)
                if not amr_data: return

                # 4. 上传
                upload_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={bot_key}&type=voice"
                form = aiohttp.FormData()
                form.add_field('media', amr_data, filename='voice.amr', content_type='audio/amr')
                
                async with session.post(upload_url, data=form) as up_resp:
                    up_data = await up_resp.json()
                    media_id = up_data.get("media_id")
                    if not media_id:
                        logging.error(f"企微素材上传失败。Key: {bot_key}, 响应: {up_data}")
                        return
                
                # 5. 发送
                send_url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={bot_key}"
                async with session.post(send_url, json={
                    "msgtype": "voice",
                    "voice": {"media_id": media_id}
                }) as send_resp:
                    res = await send_resp.json()
                    if res.get("errcode") == 0:
                        logging.info(f"成功向 {chat_id} 发送语音气泡")
                    else:
                        logging.error(f"企微语音发送失败: {res}")
                        
        except Exception as e:
            logging.error(f"企微 TTS 流程异常: {e}")