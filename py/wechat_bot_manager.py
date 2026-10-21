# py/wechat_bot_manager.py
import asyncio
import json
import random
import threading
from typing import Optional, List
import weakref
import logging
import re
import sys
import os
import glob
import shutil
import importlib
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

from py.get_setting import get_port, load_settings
from py.behavior_engine import BehaviorItem, global_behavior_engine, BehaviorSettings

try:
    import wechatbot
    from wechatbot import WeChatBot
except ImportError:
    WeChatBot = None
    wechatbot = None
    logging.warning("尚未安装 wechatbot-sdk，请执行 pip install wechatbot-sdk")

# 拦截控制台输出的终极杀器
from py import llm_gate
from py.base_bot import BaseBotManager

class StreamInterceptor:
    def __init__(self, original_stream, qr_callback, success_callback):
        self.original_stream = original_stream
        self.qr_callback = qr_callback
        self.success_callback = success_callback
        self.buffer = ""

    def write(self, text):
        self.original_stream.write(text)
        try:
            self.buffer += str(text)
            
            # 1. 嗅探二维码链接
            if "liteapp.weixin.qq.com/q/" in self.buffer:
                match = re.search(r'(https://liteapp\.weixin\.qq\.com/q/[a-zA-Z0-9_?=&]+)', self.buffer)
                if match:
                    self.qr_callback(match.group(1))
                    self.buffer = self.buffer.replace(match.group(0), "")
            
            # 2. 嗅探登录成功特征字眼
            lower_buf = self.buffer.lower()
            success_keywords =["login successfully", "log in successfully", "logged in as", "登录成功", "wechat login succeed", "start auto replying"]
            if any(kw in lower_buf for kw in success_keywords):
                self.success_callback()
                self.buffer = "" # 避免重复触发

            if len(self.buffer) > 1000:
                self.buffer = self.buffer[-500:]
        except: pass

    def flush(self):
        self.original_stream.flush()
        
    def __getattr__(self, attr):
        return getattr(self.original_stream, attr)

# 配置模型增加了 force_relogin 字段


class WeChatBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    WeChatAgent: str = "super-model"
    memoryLimit: int = 30
    separators: List[str] =['。', '\n', '？', '！']
    reasoningVisible: bool = False
    quickRestart: bool = True
    enableTTS: bool = False
    wakeWord: str = ""
    force_relogin: bool = False  # 是否强制重新扫码登录
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class WeChatBotManager(BaseBotManager):
    """批 2 起为 BaseBotManager 的 WeChat adapter。

    扫码登录拦截（StreamInterceptor）、force_relogin SDK 热重载、
    bot.run 线程/协程分派等平台对抗逻辑保留在本类；
    就绪语义=乐观置位（与企微同模式：startup/ready/is_running 同步）。
    """
    PLATFORM_LABEL = "微信"
    THREAD_NAME = "WeChatBotThread"
    SETTINGS_KEY = "wechatBotConfig"
    TARGET_FIELD = "behaviorTargetChatIds"
    ENGINE_TARGET_KEY = "wechat"
    STOP_JOIN_TIMEOUT = 3
    AUTO_START_ENGINE = False    # run_client 内 stop+start 编排（原语义）

    def __init__(self):
        super().__init__()
        self.qr_url = None
        self.qr_base64 = None
        self.is_logged_in = False

    def start_bot(self, config):
        logging.info("========================================")
        logging.info("正在初始化微信机器人...")
        if WeChatBot is None:
            raise Exception("尚未安装 wechatbot-sdk")
        self.qr_url = None
        self.qr_base64 = None
        self.is_logged_in = False
        super().start_bot(config)

    def build_client(self, config: WeChatBotConfig):
        # ======= 核心对抗逻辑 =======
        # 如果收到了强制重登指令，先清空实体文件，再重载内存模块
        if config.force_relogin:
            self._clear_wechat_cache()
            config.force_relogin = False
            try:
                global WeChatBot
                if wechatbot is not None:
                    importlib.reload(wechatbot)
                    WeChatBot = wechatbot.WeChatBot
                    logging.info("🔄 已强制热重载 SDK 模块，摧毁残留在内存里的单例状态")
            except Exception as e:
                logging.warning(f"重载 wechatbot 模块失败: {e}")
        # ============================

        bot = WeChatBot()
        client = WeChatClient(bot)
        client.WeChatAgent = config.WeChatAgent
        client.memoryLimit = config.memoryLimit
        client.separators = config.separators if config.separators else ['。', '\n', '？', '！']
        client.reasoningVisible = config.reasoningVisible
        client.quickRestart = config.quickRestart
        client.enableTTS = config.enableTTS
        client.wakeWord = config.wakeWord

        @bot.on_message
        async def handle_message_wrapper(msg):
            await self.bot_client.handle_message(msg)
        return client

    async def run_client(self):
        from py.behavior_engine import global_behavior_engine
        original_stdout, original_stderr = sys.stdout, sys.stderr
        try:
            self.is_running = True
            self._ready_complete.set()  # 乐观置位（原 start_bot 不等 ready）

            def _handle_qr(url):
                if self.qr_url:
                    return
                self.qr_url = url
                logging.info("🚀 成功拦截登录链接！正在生成前端二维码图像...")
                try:
                    import qrcode
                    import io
                    import base64
                    qr = qrcode.QRCode(border=1)
                    qr.add_data(url)
                    qr.make(fit=True)
                    logging.getLogger("app").info("\n\n" + "=" * 50)
                    logging.getLogger("app").info("👉 微信机器人验证: 请扫码登录 👈")
                    qr.print_ascii(invert=True)
                    logging.getLogger("app").info("=" * 50 + "\n\n")

                    img = qr.make_image(fill_color="black", back_color="white")
                    buffered = io.BytesIO()
                    img.save(buffered, format="PNG")
                    self.qr_base64 = "data:image/png;base64," + base64.b64encode(buffered.getvalue()).decode("utf-8")
                except Exception as e:
                    logging.error(f"二维码生成异常: {e}")

            def _handle_success():
                if not self.is_logged_in:
                    self.is_logged_in = True
                    self.qr_base64 = None
                    self.qr_url = None
                    logging.info("✅ 检测到微信登录成功信号，等待前端关闭弹窗...")

            sys.stdout = StreamInterceptor(original_stdout, _handle_qr, _handle_success)
            sys.stderr = StreamInterceptor(original_stderr, _handle_qr, _handle_success)

            if global_behavior_engine.is_running:
                global_behavior_engine.stop()
            behavior_task = asyncio.create_task(global_behavior_engine.start())

            bot = self.bot_client.bot
            if hasattr(bot, 'run') and asyncio.iscoroutinefunction(bot.run):
                bot_task = asyncio.create_task(bot.run())
            else:
                bot_task = asyncio.create_task(asyncio.to_thread(bot.run))

            await asyncio.gather(behavior_task, bot_task, return_exceptions=True)

        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

    def stop_bot(self):
        logging.info("正在停止微信机器人服务...")
        self._stop_requested = True
        self._shutdown_event.set()

        # 主动断开当前的 SDK 连接
        if self.bot_client and hasattr(self.bot_client, 'bot'):
            bot = self.bot_client.bot
            for method in ['stop', 'logout', 'exit', 'close']:
                if hasattr(bot, method):
                    try:
                        getattr(bot, method)()
                        logging.info(f"已触发微信实例的 {method}()")
                    except Exception:
                        pass

        self.is_running = False

        # 强制摧毁事件循环
        if self.loop and not self.loop.is_closed():
            try:
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
                self.loop.call_soon_threadsafe(self.loop.stop)
            except Exception:
                pass

        # 等待后台纯净退出释放文件锁
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=self.STOP_JOIN_TIMEOUT)

        self._stop_requested = False

    def _cleanup(self):
        from py.behavior_engine import global_behavior_engine
        self.is_running = False
        try:
            if global_behavior_engine.is_running:
                global_behavior_engine.stop()
        except Exception:
            pass
        if self.loop and not self.loop.is_closed():
            try:
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
                self.loop.close()
            except Exception:
                pass
        self.bot_client = None
        self.loop = None
        self._shutdown_event.set()

    def get_status(self):
        return {
            "is_running": self.is_running,
            "startup_error": self._startup_error,
            "qr_url": self.qr_url,
            "qr_base64": getattr(self, 'qr_base64', None),
            "is_logged_in": getattr(self, 'is_logged_in', False),
        }

    def update_behavior_config(self, config: WeChatBotConfig):
        self.config = config
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.update_config(config.behaviorSettings, {"wechat": config.behaviorTargetChatIds})


