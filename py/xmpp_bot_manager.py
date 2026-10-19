# -*- coding: utf-8 -*-
"""M5-XMPP bot manager（第九 bot 通道，接口与 TelegramBotManager 一致）。"""
import asyncio
import logging
import threading
from typing import List, Optional

from pydantic import BaseModel, Field

from py.behavior_engine import BehaviorSettings


class XmppBotConfig(BaseModel):
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
    behaviorSettings: Optional[BehaviorSettings] = None
    behaviorTargetJids: List[str] = Field(default_factory=list)


class XmppBotManager:
    def __init__(self):
        self.bot_thread: Optional[threading.Thread] = None
        self.bot_client = None
        self.is_running = False
        self.config: Optional[XmppBotConfig] = None
        self.loop = None
        self._startup_complete = threading.Event()
        self._ready_complete = threading.Event()
        self._startup_error: Optional[str] = None
        self._stop_requested = False

    def start_bot(self, config: XmppBotConfig):
        if self.bot_thread and self.bot_thread.is_alive():
            raise Exception("XMPP 机器人线程正在清理中，请稍后再试")
        if self.is_running:
            raise Exception("XMPP 机器人已在运行")

        self.config = config
        self._startup_complete.clear()
        self._ready_complete.clear()
        self._startup_error = None
        self._stop_requested = False

        self.bot_thread = threading.Thread(
            target=self._run_bot_thread, args=(config,), daemon=True, name="XmppBotThread")
        self.bot_thread.start()

        if not self._startup_complete.wait(timeout=40):
            self.stop_bot()
            raise Exception("XMPP 机器人连接超时")
        if self._startup_error:
            self.stop_bot()
            raise Exception(f"XMPP 机器人启动失败: {self._startup_error}")
        if not self._ready_complete.wait(timeout=30):
            self.stop_bot()
            raise Exception("XMPP 机器人就绪超时")
        if not self.is_running:
            self.stop_bot()
            raise Exception("XMPP 机器人未能正常运行")

    def _run_bot_thread(self, config: XmppBotConfig):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def main_startup():
            try:
                from py.get_setting import load_settings
                from py.behavior_engine import global_behavior_engine, BehaviorSettings
                from py.xmpp_client import XmppClient

                settings = await load_settings()
                behavior_data = settings.get("behaviorSettings", {})
                target_ids = config.behaviorTargetJids
                if not target_ids:
                    xmpp_conf = settings.get("xmppBotConfig", {})
                    target_ids = xmpp_conf.get("behaviorTargetJids", [])
                if behavior_data:
                    global_behavior_engine.update_config(behavior_data, {"xmpp": target_ids})
                    if isinstance(behavior_data, dict):
                        config.behaviorSettings = BehaviorSettings(**behavior_data)
                    else:
                        config.behaviorSettings = behavior_data
                    config.behaviorTargetJids = target_ids

                self.bot_client = XmppClient()
                self.bot_client.XmppAgent = config.XmppAgent
                self.bot_client.memoryLimit = config.memoryLimit
                self.bot_client.separators = config.separators or ["。", "\n", "？", "！"]
                self.bot_client.reasoningVisible = config.reasoningVisible
                self.bot_client.quickRestart = config.quickRestart
                self.bot_client.wakeWord = config.wakeWord
                self.bot_client.bot_username = config.bot_username
                self.bot_client.bot_password = config.bot_password
                self.bot_client.domain = config.domain
                self.bot_client.service_url = config.service_url
                self.bot_client.ignore_cert_hosts = config.ignore_cert_hosts or []
                self.bot_client.extra_outbound_dirs = config.extra_outbound_dirs or []
                self.bot_client.tools_mode = config.tools_mode or "inherit"
                self.bot_client.tools_list = config.tools_list or []
                self.bot_client.image_resize_mode = (config.image_resize_mode
                                                     if config.image_resize_mode in ("off", "fit", "downscale_only")
                                                     else "downscale_only")
                self.bot_client.image_max_side = max(256, min(4096, int(config.image_max_side or 1024)))
                self.bot_client.config = config
                self.bot_client._manager_ref = __import__("weakref").ref(self)

                if not global_behavior_engine.is_running:
                    asyncio.create_task(global_behavior_engine.start())
                    logging.info("行为引擎已在 XMPP 线程启动")

                self._startup_complete.set()
                await self.bot_client.run()
            except Exception as e:
                if not self._stop_requested:
                    logging.error(f"XMPP 机器人启动/运行异常: {e}")
                    self._startup_error = str(e)
                if not self._startup_complete.is_set():
                    self._startup_complete.set()
                if not self._ready_complete.is_set():
                    self._ready_complete.set()

        try:
            self.loop.run_until_complete(main_startup())
        except Exception as e:
            if not self._stop_requested:
                logging.error(f"XMPP 线程 Loop 异常: {e}")
        finally:
            self._cleanup()

    def _cleanup(self):
        self.is_running = False
        if self.loop and not self.loop.is_closed():
            try:
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
                if self.loop.is_running():
                    self.loop.stop()
                self.loop.close()
            except Exception as e:
                logging.warning(f"关闭 XMPP 事件循环出错: {e}")
        self.bot_client = None
        self.loop = None
        logging.info("XMPP 机器人资源清理完成")

    def stop_bot(self):
        if not self.is_running and not self.bot_thread:
            logging.info("XMPP 机器人未在运行")
            return
        logging.info("正在停止 XMPP 机器人...")
        self._stop_requested = True
        self.is_running = False
        # "trust once" and queued cert reviews live only as long as this
        # bot run (SAP restart or stop+start => fresh TOFU review).
        from py import xmpp_trust
        xmpp_trust.ONCE.clear()
        xmpp_trust.PENDING.clear()
        if self.bot_client:
            self.bot_client._shutdown_requested = True
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=15)
            if self.bot_thread.is_alive():
                logging.warning("XMPP 机器人线程未能在 15 秒内停止")
                self._cleanup()
        self._stop_requested = False

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

    def update_behavior_config(self, config: XmppBotConfig):
        self.config = config
        if self.bot_client:
            self.bot_client.XmppAgent = config.XmppAgent
            self.bot_client.wakeWord = config.wakeWord
            self.bot_client.config = config
        from py.behavior_engine import global_behavior_engine
        global_behavior_engine.update_config(config.behaviorSettings,
                                             {"xmpp": config.behaviorTargetJids})
        logging.info("XMPP 机器人: 行为配置已热更新")
