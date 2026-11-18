# S244：孤立代理项三层防御
#  A: tool_output_store 字节切分配对边界对齐（head 退/tail 进）
#  B: server._bound_tool_output 落历史前 sanitize
#  C: get_setting._encodable 入库前剥孤立代理（save_bot_conv 链路）
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import server  # noqa: E402
import py.tool_output_store as tos  # noqa: E402


def _encodable(s):
    try:
        s.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _lone(s):
    return any(0xD800 <= ord(ch) <= 0xDFFF for ch in s)


# ---------------- A: 配对边界对齐 ----------------

def test_prefix_bytes_never_ends_with_high_surrogate():
    # '🌆' 的代理对恰好横跨预算边界（100 个 ascii + emoji 7 字节）
    text = "a" * 100 + "\U0001F306" + "b" * 100
    for budget in range(100, 108):
        head = tos._take_prefix_bytes(text, budget)
        assert _encodable(head), f"budget={budget} head 带病: {head[-6:]!r}"
        assert not _lone(head)


def test_suffix_bytes_never_starts_with_low_surrogate():
    text = "a" * 100 + "\U0001F306" + "b" * 100
    for budget in range(96, 108):
        tail = tos._take_suffix_bytes(text, budget)
        assert _encodable(tail), f"budget={budget} tail 带病: {tail[:6]!r}"
        assert not _lone(tail)


def test_bounded_preview_whole_encodable_with_emoji_at_cut():
    lines = ["行内容\U0001F306" * 30 for _ in range(300)]
    text = "\n".join(lines)
    out = tos.bounded_preview(text, "<<<marker 全文已落盘>>>", 40, 2000)
    assert "<<<marker" in out
    assert _encodable(out) and not _lone(out)


# ---------------- B: _bound_tool_output 出口 sanitize ----------------

def test_bound_tool_output_sanitizes_lone_surrogates(tmp_path):
    settings = {"toolOutput": {}, "CLISettings": {"cc_path": str(tmp_path)}}
    # 未超限但输入自带孤立代理（模型端 CESU-8 / 上游残留）
    dirty = "ok \ud83c tail"
    out = server._bound_tool_output(dirty, settings)
    assert _encodable(out) and "\ud83c" not in out
    # 超限走落盘预览路径，emoji 密集体切后仍可编码
    big = ("\U0001F306" + "x" * 6) * 3000
    out2 = server._bound_tool_output(big, settings)
    assert _encodable(out2) and not _lone(out2)


# ---------------- C: 入库链路不炸且不丢轮 ----------------

def test_save_bot_conv_with_lone_surrogate_does_not_raise(tmp_path, monkeypatch):
    import sqlite3
    import py.get_setting as gs
    db = str(tmp_path / "covs.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE conversation_rows (conv_id TEXT PRIMARY KEY, data TEXT,"
                " updated_at REAL, ord INTEGER)")
    con.commit()
    con.close()
    monkeypatch.setattr(gs, "COVS_PATH", db)
    msgs = [{"role": "user", "content": "看这个 \U0001F306"},
            {"role": "tool", "name": "take_snapshot", "content": "脏尾 \ud83c"},
            {"role": "assistant", "content": "收到 \udc00 低代理"}]
    asyncio.run(gs.save_bot_conv("bot:t@s", msgs))          # 不抛 = 轮不再丢
    got = asyncio.run(gs.load_bot_conv("bot:t@s"))
    assert got is not None and len(got) == 3
    for m in got:
        assert _encodable(m["content"])
