# -*- coding: utf-8 -*-
"""S79（B11 飞书三件套）行为测：结构感知分段 + 代码块感知清洗 + card2.0 pins。"""
import ast
import io
import os
import re
import sys
import tempfile
import types
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_feishu_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

_SRC = io.open(_ROOT / "py" / "feishu_bot_manager.py", encoding="utf-8-sig").read()


def _client_stub():
    ns = {"re": re}
    tree = ast.parse(_SRC)
    wanted = {"_is_table_line", "_take_sendable_unit", "_clean_text"}
    found = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name in wanted:
            exec(compile(ast.Module(body=[n], type_ignores=[]), "<x>", "exec"), ns)
            found.append(n.name)
    assert wanted <= set(found), found
    stub = types.SimpleNamespace(separators=["。", "\n", "？", "！"])
    for k in wanted:
        setattr(stub, k, ns[k].__get__(stub))
    return stub


S = _client_stub()


def test_code_block_never_cut():
    buf = "```python\nprint(1)\n"
    assert S._take_sendable_unit(buf) == (None, buf)      # 未闭合→等待
    buf2 = buf + "```\n后面。"
    chunk, rest = S._take_sendable_unit(buf2)
    assert chunk == "```python\nprint(1)\n```\n"
    assert rest == "后面。"


def test_table_whole_unit():
    buf = "| a | b |\n|---|---|\n| 1 | 2 |\n"
    assert S._take_sendable_unit(buf) == (None, buf)      # 无终止行→等待
    buf2 = buf + "表格完了。\n"                            # 终止行需完整（带换行）
    chunk, rest = S._take_sendable_unit(buf2)
    assert chunk.startswith("| a | b |") and chunk.endswith("| 2 |\n")
    assert rest == "表格完了。\n"
    half = buf + "还没收"                                  # 半行终止=分片边界→继续等
    assert S._take_sendable_unit(half) == (None, half)


def test_plain_split_earliest_sep_stops_at_fence():
    chunk, rest = S._take_sendable_unit("第一句。第二句")
    assert chunk == "第一句。" and rest == "第二句"
    # 围栏先于分隔符：普通段不得越过 ``` 起始
    chunk, rest = S._take_sendable_unit("前文。```py")
    assert chunk == "前文。" and rest == "```py"
    assert S._take_sendable_unit("还没分隔符") == (None, "还没分隔符")


def test_clean_text_code_block_aware():
    assert S._clean_text("<b>粗</b> ![i](u)") == "粗"
    body = S._clean_text("```html\n<div><T>保留</div>\n```\n<b>清</b>")
    assert "<div><T>保留</div>" in body and "<b>" not in body
    assert S._clean_text("---") == ""                     # 独立分割线不再发空消息
    assert S._clean_text("前\n---\n后") == "前\n\n后"


# ---------------- card 2.0 / 接线 pins ----------------

def test_send_text_card2_and_gated():
    assert '"schema": "2.0"' in _SRC
    assert '"tag": "markdown"' in _SRC
    assert 'msg_type = "interactive"' in _SRC
    assert '"tag": "md"' not in _SRC                      # 旧 post 富文本退役
    i = _SRC.index("async def _send_text")
    assert _SRC[max(0, i - 60):i].count("@llm_gate.gated") == 1  # fork 串行门保留
    assert 'print("发送文本消息"' not in _SRC
    # 结构感知单点接管旧循环
    assert "self._take_sendable_unit(buffer)" in _SRC
    assert "force_split" not in _SRC
    assert 'leftover.count("```") % 2 == 1' in _SRC       # 收尾补闭合围栏


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
