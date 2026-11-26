# -*- coding: utf-8 -*-
"""S332: MsgTrim 让位 L1/L2（对齐 opencode）+ XMPP compact 持久写回。

18:47 事故量化：kerobros 展平 1012 条 est 277k > 预算 236k → 旧实现盲切 12，
引擎 L1/L2 摘要管线（autoAgentCompact=true）因所见 est 恒 ≤ 预算而永不触发；
且即使触发，context_compact 事件只有 web 前端消费者，XMPP memoryList 无写回
路径=每轮全量重放。修复：未超引擎窗口一律直通让位；超限按 token 动态尾窗；
xmpp 嗅探摘要事件写回 memoryList（opencode compaction boundary 语义）。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # 驱逐 site-packages 的 py 单体库（s323 同法）

import pytest  # noqa: E402

from py import im_chain as IC  # noqa: E402
from py.group_memory import _trim_request_messages  # noqa: E402


def _dialog(n, chars=8):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"m{i} " + "x" * chars} for i in range(n)]


class TestDeferPipeline:
    def test_over_budget_but_within_window_defers(self, caplog):
        st = {"contextManagement": {"enabled": True, "contextWindow": 45000,
                                    "compactRatio": 0.8, "keepRecentDialog": 12}}
        msgs = _dialog(60, chars=5000)  # 估算器≈8字符/token：budget=36k<est≈38k≤window=45k
        with caplog.at_level("INFO"):
            out = _trim_request_messages(msgs, settings=st)
        assert len(out) == len(msgs)  # 让位直通——L1/L2 见得到全量才会摘要
        assert "让位 L1/L2" in caplog.text

    def test_dynamic_window_keeps_far_more_than_12(self):
        st = {"contextManagement": {"enabled": True, "contextWindow": 50000,
                                    "compactRatio": 0.8, "keepRecentDialog": 12}}
        msgs = _dialog(200, chars=3000)  # est≈77k > window=50k → 动态尾窗≈118 条
        out = _trim_request_messages(msgs, settings=st)
        assert 12 < len(out) < len(msgs)  # token 驱动尽量保，非固定 12 盲切

    def test_logs_carry_est_and_budget(self, caplog):
        st = {"contextManagement": {"enabled": True, "contextWindow": 45000,
                                    "compactRatio": 0.8, "keepRecentDialog": 12}}
        with caplog.at_level("INFO"):
            _trim_request_messages(_dialog(60, chars=5000), settings=st)
        t = caplog.text
        assert "est" in t and ("cap" in t or "budget" in t)


class TestCompactMemory:
    def _entries(self, n=10, chain_tools=6):
        out = []
        for i in range(n):
            be = []
            for t in range(chain_tools):
                be.append({"role": "tool", "content": f"t{i}-{t} " + "y" * 4000,
                           "tool_call_id": f"c{i}-{t}"})
            out.append({"role": "assistant", "content": f"a{i} 回复",
                        "backend_content": be})
        return out

    def test_summary_head_replaces_old_entries(self):
        mem = self._entries()
        new, dropped = IC.compact_memory(mem, "早前任务已完成 X/Y。", 20000)
        assert dropped > 0
        assert new[0]["is_compact_summary"] and "已完成 X/Y" in new[0]["content"]
        assert new[-1] is mem[-1]  # 最新条目保留
        flat = IC.flatten_memory(new)
        assert flat[0]["role"] == "user" and "【对话摘要·已压缩】" in flat[0]["content"]

    def test_all_within_target_untouched(self):
        mem = self._entries(2, chain_tools=1)
        new, dropped = IC.compact_memory(mem, "摘要", 999999)
        assert dropped == 0 and new == mem

    def test_empty_summary_never_destroys(self):
        mem = self._entries()
        new, dropped = IC.compact_memory(mem, "   ", 1)
        assert dropped == 0 and new == mem


class TestPinsS332:
    def test_xmpp_sniffs_and_writes_back(self):
        src = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8-sig")
        assert src.count("context_compact") >= 1
        assert src.count("_apply_compact_writeback") == 3  # 定义+两处轮末调用
        assert src.count("is_compact_summary") >= 2  # 摘要头存在=条目窗让位×2

    def test_web_channel_unchanged(self):
        src = (_ROOT / "static" / "js" / "methods" / "10_chat_stream.js").read_text(
            encoding="utf-8-sig")
        assert "context_compact" in src  # web 消费闭环仍在（S332 不动前端）


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
