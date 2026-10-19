# -*- coding: utf-8 -*-
"""AST-extracted pins for server helpers (no heavy server import) and a
static sweep proving every IM channel config opted into auto_connect."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _extract(names):
    wanted_assigns, wanted_funcs = set(), set()
    for n in names:
        if n.isupper():
            wanted_assigns.add(n)
        else:
            wanted_funcs.add(n)
    tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
    ns = {}
    picked = 0
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            exec(compile(ast.Module(body=[node], type_ignores=[]), "server", "exec"), ns)
            picked += 1
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in wanted_assigns:
                    exec(compile(ast.Module(body=[node], type_ignores=[]), "server", "exec"), ns)
                    picked += 1
    assert picked == len(names), names
    return ns


class TestBotConvMeta:
    @pytest.fixture
    def meta(self):
        return _extract(["_bot_conv_meta"])["_bot_conv_meta"]

    def test_active_row(self, meta):
        assert meta("bot:xmpp:alice@example") == {
            "channel": "xmpp", "peer": "alice@example", "archived": False}

    def test_archive_row_keeps_peer_and_flags(self, meta):
        m = meta("bot:xmpp:alice@example::1730000000123")
        assert m == {"channel": "xmpp", "peer": "alice@example", "archived": True}


class TestAutostartPlan:
    @pytest.fixture
    def plan(self):
        ns = _extract(["BOT_AUTOSTART_TABLE", "_bot_autostart_plan"])
        return ns["_bot_autostart_plan"], ns["BOT_AUTOSTART_TABLE"]

    def test_filter_and_table_shape(self, plan):
        plan_fn, table = plan
        assert len(table) == 9
        assert {row[0] for row in table} == {
            "qqBotConfig", "wechatBotConfig", "feishuBotConfig", "dingtalkBotConfig",
            "discordBotConfig", "telegramBotConfig", "xmppBotConfig",
            "slackBotConfig", "weComBotConfig"}
        got = plan_fn({
            "telegramBotConfig": {"auto_connect": True, "bot_token": "x"},
            "qqBotConfig": {"auto_connect": False},
            "xmppBotConfig": {},
            "slackBotConfig": None,
        })
        assert got == [("telegramBotConfig", "py.telegram_bot_manager", "TelegramBotConfig")]
        assert plan_fn(None) == []

    def test_all_managers_have_auto_connect_field(self):
        files = {
            "py/qq_bot_manager.py": "QQBotConfig",
            "py/wechat_bot_manager.py": "WeChatBotConfig",
            "py/feishu_bot_manager.py": "FeishuBotConfig",
            "py/dingtalk_bot_manager.py": "DingtalkBotConfig",
            "py/discord_bot_manager.py": "DiscordBotConfig",
            "py/telegram_bot_manager.py": "TelegramBotConfig",
            "py/xmpp_bot_manager.py": "XmppBotConfig",
            "py/slack_bot_manager.py": "SlackBotConfig",
            "py/wecom_bot_manager.py": "WeComBotConfig",
        }
        for rel, cls_name in files.items():
            tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
            cls = next(n for n in tree.body
                       if isinstance(n, ast.ClassDef) and n.name == cls_name)
            fields = {s.target.id for s in cls.body
                      if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
            assert "auto_connect" in fields, rel
