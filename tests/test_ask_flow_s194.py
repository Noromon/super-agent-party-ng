# -*- coding: utf-8 -*-
"""S194 ask_user_question_tool 结构化提问闭环。

覆盖：问题规范化、逐题答案解析（显式/位置/单题/追问）、卡片渲染、哨兵
往返与原位替换、approval_store kind 隔离（审批/提问互不串、/y 不答问、
面板拒批提问卡）、ask 超时走未答复结算、web 入口答案拦截、通知仅 web、
sanitize 人话化、全模式工具声明、契约条款、IM/server source 钉。
"""
import asyncio
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _rec(qs, **kw):
    import time
    r = {"approval_id": "a1", "kind": "ask", "questions": qs,
         "created_at": time.time(), "expires_at": time.time() + 600}
    r.update(kw)
    return r


class TestNormalize:
    def test_valid_and_flatten(self):
        from py.ask_flow import normalize_questions
        qs, err = normalize_questions({"questions": [
            {"question": "选哪个", "options": ["A", "B", ""]}, {"question": "多大尺寸"}]})
        assert not err and len(qs) == 2 and qs[0]["options"] == ["A", "B"]
        qs2, err2 = normalize_questions({"question": "单问平铺", "options": ["x"]})
        assert not err2 and qs2[0]["question"] == "单问平铺"

    def test_rejects(self):
        from py.ask_flow import normalize_questions
        assert normalize_questions({})[1]
        assert normalize_questions({"questions": []})[1]
        assert normalize_questions({"questions": [{"question": f"q{i}"} for i in range(5)]})[1]
        assert normalize_questions({"questions": [{"question": "  "}]})[1]


class TestParse:
    def test_single_question_bare(self):
        from py.ask_flow import parse_answers
        r = _rec([{"question": "场景?", "options": ["便利店", "客厅"]}])
        ans, missing = parse_answers(r, "2")
        assert ans == {1: "客厅"} and not missing
        ans2, _ = parse_answers(r, "厨房也行吧")
        assert ans2 == {1: "厨房也行吧"}  # Other 语义

    def test_multi_explicit(self):
        from py.ask_flow import parse_answers
        r = _rec([{"question": "场景?", "options": ["A店", "B厅"]},
                  {"question": "尺度?", "options": ["收敛", "擦边"]},
                  {"question": "开放题", "options": []}])
        ans, missing = parse_answers(r, "1.2\n2：擦边\n3. 随便发挥")
        assert ans == {1: "B厅", 2: "擦边", 3: "随便发挥"} and not missing

    def test_multi_positional_by_lines(self):
        from py.ask_flow import parse_answers
        r = _rec([{"question": "a?", "options": ["x", "y"]}, {"question": "b?"}])
        ans, missing = parse_answers(r, "1\n自由文本")
        assert ans == {1: "x", 2: "自由文本"} and not missing

    def test_multi_partial_and_missing(self):
        from py.ask_flow import parse_answers
        r = _rec([{"question": "a?", "options": ["x"]}, {"question": "b?"}])
        ans, missing = parse_answers(r, "1. x")
        assert ans == {1: "x"} and missing == [2]
        ans2, missing2 = parse_answers(r, "只有一句而且多问对不上")
        assert ans2 == {} and missing2 == [1, 2]

    def test_empty(self):
        from py.ask_flow import parse_answers
        r = _rec([{"question": "a?", "options": []}])
        assert parse_answers(r, "")[1] == [1]


class TestCards:
    def test_notice_and_reask(self):
        from py.ask_flow import build_notice, build_reask_notice
        r = _rec([{"question": "场景?", "options": ["便利店", "客厅"]},
                  {"question": "开放题", "options": []}])
        card = build_notice(r)
        assert "Q1. 场景?" in card and "   2. 客厅" in card and "Q2. 开放题" in card
        assert "题号. 选项号" in card and "/stop" in card
        rk = build_reask_notice(r, [2])
        assert "Q2" in rk and "还没收到" in rk and "Q1." not in rk

    def test_result_and_timeout_text(self):
        from py.ask_flow import format_result_text, timeout_result_text
        r = _rec([{"question": "a?", "options": ["x"]}, {"question": "b?", "options": []}])
        t = format_result_text(r, {1: "x"})
        assert "1. a? → x" in t and "（未答复）" in t and "默认假设" in t
        assert timeout_result_text(r).count("（未答复）") == 2


