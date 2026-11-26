# -*- coding: utf-8 -*-
"""S328 吞子钉：el-switch 禁自闭合写法（HTML 自定义元素吞兄弟事故）。

事故链：HTML5 解析器无视自定义元素的 `/>`——<el-switch/> 是未闭合
开始标签，后续同父兄弟全部嵌套其内，Vue 组件渲染时丢弃默认插槽内容
→ 文字在编译前蒸发、无任何 console 报错。全仓 40+ 历史自闭合因处于
容器末位（无兄弟可吞）而多年无恙；S324 两处新写法后面跟了文字 → 文案
"消失"三轮排查（缓存/指纹/双实例）全被带偏。
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TPLS = sorted(list((_ROOT / "static" / "templates").glob("*.html"))
               + list((_ROOT / "static").glob("*.html")))

SELF_CLOSED = re.compile(r"<el-switch\b[^<]*?/>", re.S)


def test_no_self_closed_el_switch_anywhere():
    bad = []
    for p in _TPLS:
        t = p.read_text(encoding="utf-8")
        for m in SELF_CLOSED.finditer(t):
            bad.append(f"{p.name}:L{t[:m.start()].count(chr(10)) + 1}")
    assert not bad, (
        f"self-closed <el-switch/> swallows following siblings in in-DOM "
        f"templates (renders them invisible): {bad}. "
        "Fix: <el-switch ...></el-switch>"
    )


def test_ext_card_switch_is_paired_and_label_follows():
    t = (_ROOT / "static" / "templates" / "page_api-group.html").read_text(
        encoding="utf-8")
    i = t.index("toggleAgentAccess")
    seg = t[i:i + 600]
    assert "</el-switch>" in seg.split("tf('allowAiStartExtension')")[0], (
        "ext-card: label text must come AFTER a paired </el-switch>")


def test_allowlist_switch_is_paired_and_label_follows():
    t = (_ROOT / "static" / "templates" / "page_system.html").read_text(
        encoding="utf-8")
    i = t.index("setToolPerm(pname, $event)")
    seg = t[i:i + 600]
    assert "</el-switch>" in seg.split("tf('permToolDesc')")[0], (
        "allowlist row: tool label must come AFTER a paired </el-switch>")
