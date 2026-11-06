# -*- coding: utf-8 -*-
"""S193 闸门提问放行：等待用户拍板是合法收尾，不再打回制造自我循环。

覆盖：提问形态启发式（问号/征询短语/尾窗/否定）、_stream_gate_check 提问
pass 与非提问 block、注记文案新句、前缀格式兼容 s183 钉。
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


class TestQuestionHeuristic:
    def test_positive(self):
        import server
        assert server._gate_looks_like_question("选 A/B/C 或 D，也可以自己报地点。")
        assert server._gate_looks_like_question("场景选哪个？")
        assert server._gate_looks_like_question("Pick a scene?")
        assert server._gate_looks_like_question("告诉我你想去哪")
        assert server._gate_looks_like_question("要哪个我来画")

    def test_negative(self):
        import server
        assert not server._gate_looks_like_question("画好了，交付在 outputs/a.png。")
        assert not server._gate_looks_like_question("")
        assert not server._gate_looks_like_question(None)
        # 问号在 400 字符尾窗之外（很久以前的问句不算等待拍板）
        long_text = "还记得我早前问过你吗？" + "正文内容" * 200
        assert not server._gate_looks_like_question(long_text)


class TestGateCheck:
    def _patch_todos(self, monkeypatch, items):
        from py import cli_tool

        async def fake():
            return items
        monkeypatch.setattr(cli_tool, "read_todo_snapshot", fake)

    def test_question_passes_gate(self, monkeypatch):
        import server
        self._patch_todos(monkeypatch, [{"id": 36, "status": "pending"}])
        st = {"turn_used_todo": True}
        act, payload = asyncio.run(server._stream_gate_check(
            st, [{"type": "function"}], "场景选哪个？A 便利店 B 客厅"))
        assert act == "pass" and payload is None
        assert "gate_retries" not in st  # 提问放行不消耗闸门额度

    def test_statement_still_blocks(self, monkeypatch):
        import server
        self._patch_todos(monkeypatch, [{"id": 36, "status": "pending"}])
        st = {"turn_used_todo": True}
        act, payload = asyncio.run(server._stream_gate_check(
            st, [{"type": "function"}], "这一单做完了，产物已交付。"))
        assert act == "block" and "完成闸门 1/2" in payload
        assert st["gate_retries"] == 1

    def test_note_text_has_ask_clause(self):
        import server
        txt = server._gate_note_text([{"id": 5, "status": "pending"}], 1)
        assert txt.startswith("【完成闸门 1/2】") and "#5[pending]" in txt
        assert "提问式收尾闸门会放行" in txt