class WeChatClient:
    def __init__(self, bot):
        self.bot = bot
        self.WeChatAgent = "super-model"
        self.memoryLimit = 10
        self.memoryList = {}
        self.separators = ['。', '\n', '？', '！']
        self.reasoningVisible = False
        self.quickRestart = True
        self.port = get_port()
        self._shutdown_requested = False
        self._manager_ref = None
        self.enableTTS = False
        self.wakeWord = None
        self.last_active_chat_id = None
        global_behavior_engine.register_handler("wechat", self.execute_behavior_event)

    @llm_gate.gated
    async def handle_message(self, msg) -> None:
        """处理微信消息（修复流式分段逻辑）"""
        if self._shutdown_requested: return
        
        chat_id = getattr(msg, 'user_id', 'unknown_user')
        self.last_active_chat_id = chat_id 
        global_behavior_engine.report_activity("wechat", chat_id)
        
        user_text = getattr(msg, 'text', '')
        if not user_text: return

        # 指令和记忆逻辑
        if "/id" in user_text.lower():
            info_msg = f"🤖 **会话信息识别成功**\n\n当前 ChatID:\n`{chat_id}`\n\n💡 说明: 请复制上方 ID 填入自主行为列表。"
            await self._send_text(msg, info_msg)
            return

        # A11 IM 快捷指令（上游 3e58049f fork 适配：fork 无本地任务表，/stop 仅回执）
        from py import shortcut_commands
        _sub = shortcut_commands.parse_subscribe_action(user_text)
        if _sub:
            _reply = await shortcut_commands.handle_subscribe_command("wechat", chat_id, _sub == "sub", "zh")
            if _reply:
                await self._send_text(msg, _reply)
            return

        if await shortcut_commands.im_shortcuts_enabled():
            _act = shortcut_commands.parse_im_action(user_text)
            if _act:
                if _act == "stop":
                    await self._send_text(msg, shortcut_commands.STOP_MSG_ZH)
                elif _act == "reset":
                    self.memoryList[chat_id] = []
                    await self._send_text(msg, shortcut_commands.RESET_MSG_ZH)
                elif _act == "help":
                    await self._send_text(msg, shortcut_commands.build_help_text("zh"))
                elif _act == "skills":
                    await self._send_text(msg, await shortcut_commands.build_skills_text("zh"))
                elif _act == "model":
                    await self._send_text(msg, await shortcut_commands.handle_model_command(user_text, "zh"))
                elif _act == "personality":
                    await self._send_text(msg, await shortcut_commands.handle_personality_command(user_text, "zh"))
                elif _act == "retry":
                    await self._send_text(msg, shortcut_commands.retry_hint("zh"))
                elif _act == "mode":
                    await self._send_text(msg, await shortcut_commands.build_mode_info_text("zh"))
                return
        if self.quickRestart and ("/重启" in user_text or "/restart" in user_text):
            self.memoryList[chat_id] = []
            await self._send_text(msg, "对话记录已重置。")
            return
            
        if chat_id not in self.memoryList: self.memoryList[chat_id] = []
        self.memoryList[chat_id].append({"role": "user", "content": user_text})

        client = AsyncOpenAI(api_key="super-secret-key", base_url=f"http://127.0.0.1:{self.port}/v1")
        
        state = {"text_buffer": ""}
        try:
            stream = await client.chat.completions.create(
                model=self.WeChatAgent,
                messages=self.memoryList[chat_id],
                stream=True,
                extra_body={
                    "is_app_bot": True,
                    "platform": "wechat",
                }
            )
            
            full_response = []
            async for chunk in stream:
                if not chunk.choices: continue
                content = chunk.choices[0].delta.content or ""
                
                # 处理推理内容
                reasoning = ""
                if hasattr(chunk.choices[0].delta, "reasoning_content"):
                    reasoning = chunk.choices[0].delta.reasoning_content
                if reasoning and self.reasoningVisible:
                    content = reasoning
                
                full_response.append(content)
                state["text_buffer"] += content
                
                # 分段逻辑
                buffer = state["text_buffer"]
                split_pos = -1
                
                if len(buffer) > 800:
                    for sep in self.separators:
                        pos = buffer.find(sep)
                        if pos != -1:
                            split_pos = pos + len(sep)
                            break
                    if split_pos == -1 and len(buffer) > 1200:
                        split_pos = 1000
                else:
                    for sep in self.separators:
                        pos = buffer.find(sep)
                        if pos != -1:
                            split_pos = pos + len(sep)
                            break
                
                if split_pos != -1:
                    current_chunk = buffer[:split_pos]
                    state["text_buffer"] = buffer[split_pos:]
                    
                    clean_text = self._clean_text(current_chunk)
                    if clean_text:
                        await self._send_text(msg, clean_text)
                        await asyncio.sleep(0.1)

            # 处理流结束后的残留内容
            if state["text_buffer"]:
                clean_text = self._clean_text(state["text_buffer"])
                if clean_text:
                    await self._send_text(msg, clean_text)

            # 更新记忆
            full_content = "".join(full_response)
            self.memoryList[chat_id].append({"role": "assistant", "content": full_content})
            
            if self.enableTTS:
                await self._send_voice(msg, full_content)

        except Exception as e:
            logging.error(f"微信消息处理异常: {e}")

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        text = re.sub(r'<.*?>', '', text)
        return text.strip()
    
    async def _send_text(self, msg, text):
        if hasattr(self.bot, 'reply'): await self.bot.reply(msg, text)

    @llm_gate.gated
    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """
        [优化版] 响应行为引擎的主动推送指令
        改为非流式合并发送，避免频率限制
        """
        # 1. 目标 ID 决策逻辑
        target_id = chat_id
        
        # 如果前端没配置固定 ID，尝试使用最后一次对话的活跃 ID
        if not target_id or target_id == "":
            target_id = getattr(self, 'last_active_chat_id', None)
            
        if not target_id:
            logging.info("ℹ️ [微信行为引擎] 行为触发，但既无配置 ID 也无活跃记录，跳过执行。")
            return
            
        # 2. 微信 Context Token 检查
        ct = self.bot._context_tokens.get(target_id)
        if not ct:
            logging.warning(f"⚠️ [微信行为引擎] 无法向 {target_id} 推送消息：缺少 Context Token。")
            logging.warning(f"💡 请先在微信里给机器人发个消息（或表情）激活会话。")
            return

        logging.info(f"🚀 [微信行为引擎] 触发主动行为! 目标: {target_id}, 类型: {behavior_item.action.type}")
        
        # 3. 解析 Prompt
        prompt_content = await self._resolve_behavior_prompt(behavior_item)
        if not prompt_content: 
            return

        # 4. 准备 AI 请求（使用非流式）
        if target_id not in self.memoryList: 
            self.memoryList[target_id] = []
        
        messages = self.memoryList[target_id].copy()
        messages.append({"role": "user", "content": f"[system]: {prompt_content}"})

        client = AsyncOpenAI(
            api_key="super-secret-key", 
            base_url=f"http://127.0.0.1:{self.port}/v1"
        )
        
        try:
            # 【核心优化】使用非流式请求，一次性获取完整回复
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self.WeChatAgent,
                    messages=messages,
                    stream=False,  # 改为非流式
                    extra_body={
                        "is_app_bot": True,
                        "platform": "wechat",
                        "behavior_trigger": True
                    }
                ),
                timeout=60.0
            )
            
            # 获取完整回复内容
            full_content = response.choices[0].message.content
            
            # 清理文本
            clean_content = self._clean_text(full_content)
            
            if clean_content:
                # 【核心优化】合并成一条消息发送，避免频率限制
                await self.bot.send(target_id, clean_content)
                
                # 更新长期记忆
                self.memoryList[target_id].append({"role": "user", "content": f"[system]: {prompt_content}"})
                self.memoryList[target_id].append({"role": "assistant", "content": full_content})
                
                logging.info(f"✅ [微信行为引擎] 主动消息已成功推送到 {target_id}")
                
                # 同步下发 TTS 语音文件
                if self.enableTTS:
                    await self._send_voice(target_id, full_content)
                    
        except asyncio.TimeoutError:
            logging.error(f"❌ [微信行为引擎] AI 请求超时")
        except Exception as e:
            logging.error(f"❌ [微信行为引擎] 运行时异常: {e}")
            import traceback
            traceback.print_exc()

    async def _resolve_behavior_prompt(self, behavior: BehaviorItem) -> str:
        action = behavior.action
        if action.type == "prompt": return action.prompt
        elif action.type == "random": return random.choice(action.random.events)
        return None
    

    async def _send_voice(self, target, text):
        """生成 TTS 语音并作为文件发送给微信"""
        try:
            from py.get_setting import load_settings
            import aiohttp
            
            settings = await load_settings()
            tts_settings = settings.get("ttsSettings", {})
            
            # 清理 Markdown 字符
            clean_tts_text = self._clean_text(text)
            if not clean_tts_text: return
            
            payload = {
                "text": clean_tts_text,
                "voice": "default",
                "ttsSettings": tts_settings,
                "index": 0,
                "format": "mp3"
            }
            
            logging.info("正在请求 TTS 生成微信语音回复...")
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(f"http://127.0.0.1:{self.port}/tts", json=payload) as resp:
                    if resp.status != 200:
                        logging.error(f"TTS 请求失败: {resp.status}")
                        return
                    
                    audio_bytes = await resp.read()
                    
                    chat_id = getattr(target, 'user_id', target)
                    
                    try:
                        logging.info("正在向微信发送 TTS 语音文件...")
                        content_dict = {
                            "file": audio_bytes, 
                            "file_name": "voice_reply.mp3"
                        }
                        
                        if hasattr(self.bot, 'send_media'):
                            await self.bot.send_media(chat_id, content_dict)
                        elif hasattr(self.bot, 'reply_media') and hasattr(target, '_context_token'):
                            await self.bot.reply_media(target, content_dict)
                        else:
                            logging.warning("未能在 wechatbot 实例上找到发送媒体的 API")
                            
                    except Exception as send_err:
                        logging.error(f"微信发送语音失败: {send_err}")
                        import traceback
                        traceback.print_exc()
                        
        except Exception as e:
            logging.error(f"TTS 处理异常: {e}")