class TestSentinel:
    def test_roundtrip_and_replace(self):
        from py import ask_flow
        s = ask_flow.make_sentinel("abc")
        assert ask_flow.is_ask_result(s) is not None
        assert ask_flow.is_ask_result('{"__sap_approval_v1__":1,') is None
        assert ask_flow.is_ask_result("plain text") is None
        msgs = [{"role": "tool", "tool_call_id": "t", "content": s}]
        assert ask_flow.replace_ask_sentinel(msgs, "ANSWERED")
        assert msgs[0]["content"] == "ANSWERED"
        assert not ask_flow.replace_ask_sentinel([], "x")

    def test_sanitize_humanizes_ask(self):
        from py import approval_im
        from py.ask_flow import make_sentinel
        msgs = [{"role": "tool", "tool_call_id": "t", "content": make_sentinel("x")}]
        assert approval_im.sanitize_incoming(msgs) == 1
        assert "提问卡" in msgs[0]["content"]


class TestStoreKind:
    def test_kind_isolation(self, tmp_path, monkeypatch):
        from py import approval_store as st

        async def _go():
            monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
            st.clear_all()
            await st.create(platform="xmpp", peer_id="j", tool_name="t", ttl=600)
            await st.create(platform="xmpp", peer_id="j", tool_name="ask_user_question_tool",
                            kind="ask", questions=[{"question": "q", "options": []}], ttl=600)
            assert st.has_pending("xmpp", "j")               # 审批视角
            assert st.latest_pending_ask("xmpp", "j")         # 提问视角
            assert st.has_pending("xmpp", "j", kind="ask")
            # /y 只审批，不答问
            rec, _ = await st.resolve("xmpp", "j", "approve")
            assert rec and rec.get("kind", "approval") == "approval"
            # 面板不能批复提问卡
            ask_rec = st.latest_pending_ask("xmpp", "j")
            bad, msg = await st.resolve_by_id(ask_rec["approval_id"])
            assert bad is None and "提问卡" in msg
            # /stop 全清（含提问卡）
            n = await st.cancel_all("xmpp", "j")
            assert n == 1 and st.latest_pending_ask("xmpp", "j") is None
            st.clear_all()
        asyncio.run(_go())

    def test_ask_timeout_uses_unanswered_text(self, tmp_path, monkeypatch):
        from py import approval_store as st
        seen = {}

        async def resolver(record, decision, note, result_text):
            seen["decision"] = decision
            seen["text"] = result_text

        async def _go():
            monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
            st.clear_all()
            st.register_handlers("xmpp2", resolver=resolver)
            await st.create(platform="xmpp2", peer_id="j", tool_name="ask_user_question_tool",
                            kind="ask", questions=[{"question": "q?", "options": ["x"]}], ttl=0.05)
            await asyncio.sleep(0.4)
            assert seen.get("decision") == "timeout"
            assert "（未答复）" in seen.get("text", "")
            st.clear_all()
            st._RESOLVER.pop("xmpp2", None)
        asyncio.run(_go())

    def test_ask_notification_web_only(self, tmp_path, monkeypatch):
        from py import approval_store as st
        from py import notification_center as nc
        emitted = []
        monkeypatch.setattr(nc, "emit", lambda *a, **k: emitted.append(k.get("extra") or a))

        async def _go():
            monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
            st.clear_all()
            await st.create(platform="xmpp", peer_id="j", tool_name="ask_user_question_tool",
                            kind="ask", questions=[{"question": "q"}], ttl=600)
            await st.create(platform="web", peer_id="c1", tool_name="ask_user_question_tool",
                            kind="ask", questions=[{"question": "q"}], ttl=600)
            st.clear_all()
        asyncio.run(_go())
        assert len(emitted) == 1  # 只有 web 来源入面板


