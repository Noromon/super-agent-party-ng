# S307: 任务锚点（df2f8248 事故修复 F1+F2+F3+F5）。
# 事故（2026-11-23）：审批续跑 POST 头部残缺（[assistant 问候, user 任务原文] 消失），
# 服务端链条从未持有任务原文 → 模型被 user-role 注入与陈旧记忆召回带跑，思维链涣散。
# 本测钉桩：F1 锚点持久化 / F2 缺头回注 / F3 nudge 并入 tool 尾部+视觉注入元声明 / F5 前端溯源插桩。
import asyncio
import sys
import types
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

ROOT = Path(__file__).resolve().parent.parent

from py import task_anchor  # noqa: E402
from py.stream_prep import RESUME_NUDGE_TEXT, append_resume_nudge  # noqa: E402

STREAM_RESPONSE = (ROOT / "py" / "stream_response.py").read_text(encoding="utf-8")
STREAM_PREP = (ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8")
STREAM_ENGINE = (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
GET_SETTING = (ROOT / "py" / "get_setting.py").read_text(encoding="utf-8")
CHAT_JS = (ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(encoding="utf-8")


def _msgs(with_task=True, with_system=True):
    out = []
    if with_system:
        out.append({"role": "system", "content": "contract"})
    if with_task:
        out.append({"role": "assistant", "content": "今天有什么事我能帮上忙吗？"})
        out.append({"role": "user", "content": "帮我做一个 GUI 工具清洗差分图片"})
    out.append({"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function",
                                "function": {"name": "list_files_tool_local", "arguments": "{}"}}]})
    out.append({"role": "tool", "tool_call_id": "c1", "content": "ok"})
    return out


class TestGenuineUserDetection:
    def test_plain_user_is_genuine(self):
        assert task_anchor.is_genuine_user_msg({"role": "user", "content": "干活"})

    def test_injections_not_genuine(self):
        assert not task_anchor.is_genuine_user_msg(
            {"role": "user", "name": "system_note", "content": "【系统提示】继续"})
        assert not task_anchor.is_genuine_user_msg(
            {"role": "user", "name": "browser_vision", "content": "[First-hand image]"})
        assert not task_anchor.is_genuine_user_msg({"role": "user", "content": "   "})
        assert not task_anchor.is_genuine_user_msg({"role": "assistant", "content": "hi"})

    def test_last_genuine_skips_injections(self):
        msgs = [{"role": "user", "content": "任务原文"},
                {"role": "user", "name": "system_note", "content": "nudge"},
                {"role": "user", "name": "browser_vision", "content": "img"}]
        assert task_anchor.last_genuine_user_text(msgs) == "任务原文"
        assert task_anchor.last_genuine_user_text(msgs[1:]) is None


class TestInsertAnchor:
    def test_missing_head_repaired_after_system(self):
        msgs = _msgs(with_task=False)
        assert task_anchor.insert_anchor(msgs, "帮我做一个 GUI 工具清洗差分图片")
        assert msgs[1] == {"role": "user", "content": "帮我做一个 GUI 工具清洗差分图片"}
        assert msgs[0]["role"] == "system"

    def test_no_system_inserts_at_zero(self):
        msgs = _msgs(with_task=False, with_system=False)
        assert task_anchor.insert_anchor(msgs, "任务")
        assert msgs[0] == {"role": "user", "content": "任务"}

    def test_existing_genuine_user_noop(self):
        msgs = _msgs()
        before = list(msgs)
        assert not task_anchor.insert_anchor(msgs, "任务")
        assert msgs == before


class TestResumeRepairFlow:
    def _run(self, tmp_path, monkeypatch, scenario):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", str(tmp_path / "covs.db"))
            req = types.SimpleNamespace(conversation_id="conv-1", messages=_msgs())
            await task_anchor.anchor_stream_in(req)  # 首流：锚点持久化
            broken = types.SimpleNamespace(conversation_id="conv-1",
                                           messages=_msgs(with_task=False))
            await task_anchor.anchor_stream_in(broken)  # 续跑缺头：回注
            other = types.SimpleNamespace(conversation_id="conv-noanchor",
                                          messages=_msgs(with_task=False))
            await task_anchor.anchor_stream_in(other)  # 无锚点会话：不动
            return req, broken, other
        return asyncio.run(body())

    def test_anchor_persist_and_repair(self, tmp_path, monkeypatch):
        req, broken, other = self._run(tmp_path, monkeypatch, None)
        assert task_anchor.last_genuine_user_text(req.messages)  # 首流原样
        repaired = task_anchor.last_genuine_user_text(broken.messages)
        assert repaired == "帮我做一个 GUI 工具清洗差分图片"  # F2 回注
        assert task_anchor.last_genuine_user_text(other.messages) is None  # 无锚点不动

    def test_anchor_roundtrip_db(self, tmp_path, monkeypatch):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", str(tmp_path / "covs.db"))
            await task_anchor.remember_anchor("cX", "任务A")
            assert await task_anchor.fetch_anchor("cX") == "任务A"
            await task_anchor.remember_anchor("cX", "任务B")
            assert await task_anchor.fetch_anchor("cX") == "任务B"
            assert await task_anchor.fetch_anchor("missing") is None
        asyncio.run(body())

    def test_never_raises_on_bad_state(self, monkeypatch):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", "\x00 illegal path")
            req = types.SimpleNamespace(conversation_id="c", messages=_msgs())
            await task_anchor.anchor_stream_in(req)  # DB 失败必须被吞
            assert req.messages[2]["role"] == "user"
        asyncio.run(body())


class TestNudgeMergedIntoToolTail:
    def test_str_tool_tail_merged_no_new_message(self):
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": "结果正文"}]
        append_resume_nudge(msgs)
        assert len(msgs) == 1
        assert msgs[0]["content"].endswith(RESUME_NUDGE_TEXT)

    def test_dedup_on_repeat(self):
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": "x"}]
        append_resume_nudge(msgs)
        append_resume_nudge(msgs)
        assert msgs[0]["content"].count(RESUME_NUDGE_TEXT) == 1

    def test_non_str_tail_falls_back_to_legacy_note(self):
        msgs = [{"role": "tool", "tool_call_id": "c1", "content": [{"type": "text"}]}]
        append_resume_nudge(msgs)
        assert len(msgs) == 2 and msgs[1].get("name") == "system_note"

    def test_non_tool_tail_untouched(self):
        msgs = [{"role": "assistant", "content": "done"}]
        append_resume_nudge(msgs)
        assert len(msgs) == 1


class TestPinsAndWiring:
    def test_stream_response_hook_before_s172_gate(self):
        i_hook = STREAM_RESPONSE.index("await anchor_stream_in(request)")
        i_gate = STREAM_RESPONSE.index(
            "if pending_approval_at_tail(request.messages) is None: append_resume_nudge(request.messages)")
        assert i_hook < i_gate  # 锚点先回注，模型同轮即可见

    def test_anchor_table_created_in_covs_init(self):
        assert "CREATE TABLE IF NOT EXISTS task_anchor" in GET_SETTING

    def test_s166_pin_survives_nudge_rewrite(self):
        assert '"content": RESUME_NUDGE_TEXT, "name": "system_note"' in STREAM_PREP

    def test_vision_injection_meta_prefix(self):
        assert "[First-hand image]【框架视觉注入·非用户发言】" in STREAM_ENGINE
        assert "[Browser screenshot]【框架视觉注入·非用户发言】" in STREAM_ENGINE

    def test_resume_provenance_instrumentation(self):
        assert "[ResumeProvenance]" in CHAT_JS
        assert "firstUserIdx=" in CHAT_JS
