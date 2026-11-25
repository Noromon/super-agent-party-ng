"""S322：完成闸门放行提示必达 IM。

事故背景（2026-11-26 02:36）：闸门返工上限用尽后 stream_engine 已生成
"⚠️ 任务未完结即收尾" 的 type=error 通知，但 xmpp 消费循环只处理
call/tool_result 两类帧，error 帧被静默丢弃（progress_mode 默认 off 也救不
回来——根本没走 ledger）→ 用户视角=agent 跑一半擅自停手、零解释。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.base_bot import ToolProgressLedger  # noqa: E402

XMPP_SRC = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8")
ENGINE_SRC = (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")


def _error_branch_seg():
    i = XMPP_SRC.index('elif _tt == "error":')
    return XMPP_SRC[i:i + 900]


class TestLedgerBlindToError:
    def test_off_mode_swallows_tool_rows(self):
        # 前提钉桩：ledger off 档无任何可发文本——error 若走 ledger 必被吞
        led = ToolProgressLedger(mode="off")
        led.on_call("search_files_tool_local")
        assert led.on_result("search_files_tool_local", "x") is None
        assert led.summary_line() is None
        # detail 档才有进度行（对照：off 的沉默是模式使然，非 error 可达路径）
        det = ToolProgressLedger(mode="detail")
        det.on_call("t")
        assert det.on_result("t", "ok") == "✅ t 完成"


class TestXmppErrorBridge:
    def test_error_branch_exists_and_sends_directly(self):
        seg = _error_branch_seg()
        assert "_send_text" in seg
        # 不经过 ledger（off/summary 档也必达）：分支体内无 ledger.on_*
        assert "ledger.on" not in seg.split("elif")[0]

    def test_error_branch_seals_buffer_and_dedupes(self):
        seg = _error_branch_seg()
        assert "err_noticed" in seg and "out_buffer" in seg

    def test_error_noticed_initialized(self):
        assert "err_noticed = set()" in XMPP_SRC


class TestExhaustNoticeItems:
    def test_exhaust_lists_open_items(self):
        i = ENGINE_SRC.index('if _g_act == "exhaust":')
        seg = ENGINE_SRC[i:i + 700]
        assert "_g_payload[:8]" in seg          # 列明未完成项而非只报数
        assert "未收口：{_gids}" in seg
        assert "回复「继续」可再推进" in seg
        assert "yield _tool_notice_chunk" in seg  # 仍走同一通知通道（web 不受损）