class TestWebIncoming:
    def test_answer_intercept(self, tmp_path, monkeypatch):
        from py import approval_store as st, ask_flow

        async def _go():
            monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
            st.clear_all()
            await st.create(platform="web", peer_id="42", tool_name="ask_user_question_tool",
                            kind="ask", questions=[{"question": "a?", "options": ["x", "y"]}],
                            ttl=600)
            sent = ask_flow.make_sentinel("pending")
            req = types.SimpleNamespace(
                is_app_bot=False, conversation_id=42,
                messages=[{"role": "tool", "tool_call_id": "t1", "content": sent},
                          {"role": "user", "content": "2"}])
            assert await ask_flow.web_resolve_incoming(req)
            assert "a? → y" in req.messages[0]["content"]
            assert st.latest_pending_ask("web", "42") is None
            # 再来一条消息不再拦截
            assert not await ask_flow.web_resolve_incoming(req)
            st.clear_all()
        asyncio.run(_go())

    def test_web_partial_resolves_all(self, tmp_path, monkeypatch):
        from py import approval_store as st, ask_flow

        async def _go():
            monkeypatch.setattr(st, "_snapshot_dir_override", str(tmp_path))
            st.clear_all()
            await st.create(platform="web", peer_id="43", tool_name="ask_user_question_tool",
                            kind="ask",
                            questions=[{"question": "a?", "options": []},
                                       {"question": "b?", "options": []}], ttl=600)
            req = types.SimpleNamespace(
                is_app_bot=False, conversation_id=43,
                messages=[{"role": "tool", "tool_call_id": "t",
                           "content": ask_flow.make_sentinel("p")},
                          {"role": "user", "content": "对不上号的一句话"}])
            assert await ask_flow.web_resolve_incoming(req)  # 不追问，直接结算
            assert "（未答复）" in req.messages[0]["content"]
            assert st.latest_pending_ask("web", "43") is None
            st.clear_all()
        asyncio.run(_go())


class TestMisc:
    def test_fallback_direct_call(self):
        from py.cli_tool import ask_user_question_tool

        async def _go():
            out = await ask_user_question_tool(questions=[{"question": "q"}])
            assert "main chat stream" in out
        asyncio.run(_go())

    def test_tool_declared_all_modes(self):
        from py.cli_tool import get_local_tools_for_mode, get_local_tools_for_permission

        def _has(tl):
            return any(t.get("function", {}).get("name") == "ask_user_question_tool" for t in tl)
        for m in ("default", "plan", "auto-approve", "yolo"):
            assert _has(get_local_tools_for_mode(m)), m
        for p in ("plan", "auto-approve", "default", "yolo"):
            assert _has(get_local_tools_for_permission(p)), p

    def test_contract_has_ask_clause(self):
        from py.agent_prompt import build_agent_core_prompt
        core = build_agent_core_prompt(engine="local", permission_mode="default",
                                       is_cowork_main=False)
        assert "ask_user_question_tool" in core and "plain-text question" in core


class TestSourcePins:
    def test_server_wiring(self):
        s = (_ROOT / "server.py").read_text(encoding="utf-8")
        assert '_ask_tool_handle(request, args_dict, tool_calls, tool_call_id, _ask_state)' in s
        assert 'ask_flow_is_ask_result(results)' in s
        assert "_stream_ask_hang(request, _st, _ask_state)" in s
        assert '_ask_state.get("ask_qs") is None' in s
        assert '_st.get("ask_hit")' in s
        assert "web_resolve_incoming(request)" in s

    def test_xmpp_wiring(self):
        s = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")
        assert 'record.get("kind") == "ask"' in s
        assert "latest_pending_ask(\"xmpp\", frm)" in s
        assert "build_reask_notice" in s
