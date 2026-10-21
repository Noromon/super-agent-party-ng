# -*- coding: utf-8 -*-
"""Telegram bot manager。批 2 起为 BaseBotManager 的 Telegram adapter：
生命周期模板在 py/base_bot.py，本文件只留平台差异。"""
import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from py.base_bot import BaseBotManager
from py.behavior_engine import BehaviorSettings
from py.telegram_client import TelegramClient


class TelegramBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    TelegramAgent: str        # LLM 模型名
    memoryLimit: int
    separators: list[str]
    reasoningVisible: bool
    quickRestart: bool
    enableTTS: bool
    bot_token: str            # Telegram 必填
    wakeWord: str              # 唤醒词
    # --- 新增：行为规则设置 ---
    behaviorSettings: Optional[BehaviorSettings] = None
    # Telegram 特定的推送目标 ID 列表 (Chat IDs)
    behaviorTargetChatIds: List[str] = Field(default_factory=list)


class TelegramBotManager(BaseBotManager):
    PLATFORM_LABEL = "Telegram"
    THREAD_NAME = "TelegramBotThread"
    SETTINGS_KEY = "telegramBotConfig"
    TARGET_FIELD = "behaviorTargetChatIds"
    ENGINE_TARGET_KEY = "telegram"
    STOP_JOIN_TIMEOUT = 15

    # 以下接口与基类模板一致，路由复用不变
    def build_client(self, config: TelegramBotConfig):
        client = TelegramClient()
        client.TelegramAgent = config.TelegramAgent
        client.memoryLimit = config.memoryLimit
        client.separators = config.separators or ["。", "\n", "？", "！"]
        client.reasoningVisible = config.reasoningVisible
        client.quickRestart = config.quickRestart
        client.enableTTS = config.enableTTS
        client.wakeWord = config.wakeWord
        client.bot_token = config.bot_token
        return client

    def post_client_init(self, config):
        self.bot_client._ready_callback = self._on_bot_ready

    def apply_live_fields(self, client, config: TelegramBotConfig):
        client.TelegramAgent = config.TelegramAgent
        client.enableTTS = config.enableTTS
        client.wakeWord = config.wakeWord
        client.config = config

    def get_status(self):
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "client_ready": self.bot_client._is_ready if self.bot_client else False,
            "config": self.config.model_dump() if self.config else None,
            "loop_running": self.loop and not self.loop.is_closed() if self.loop else False,
            "startup_error": self._startup_error,
            "connection_established": self._startup_complete.is_set(),
            "ready_completed": self._ready_complete.is_set(),
            "stop_requested": self._stop_requested,
        }
