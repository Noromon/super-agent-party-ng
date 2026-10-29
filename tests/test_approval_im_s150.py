# -*- coding: utf-8 -*-
"""S150：IM 审批闭环钉桩（挂起表/TTL/斜杠解析/approver 门禁/编排/人话化/接线）。"""
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SENTINEL = ('{"__sap_approval_v1__":1,"type":"approval_required","tool_name":"shell_tool_local",'
            '"tool_params":{"command":"git push"},"permission_mode":"default","cwd":""}')


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _snapshot():
    return [
        {"role": "system", "content": "注入类系统提示（快照预处理应剔除）"},
        {"role": "user", "content": "帮我推送代码"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "call_1", "type": "function",
             "function": {"name": "shell_tool_local", "arguments": "{\"command\":\"git push\"}"}}]},
        {"role": "tool", "tool_call_id": "call_1", "name": "shell_tool_local", "content": SENTINEL},
    ]


class TestStore:
    def test_create_resolve_atomic(self):
        from py import approval_store as st

        async def run():
            st.clear_all()
            rec = await st.create(platform="t1", peer_id="p1", tool_name="t",
                                  messages=_snapshot())
            assert st.has_pending("t1", "p1")
            assert st.latest_pending("t1", "p1")["approval_id"] == rec["approval_id"]
            got, err = await st.resolve("t1", "p1", "approve")
            assert got and got["approval_id"] == rec["approval_id"] and not err
            assert not st.has_pending("t1", "p1")
            got2, err2 = await st.resolve("t1", "p1", "approve")
            assert got2 is None and err2  # 二次批复（并发 /y /y）拿不到记录
            st.clear_all()
        asyncio.run(run())

    def test_ttl_timeout_fires(self):
        from py import approval_store as st
        seen = []

        async def run():
            st.clear_all()

            async def resolver(record, decision, note, result_text):
                seen.append((decision, result_text))

            st.register_handlers("t2", resolver=resolver)
            await st.create(platform="t2", peer_id="p2", tool_name="boom", ttl=0.05)
            for _ in range(150):
                if seen:
                    break
                await asyncio.sleep(0.02)
            assert seen and seen[0][0] == "timeout"
            assert "boom" in seen[0][1] and "未执行" in seen[0][1]
            assert not st.has_pending("t2", "p2")
            st.clear_all()
        asyncio.run(run())

    def test_cancel_all_fires_stop(self):
        from py import approval_store as st
        fired = []

        async def run():
            st.clear_all()

            async def resolver(record, decision, note, result_text):
                fired.append(decision)

            st.register_handlers("t3", resolver=resolver)
            await st.create(platform="t3", peer_id="p3", tool_name="a")
            await st.create(platform="t3", peer_id="p3", tool_name="b")
            n = await st.cancel_all("t3", "p3")
            assert n == 2 and fired == ["stop", "stop"]
            assert not st.has_pending("t3", "p3")
            st.clear_all()
        asyncio.run(run())


class TestParseAndHumanize:
    def test_parse_variants(self):
        from py.approval_im import parse_approval_command
        assert parse_approval_command("/y") == ("approve", "")
        assert parse_approval_command("/批准 可以小心点") == ("approve", "可以小心点")
        assert parse_approval_command("/N") == ("deny", "")
        assert parse_approval_command("/否决") == ("deny", "")
        assert parse_approval_command("/a 以后都允许") == ("always", "以后都允许")
        assert parse_approval_command("/一直允许") == ("always", "")
        assert parse_approval_command("/yolo") is None       # 模式指令不受影响
        assert parse_approval_command("/yes but wait") == ("approve", "but wait")
        assert parse_approval_command("hello") is None
        assert parse_approval_command("") is None

    def test_sanitize_incoming(self):
        from py.approval_im import sanitize_incoming
        msgs = [{"role": "user", "content": SENTINEL},  # 非 tool 不动
                {"role": "tool", "tool_call_id": "c1", "name": "x", "content": SENTINEL},
                {"role": "tool", "tool_call_id": "c2", "name": "x", "content": "正常结果"}]
        n = sanitize_incoming(msgs)
        assert n == 1
        assert "待审批" in msgs[1]["content"] and "shell_tool_local" in msgs[1]["content"]
        assert "__sap_approval_v1__" not in msgs[1]["content"]
        assert msgs[0]["content"] == SENTINEL and msgs[2]["content"] == "正常结果"

    def test_snapshot_helpers(self):
        from py.approval_im import replace_sentinel_content, strip_system_messages
        msgs = strip_system_messages(_snapshot())
        assert all(m["role"] != "system" for m in msgs)
        assert replace_sentinel_content(msgs, "RESULT")
        assert msgs[-1]["content"] == "RESULT"
        assert not replace_sentinel_content([{"role": "user", "content": "x"}], "R")


