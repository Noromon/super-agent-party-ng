# -*- coding: utf-8 -*-
"""S142：IM 机器人「思考过程可见」热更新修复钉桩。

背景：流式发送读 client 属性 reasoningVisible（discord 读 client.config.reasoning_visible），
而各平台 apply_live_fields（保存设置→sync_all_bots_behavior→update_behavior_config 热更入口）
原先未同步该字段 → 开关热改永不生效。本测直调 apply_live_fields 断言字段落到运行中 client。
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _mgr(cls):
    return cls.__new__(cls)  # 绕开 __init__（不起线程），apply_live_fields 不依赖实例态


def _attrs(client):
    d = dict(vars(client))
    d.update(vars(client.config) if isinstance(getattr(client, "config", None), SimpleNamespace) else {})
    return d


class TestReasoningHotApplyS142:
    def test_xmpp(self):
        from py.xmpp_bot_manager import XmppBotConfig, XmppBotManager
        c = SimpleNamespace(reasoningVisible=False, config=None)
        _mgr(XmppBotManager).apply_live_fields(c, XmppBotConfig.model_construct(
            XmppAgent="m", wakeWord=None, reasoningVisible=True))
        assert c.reasoningVisible is True

    def test_telegram(self):
        from py.telegram_bot_manager import TelegramBotConfig, TelegramBotManager
        c = SimpleNamespace(reasoningVisible=False, config=None)
        _mgr(TelegramBotManager).apply_live_fields(c, TelegramBotConfig.model_construct(
            TelegramAgent="m", enableTTS=False, wakeWord=None, reasoningVisible=True))
        assert c.reasoningVisible is True

    def test_feishu(self):
        from py.feishu_bot_manager import FeishuBotConfig, FeishuBotManager
        c = SimpleNamespace(reasoningVisible=False, config=None)
        _mgr(FeishuBotManager).apply_live_fields(c, FeishuBotConfig.model_construct(
            FeishuAgent="m", enableTTS=False, wakeWord=None, reasoningVisible=True))
        assert c.reasoningVisible is True

    def test_wecom(self):
        from py.wecom_bot_manager import WeComBotConfig, WeComBotManager
        c = SimpleNamespace(reasoningVisible=False, config=None)
        _mgr(WeComBotManager).apply_live_fields(c, WeComBotConfig.model_construct(
            WeComAgent="m", wakeWord=None, reasoningVisible=True))
        assert c.reasoningVisible is True

    def test_qq(self):
        from py.qq_bot_manager import QQBotConfig, QQBotManager
        c = SimpleNamespace(reasoningVisible=False, config=None)
        _mgr(QQBotManager).apply_live_fields(c, QQBotConfig.model_construct(reasoningVisible=True))
        assert c.reasoningVisible is True

    def test_wechat(self):
        from py.wechat_bot_manager import WeChatBotConfig, WeChatBotManager
        c = SimpleNamespace(reasoningVisible=False, wakeWord="x", enableTTS=False, config=None)
        _mgr(WeChatBotManager).apply_live_fields(c, WeChatBotConfig.model_construct(
            reasoningVisible=True, wakeWord=None, enableTTS=True))
        assert c.reasoningVisible is True

    def test_discord_inplace_config(self):
        from py.discord_bot_manager import DiscordBotConfig, DiscordBotManager
        c = SimpleNamespace(config=SimpleNamespace(llm_model="old", enable_tts=False,
                                                   wakeWord="old", reasoning_visible=False))
        _mgr(DiscordBotManager).apply_live_fields(c, DiscordBotConfig.model_construct(
            llm_model="m", enable_tts=False, wakeWord=None, reasoning_visible=True))
        assert c.config.reasoning_visible is True

    def test_dingtalk_slack_read_config_object(self):
        # 这两家流式读整份 config 对象（基类 apply 换 client.config 即生效），钉住现状防回归改坏
        s = io_read("py", "dingtalk_bot_manager.py")
        assert "self.config.reasoningVisible" in s
        s = io_read("py", "slack_bot_manager.py")
        assert "self.config.reasoning_visible" in s


def io_read(*p):
    return open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), *p),
                encoding="utf-8").read()
