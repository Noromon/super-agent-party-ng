# -*- coding: utf-8 -*-
"""S73：自主事件工具策略——server 空名单语义修复 + BehaviorItem 策略 + 接线 pins。"""
import ast
import io
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_beh_tools_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py.behavior_engine import BehaviorAction, BehaviorItem, BehaviorTrigger  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


# --- 从 server.py 抽取自包含的 _stream_filter_tools（不导入重型 server 模块） ---
def _load_filter():
    tree = ast.parse(_read("server.py"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "_stream_filter_tools")
    ns = {"logging": logging}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "<extract>", "exec"), ns)
    return ns["_stream_filter_tools"]


_flt = _load_filter()
_TOOLS = [{"function": {"name": "shell_tool_local"}}, {"function": {"name": "time"}}]


def _req(**kw):
    d = {"is_sub_agent": False, "enable_tools": None, "disable_tools": None}
    d.update(kw)
    return types.SimpleNamespace(**d)


def test_none_semantics_unchanged():
    assert _flt(_req(), list(_TOOLS)) == _TOOLS


def test_empty_enable_means_zero_tools():
    # S73 核心：[] 是有效指令（旧语义被当“未指定”-> 全量工具，chatSummary 事故根因）
    assert _flt(_req(enable_tools=[]), list(_TOOLS)) == []


def test_whitelist_and_blacklist_still_work():
    assert [t["function"]["name"] for t in _flt(_req(enable_tools=["time"]), list(_TOOLS))] == ["time"]
    got = _flt(_req(disable_tools=["shell_tool_local"]), list(_TOOLS))
    assert [t["function"]["name"] for t in got] == ["time"]


def test_subagent_policy_and_empty_disable_noop():
    tools = _TOOLS + [{"function": {"name": "create_subtask"}}]
    got = _flt(_req(is_sub_agent=True), list(tools))
    assert "create_subtask" not in [t["function"]["name"] for t in got]
    assert _flt(_req(is_sub_agent=False, disable_tools=[]), list(_TOOLS)) == _TOOLS


# --- BehaviorItem.tools_override ---

def _item(**kw):
    base = dict(enabled=True,
                trigger=BehaviorTrigger(type="time"),
                action=BehaviorAction(type="prompt", prompt="p"),
                platforms=["chat"])
    base.update(kw)
    return BehaviorItem(**base)


def test_item_default_none_policy_zero_tools():
    assert _item().tools_override() == {"enable_tools": []}


def test_item_modes():
    assert _item(tools_mode="inherit").tools_override() == {}
    assert _item(tools_mode="whitelist", tools_list=["time"]).tools_override() \
        == {"enable_tools": ["time"]}
    assert _item(tools_mode="blacklist", tools_list=["shell_tool_local"]).tools_override() \
        == {"disable_tools": ["shell_tool_local"]}
    assert _item(tools_mode="").tools_override() == {"enable_tools": []}


def test_legacy_config_loads_with_none_default():
    legacy = {"enabled": True, "trigger": {"type": "time"},
              "action": {"type": "prompt", "prompt": "x"}}
    assert BehaviorItem(**legacy).tools_mode == "none"


# --- 接线 pins ---

PLATFORM_FILES = [
    "py/telegram_client.py", "py/discord_bot_manager.py", "py/feishu_bot_manager.py",
    "py/slack_bot_manager.py", "py/wechat_bot_manager.py", "py/wecom_bot_manager.py",
    "py/dingtalk_bot_manager.py", "py/xmpp_client.py",
]


@pytest.mark.parametrize("rel", PLATFORM_FILES)
def test_behavior_call_merges_event_policy(rel):
    assert "**behavior_item.tools_override()" in _read(rel)


def test_telegram_platform_label_fixed():
    src = _read("py/telegram_client.py")
    assert '"platform": "telegram",' in src
    assert '"platform": "slack",\n                }' not in src


def test_chat_summary_prompt_ban_and_empty_list():
    src = _read("py/diary_chat_integration.py")
    assert '"enable_tools": [],' in src
    assert "禁止调用任何工具" in src


def test_ui_and_i18n_wired():
    role = _read("static/templates/page_role.html")
    assert "behaviorToolsPolicy" in role and "tempBehavior.tools_mode" in role
    js = _read("static/js/methods/78_behavior.js")
    assert "tools_mode" in js and "tools_list" in js
    data = _read("static/js/data/40_tts_voice.js")
    assert 'tools_mode:"none"' in data
    for loc in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        s = _read(loc)
        for key in ("behaviorToolsPolicy", "behaviorToolsNone", "behaviorToolsInherit",
                    "behaviorToolsWhitelist", "behaviorToolsBlacklist",
                    "behaviorToolsList", "behaviorToolsListHint"):
            assert key in s, (loc, key)
