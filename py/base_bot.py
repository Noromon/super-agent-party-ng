# -*- coding: utf-8 -*-
"""BaseBotManager：IM 渠道 bot 管理器统一契约（批 2 / 审计 09-E-3/M-4）。

模板方法下沉（契约类，9 平台一致部分）：
  start_bot  双开/清理中拒绝 → 起线程 → 等 startup → 错误传播 → 等 ready
  _run_bot_thread  新事件循环 → 行为配置同步 → build_client → 起行为引擎 → run
  stop_bot   幂等停止 → on_stop_requested → join(STOP_JOIN_TIMEOUT) → 兜底 _cleanup
  _cleanup   取消任务/停循环/关循环/释 client（原 dingtalk/qq 缺失，继承即得=D3）
  update_behavior_config  热更（client 实时字段=平台钩子 + 全局行为引擎）

平台钩子（子类实现/覆写）：
  build_client(config)       构建并映射 client（含平台特有字段）
  post_client_init(config)   client 就绪回调等附加接线（默认 no-op）
  on_stop_requested()        停止时清平台会话态（默认 no-op）
  get_status()               平台状态形状 = 前端契约，故意不下沉

参数类（子类显式赋值，保持现值）：PLATFORM_LABEL / THREAD_NAME / SETTINGS_KEY /
TARGET_FIELD / ENGINE_TARGET_KEY / STARTUP_TIMEOUT / READY_TIMEOUT /
STOP_JOIN_TIMEOUT。

能力类不进基类：自动重连（仅 feishu）等留在子类，不向其余平台扩散
（批 2 裁决清单 B 区）。
"""
import asyncio
import inspect
import logging
import threading
import weakref


