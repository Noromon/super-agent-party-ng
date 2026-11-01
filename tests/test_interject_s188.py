# S188：插话（interject）功能钉桩——连续生成期间用户消息入队，轮边界注入
# request.messages 随下一轮推理处理；审批挂起→批复闭环释放；IM 入口拦截不起新流。
# 前端三态按钮（opencode 式）+ 待发区 + 流收尾三规则兜底。
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SERVER = (_ROOT / "server.py").read_text(encoding="utf-8")
TASKS = (_ROOT / "py" / "routers" / "tasks.py").read_text(encoding="utf-8")
STORE = (_ROOT / "py" / "approval_store.py").read_text(encoding="utf-8")
CHAT_JS = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")
RESUME_JS = (_ROOT / "static" / "js" / "methods" / "13_resume_stream.js").read_text(encoding="utf-8")
PAGE_MAIN = (_ROOT / "static" / "templates" / "page_chat_main.html").read_text(encoding="utf-8")
PAGE_HOME = (_ROOT / "static" / "templates" / "page_home.html").read_text(encoding="utf-8")
LOCALES_ZH = (_ROOT / "static" / "js" / "locales" / "zh-CN.js").read_text(encoding="utf-8")
LOCALES_EN = (_ROOT / "static" / "js" / "locales" / "en-US.js").read_text(encoding="utf-8")


@pytest.fixture()
def interject_mod():
    from py import interject
    interject._IM_TARGETS.clear()
    interject._HELD.clear()
    yield interject
    interject._IM_TARGETS.clear()
    interject._HELD.clear()


def _entry(**kw):
    e = {"done": False, "cancelled": False, "_interjections": []}
    e.update(kw)
    return e


class TestWebInterject:
    def test_enqueue_alive_stream(self, interject_mod):
        import asyncio

        async def run():
            streams = {"s1": _entry()}
            assert await interject_mod.web_interject(streams, "s1", " 插一句 ") is True
            assert streams["s1"]["_interjections"] == ["插一句"]
        asyncio.run(run())

    def test_dead_stream_returns_false(self, interject_mod):
        import asyncio

        async def run():
            streams = {"s1": _entry(done=True), "s2": _entry(cancelled=True)}
            assert await interject_mod.web_interject(streams, "s1", "x") is False
            assert await interject_mod.web_interject(streams, "s2", "x") is False
            assert await interject_mod.web_interject(streams, "nope", "x") is False
            assert await interject_mod.web_interject(streams, "s1", "   ") is False
        asyncio.run(run())


class TestImIntercept:
    def test_active_stream_enqueue(self, interject_mod, monkeypatch):
        from py import approval_store, stream_relay
        monkeypatch.setattr(approval_store, "has_pending", lambda p, peer: False)
        streams = {"sid-im": _entry()}
        monkeypatch.setattr(stream_relay, "_active_streams", streams, raising=False)
        interject_mod._IM_TARGETS[("xmpp", "peer1")] = "sid-im"
        req = SimpleNamespace(platform="xmpp", peer_id="peer1", model="m",
                              messages=[{"role": "user", "content": "等一下再做"}])
        rep = interject_mod.im_intercept(req)
        assert rep is not None and "已排队" in rep["choices"][0]["message"]["content"]
        assert streams["sid-im"]["_interjections"] == ["等一下再做"]

    def test_approval_pending_holds(self, interject_mod, monkeypatch):
        from py import approval_store
        monkeypatch.setattr(approval_store, "has_pending", lambda p, peer: True)
        req = SimpleNamespace(platform="xmpp", peer_id="peer2", model="m",
                              messages=[{"role": "user", "content": "插嘴A"}])
        rep = interject_mod.im_intercept(req)
        assert rep is not None and "审批闭环" in rep["choices"][0]["message"]["content"]
        assert interject_mod._HELD[("xmpp", "peer2")] == ["插嘴A"]
        assert interject_mod.take_held(("xmpp", "peer2")) == ["插嘴A"]
        assert interject_mod.take_held(("xmpp", "peer2")) == []

    def test_no_stream_no_pending_passes_through(self, interject_mod, monkeypatch):
        from py import approval_store, stream_relay
        monkeypatch.setattr(approval_store, "has_pending", lambda p, peer: False)
        monkeypatch.setattr(stream_relay, "_active_streams", {}, raising=False)
        req = SimpleNamespace(platform="xmpp", peer_id="peer3", model="m",
                              messages=[{"role": "user", "content": "正常消息"}])
        assert interject_mod.im_intercept(req) is None


