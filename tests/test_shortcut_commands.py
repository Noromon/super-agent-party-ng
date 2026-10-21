# -*- coding: utf-8 -*-
"""P4 A11 IM 快捷指令移植冒烟（S65）。"""
import asyncio
import importlib.util as ilu
import io
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_sc():
    spec = ilu.spec_from_file_location("shortcut_commands_x", str(_ROOT / "py/shortcut_commands.py"))
    mod = ilu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load_sc()


def test_parse_im_action_aliases():
    assert sc.parse_im_action("/stop") == "stop"
    assert sc.parse_im_action("/停止") == "stop"
    assert sc.parse_im_action("/MODEL gpt-4o") == "model"
    assert sc.parse_im_action("/重启 一下") == "reset"
    assert sc.parse_im_action("/yolo") == "mode"
    assert sc.parse_im_action("/角色") == "personality"
    assert sc.parse_im_action("/sub") is None
    assert sc.parse_im_action("plain text") is None
    assert sc.parse_im_action("") is None


def test_parse_subscribe_action():
    assert sc.parse_subscribe_action("/sub") == "sub"
    assert sc.parse_subscribe_action("/取消订阅") == "unsub"
    assert sc.parse_subscribe_action("/restart") is None


def test_is_shortcuts_enabled_default_true():
    assert sc.is_shortcuts_enabled({}) is True
    assert sc.is_shortcuts_enabled({"systemSettings": {"enableShortcuts": False}}) is False
    assert sc.is_shortcuts_enabled({"systemSettings": {"enableShortcuts": True}}) is True


def test_help_text_contains_commands():
    zh = sc.build_help_text("zh")
    assert "/stop" in zh and "/model" in zh
    en = sc.build_help_text("en")
    assert "/stop" in en


def test_subscribe_command_add_remove(monkeypatch):
    state = {"settings": {"dingtalkBotConfig": {"behaviorTargetChatIds": ["cidA"]}}}

    async def fake_load():
        return state["settings"]

    saved = {}

    async def fake_save(settings):
        saved["settings"] = settings

    monkeypatch.setattr(sc, "_load_settings_safe", fake_load)
    monkeypatch.setattr(sc, "_save_and_broadcast", fake_save)

    async def run():
        r = await sc.handle_subscribe_command("dingtalk", "cidB", True, "zh")
        assert r and "cidB" in state["settings"]["dingtalkBotConfig"]["behaviorTargetChatIds"]
        assert await sc.handle_subscribe_command("dingtalk", "cidA", False, "zh")
        assert "cidA" not in state["settings"]["dingtalkBotConfig"]["behaviorTargetChatIds"]
        assert saved.get("settings") is state["settings"]
        # QQ 无主动消息能力 → None
        assert await sc.handle_subscribe_command("qq", "x", True, "zh") is None
    asyncio.run(run())


def test_manager_hooks_wired():
    managers = [
        "py/dingtalk_bot_manager.py", "py/discord_bot_manager.py", "py/feishu_bot_manager.py",
        "py/qq_bot_manager.py", "py/slack_bot_manager.py", "py/telegram_client.py",
        "py/wechat_bot_manager.py", "py/wecom_bot_manager.py", "py/xmpp_client.py",
    ]
    total = 0
    for m in managers:
        s = io.open(_ROOT / m, encoding="utf-8-sig").read()
        n = s.count("shortcut_commands.parse_im_action")
        assert n >= 1, m
        total += n
    assert total == 10  # 9 平台 + qq 双入口（C2C + 群）

    s = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()
    assert "im_shortcuts_enabled" in s
    assert "enableShortcuts" in io.open(_ROOT / "config/settings_template.json", encoding="utf-8-sig").read()
    html = io.open(_ROOT / "static/templates/page_system.html", encoding="utf-8-sig").read()
    assert "systemSettings.enableShortcuts" in html
