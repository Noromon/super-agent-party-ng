import asyncio
import json
import random
import threading
import os
import time
import logging
import aiohttp
import re
import base64
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from openai import AsyncOpenAI

# 钉钉官方 SDK
import dingtalk_stream
from dingtalk_stream import AckMessage, ChatbotMessage

# 假设这两个函数在你的 py.get_setting 中定义
from py.behavior_engine import BehaviorItem, BehaviorSettings,global_behavior_engine
from py.get_setting import get_port, load_settings
from py.random_topic import get_random_topics

# 配置模型
from py import llm_gate
from py.base_bot import BaseBotManager

class DingtalkBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    DingtalkAgent: str
    memoryLimit: int
    appKey: str
    appSecret: str
    separators: List[str]
    reasoningVisible: bool
    quickRestart: bool
    enableTTS: bool 
    wakeWord: str
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetChatIds: List[str] = Field(default_factory=list)

class DingtalkBotManager(BaseBotManager):
    """批 2 起为 BaseBotManager 的 Dingtalk adapter。

    D1（已批准）：start_bot 不再抢先置 is_running——client 长驻任务经
    稳定窗口（START_SETTLE_SECONDS）未抛错才就绪；快速失败经
    _startup_error 传播。行为引擎与长连接同生命周期（run_client 编排，
    AUTO_START_ENGINE=False）。
    """
    PLATFORM_LABEL = "钉钉"
    THREAD_NAME = "DingtalkBotThread"
    SETTINGS_KEY = "dingtalkBotConfig"
    TARGET_FIELD = "behaviorTargetChatIds"
    ENGINE_TARGET_KEY = "dingtalk"
    STOP_JOIN_TIMEOUT = 5
    AUTO_START_ENGINE = False
    START_SETTLE_SECONDS = 5

    def __init__(self):
        super().__init__()
        self.client = None
        self.bot_logic = None

    def build_client(self, config: DingtalkBotConfig):
        self.bot_logic = DingtalkClientLogic(config)
        credential = dingtalk_stream.Credential(config.appKey, config.appSecret)
        client = dingtalk_stream.DingTalkStreamClient(credential)
        client.register_callback_handler(ChatbotMessage.TOPIC, DingtalkInternalHandler(self.bot_logic))
        self.client = client  # run_client/stop 沿用平台原属性名
        return client

    async def run_client(self):
        from py.behavior_engine import global_behavior_engine
        logging.info("[Dingtalk] 正在并发启动：行为引擎 + 钉钉长连接...")
        eng_task = asyncio.create_task(global_behavior_engine.start())
        cli_task = asyncio.create_task(self.client.start())
        try:
            done, _ = await asyncio.wait(
                {cli_task}, timeout=self.START_SETTLE_SECONDS,
                return_when=asyncio.FIRST_COMPLETED)
            if cli_task in done and cli_task.exception():
                raise cli_task.exception()
            self.is_running = True
            self._ready_complete.set()
            logging.info("[Dingtalk] 机器人已完全就绪")
            await asyncio.wait({cli_task, eng_task}, return_when=asyncio.FIRST_COMPLETED)
            # RA-05：settle 窗后 cli_task 异常死亡须继续上抛（旧 gather 必记语义），
            # 交由基类 except 填 _startup_error，避免静默死亡+泛化报错
            if cli_task.done() and cli_task.exception():
                raise cli_task.exception()
        finally:
            for t in (cli_task, eng_task):
                if not t.done():
                    t.cancel()
            global_behavior_engine.stop()

    def on_stop_requested(self):
        if self.client:
            try:
                self.client.stop()
            except Exception:
                pass

    def get_status(self):
        return {
            "is_running": self.is_running,
            "has_error": self._startup_error is not None,
            "error_message": self._startup_error,
            "config_loaded": self.config is not None,
        }

    def apply_live_fields(self, client, config: DingtalkBotConfig):
        if self.bot_logic:
            self.bot_logic.config = config


class DingtalkInternalHandler(dingtalk_stream.ChatbotHandler):
    def __init__(self, bot_logic):
        super(DingtalkInternalHandler, self).__init__()
        self.bot_logic = bot_logic

    async def process(self, callback: dingtalk_stream.CallbackMessage):
        try:
            # 解析原始消息
            incoming_message = ChatbotMessage.from_dict(callback.data)
            # 传入完整数据 callback.data 以便解析更多隐藏字段
            await self.bot_logic.on_message(callback.data, incoming_message, self)
        except Exception as e:
            logging.getLogger("app").info(f"消息处理异常: {e}")
        return AckMessage.STATUS_OK, 'OK'