class TestGateAndOrchestration:
    def _patch_settings(self, monkeypatch, roster):
        import py.get_setting as gs

        async def fake():
            return {"imPeerSettings": {"injectEnabled": True, "roster": roster}}

        monkeypatch.setattr(gs, "load_settings", fake)

    def test_approver_gate(self, monkeypatch):
        from py.approval_im import approver_gate

        async def run():
            self._patch_settings(monkeypatch, {})
            assert await approver_gate("xmpp", "any@one") == (True, "")  # 未配置=不设门禁
            self._patch_settings(monkeypatch, {"xmpp": {"boss@x": {"approver": True}}})
            assert await approver_gate("xmpp", "boss@x") == (True, "")
            ok, reason = await approver_gate("xmpp", "stranger@x")
            assert not ok and "审批人" in reason
        asyncio.run(run())

    def test_resolve_and_resume_paths(self, monkeypatch):
        from py import approval_im, approval_store as st
        calls = []
        resolved = []

        async def executor(name, params, typ, sid):
            calls.append((name, typ))
            return {"result": f"RAN:{typ}:{params.get('command', '')}"}

        async def resolver(record, decision, note, result_text):
            resolved.append((decision, result_text))

        async def run():
            st.clear_all()
            approval_im.set_executor(executor)
            try:
                st.register_handlers("t9", resolver=resolver)
                self._patch_settings(monkeypatch, {})
                # 批准
                await st.create(platform="t9", peer_id="p9", tool_name="shell_tool_local",
                                tool_params={"command": "git push"}, messages=_snapshot())
                reply = await approval_im.resolve_and_resume("t9", "p9", "approve", "")
                assert "已按批准执行" in reply
                await asyncio.sleep(0.1)
                assert calls == [("shell_tool_local", "approve")]
                assert resolved and resolved[-1][0] == "approve"
                assert resolved[-1][1].startswith("RAN:approve:git push")
                # 拒绝（含批语）
                await st.create(platform="t9", peer_id="p9", tool_name="rm_tool", messages=_snapshot())
                reply = await approval_im.resolve_and_resume("t9", "p9", "deny", "太危险")
                assert "已拒绝" in reply
                await asyncio.sleep(0.1)
                assert "拒绝执行工具" in resolved[-1][1] and "太危险" in resolved[-1][1]
                # 无挂起
                reply = await approval_im.resolve_and_resume("t9", "p9", "approve", "")
                assert "没有待审批" in reply
                # 门禁拦截时审批仍挂起
                self._patch_settings(monkeypatch, {"t9b": {"boss@x": {"approver": True}}})
                st.register_handlers("t9b", resolver=resolver)
                await st.create(platform="t9b", peer_id="stranger@x", tool_name="t")
                reply = await approval_im.resolve_and_resume("t9b", "stranger@x", "approve", "")
                assert "审批人" in reply and st.has_pending("t9b", "stranger@x")
            finally:
                approval_im.set_executor(None)
                st.clear_all()
        asyncio.run(run())


class TestShortcutCatalog:
    def test_specs_and_help(self):
        from py.shortcut_commands import COMMAND_SPECS, build_help_text, parse_im_action
        ids = {s["id"] for s in COMMAND_SPECS}
        assert {"approval_approve", "approval_always", "approval_deny"} <= ids
        for zh, sy in (("zh", "/y"), ("zh", "/a"), ("zh", "/n")):
            assert sy in build_help_text(zh)
        assert parse_im_action("/y") is None  # 不被旧解析器吞掉

    def test_notice(self):
        from py import approval_store as st
        from py.approval_im import build_notice

        async def run():
            st.clear_all()
            rec = await st.create(platform="t8", peer_id="p8", tool_name="shell_tool_local",
                                  tool_params={"command": "rm -rf build"}, ttl=600)
            txt = build_notice(rec)
            assert "shell_tool_local" in txt and "rm -rf build" in txt
            assert "/y" in txt and "/n" in txt and "/a" in txt and "超时" in txt
            st.clear_all()
        asyncio.run(run())


class TestWiringS150:
    def test_server_chain(self):
        s = _read("server.py")
        seg = s[s.find("# S150：IM 渠道审批挂起"):][:800]
        assert seg and "approval_store.create(" in seg and "has_handlers" in seg
        assert "approval_im.sanitize_incoming(request.messages)" in s
        assert "async def execute_approved_tool(" in s
        ep = s[s.find('@app.post("/execute_tool_manually")'):][:900]
        # S151：端点先执行后发射决策事件，故改为 result 中转（委托关系不变）
        assert "await execute_approved_tool(" in ep and "return result" in ep
        assert "_approval_im.set_executor(execute_approved_tool)" in s

    def test_xmpp_chain(self):
        s = _read("py/xmpp_client.py")
        assert 'approval_store.register_handlers("xmpp"' in s
        assert "approval_im.parse_approval_command(text)" in s
        # S162：/stop 审批作废吸收进 stream_stop 编排（围栏语义不变）
        assert 'stream_stop.handle_im_stop("xmpp", frm)' in s
        assert "approval_im.cancel_pending(" in _read("py/stream_stop.py")
        assert "self._approval_queue.setdefault" in s
        assert "async def _resume_llm(" in s and "approval_im.replace_sentinel_content" in s
        assert s.count("_agent_stream_to_peer") >= 3  # 定义 + 两处共用
        assert 'if approval_store.has_pending("xmpp", chat_jid):' in s

    def test_no_duplicate_history_on_pending(self):
        # 挂起轮不闭合回合：assistant 文本仅在续流后落账
        s = _read("py/xmpp_client.py")
        guard = s[s.find("# S150：本轮被审批挂起掐断"):][:400]
        assert "has_pending" in guard and "return" in guard
