# -*- coding: utf-8 -*-
"""bot 域共享设施（批 1d 自 server.py 迁出）：惰性 manager 容器、
自动启动计划表、bot 渠道会话元数据、行为引擎配置全平台热同步。

消费方：server.py（lifespan 自动启动、/ws settings 更新热同步）、
py/routers/bots.py 与 bot_conversations.py（实例存取）。
BaseBotManager 统一契约手术（批 2）以本模块为落点。
"""
import logging
# (settings key, config module, config class, BotContainer getter name)
BOT_AUTOSTART_TABLE = (
    ("qqBotConfig", "py.qq_bot_manager", "QQBotConfig", "get_qq"),
    ("wechatBotConfig", "py.wechat_bot_manager", "WeChatBotConfig", "get_wechat"),
    ("feishuBotConfig", "py.feishu_bot_manager", "FeishuBotConfig", "get_feishu"),
    ("dingtalkBotConfig", "py.dingtalk_bot_manager", "DingtalkBotConfig", "get_dingtalk"),
    ("discordBotConfig", "py.discord_bot_manager", "DiscordBotConfig", "get_discord"),
    ("telegramBotConfig", "py.telegram_bot_manager", "TelegramBotConfig", "get_telegram"),
    ("xmppBotConfig", "py.xmpp_bot_manager", "XmppBotConfig", "get_xmpp"),
    ("slackBotConfig", "py.slack_bot_manager", "SlackBotConfig", "get_slack"),
    ("weComBotConfig", "py.wecom_bot_manager", "WeComBotConfig", "get_wecom"),
)


def _bot_autostart_plan(settings_dict):
    """Pure filter: channels whose saved config opts into auto_connect.
    The lifespan boot loop executes the plan."""
    return [(key, mod, cls) for key, mod, cls, _g in BOT_AUTOSTART_TABLE
            if isinstance((settings_dict or {}).get(key), dict)
            and (settings_dict or {}).get(key, {}).get("auto_connect")]


class BotContainer:
    """管理所有机器人的单例，只有在第一次调用 get 方法时才会 import 对应的重型 SDK"""
    _qq = None
    _feishu = None
    _dingtalk = None
    _discord = None
    _slack = None
    _telegram = None
    _wecom = None
    _wechat = None
    _xmpp = None


    @classmethod
    def get_qq(cls):
        if cls._qq is None:
            from py.qq_bot_manager import QQBotManager
            cls._qq = QQBotManager()
        return cls._qq

    @classmethod
    def get_feishu(cls):
        if cls._feishu is None:
            from py.feishu_bot_manager import FeishuBotManager
            cls._feishu = FeishuBotManager()
        return cls._feishu

    @classmethod
    def get_dingtalk(cls):
        if cls._dingtalk is None:
            from py.dingtalk_bot_manager import DingtalkBotManager
            cls._dingtalk = DingtalkBotManager()
        return cls._dingtalk

    @classmethod
    def get_discord(cls):
        if cls._discord is None:
            from py.discord_bot_manager import DiscordBotManager
            cls._discord = DiscordBotManager()
        return cls._discord

    @classmethod
    def get_slack(cls):
        if cls._slack is None:
            from py.slack_bot_manager import SlackBotManager
            cls._slack = SlackBotManager()
        return cls._slack

    @classmethod
    def get_telegram(cls):
        if cls._telegram is None:
            from py.telegram_bot_manager import TelegramBotManager
            cls._telegram = TelegramBotManager()
        return cls._telegram

    @classmethod
    def get_wecom(cls):
        if cls._wecom is None:
            from py.wecom_bot_manager import WeComBotManager
            cls._wecom = WeComBotManager()
        return cls._wecom

    @classmethod
    def get_wechat(cls):
        if cls._wechat is None:
            from py.wechat_bot_manager import WeChatBotManager
            cls._wechat = WeChatBotManager()
        return cls._wechat

    @classmethod
    def get_xmpp(cls):
        if cls._xmpp is None:
            from py.xmpp_bot_manager import XmppBotManager
            cls._xmpp = XmppBotManager()
        return cls._xmpp

# ==========================================
# 2.5 XMPP 机器人全量路由（第九通道）
# ==========================================


# ---------- bot 渠道会话元数据 ----------

