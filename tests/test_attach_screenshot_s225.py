# -*- coding: utf-8 -*-
"""S225 旁观发言附截图（窥屏主动发言生成输入附帧，非输出注入）。

契约：仅 attachScreenshot + unifiedModel 双开且有本帧时，把观察帧以原生 image_url
注入本次发言**生成调用**的消息（server 在 images_add_in_messages 的 deepcopy 上注入），
主模型一手"亲眼看"；截图绝不进输出消息、记忆、turn-log、DB，绝不落盘；不改任何 IM bot。
"""
import ast
import copy
import inspect
import json
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SERVER_SRC = ((_ROOT / "server.py").read_text(encoding="utf-8") + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）


def _mk_item():
    from py.screen_speak import build_behavior_item
    return build_behavior_item(
        {"iso": "x", "title": "t", "summary": "s", "activity": "a", "importance": 5})


# ---------------------------------------------------------------- 行为载荷桥
class TestBehaviorPayloadBridge:
    def test_default_empty_and_absent_from_override(self):
        it = _mk_item()
        assert it.screen_image == ""
        out = it.tools_override()
        assert "screen_image" not in out          # 未附图零污染，旧契约不变
        assert out == {"enable_tools": []}

    def test_image_appended_preserving_tool_filter(self):
        it = _mk_item()
        it.screen_image = "AAA"
        assert it.tools_override() == {"enable_tools": [], "screen_image": "AAA"}

    def test_inherit_mode_with_image(self):
        it = _mk_item()
        it.tools_mode = "inherit"
        assert it.tools_override() == {}          # inherit 无图 → 空
        it.screen_image = "AAA"
        assert it.tools_override() == {"screen_image": "AAA"}

    def test_whitelist_blacklist_still_honored(self):
        it = _mk_item()
        it.tools_mode = "whitelist"
        it.tools_list = ["x"]
        it.screen_image = "AAA"
        assert it.tools_override() == {"enable_tools": ["x"], "screen_image": "AAA"}
        it.tools_mode = "blacklist"
        assert it.tools_override() == {"disable_tools": ["x"], "screen_image": "AAA"}

    def test_blank_image_not_propagated(self):
        it = _mk_item()
        it.screen_image = "   "
        assert "screen_image" not in it.tools_override()   # 空白视同无图


# ---------------------------------------------------------------- ChatRequest 字段
class TestChatRequestField:
    def test_screen_image_default_none(self):
        import server
        assert "screen_image" in server.ChatRequest.model_fields
        assert server.ChatRequest.model_fields["screen_image"].default is None


# ---------------------------------------------------------------- server 注入器
def _req(trigger=True, image=""):
    return types.SimpleNamespace(behavior_trigger=trigger, screen_image=image)


def _msgs(text="hi"):
    return [{"role": "system", "content": "sys"}, {"role": "user", "content": text}]


class TestInjectHelper:
    def test_not_behavior_round_untouched(self):
        import server
        m = _msgs()
        server._attach_screen_image_for_behavior(m, _req(False, "AAA"), {"unifiedModel": True})
        assert m[-1]["content"] == "hi"

    def test_no_image_untouched(self):
        import server
        m = _msgs()
        server._attach_screen_image_for_behavior(m, _req(True, ""), {"unifiedModel": True})
        assert m[-1]["content"] == "hi"

    def test_unified_off_untouched(self):
        import server
        m = _msgs()
        server._attach_screen_image_for_behavior(m, _req(True, "AAA"), {})  # unified off
        assert m[-1]["content"] == "hi"

    def test_all_conditions_injects_native_image(self):
        import server
        m = _msgs("看看这个")
        server._attach_screen_image_for_behavior(m, _req(True, "QUJD"), {"unifiedModel": True})
        c = m[-1]["content"]
        assert isinstance(c, list)
        assert c[0] == {"type": "text", "text": "看看这个"}
        assert c[1] == {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}

    def test_existing_list_content_appends(self):
        import server
        m = [{"role": "user", "content": [{"type": "text", "text": "x"}]}]
        server._attach_screen_image_for_behavior(m, _req(True, "QUJD"), {"unifiedModel": True})
        assert m[0]["content"][-1]["type"] == "image_url"

    def test_empty_messages_noop(self):
        import server
        m = []
        server._attach_screen_image_for_behavior(m, _req(True, "QUJD"), {"unifiedModel": True})
        assert m == []

    def test_does_not_mutate_request_messages(self):
        # 注入只动传入的 msg（deepcopy），request.messages 原件零改动 → 不落 mem0/turn-log/DB
        import server
        original = {"role": "user", "content": "keep"}
        m = copy.deepcopy([original])
        server._attach_screen_image_for_behavior(m, _req(True, "QUJD"), {"unifiedModel": True})
        assert original["content"] == "keep"


# ---------------------------------------------------------------- 接线 + M3
class TestWiring:
    def test_def_and_single_call_site(self):
        # S299 挪锚：定义随视觉域迁至 py/vision_tools.py；调用点仍必须只在 server 一处
        vt = (_ROOT / "py" / "vision_tools.py").read_text(encoding="utf-8")
        assert "def _attach_screen_image_for_behavior" in vt
        assert SERVER_SRC.count("_attach_screen_image_for_behavior(msg, request, settings)") == 1

    def test_generate_complete_impl_within_m3(self):
        tree = ast.parse(SERVER_SRC)
        for n in ast.walk(tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_generate_complete_impl":
                size = n.end_lineno - n.lineno + 1
                # S225 实测 289；S296 绕圈熔断 +1（watch 初始化）；S331 非流式锚点钩子 +2
                assert size <= 293   # <300 M3 红线
                return
        raise AssertionError("_generate_complete_impl not found")


# ---------------------------------------------------------------- watcher 门与传参
class TestWatcherGate:
    def test_maybe_speak_accepts_attach_b64(self):
        import py.screen_watcher as sw
        p = inspect.signature(sw.ScreenWatcher._maybe_speak).parameters
        assert "attach_b64" in p and p["attach_b64"].default is None

    def test_observe_once_double_gate_and_pass(self):
        import py.screen_watcher as sw
        src = inspect.getsource(sw.ScreenWatcher._observe_once)
        assert "attachScreenshot" in src
        assert 'settings.get("unifiedModel")' in src
        assert "_maybe_speak(ev, attach_b64)" in src

    def test_maybe_speak_assigns_only_when_present(self):
        import py.screen_watcher as sw
        src = inspect.getsource(sw.ScreenWatcher._maybe_speak)
        assert "if attach_b64:" in src
        assert "item.screen_image = attach_b64" in src

    def test_no_persistence_in_watcher(self):
        # 附帧只能来自内存局部（attach_b64），watcher 源码不得把帧写盘
        import py.screen_watcher as sw
        src = inspect.getsource(sw)
        assert "screen_image" in src
        # screen_image 仅出现在发言项赋值，绝不出现在任何 open(...)/jsonl 落盘语句
        for line in src.splitlines():
            if "screen_image" in line:
                assert "open(" not in line and ".jsonl" not in line


# ---------------------------------------------------------------- 设置链
class TestSettingsChain:
    def test_template_default(self):
        data = json.loads((_ROOT / "config" / "settings_template.json").read_text(encoding="utf-8-sig"))
        assert data["screenWatchSettings"]["speak"]["attachScreenshot"] is False

    def test_schema_default(self):
        src = (_ROOT / "static" / "js" / "settings_schema.js").read_text(encoding="utf-8")
        assert "attachScreenshot: false" in src

    def test_frontend_data_default(self):
        src = (_ROOT / "static" / "js" / "data" / "60_cards_options.js").read_text(encoding="utf-8")
        assert "attachScreenshot: false" in src

    def test_panel_switch_gated_by_unified(self):
        src = (_ROOT / "static" / "templates" / "page_role.html").read_text(encoding="utf-8")
        assert "screenWatchSettings.speak.attachScreenshot" in src
        assert ':disabled="!settings.unifiedModel"' in src

    def test_locales_present(self):
        for loc in ("zh-CN.js", "en-US.js"):
            src = (_ROOT / "static" / "js" / "locales" / loc).read_text(encoding="utf-8")
            assert "screenWatchAttach" in src and "screenWatchAttachHint" in src
