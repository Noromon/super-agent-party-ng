# -*- coding: utf-8 -*-
"""S213：TCG 泄漏终结必须过完成闸门 + 自纠预算衰减。

事故实证（backend.log.1 尾，2026-11-13 20:48 minimax-h3 长任务）：
①泄漏终结走 `if not _leaked:` 分支，完成闸门（todo 未清→打回续跑）被整体跳过，
回合静默终结——长任务无完成反馈就停了；
②tcg_retries 按回合累计：额度被 4 分钟前的两次泄漏烧光，其间几十次成功工具
调用不作数，新泄漏直接判"返工已达上限"。
修复：泄漏终结也过闸门（block 时合并 did-you-mean 自纠提示注入）；
成功结构化工具轮后预算衰减 1；闸门用尽且泄漏收尾时通知明示"回复继续可再推进"。
"""
import json
import os
from pathlib import Path

from test_contract_sse import collect, post_chat, sse

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

LEAK_TEXT = ("处理这个文件。\n"
             "<tool_call>\n<function=edit_file_tool_patch_tool_local>\n"
             '{"path": "notes.md"}\n</function>\n</tool_call>')

TODOS = [{"id": "1", "content": "probe task", "status": "in_progress", "priority": "high"}]


def _seed_todos(sap):
    project = Path(sap.data_dir).parent / "project"
    agent = project / ".agent"
    agent.mkdir(parents=True, exist_ok=True)
    f = agent / "ai_todos.json"
    f.write_text(json.dumps(TODOS, ensure_ascii=False), encoding="utf-8")
    return f


def _last_messages(mock_llm):
    return mock_llm.history[-1]["messages"]


def _count(msgs, needle):
    return sum(1 for m in msgs
               if isinstance(m, dict) and isinstance(m.get("content"), str)
               and needle in m["content"])


class TestGateOnLeakedEnd:
    def test_leak_exhaustion_bounces_on_gate_not_silent_stop(self, sap, mock_llm):
        # 泄漏×5：自纠 2 次 → 闸门 1/2、2/2 合并注记打回 → 用尽明示收尾。
        # 旧代码在第 3 个泄漏处就终结（闸门被 if not _leaked 跳过），
        # 最后一条请求里绝不会有任何"完成闸门"注记。
        f = _seed_todos(sap)
        try:
            mock_llm.script([{"kind": "text", "content": LEAK_TEXT}] * 5)
            r = post_chat(sap, {"messages": [{"role": "user", "content": "patch it"}]})
            assert r.status_code == 200
            frames = collect(sse(r))
            assert frames[-1].get("__done__"), "stream must still end with [DONE]"
            msgs = _last_messages(mock_llm)
            assert _count(msgs, "完成闸门 1/2") == 1
            assert _count(msgs, "完成闸门 2/2") == 1
            merged = [m for m in msgs
                      if isinstance(m.get("content"), str)
                      and "完成闸门 1/2" in m["content"]
                      and "PLAIN TEXT" in m["content"]
                      and "Closest declared name" in m["content"]]
            assert merged, "泄漏终结闸门打回必须注入 did-you-mean+闸门提醒的合并注记"
            joined = str(frames)
            assert "畸形工具调用（已拦截，未执行）" in joined
            assert "回复「继续」可再推进" in joined
        finally:
            f.unlink(missing_ok=True)

    def test_no_todos_leak_end_closes_normally(self, sap, mock_llm):
        # todo 文件不存在（无活动任务）：泄漏烧尽后合法按正文收尾，闸门不打回。
        mock_llm.script([{"kind": "text", "content": LEAK_TEXT}] * 3)
        r = post_chat(sap, {"messages": [{"role": "user", "content": "patch it"}]})
        assert r.status_code == 200
        collect(sse(r))
        msgs = _last_messages(mock_llm)
        assert _count(msgs, "PLAIN TEXT") == 2
        assert _count(msgs, "完成闸门") == 0


class TestTcgBudgetDecay:
    def test_legit_tool_rounds_decay_leak_budget(self, sap, mock_llm):
        # 泄漏→成功工具轮→泄漏→成功工具轮→泄漏：旧语义第三次烧尽即终结
        # （自纠注记只有 2 条）；S213 衰减后三条泄漏全部获得自纠。
        f = _seed_todos(sap)
        try:
            mock_llm.script([
                {"kind": "text", "content": LEAK_TEXT},
                {"kind": "tool", "name": "list_files_tool_local", "arguments": {"path": "."}},
                {"kind": "text", "content": LEAK_TEXT},
                {"kind": "tool", "name": "list_files_tool_local", "arguments": {"path": "."}},
                {"kind": "text", "content": LEAK_TEXT},
            ])
            r = post_chat(sap, {"messages": [{"role": "user", "content": "go"}]})
            assert r.status_code == 200
            collect(sse(r))
            msgs = _last_messages(mock_llm)
            assert _count(msgs, "PLAIN TEXT") == 3
        finally:
            f.unlink(missing_ok=True)


class TestS213Pins:
    def _src(self):
        with open(os.path.join(REPO, "server.py"), encoding="utf-8") as f:
            return f.read()

    def test_gate_no_longer_bypassed_by_leak(self):
        s = self._src()
        assert "if not _leaked:\n                _g_act" not in s
        assert ('_g_payload = build_correction_message(_leaked, _declared) + "\\n" + _g_payload'
                in s)

    def test_decay_wired(self):
        s = self._src()
        assert '_st["tcg_retries"] = _st["tcg_retries"] - 1' in s
        assert 'if tool_calls and _st.get("tcg_retries"):' in s

    def test_terminal_notice_has_resume_hint(self):
        assert "回复「继续」可再推进" in self._src()

    def test_notes_reach_retry_requests_not_stale_copy(self):
        # S163 安慰剂缺陷防再犯：second_round 的自纠/闸门 continue 重发必须
        # 重绑 msg——否则注记只落 request.messages，重试请求用旧 deepcopy 永远看不见
        s = self._src()
        i = s.find("async def _stream_second_round")
        j = s.find("async def _todo_stats_event_chunk")
        assert i > 0 and j > i
        assert s[i:j].count("msg = request.messages") == 2
