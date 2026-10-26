# -*- coding: utf-8 -*-
"""M5-XMPP bot manager（第九 bot 通道）。批 2 起为 BaseBotManager 的
XMPP adapter：生命周期模板在 py/base_bot.py，本文件只留平台差异。"""
from typing import List, Optional

from pydantic import BaseModel, Field

from py.base_bot import BaseBotManager
from py.behavior_engine import BehaviorSettings


class XmppBotConfig(BaseModel):
    auto_connect: bool = False  # SAP 启动时自动连接
    XmppAgent: str
    memoryLimit: int = 10
    separators: list[str] = Field(default_factory=lambda: ["。", "\n", "？", "！"])
    reasoningVisible: bool = False
    quickRestart: bool = True
    wakeWord: Optional[str] = None
    bot_username: str
    bot_password: str
    domain: str = "localhost"
    service_url: str = "tcp://localhost:5222"
    ignore_cert_hosts: List[str] = Field(default_factory=list)
    extra_outbound_dirs: List[str] = Field(default_factory=list)
    tools_mode: str = "inherit"          # inherit | whitelist | blacklist
    tools_list: List[str] = Field(default_factory=list)
    image_resize_mode: str = "downscale_only"   # off | fit | downscale_only
    image_max_side: int = 1024
    image_oversize_action: str = "reject"   # off | reject | shrink
    image_max_mb: int = 20
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetJids: List[str] = Field(default_factory=list)


class XmppBotManager(BaseBotManager):
    PLATFORM_LABEL = "XMPP"
    THREAD_NAME = "XmppBotThread"
    SETTINGS_KEY = "xmppBotConfig"
    TARGET_FIELD = "behaviorTargetJids"
    ENGINE_TARGET_KEY = "xmpp"
    STARTUP_TIMEOUT = 40
    STOP_JOIN_TIMEOUT = 15

    def build_client(self, config: XmppBotConfig):
        from py.xmpp_client import XmppClient

        client = XmppClient()
        client.XmppAgent = config.XmppAgent
        client.memoryLimit = config.memoryLimit
        client.separators = config.separators or ["。", "\n", "？", "！"]
        client.reasoningVisible = config.reasoningVisible
        client.quickRestart = config.quickRestart
        client.wakeWord = config.wakeWord
        client.bot_username = config.bot_username
        client.bot_password = config.bot_password
        client.domain = config.domain
        client.service_url = config.service_url
        client.ignore_cert_hosts = config.ignore_cert_hosts or []
        client.extra_outbound_dirs = config.extra_outbound_dirs or []
        client.tools_mode = config.tools_mode or "inherit"
        client.tools_list = config.tools_list or []
        client.image_resize_mode = (config.image_resize_mode
                                    if config.image_resize_mode in ("off", "fit", "downscale_only")
                                    else "downscale_only")
        client.image_max_side = max(256, min(4096, int(config.image_max_side or 1024)))
        client.image_oversize_action = (config.image_oversize_action
                                        if config.image_oversize_action in ("off", "reject", "shrink")
                                        else "reject")
        client.image_max_mb = max(1, min(1024, int(config.image_max_mb or 20)))
        client.behaviorTargetJids = list(config.behaviorTargetJids or [])
        return client

    def on_stop_requested(self):
        # "trust once" and queued cert reviews live only as long as this
        # bot run (SAP restart or stop+start => fresh TOFU review).
        from py import xmpp_trust
        xmpp_trust.ONCE.clear()
        xmpp_trust.PENDING.clear()

    def apply_live_fields(self, client, config: XmppBotConfig):
        client.XmppAgent = config.XmppAgent
        client.wakeWord = config.wakeWord
        client.reasoningVisible = config.reasoningVisible  # S142：流式读 client 属性，热更必须同步
        client.config = config

    def get_status(self):
        from py import xmpp_trust
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "session_ready": self.bot_client._is_ready if self.bot_client else False,
            "config": self.config.model_dump() if self.config else None,
            "startup_error": self._startup_error,
            "pending_certs": xmpp_trust.PENDING.list(),
        }
