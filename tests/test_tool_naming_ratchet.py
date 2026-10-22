# -*- coding: utf-8 -*-
"""M-10 工具命名冲突棘轮（审计 09）。

*_tool vs *_tool_local 双工具族 + 近邻语义名（edit_file_patch_tool vs
edit_file_tool 等）是 LLM 幻觉工具名（C-19）的温床。difflib 近似名
冲突对基线现值见 _CONFLICT_CAP 行注（162=2026-10-21 实测，165=S65-A10 youcom_search
移植入 *_search 家族契约名 +3 对；RA-36/RA G9-10 勘误：原 docstring 滞留 162）。整族改名按审计原文排在 E-1 工具
registry 落地之后（改名=LLM 可见契约+审批 UI/auto-approve/.party 白名单
连锁）；在此之前本棘轮保证冲突对**只降不升**——新增工具引入新近似名
冲突即转红。

若你完成了族改名/合并：下调 _CONFLICT_CAP 到新的实测值。
"""
import difflib
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

_CONFLICT_CAP = 165  # 2026-10-21 S65-A10 上游 youcom_search 移植（*_search 家族契约名，+3 对）


def _hook_names():
    src = (_ROOT / "server.py").read_text(encoding="utf-8-sig")
    names = set()
    for m in re.finditer(r"_TOOL_HOOKS\s*=\s*\{", src):
        depth, i = 1, m.end()
        while depth and i < len(src):
            if src[i] == "{":
                depth += 1
            elif src[i] == "}":
                depth -= 1
            i += 1
        names.update(re.findall(r'"([A-Za-z0-9_\.]+)":', src[m.end():i]))
    return sorted(names)


def _conflict_pairs(names):
    pairs = set()
    for n in names:
        for m in difflib.get_close_matches(n, [x for x in names if x != n], n=5, cutoff=0.6):
            pairs.add(tuple(sorted((n, m))))
    return pairs


def test_hook_table_nonempty():
    assert len(_hook_names()) > 80


def test_naming_conflict_pairs_do_not_grow():
    names = _hook_names()
    pairs = _conflict_pairs(names)
    assert len(pairs) <= _CONFLICT_CAP, (
        f"工具命名冲突对 {len(pairs)} > 上限 {_CONFLICT_CAP}（M-10 防恶化棘轮）。"
        "请给新工具起与既有名相似度 <0.6 的名字；"
        "若完成了 ±local 族改名（E-1 后），按实测值下调 _CONFLICT_CAP")
