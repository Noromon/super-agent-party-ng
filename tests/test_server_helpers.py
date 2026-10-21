# -*- coding: utf-8 -*-
"""AST-extracted pins for server helpers (no heavy server import) and a
static sweep proving every IM channel config opted into auto_connect."""
import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _extract(names, rel="server.py"):
    wanted_assigns, wanted_funcs = set(), set()
    for n in names:
        if n.isupper():
            wanted_assigns.add(n)
        else:
            wanted_funcs.add(n)
    tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
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
        return _extract(["_bot_conv_meta"], rel="py/bot_container.py")["_bot_conv_meta"]

    def test_active_row(self, meta):
        assert meta("bot:xmpp:alice@example") == {
            "channel": "xmpp", "peer": "alice@example", "archived": False}

    def test_archive_row_keeps_peer_and_flags(self, meta):
        m = meta("bot:xmpp:alice@example::1730000000123")
        assert m == {"channel": "xmpp", "peer": "alice@example", "archived": True}


class TestAutostartPlan:
    @pytest.fixture
    def plan(self):
        ns = _extract(["BOT_AUTOSTART_TABLE", "_bot_autostart_plan"], rel="py/bot_container.py")
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

    def test_boot_loop_calls_start_bot(self):
        # regression pin: the to_thread mount must be manager.start_bot,
        # not the manager instance itself ('XmppBotManager' not callable)
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        boot = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "autostart_im_bots":
                boot = node
                break
        assert boot is not None, "autostart_im_bots missing from lifespan"
        src = ast.get_source_segment((ROOT / "server.py").read_text(encoding="utf-8"), boot)
        assert ".start_bot," in src.replace("\n", " ").replace("  ", " ") or \
            ").start_bot" in src, src
        assert "to_thread" in src

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


class TestStreamTtlSweep:
    """T-4: _active_streams TTL backstop (created_at finally has a reader)."""

    @pytest.fixture
    def ns(self):
        import logging
        import time as _time
        ns = _extract(["_stream_ttl_sweep", "_STREAM_TTL_DONE", "_STREAM_TTL_HARD"],
                      rel="py/stream_relay.py")
        ns["time"] = _time
        ns["logger"] = logging.getLogger("t")
        return ns

    @staticmethod
    def _entry(done, age, task=None, now=1000.0):
        return {"done": done, "created_at": now - age, "task": task,
                "buffer": [], "consumer_count": 1}

    def test_done_expired_reaped(self, ns):
        ns["_active_streams"] = {"a": self._entry(True, 1900)}
        assert ns["_stream_ttl_sweep"](now=1000.0) == ["a"]
        assert "a" not in ns["_active_streams"]

    def test_running_fresh_kept(self, ns):
        ns["_active_streams"] = {"b": self._entry(False, 60)}
        assert ns["_stream_ttl_sweep"](now=1000.0) == []

    def test_done_but_fresh_kept(self, ns):
        ns["_active_streams"] = {"c": self._entry(True, 60)}
        assert ns["_stream_ttl_sweep"](now=1000.0) == []

    def test_hard_ttl_reaps_running_and_cancels_task(self, ns):
        class T:
            cancelled = False
            def done(self):
                return False
            def cancel(self):
                self.cancelled = True
        t = T()
        ns["_active_streams"] = {"d": self._entry(False, 30 * 3600, task=t)}
        assert ns["_stream_ttl_sweep"](now=1000.0) == ["d"]
        assert t.cancelled

    def test_release_helper_defined_and_used(self):
        # R1 router migration: the resume call site moved to py/routers/tasks.py
        # 批 1: 中继核心迁 py/stream_relay.py
        src = (ROOT / "server.py").read_text(encoding="utf-8")
        src += (ROOT / "py" / "routers" / "tasks.py").read_text(encoding="utf-8")
        src += (ROOT / "py" / "stream_relay.py").read_text(encoding="utf-8")
        assert src.count("_release_consumer(stream_id)") >= 2


class TestApprovalSentinel:
    """T-9/X-9: structured approval sentinel replaces substring sniffing."""

    @pytest.fixture
    def ns(self):
        import json as _json
        ns = _extract(["_approval_payload", "_is_approval_result", "_APPROVAL_PREFIX"],
                      rel="py/tool_dispatch.py")
        ns.setdefault("json", _json)
        return ns

    def test_roundtrip(self, ns):
        s = ns["_approval_payload"]("rm_tool", {"p": 1}, "ask", "/cwd")
        assert s.startswith(ns["_APPROVAL_PREFIX"])
        obj = ns["_is_approval_result"](s)
        assert obj and obj["tool_name"] == "rm_tool"
        assert obj["type"] == "approval_required"

    def test_smuggled_literal_not_trigger(self, ns):
        assert ns["_is_approval_result"]('{"note": "see approval_required docs"}') is None
        assert ns["_is_approval_result"]('junk "approval_required" junk') is None

    def test_prefix_spoof_wrong_type(self, ns):
        assert ns["_is_approval_result"]('{"__sap_approval_v1__":1,"type":"other"}') is None

    def test_prefix_then_broken_json(self, ns):
        assert ns["_is_approval_result"]('{"__sap_approval_v1__":1,broken') is None

    def test_non_string(self, ns):
        assert ns["_is_approval_result"](None) is None
        assert ns["_is_approval_result"](["x"]) is None