def _bot_conv_meta(conv_id: str) -> dict:
    rest = str(conv_id)[len("bot:"):]
    channel, _, peer = rest.partition(":")
    archived = "::" in peer
    if archived:
        peer = peer.partition("::")[0]
    return {"channel": channel, "peer": peer or rest, "archived": archived}









async def sync_all_bots_behavior(settings_dict: dict):
    """
    统一同步所有平台机器人的行为引擎配置。
    注意：此处必须统一使用 BotContainer 获取实例，确保与路由中操作的是同一个对象。
    """
    # 提取全局行为设置
    behavior_data = settings_dict.get("behaviorSettings", {})
    
    # 1. --- 同步飞书 (Feishu) ---
    try:
        # 检查 BotContainer 内部存储的静态变量是否已初始化
        if BotContainer._feishu is not None:
            mgr = BotContainer.get_feishu()
            # 只有在机器人正在运行时才同步配置
            if mgr.is_running:
                from py.feishu_bot_manager import FeishuBotConfig
                config_data = settings_dict.get("feishuBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                # 构建新的配置模型并更新
                new_config = FeishuBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: 飞书机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (Feishu): {e}")

    # --- 同步微信 (WeChat) ---
    try:
        if BotContainer._wechat is not None:
            mgr = BotContainer.get_wechat()
            if mgr.is_running:
                from py.wechat_bot_manager import WeChatBotConfig
                config_data = settings_dict.get("wechatBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = WeChatBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: 微信机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (WeChat): {e}")

    # 2. --- 同步钉钉 (DingTalk) ---
    try:
        if BotContainer._dingtalk is not None:
            mgr = BotContainer.get_dingtalk()
            if mgr.is_running:
                from py.dingtalk_bot_manager import DingtalkBotConfig
                config_data = settings_dict.get("dingtalkBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = DingtalkBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: 钉钉机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (DingTalk): {e}")

    # 3. --- 同步 Discord ---
    try:
        if BotContainer._discord is not None:
            mgr = BotContainer.get_discord()
            if mgr.is_running:
                from py.discord_bot_manager import DiscordBotConfig
                config_data = settings_dict.get("discordBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = DiscordBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: Discord 机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (Discord): {e}")

    # 4. --- 同步 Telegram ---
    try:
        if BotContainer._telegram is not None:
            mgr = BotContainer.get_telegram()
            if mgr.is_running:
                from py.telegram_bot_manager import TelegramBotConfig
                config_data = settings_dict.get("telegramBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = TelegramBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: Telegram 机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (Telegram): {e}")

    # 4.5 --- 同步 XMPP ---
    try:
        if BotContainer._xmpp is not None:
            mgr = BotContainer.get_xmpp()
            if mgr.is_running:
                from py.xmpp_bot_manager import XmppBotConfig
                config_data = settings_dict.get("xmppBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = XmppBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: XMPP 机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (XMPP): {e}")

    # 5. --- 同步 Slack ---
    try:
        if BotContainer._slack is not None:
            mgr = BotContainer.get_slack()
            if mgr.is_running:
                from py.slack_bot_manager import SlackBotConfig
                config_data = settings_dict.get("slackBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = SlackBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: Slack 机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (Slack): {e}")

    # 6. --- 同步 QQ ---
    try:
        if BotContainer._qq is not None:
            mgr = BotContainer.get_qq()
            if mgr.is_running:
                from py.qq_bot_manager import QQBotConfig
                config_data = settings_dict.get("qqBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                new_config = QQBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: QQ 机器人行为配置已同步")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (QQ): {e}")

    # 7. --- 同步企业微信 (WeCom) ---
    try:
        # 核心检查：BotContainer._wecom 是 /start_wecom_bot 路由存放实例的地方
        if BotContainer._wecom is not None:
            mgr = BotContainer.get_wecom()
            if mgr.is_running:
                from py.wecom_bot_manager import WeComBotConfig
                config_data = settings_dict.get("weComBotConfig", {})
                config_data["behaviorSettings"] = behavior_data
                # 校验并同步更新
                new_config = WeComBotConfig(**config_data)
                mgr.update_behavior_config(new_config)
                logging.getLogger("app").info("WebSocket Sync: 企微机器人行为配置已同步 (BotContainer 实例同步成功)")
            else:
                logging.getLogger("app").info("WebSocket Sync: 企微机器人已初始化但尚未启动 (is_running 为 False)")
    except Exception as e:
        logging.getLogger("app").info(f"WebSocket Sync Error (WeCom): {e}")