class DingtalkClientLogic:
    def __init__(self, config):
        self.config = config
        self.memoryList = {}
        self.port = get_port()
        self.separators = config.separators if config.separators else ['。', '\n', '？', '！']
        
        # --- 新增：注册到行为引擎 ---
        # 告知引擎：dingtalk 平台的执行逻辑由我负责
        global_behavior_engine.register_handler("dingtalk", self.execute_behavior_event)

    async def _get_image_base64(self, url: str) -> Optional[str]:
        """下载钉钉图片并转换为 Base64，解决 AI 访问 403 问题"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.read()
                        return base64.b64encode(data).decode('utf-8')
                    else:
                        logging.getLogger("app").info(f"图片下载失败, HTTP状态码: {response.status}")
        except Exception as e:
            logging.getLogger("app").info(f"图片处理异常: {e}")
        return None

    @llm_gate.gated
    async def on_message(self, raw_data: dict, incoming_message: ChatbotMessage, handler: DingtalkInternalHandler):
        cid = incoming_message.conversation_id
        msg_type = incoming_message.message_type
        global_behavior_engine.report_activity("dingtalk", cid)
        user_text_parts = []  # 收集所有文本片段
        user_content_items = []  # 构造 OpenAI 格式的 content
        has_image = False
        
        # --- A. 增强型消息解析 ---
        
        # 1. 处理纯文本消息
        if msg_type == "text":
            if hasattr(incoming_message, 'text') and incoming_message.text:
                user_text_parts.append(incoming_message.text.content.strip())
        
        # 2. 处理纯图片消息
        elif msg_type == "picture":
            download_code = incoming_message.image_content.download_code
            if download_code:
                img_url = handler.get_image_download_url(download_code)
                if img_url:
                    base64_str = await self._get_image_base64(img_url)
                    if base64_str:
                        has_image = True
                        user_content_items.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                        })
            # 尝试获取图片附带文字
            if hasattr(incoming_message, 'text') and incoming_message.text:
                user_text_parts.append(incoming_message.text.content.strip())
            elif raw_data.get("content", {}).get("text"):
                user_text_parts.append(raw_data["content"]["text"].strip())
        
        # 3. 处理富文本消息（同时包含文字和图片）
        elif msg_type == "richText":
            # 关键修正：SDK 中定义的是 rich_text_content
            if hasattr(incoming_message, 'rich_text_content') and incoming_message.rich_text_content:
                rich_list = incoming_message.rich_text_content.rich_text_list
                
                if rich_list:
                    for item in rich_list:
                        # 提取文本
                        if 'text' in item and item['text']:
                            user_text_parts.append(item['text'])
                        
                        # 提取图片
                        if 'downloadCode' in item and item['downloadCode']:
                            download_code = item['downloadCode']
                            img_url = handler.get_image_download_url(download_code)
                            if img_url:
                                base64_str = await self._get_image_base64(img_url)
                                if base64_str:
                                    has_image = True
                                    user_content_items.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                                    })
            
            # 备用：如果 SDK 解析失败，尝试从 raw_data 解析
            if not user_text_parts and not user_content_items:
                content = raw_data.get('content', {})
                if 'richText' in content:
                    for item in content['richText']:
                        if 'text' in item:
                            user_text_parts.append(item['text'])
                        if 'downloadCode' in item:
                            # 同样的图片处理逻辑...
                            download_code = item['downloadCode']
                            img_url = handler.get_image_download_url(download_code)
                            if img_url:
                                base64_str = await self._get_image_base64(img_url)
                                if base64_str:
                                    has_image = True
                                    user_content_items.append({
                                        "type": "image_url",
                                        "image_url": {"url": f"data:image/jpeg;base64,{base64_str}"}
                                    })

        # 合并所有文本
        user_text = "\n".join(user_text_parts).strip()
        
        # --- B. 指令与过滤（保持原逻辑）---
        if not user_text and not has_image:
            return

        # 在 on_message 方法中
        if "/id" in user_text.lower():
            # 判断当前是群聊还是单聊
            if cid.startswith("cid"):
                # --- 情况 A: 群聊 ---
                msg = (
                    f"【当前为群聊】\n"
                    f"群会话 ID (OpenConversationId):\n`{cid}`\n\n"
                    f"请复制上方 ID 填入目标列表，机器人将向**本群**推送消息。"
                )
            else:
                # --- 情况 B: 单聊 ---
                # 优先获取企业内部 StaffId
                staff_id = getattr(incoming_message, 'sender_staff_id', None)
                if not staff_id:
                    staff_id = raw_data.get("senderStaffId")
                
                # 兜底：如果你之前测出来的 0246... 那个ID能用，也可以显示 sender_id
                final_id = staff_id if staff_id else incoming_message.sender_id

                msg = (
                    f"【当前为单聊】\n"
                    f"您的用户 ID (UserID):\n`{final_id}`\n\n"
                    f"请复制上方 ID 填入目标列表，机器人将向**您个人**推送消息。"
                )
            
            handler.reply_markdown("ID 抓取助手", msg, incoming_message)
            return

        # A11 IM 快捷指令（上游 3e58049f fork 适配：fork 无本地任务表，/stop 仅回执）
        from py import shortcut_commands
        _sub = shortcut_commands.parse_subscribe_action(user_text)
        if _sub:
            _reply = await shortcut_commands.handle_subscribe_command("dingtalk", cid, _sub == "sub", "zh")
            if _reply:
                handler.reply_text(_reply, incoming_message)
            return

        if await shortcut_commands.im_shortcuts_enabled():
            _act = shortcut_commands.parse_im_action(user_text)
            if _act:
                if _act == "stop":
                    handler.reply_text(shortcut_commands.STOP_MSG_ZH, incoming_message)
                elif _act == "reset":
                    self.memoryList[cid] = []
                    handler.reply_text(shortcut_commands.RESET_MSG_ZH, incoming_message)
                elif _act == "help":
                    handler.reply_text(shortcut_commands.build_help_text("zh"), incoming_message)
                elif _act == "skills":
                    handler.reply_text(await shortcut_commands.build_skills_text("zh"), incoming_message)
                elif _act == "model":
                    handler.reply_text(await shortcut_commands.handle_model_command(user_text, "zh"), incoming_message)
                elif _act == "personality":
                    handler.reply_text(await shortcut_commands.handle_personality_command(user_text, "zh"), incoming_message)
                elif _act == "retry":
                    handler.reply_text(shortcut_commands.retry_hint("zh"), incoming_message)
                elif _act == "mode":
                    handler.reply_text(await shortcut_commands.build_mode_info_text("zh"), incoming_message)
                return
        if self.config.quickRestart and user_text and ("/重启" in user_text or "/restart" in user_text):
            self.memoryList[cid] = []
            handler.reply_text("对话记录已重置。", incoming_message)
            return
        
        if self.config.wakeWord and self.config.wakeWord not in user_text and not has_image:
            return

        # --- C. 构造 OpenAI 消息格式 ---
        if cid not in self.memoryList: 
            self.memoryList[cid] = []
        
        current_content = []
        if user_text:
            current_content.append({"type": "text", "text": user_text})
        
        # 插入图片（OpenAI 格式要求图片在文本之前或混合插入，这里放在文本后也可以）
        if has_image:
            current_content.extend(user_content_items)
            if not user_text:
                current_content.insert(0, {"type": "text", "text": "请分析这张图片"})

        self.memoryList[cid].append({"role": "user", "content": current_content})

        # --- D. AI 调用与流式输出 ---
        ai_client = AsyncOpenAI(api_key="none", base_url=f"http://127.0.0.1:{self.port}/v1")
        state = {"text_buffer": "", "full_response": ""}

        try:
            stream = await ai_client.chat.completions.create(
                model=self.config.DingtalkAgent,
                messages=self.memoryList[cid],
                stream=True,
                extra_body={
                    "is_app_bot": True,
                    "platform": "dingtalk",
                },
            )

            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                
                # 处理推理内容 (如 DeepSeek R1)
                reasoning = ""
                if hasattr(delta, "reasoning_content") and delta.reasoning_content:
                    if self.config.reasoningVisible:
                        reasoning = delta.reasoning_content
                
                content = delta.content or ""
                combined_chunk = reasoning + content
                
                if not combined_chunk:
                    continue

                state["text_buffer"] += combined_chunk
                state["full_response"] += content

                # 检查分段符，流式回复钉钉
                if any(sep in state["text_buffer"] for sep in self.separators):
                    if state["text_buffer"].strip():
                        handler.reply_markdown("AI 助手", state["text_buffer"], incoming_message)
                    state["text_buffer"] = ""

            # 扫尾
            if state["text_buffer"].strip():
                handler.reply_markdown("AI 助手", state["text_buffer"], incoming_message)

            # --- E. 记忆持久化与裁剪 ---
            self.memoryList[cid].append({"role": "assistant", "content": state["full_response"]})
            if self.config.memoryLimit > 0:
                # 保持 memoryLimit 组对话 (1 user + 1 assistant = 2条)
                while len(self.memoryList[cid]) > self.config.memoryLimit * 2:
                    self.memoryList[cid].pop(0)

        except Exception as e:
            logging.getLogger("app").info(f"钉钉 AI 生成异常: {e}")
            handler.reply_text(f"抱歉，处理消息时出错: {str(e)}", incoming_message)

    async def _get_access_token(self) -> Optional[str]:
        """获取钉钉 OpenAPI 的访问令牌"""
        url = "https://api.dingtalk.com/v1.0/oauth2/accessToken"
        payload = {
            "appKey": self.config.appKey,
            "appSecret": self.config.appSecret
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("accessToken")
                    else:
                        logging.getLogger("app").info(f"钉钉获取Token失败: {await resp.text()}")
        except Exception as e:
            logging.getLogger("app").info(f"钉钉获取Token异常: {e}")
        return None
    
    @llm_gate.gated
    async def execute_behavior_event(self, chat_id: str, behavior_item: BehaviorItem):
        """
        【终极全能版】自动识别 ID 类型并推送
        - 如果是 cid 开头 -> 调群聊接口
        - 如果是其他 -> 调单聊 batchSend 接口
        """
        # 清理 ID (去掉可能存在的空格)
        target_id = str(chat_id).strip()
        if not target_id: return

        logging.info(f"[Dingtalk] 触发主动行为! 目标: {target_id}")

        # --- 1. 准备 AI 回复内容 (保持不变) ---
        def resolve_prompt(behavior):
            action = behavior.action
            if action.type == "prompt": return action.prompt
            elif action.type == "random":
                events = action.random.events
                if not events: return None
                return random.choice(events) if action.random.type == "random" else events[action.random.orderIndex % len(events)]

        prompt_content = resolve_prompt(behavior_item)
        if not prompt_content: return

        try:
            # --- 2. 调用 AI 生成文本 (保持不变) ---
            ai_client = AsyncOpenAI(api_key="none", base_url=f"http://127.0.0.1:{self.port}/v1")
            response = await ai_client.chat.completions.create(
                model=self.config.DingtalkAgent,
                messages=[{"role": "user", "content": "[system]: "+prompt_content}],
                stream=False
            )
            reply_content = response.choices[0].message.content
            if not reply_content: return

            # --- 3. 获取 Token ---
            token = await self._get_access_token()
            if not token: return
            
            headers = {
                "x-acs-dingtalk-access-token": token,
                "Content-Type": "application/json"
            }

            # --- 4. 核心：智能分流逻辑 ---
            if target_id.startswith("cid"):
                # ============ 分支 A: 群聊推送 ============
                logging.info(f"[Dingtalk] 识别为群聊 ID，调用 groupMessages/send")
                url = "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
                payload = {
                    "msgKey": "sampleMarkdown",
                    "msgParam": json.dumps({
                        "title": "AI 助手",
                        "text": reply_content
                    }),
                    "openConversationId": target_id, # 群 ID
                    "robotCode": self.config.appKey
                }
            else:
                # ============ 分支 B: 单聊推送 (BatchSend) ============
                logging.info(f"[Dingtalk] 识别为用户 ID，调用 oToMessages/batchSend")
                url = "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
                
                # 注意：batchSend 的 msgParam 必须是字符串格式的 JSON
                param_str = json.dumps({
                    "title": "AI 助手",
                    "text": reply_content
                })
                
                payload = {
                    "robotCode": self.config.appKey,
                    "userIds": [target_id],    # 用户 ID 列表
                    "msgKey": "sampleMarkdown",
                    "msgParam": param_str      # 这是一个字符串
                }

            # --- 5. 发送请求 ---
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    result = await resp.json()
                    
                    # 成功判断：
                    # 群聊返回 processQueryKey，单聊也返回 processQueryKey
                    if resp.status == 200 and result.get("processQueryKey"):
                        logging.info(f"[Dingtalk] 推送成功! 目标: {target_id}")
                        # 写入记忆
                        if target_id not in self.memoryList: self.memoryList[target_id] = []
                        self.memoryList[target_id].append({"role": "assistant", "content": reply_content})
                    else:
                        logging.error(f"[Dingtalk] 推送失败: {result}")
                        
        except Exception as e:
            logging.error(f"[Dingtalk] 执行异常: {e}")       