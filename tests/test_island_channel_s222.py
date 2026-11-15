# -*- coding: utf-8 -*-
"""S222: island HUD 主动发言频道接线钉。

覆盖：handler 三态（生成成功 emit / 空回复吞 / 失败回退事实文本）、fact_text 优先序、
screen_fact 字段与 build_behavior_item 填充、target_platforms 交集含 island、
注册 source-pin 与 llm_gate 棘轮满足、behaviorList 边界（不触 platform_targets）、
面板 island 选项与 vision 轻提示三处绑定、双语键。
"""
import asyncio
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import notification_center  # noqa: E402
from py import screen_speak  # noqa: E402
from py.behavior_engine import BehaviorItem  # noqa: E402
from py.island_channel import fact_text, island_behavior_handler  # noqa: E402
from py.screen_speak import build_behavior_item  # noqa: E402

_ROLE = (ROOT / "py" / "island_channel.py").read_text(encoding="utf-8-sig")
_SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8-sig")


def _item(fact="有人物出现在编辑器前", prompt="p"):
    from py.behavior_engine import BehaviorAction, BehaviorTrigger
    return BehaviorItem(enabled=True, trigger=BehaviorTrigger(type="screenEvent"),
                        action=BehaviorAction(type="prompt", prompt=prompt),
                        platforms=[], screen_fact=fact)


def _run_handler(monkeypatch, generate):
    from py import island_channel
    calls = []
    monkeypatch.setattr(island_channel, "_generate", generate)
    monkeypatch.setattr(notification_center, "emit",
                        lambda cat, msg, extra=None: calls.append((cat, msg, extra)))
    asyncio.run(island_channel.island_behavior_handler("", _item()))
    return calls


class TestHandlerSemantics:
    def test_generated_reply_emits_bot_category(self, monkeypatch):
        async def gen(item):
            return "嘿，看你又在改那个 bug 啦"
        calls = _run_handler(monkeypatch, gen)
        assert len(calls) == 1
        cat, msg, extra = calls[0]
        assert cat == "bot" and "看你" in msg
        assert extra.get("platform") == "island"
        assert extra.get("source") == "screen_speak"  # 旁观 item（带 screen_fact）

    def test_empty_reply_swallowed_no_fallback(self, monkeypatch):
        async def gen(item):
            return ""  # 模型判定不值得打扰
        calls = _run_handler(monkeypatch, gen)
        assert calls == []

    def test_generation_failure_falls_back_to_fact(self, monkeypatch):
        async def gen(item):
            raise RuntimeError("boom")
        calls = _run_handler(monkeypatch, gen)
        assert len(calls) == 1
        assert "【屏幕旁观】" in calls[0][1] and "编辑器" in calls[0][1]

    def test_none_item_noop(self, monkeypatch):
        from py import island_channel
        calls = []
        monkeypatch.setattr(notification_center, "emit",
                            lambda *a, **k: calls.append(a))
        asyncio.run(island_channel.island_behavior_handler("", None))
        assert calls == []

    def test_handler_signature_matches_contract(self):
        params = list(inspect.signature(island_behavior_handler).parameters)
        assert params == ["chat_id", "item"]


class TestFactTextAndFields:
    def test_fact_text_precedence(self):
        assert fact_text(_item(fact="X — Y")) == "【屏幕旁观】X — Y"
        plain = _item(fact="", prompt="日记内容abc")
        assert fact_text(plain).startswith("【主动消息】")  # 非旁观直投退化形

    def test_screen_fact_field_default_and_fill(self):
        from py.behavior_engine import BehaviorAction, BehaviorTrigger
        base = BehaviorItem(enabled=True, trigger=BehaviorTrigger(type="time"),
                            action=BehaviorAction(type="prompt", prompt="a"))
        assert base.screen_fact == ""  # 其余构造零影响
        ev = {"title": "调试", "summary": "s", "activity": "coding", "importance": 5}
        assert build_behavior_item(ev).screen_fact == "调试 — s"

    def test_speak_extra_source_behavior_for_non_observer(self, monkeypatch):
        from py import island_channel
        calls = []

        async def gen(item):
            return "你好"
        monkeypatch.setattr(island_channel, "_generate", gen)
        monkeypatch.setattr(notification_center, "emit",
                            lambda cat, msg, extra=None: calls.append(extra))
        asyncio.run(island_channel.island_behavior_handler(
            "", _item(fact="")))
        assert calls[0]["source"] == "behavior"


class TestRegistryAndRatchet:
    def test_registered_in_boot(self):
        assert "register_island_channel()" in _SERVER_SRC
        assert "from py.island_channel import register_island_channel" in _SERVER_SRC

    def test_llm_gate_ratchet_satisfied(self):
        # py/*.py 的 chat.completions 出口必须在 gated 链上（棘轮规则自证）
        assert "@llm_gate.gated" in _ROLE
        assert "chat.completions.create" in _ROLE

    def test_no_platform_targets_touch(self):
        # island 恒可用但从不登记 platform_targets → behaviorList 的 all 枚举空目标静默
        # （查使用形态而非裸词：模块 docstring 含该词属解释性文案）
        import re
        assert not re.search(r"platform_targets\s*(\.|\[)", _ROLE)

    def test_target_platforms_intersect_island(self):
        cfg = {"platforms": ["island"]}
        assert screen_speak.target_platforms(cfg, ["island", "xmpp"]) == ["island"]
        assert "island" in screen_speak.target_platforms({"platforms": ["all"]},
                                                         ["island", "xmpp"])


class TestFrontendPins:
    def _read(self, rel):
        return (ROOT / rel).read_text(encoding="utf-8-sig")

    def test_panel_island_option_and_vision_warn(self):
        role = self._read("static/templates/page_role.html")
        assert "'island','xmpp','telegram'" in role
        assert "screenWatchIslandNotice" in role
        assert "screenWatchSettings.enabled && !visionSettings.enabled" in role

    def test_quick_buttons_title_warn(self):
        for page in ("static/templates/page_chat_main.html",
                     "static/templates/page_home.html"):
            src = self._read(page)
            assert "(screenWatchSettings.enabled && !visionSettings.enabled) ? t('screenWatchVisionWarn')" in src, page

    def test_locale_keys(self):
        for loc in ("zh-CN", "en-US"):
            src = self._read("static/js/locales/%s.js" % loc)
            assert "'screenWatchVisionWarn':" in src, loc
            assert "'screenWatchIslandNotice':" in src, loc