class BaseBotManager:
    PLATFORM_LABEL = "Bot"
    THREAD_NAME = "BotThread"
    SETTINGS_KEY = ""            # settings 里本平台配置键（行为目标兜底读取）
    TARGET_FIELD = ""            # config 上行为目标 ID 列表的字段名
    ENGINE_TARGET_KEY = ""       # 行为引擎 target_map 的平台键
    STARTUP_TIMEOUT = 30
    READY_TIMEOUT = 30
    STOP_JOIN_TIMEOUT = 5
    AUTO_START_ENGINE = True     # False=行为引擎生命周期由平台 run_client 自行编排
    SYNC_BEHAVIOR_ON_START = True  # False=启动时不做全局行为同步（qq 无行为接入）
    SYNC_CONFIG_WRITEBACK = True   # False=行为同步不回写 config（RA-07：wecom 旧语义）

    def pre_start_reset(self):
        """守卫通过、启动开始前的平台侧状态复位钩子（RA-06：须晚于「已在运行」守卫）。"""

    def __init__(self):
        self.bot_thread = None
        self.bot_client = None
        self.is_running = False
        self.config = None
        self.loop = None
        self._shutdown_event = threading.Event()
        self._startup_complete = threading.Event()
        self._ready_complete = threading.Event()
        self._startup_error = None
        self._stop_requested = False

    # ---------- 启动 ----------

    def start_bot(self, config):
        if self.bot_thread and self.bot_thread.is_alive():
            raise Exception(f"{self.PLATFORM_LABEL} 机器人线程正在清理中，请稍后再试")
        if self.is_running:
            raise Exception(f"{self.PLATFORM_LABEL} 机器人已在运行")

        self.pre_start_reset()
        self.config = config
        self._shutdown_event.clear()
        self._startup_complete.clear()
        self._ready_complete.clear()
        self._startup_error = None
        self._stop_requested = False

        self.bot_thread = threading.Thread(
            target=self._run_bot_thread, args=(config,), daemon=True,
            name=self.THREAD_NAME)
        self.bot_thread.start()

        if not self._startup_complete.wait(timeout=self.STARTUP_TIMEOUT):
            self.stop_bot()
            err = self._startup_error
            raise Exception(f"{self.PLATFORM_LABEL} 机器人连接超时" + (f": {err}" if err else ""))
        if self._startup_error:
            self.stop_bot()
            raise Exception(f"{self.PLATFORM_LABEL} 机器人启动失败: {self._startup_error}")
        if not self._ready_complete.wait(timeout=self.READY_TIMEOUT):
            self.stop_bot()
            err = self._startup_error
            raise Exception(f"{self.PLATFORM_LABEL} 机器人就绪超时" + (f": {err}" if err else ""))
        if not self.is_running:
            # RA-04/RA-03：就绪阶段异常在 _startup_error 迟写入（先写后 set 事件，无竞态窗口），
            # 此处二次读取并拼入消息，避免真实异常被泛化文案吞没
            self.stop_bot()
            err = self._startup_error
            raise Exception(
                f"{self.PLATFORM_LABEL} 机器人未能正常运行" + (f": {err}" if err else ""))

    def _run_bot_thread(self, config):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def main_startup():
            try:
                from py.get_setting import load_settings
                from py.behavior_engine import global_behavior_engine, BehaviorSettings

                # RA-02：读设置+行为同步=旧 per-platform 语义「失败吞错继续启动」；
                # 且仅接入行为的平台才读设置（qq 等 SYNC_BEHAVIOR_ON_START=False 不再无谓读盘）
                settings = {}
                if self.SYNC_BEHAVIOR_ON_START:
                    try:
                        settings = await load_settings()
                    except Exception as e:
                        logging.warning(f"{self.PLATFORM_LABEL} 启动读取设置失败（跳过行为同步继续启动）: {e}")

                await self.pre_client_setup()

                # 行为配置同步（各平台原逐份复制的同一段逻辑，字段名参数化）
                if self.SYNC_BEHAVIOR_ON_START:
                    try:
                        behavior_data = settings.get("behaviorSettings", {})
                        target_ids = getattr(config, self.TARGET_FIELD, None) if self.TARGET_FIELD else None
                        if not target_ids and self.SETTINGS_KEY:
                            target_ids = (settings.get(self.SETTINGS_KEY, {}) or {}).get(self.TARGET_FIELD, [])
                        if behavior_data:
                            global_behavior_engine.update_config(
                                behavior_data, {self.ENGINE_TARGET_KEY: target_ids})
                            # RA-07：config 回写受开关门控（wecom 旧语义=不回写）
                            if self.SYNC_CONFIG_WRITEBACK:
                                if isinstance(behavior_data, dict):
                                    config.behaviorSettings = BehaviorSettings(**behavior_data)
                                else:
                                    config.behaviorSettings = behavior_data
                                if self.TARGET_FIELD:
                                    setattr(config, self.TARGET_FIELD, target_ids)
                    except Exception as e:
                        logging.warning(f"{self.PLATFORM_LABEL} 启动行为配置同步失败（继续启动）: {e}")

                # client 构建（平台钩子，可 async：如需网络握手）+ 公共接线
                client = self.build_client(config)
                if inspect.isawaitable(client):
                    client = await client
                self.bot_client = client
                self.bot_client.config = config
                self.bot_client._manager_ref = weakref.ref(self)
                self.post_client_init(config)

                if self.AUTO_START_ENGINE and not global_behavior_engine.is_running:
                    asyncio.create_task(global_behavior_engine.start())
                    logging.info(f"行为引擎已在 {self.PLATFORM_LABEL} 线程启动")

                self._startup_complete.set()
                await self.run_client()
            except Exception as e:
                if not self._stop_requested:
                    logging.error(f"{self.PLATFORM_LABEL} 机器人启动/运行异常: {e}")
                    self._startup_error = str(e)
                # 确保主线程不被卡死
                if not self._startup_complete.is_set():
                    self._startup_complete.set()
                if not self._ready_complete.is_set():
                    self._ready_complete.set()

        try:
            self.loop.run_until_complete(main_startup())
        except Exception as e:
            if not self._stop_requested:
                if not self._startup_error:
                    self._startup_error = str(e)
                logging.error(f"{self.PLATFORM_LABEL} 线程 Loop 异常: {e}")
        finally:
            self._cleanup()

    def _on_bot_ready(self):
        """client 就绪回调（供 post_client_init 接线，或 client 经 _manager_ref 调用）"""
        self.is_running = True
        if not self._ready_complete.is_set():
            self._ready_complete.set()
        logging.info(f"{self.PLATFORM_LABEL} 机器人已完全就绪")

    # ---------- 停止与清理 ----------

    def stop_bot(self):
        if not self.is_running and not self.bot_thread:
            logging.info(f"{self.PLATFORM_LABEL} 机器人未在运行")
            return
        logging.info(f"正在停止 {self.PLATFORM_LABEL} 机器人...")
        self._stop_requested = True
        self.is_running = False
        self.on_stop_requested()
        if self.bot_client:
            self.bot_client._shutdown_requested = True
        self._shutdown_event.set()
        if self.bot_thread and self.bot_thread.is_alive():
            self.bot_thread.join(timeout=self.STOP_JOIN_TIMEOUT)
            if self.bot_thread.is_alive():
                logging.warning(f"{self.PLATFORM_LABEL} 机器人线程未能在 {self.STOP_JOIN_TIMEOUT} 秒内停止")
                self._cleanup()
        self._stop_requested = False

    def _cleanup(self):
        """D3：统一清理形状（原先 7/9 各自复制、dingtalk/qq 缺失）。"""
        self.is_running = False
        if self.loop and not self.loop.is_closed():
            try:
                for task in asyncio.all_tasks(self.loop):
                    task.cancel()
                if self.loop.is_running():
                    self.loop.stop()
                self.loop.close()
            except Exception as e:
                logging.warning(f"关闭 {self.PLATFORM_LABEL} 事件循环出错: {e}")
        self.bot_client = None
        self.loop = None
        self._shutdown_event.set()
        logging.info(f"{self.PLATFORM_LABEL} 机器人资源清理完成")

    # ---------- 行为热更 ----------

    def update_behavior_config(self, config):
        self.config = config
        if self.bot_client:
            self.apply_live_fields(self.bot_client, config)
        from py.behavior_engine import global_behavior_engine
        target_map = {self.ENGINE_TARGET_KEY:
                      getattr(config, self.TARGET_FIELD, []) if self.TARGET_FIELD else []}
        global_behavior_engine.update_config(config.behaviorSettings, target_map)
        logging.info(f"{self.PLATFORM_LABEL} 机器人: 行为配置已热更新")

    # ---------- 平台钩子 ----------

    def build_client(self, config):
        raise NotImplementedError

    async def pre_client_setup(self):
        """client 构建前的异步准备（如行为引擎 handler 注册），默认 no-op。"""

    async def run_client(self):
        """启动 client 主循环，默认 client.run()；平台可覆写（discord.start 等）。"""
        await self.bot_client.run()

    def post_client_init(self, config):
        """默认无附加接线；client 支持 _ready_callback 的平台自行覆写接线。"""

    def on_stop_requested(self):
        """停止时清理平台会话态（如证书一次性信任），默认 no-op。"""

    def apply_live_fields(self, client, config):
        """热更时把 config 实时字段映射到运行中的 client，默认仅同步整体 config。"""
        client.config = config

    # ---------- 状态（形状=前端契约，平台各自实现 get_status） ----------

    def _base_status(self):
        return {
            "is_running": self.is_running,
            "thread_alive": self.bot_thread.is_alive() if self.bot_thread else False,
            "startup_error": self._startup_error,
        }