class TestDrainInject:
    def test_round_boundary_injection_and_ack(self, interject_mod):
        req = SimpleNamespace(messages=[])
        st = {"_entry": _entry(_interjections=["A", "B"])}
        frames = interject_mod.drain_inject(st, req)
        assert len(frames) == 2 and all("interject" in f for f in frames)
        assert req.messages == [{"role": "user", "content": "A"}, {"role": "user", "content": "B"}]
        assert st["_entry"]["_interjections"] == []
        assert interject_mod.drain_inject(st, req) == []


class TestBackendWiring:
    def test_register_at_stream_creation(self):
        assert "_interject.register_stream(request, stream_id, _active_streams[stream_id])" in SERVER

    def test_drain_at_round_boundary(self):
        i_abort = SERVER.index('if _st.pop("w1_abort", False):')
        i_drain = SERVER.index("_interject.drain_inject(_st, request)")
        i_results = SERVER.index("results = _st.get(\"results\")", i_abort)
        assert i_abort < i_drain < i_results

    def test_im_intercept_before_s172_guard(self):
        i_ij = SERVER.index("_interject.im_intercept(request)")
        i_guard = SERVER.index("_ap_tail = pending_approval_at_tail(request.messages)")
        assert i_ij < i_guard

    def test_web_endpoint_defined(self):
        assert '"/v1/streams/{stream_id}/interject"' in TASKS
        assert "interject.web_interject(_active_streams, stream_id, req.content)" in TASKS

    def test_release_at_approval_closeout(self):
        assert "interject.take_held((record[\"platform\"], record[\"peer_id\"]))" in STORE
        i_held = STORE.index("interject.take_held")
        i_resolver = STORE.index("resolver = _RESOLVER.get(record[\"platform\"])")
        assert i_held < i_resolver  # 释放必须在重放续跑之前并入快照


class TestFrontendSemantics:
    def test_three_state_button_both_pages(self):
        for page in (PAGE_MAIN, PAGE_HOME):
            assert "isSending ? (userInput.trim() ? interjectSend() : stopGenerate()) : sendMessage()" in page
            assert "fa-comment-dots" in page
            assert "interjectQueue.length" in page

    def test_send_message_interject_branch_first(self):
        i_branch = CHAT_JS.index("if (this.isSending && this.userInput.trim()) { this.interjectSend(); return; }")
        i_guard = CHAT_JS.index("if (this.isTyping) return;")
        assert i_branch < i_guard

    def test_methods_defined(self):
        for m in ("async interjectSend()", "_ackInterject(content)", "_ijFinished()",
                  "_flushInterjectsSoon()", "async _flushInterjects()"):
            assert m in CHAT_JS

    def test_ack_ingest_both_loops(self):
        assert CHAT_JS.count("delta.interject") >= 1
        assert RESUME_JS.count("delta.interject") >= 1

    def test_finished_hook_at_all_stream_ends(self):
        assert CHAT_JS.count("this._ijFinished();") >= 2
        assert RESUME_JS.count("this._ijFinished();") >= 1
        assert "this._ijUserStopped = true;" in RESUME_JS

    def test_data_and_locales(self):
        data = (_ROOT / "static" / "js" / "data" / "00_ui_core.js").read_text(encoding="utf-8")
        assert "interjectQueue: []" in data
        for key in ("interject", "interjectQueued", "interjectSendNow", "interjectClear"):
            assert f"'{key}'" in LOCALES_ZH and f"'{key}'" in LOCALES_EN
