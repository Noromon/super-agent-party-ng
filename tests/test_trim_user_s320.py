# S320：审批续跑 500（No user query found）根治。
# 事故（2026-11-25 kerobros/xmpp）：_apply_group_memory_context 对全部请求经
# _trim_request_messages 静默保留后 12 条对话——续跑快照的真实 user 恰在窗口外
# 被剪掉，严格 chat 模板倒扫无 user raise 500；xmpp 无 conversation_id 又绕过
# S307 锚点防线。本测钉桩：F-A 裁剪保 user/配对安全/留痕 / F-B im 锚点键 /
# F-C 占位兜底与行为轮豁免 / xmpp 每轮锚点登记。
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
from py.context_builder import sanitize_tool_chains  # noqa: E402
from py.group_memory import _trim_request_messages  # noqa: E402

GM_SRC = (ROOT / "py" / "group_memory.py").read_text(encoding="utf-8")
XMPP_SRC = (ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")

TASK = "看看96m的数据分析"


def _pair(i):
    return [{"role": "assistant", "content": "",
             "tool_calls": [{"id": f"c{i}", "type": "function",
                             "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"c{i}", "content": "r"}]


def _parallel_group(i):
    return [{"role": "assistant", "content": "",
             "tool_calls": [{"id": f"x{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}},
                            {"id": f"y{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": f"x{i}", "content": "r"},
            {"role": "tool", "tool_call_id": f"y{i}", "content": "r"}]


class TestTrimUserPreserve:
    def test_short_dialog_untouched_and_copied(self):
        msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": TASK},
                {"role": "assistant", "content": "好的"}]
        out = _trim_request_messages(msgs, recent_count=12)
        assert out == msgs
        assert out[1] is not msgs[1]

    def test_user_outside_window_preserved_in_order(self):
        # 复刻事故形态：user 之后 12 对工具（24 条），窗口 12 全是对——user 必须保留
        dialog = [{"role": "user", "content": TASK}]
        for i in range(12):
            dialog.extend(_pair(i))
        out = _trim_request_messages([{"role": "system", "content": "s"}] + dialog,
                                     recent_count=12)
        assert out[0]["role"] == "system"
        assert task_anchor.last_genuine_user_text(out) == TASK
        assert out[1] == {"role": "user", "content": TASK}
        assert out[-2:] == dialog[-2:]  # 窗口尾部原样
        assert len(out) <= 1 + 12 + 1

    def test_trim_result_has_no_orphan_tools(self):
        # 配对安全：裁剪结果经 sanitize 必须零丢弃（含并行工具组切点场景）
        dialog = []
        for i in range(10):
            dialog.extend(_pair(i))
        for i in range(4):
            dialog.extend(_parallel_group(100 + i))
        for rc in (12, 7, 5, 4, 3):
            out = _trim_request_messages(dialog, recent_count=rc)
            assert sanitize_tool_chains([dict(m) for m in out]) == out, f"rc={rc} 出现孤儿/丢失"

    def test_genuine_window_untouched_by_preservation(self):
        dialog = []
        for i in range(8):
            dialog.extend(_pair(i))
        dialog.append({"role": "user", "content": TASK})  # user 已在窗口内
        out = _trim_request_messages(dialog, recent_count=12)
        assert task_anchor.last_genuine_user_text(out) == TASK
        assert out[-1] == {"role": "user", "content": TASK}
        assert len(out) < len(dialog)  # 正常裁剪仍生效，不额外保人


class TestReqKey:
    def test_web_conversation_id(self):
        req = types.SimpleNamespace(conversation_id="conv-9", messages=[])
        assert task_anchor.req_key(req) == "conv-9"

    def test_im_fallback_key(self):
        req = types.SimpleNamespace(conversation_id=None, is_app_bot=True,
                                    platform="xmpp", peer_id="k@l", messages=[])
        assert task_anchor.req_key(req) == "im:xmpp:k@l"

    def test_no_key_without_bot_identity(self):
        req = types.SimpleNamespace(conversation_id=None, is_app_bot=False,
                                    platform="xmpp", peer_id="k@l", messages=[])
        assert task_anchor.req_key(req) is None


class TestImResumeRepair:
    def _bot_req(self, messages):
        return types.SimpleNamespace(conversation_id=None, is_app_bot=True,
                                     platform="xmpp", peer_id="k@l", messages=messages)

    def test_im_anchor_persist_and_repair(self, tmp_path, monkeypatch):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", str(tmp_path / "covs.db"))
            ok = self._bot_req([{"role": "system", "content": "s"},
                                {"role": "user", "content": TASK},
                                {"role": "assistant", "content": "好的"}])
            await task_anchor.anchor_stream_in(ok)  # 首流：按 im 键持久化
            assert await task_anchor.fetch_anchor("im:xmpp:k@l") == TASK
            broken = self._bot_req([{"role": "system", "content": "s"}] + _pair(1))
            await task_anchor.anchor_stream_in(broken)  # 续跑缺 user：锚点回注
            assert task_anchor.last_genuine_user_text(broken.messages) == TASK
        asyncio.run(body())

    def test_web_no_anchor_gets_placeholder(self, tmp_path, monkeypatch):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", str(tmp_path / "covs.db"))
            req = types.SimpleNamespace(conversation_id="conv-fresh",
                                        messages=[{"role": "system", "content": "s"}] + _pair(1))
            await task_anchor.anchor_stream_in(req)
            assert task_anchor.last_genuine_user_text(req.messages) == task_anchor.FALLBACK_USER_TEXT
        asyncio.run(body())

    def test_diary_and_behavior_turns_skip_placeholder(self, tmp_path, monkeypatch):
        async def body():
            monkeypatch.setattr(task_anchor, "COVS_PATH", str(tmp_path / "covs.db"))
            diary = types.SimpleNamespace(conversation_id=None, is_app_bot=True,
                                          platform="diary", peer_id="solo",
                                          messages=[{"role": "system", "content": "s"},
                                                    {"role": "assistant", "content": "x"}])
            await task_anchor.anchor_stream_in(diary)  # 独处书写：不塞占位
            assert task_anchor.last_genuine_user_text(diary.messages) is None
            beh = types.SimpleNamespace(conversation_id=None, is_app_bot=True,
                                        platform="xmpp", peer_id="k@l",
                                        behavior_trigger=True,
                                        messages=[{"role": "system", "content": "s"},
                                                  {"role": "assistant", "content": "x"}])
            await task_anchor.anchor_stream_in(beh)  # 行为/主动外发轮：同豁免
            assert task_anchor.last_genuine_user_text(beh.messages) is None
        asyncio.run(body())


class TestPins:
    def test_trim_logging_and_user_guard_present(self):
        assert "[MsgTrim]" in GM_SRC
        assert "is_genuine_user_msg" in GM_SRC

    def test_xmpp_registers_anchor_per_turn(self):
        seg = XMPP_SRC.split("def _process_llm", 1)[1].split("def _agent_stream_to_peer", 1)[0]
        assert "remember_anchor" in seg
        assert "im:xmpp:" in seg
