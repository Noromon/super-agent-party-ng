# -*- coding: utf-8 -*-
"""S78（N2 小修包）行为测 + 源码 pin：B1/B2-2/B8/B5/B4。"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s78_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py.get_setting import deep_update  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


# ---------------- B8-1 deep_update 行为测 ----------------

def test_deep_update_recursive_and_override():
    base = {"a": {"x": 1, "y": 2}, "b": [1, 2], "c": 3}
    deep_update(base, {"a": {"y": 9, "z": 4}, "b": [5]})
    assert base == {"a": {"x": 1, "y": 9, "z": 4}, "b": [5], "c": 3}


# ---------------- B1 / B2-2 server 源 pin + helper 行为测 ----------------

def _load_fns(names):
    import ast
    import logging
    tree = ast.parse(_read("server.py"))
    ns = {"logging": logging}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in names:
            exec(compile(ast.Module(body=[n], type_ignores=[]), "<extract>", "exec"), ns)
    return ns


def test_b1_delta_and_message_guards():
    src = _read("server.py")
    assert src.count("if choice.delta is None") == 2       # 两处流式
    assert "if response.choices[0].message and response.choices[0].message.tool_calls" in src
    assert "while response.choices[0].message and (response.choices[0].message.tool_calls or search_not_done):" in src
    assert "if choice.delta.tool_calls:" in src            # 守卫后的原逻辑仍在


def test_b2_2_drs_loop_caps_both_paths():
    src = _read("server.py")
    assert src.count("not _drs_round_cap(") == 2           # 流式+非流式共用单点
    assert src.count('_append_loopcap_hint(request, "') == 2
    # ws 保存重活已 helper 化（棘轮友好）且广播合并后全量
    assert "await _ws_save_settings(websocket, data)" in src
    assert "broadcast_settings_update(current, exclude=websocket)" in src
    # 纯 DRS 轮不再无出口；工具轮仍走收尾提示
    assert "if tool_calls and _tool_loop_count > _max_tool_iterations:" in src
    assert "if response.choices[0].message.tool_calls and _ns_loop_count > _ns_max_iterations:" in src


def test_b2_2_cap_helpers_behavior():
    ns = _load_fns({"_drs_round_cap", "_append_loopcap_hint"})
    cap = ns["_drs_round_cap"]
    assert cap(1, 10, True, [], "t") is True               # 未超轮数
    assert cap(11, 10, False, ["tc"], "t") is True         # 纯工具轮→交给收尾提示
    assert cap(11, 10, True, ["tc"], "t") is False         # 混合轮超限→结束
    assert cap(11, 10, False, [], "t") is False            # 纯 DRS 空转→结束

    class _R:
        messages = []
    r = _R()
    ns["_append_loopcap_hint"](r, "流式")
    assert r.messages[-1]["role"] == "user"
    assert "迭代上限" in r.messages[-1]["content"]


# ---------------- B8 server/routers 源 pin ----------------

def test_b8_ws_save_merged_and_storage_safe():
    src = _read("server.py")
    assert "deep_update(current, settings_dict)" in src
    assert "await save_settings(current)" in src
    gs = _read("py/get_setting.py")
    assert "asyncio.create_task(save_settings(user_settings))" not in gs
    sysr = _read("py/routers/system.py")
    assert 'item["unique_filename"]' not in sysr
    assert "def _names(items):" in sysr


# ---------------- B5 表单防原生提交 ----------------

def test_b5_rename_forms_prevent_native_submit():
    src = _read("static/templates/page_chat_main.html")
    assert src.count('<el-form label-position="top" @submit.native.prevent>') == 2


# ---------------- B4 渲染剥离事件属性 ----------------

def test_b4_message_render_strips_on_attrs():
    src = _read("static/js/methods/08_message_render.js")
    assert r"\s+on\w+\s*=" in src
    assert "safeAttrs = attrs.replace(" in src
    assert "return `<${slash}${tagName}${safeAttrs}>`;" in src


# ---------------- B2-2 前端提前建会话 ----------------

def test_b2_2_early_conversation_created():
    conv = _read("static/js/methods/15_conversations.js")
    assert "ensureConversationCreated(titleMessages)" in conv
    assert "MAX_CONVERSATIONS" not in conv                 # fork 决策：不带 50 条裁剪
    cs = _read("static/js/methods/10_chat_stream.js")
    assert "this.ensureConversationCreated(messagesPayload);" in cs
    assert "conversations.unshift" not in cs               # finally 内建会话块已收拢
    assert cs.count("this.ensureConversationCreated(messagesPayload);") == 2


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
