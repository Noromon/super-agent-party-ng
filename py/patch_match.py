# -*- coding: utf-8 -*-
"""S201 补丁匹配内核（edit_file_patch_tool / _local 共享，纯函数无 IO）。

设计目标（取代旧两个 variant 各自内嵌的策略副本）：
- 分级匹配：精确 → CRLF 适配 → 换行归一 → 忽略行首尾空白的行块滑窗
  → 行相似度（唯一且 ratio >= 0.85 才自动应用）；
- 歧义即安全：同层级命中 >1 处且未显式 replace_all → 零改动，报错列出全部命中行号；
- 多点编辑：edits 顺序应用；调用方仅在 ok=True 时落盘（原子性）；
- 诊断带现场：失配回显最相近窗口的真实内容（带行号），模型据此直接重试补丁、
  无需整读文件；成功回显 unified diff 摘要供确认，无需重读。
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

FUZZY_MIN = 0.85
FUZZY_MARGIN = 0.05
_MAX_FUZZY_LINES = 20000
_SNIPPET_PAD = 2
_SNIPPET_MAX_LINES = 14
_DIFF_MAX_LINES = 24


@dataclass
class PatchResult:
    ok: bool
    content: str = ""
    report: str = ""
    edit_lines: List[int] = field(default_factory=list)


# ---------------------------------------------------------------- 匹配工具

def _starts_of(hay: str, needle: str) -> List[int]:
    starts, i = [], hay.find(needle)
    while i != -1:
        starts.append(i)
        i = hay.find(needle, i + max(1, len(needle)))
    return starts


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _snippet(content: str, start_line: int, end_line: int) -> str:
    lines = content.split("\n")
    a = max(0, start_line - 1 - _SNIPPET_PAD)
    b = min(len(lines), end_line + _SNIPPET_PAD)
    body = [f"{i + 1:>5}|{lines[i]}" for i in range(a, b)]
    if len(body) > _SNIPPET_MAX_LINES:
        body = body[:_SNIPPET_MAX_LINES] + ["  ... (truncated)"]
    return "\n".join(body)


def _line_windows(content: str, old: str) -> List[Tuple[int, int]]:
    """行块滑窗：strip 后逐行相等的所有窗口 (start0, end0)。"""
    kept = content.split("\n")
    tgt = [ln.strip() for ln in old.split("\n")]
    if not tgt or (len(tgt) == 1 and not tgt[0]):
        return []
    return [(i, i + len(tgt)) for i in range(len(kept) - len(tgt) + 1)
            if all(kept[i + j].strip() == tgt[j] for j in range(len(tgt)))]


def _best_similar_window(content: str, old: str) -> Tuple[float, Optional[Tuple[int, int]]]:
    kept = [ln.strip() for ln in content.split("\n")]
    tgt = [ln.strip() for ln in old.split("\n") if ln.strip()]
    if not tgt or not kept or len(kept) < len(tgt):
        return 0.0, None
    sm = difflib.SequenceMatcher(None)
    joined_tgt = "\x1f".join(tgt)
    w = len(tgt)
    best, best_pos, second = 0.0, None, 0.0
    for i in range(len(kept) - w + 1):
        sm.set_seqs("\x1f".join(kept[i:i + w]), joined_tgt)
        r = sm.ratio()
        if r > best:
            second, best, best_pos = best, r, i
        elif r > second:
            second = r
    return best, ((best_pos, best_pos + w) if best_pos is not None else None)


# ---------------------------------------------------------------- 应用与报告

def _replace_spans(hay: str, starts: List[int], old_part: str, new_part: str) -> str:
    out, prev = [], 0
    for s in starts:
        out.append(hay[prev:s])
        out.append(new_part)
        prev = s + len(old_part)
    out.append(hay[prev:])
    return "".join(out)


def _replace_windows(content: str, wins: List[Tuple[int, int]], new: str) -> str:
    lines = content.split("\n")
    for a, b in sorted(wins, reverse=True):
        tail_cr = lines[a].endswith("\r")
        new_lines = new.replace("\r\n", "\n").split("\n")
        if len(new_lines) > 1 and new_lines[-1] == "":
            new_lines.pop()  # new 以换行结尾：尾部空行不代表额外一行内容
        if tail_cr:
            new_lines = [ln + "\r" for ln in new_lines]
        lines[a:b] = new_lines
    return "\n".join(lines)


def _ambiguity_error(style: str, starts_or_wins: List[Any], src: str, edit_no: int,
                     spans_are_lines: bool) -> str:
    if spans_are_lines:
        locs = [f"  line {a + 1}" for a, _b in starts_or_wins[:6]]
    else:
        locs = [f"  line {_line_of(src, s)}" for s in starts_or_wins[:6]]
    more = "" if len(starts_or_wins) <= 6 else f"  ... ({len(starts_or_wins)} occurrences total)"
    return (f"[Error] edit {edit_no}: ambiguous match — old_string occurs "
            f"{len(starts_or_wins)} times ({style}). No changes were made.\n"
            f"Locations:\n" + "\n".join(locs) + more +
            "\nEither widen old_string with surrounding context to hit one spot, "
            "or set replace_all=true to replace every occurrence.")


def _miss_report(content: str, old: str, edit_no: int) -> str:
    ratio, win = 0.0, None
    if len(content.split("\n")) <= _MAX_FUZZY_LINES:
        ratio, win = _best_similar_window(content, old)
    if win:
        return (f"[Error] edit {edit_no}: old_string not found (closest region similarity "
                f"{ratio:.2f}). No changes were made.\n"
                f"Closest actual content:\n--- actual ---\n"
                f"{_snippet(content, win[0] + 1, win[1])}\n--- end ---\n"
                "Retry the patch by copying the text above VERBATIM; "
                "no need to re-read the whole file. If you already tried THIS edit before and got "
                "success/[No-op], the change IS on disk — verify by running the program or reading "
                "those lines; NEVER resend the same old_string unchanged.")
    return (f"[Error] edit {edit_no}: old_string not found and no similar region exists. "
            "No changes were made. Verify the path and that this content belongs to this file. "
            "If a previous attempt reported success, the file is already in the target state — stop.")


def _apply_edit(content: str, old: str, new: str, replace_all: bool,
                edit_no: int) -> Tuple[bool, Optional[str], Optional[int], str]:
    """返回 (ok, 新内容, 首个改动行号, 摘要或错误)。"""
    # 1) 精确
    starts = _starts_of(content, old)
    if starts:
        if len(starts) > 1 and not replace_all:
            return False, None, None, _ambiguity_error("exact match", starts, content, edit_no, False)
        pick = starts if replace_all else starts[:1]
        new_part = new
        if "\r\n" in content and "\r\n" not in new and "\n" in new:
            new_part = new.replace("\n", "\r\n")
        return (True, _replace_spans(content, pick, old, new_part),
                _line_of(content, pick[0]),
                f"edit {edit_no}: {len(pick)} replacement(s) (exact match)")
    # 2) CRLF 适配：文件是 CRLF，old 是 LF → old 转 CRLF 后在原文上找
    if "\r\n" in content and "\r\n" not in old:
        old_c = old.replace("\n", "\r\n")
        starts = _starts_of(content, old_c)
        if starts:
            if len(starts) > 1 and not replace_all:
                return False, None, None, _ambiguity_error("CRLF-adapted match", starts, content, edit_no, False)
            pick = starts if replace_all else starts[:1]
            new_c = new.replace("\n", "\r\n") if "\n" in new else new
            return (True, _replace_spans(content, pick, old_c, new_c),
                    _line_of(content, pick[0]),
                    f"edit {edit_no}: {len(pick)} replacement(s) (CRLF line endings adapted, file style preserved)")
    # 3) 换行归一：old 带 CRLF 或文件含混合换行 → 双侧归一到 LF 再找
    if "\r\n" in old or "\r\n" in content:
        content_n = content.replace("\r\n", "\n")
        old_n = old.replace("\r\n", "\n")
        starts = _starts_of(content_n, old_n)
        if starts:
            if len(starts) > 1 and not replace_all:
                return False, None, None, _ambiguity_error("line-ending-normalized match", starts, content_n, edit_no, False)
            pick = starts if replace_all else starts[:1]
            return (True, _replace_spans(content_n, pick, old_n, new.replace("\r\n", "\n")),
                    _line_of(content_n, pick[0]),
                    f"edit {edit_no}: {len(pick)} replacement(s) (line endings normalized to LF for the whole file)")
    # 4) 忽略行首尾空白的行块滑窗
    wins = _line_windows(content, old)
    if wins:
        if len(wins) > 1 and not replace_all:
            return False, None, None, _ambiguity_error("whitespace-insensitive match", wins, content, edit_no, True)
        pick = wins if replace_all else wins[:1]
        return (True, _replace_windows(content, pick, new), pick[0][0] + 1,
                f"edit {edit_no}: {len(pick)} replacement(s) (whitespace/indentation differences ignored)")
    # 5) 行相似度：唯一且过阈值才自动应用，否则只诊断
    if len(content.split("\n")) <= _MAX_FUZZY_LINES:
        ratio, win = _best_similar_window(content, old)
        if win and ratio >= FUZZY_MIN:
            lines = content.split("\n")
            a, b = win
            masked = "\n".join(lines[:a] + ["\x00" * 40] * (b - a) + lines[b:])
            r2, _ = _best_similar_window(masked, old)
            if ratio - r2 >= FUZZY_MARGIN or r2 < FUZZY_MIN:
                return (True, _replace_windows(content, [win], new), a + 1,
                        f"edit {edit_no}: 1 replacement (approximate match ratio={ratio:.2f}, "
                        f"line {a + 1}-{b}) — verify the diff below carefully")
            return False, None, None, (
                f"[Error] edit {edit_no}: ambiguous approximate match (two equally similar "
                f"locations, ratio {ratio:.2f}). No changes were made.\n"
                f"Closest actual content:\n--- actual ---\n"
                f"{_snippet(content, a + 1, b)}\n--- end ---")
    return False, None, None, _miss_report(content, old, edit_no)


def _failure_report(original: str, work: str, old: str, new: str, ra: bool,
                    edit_no: int, work_msg: str) -> str:
    """S202：报错回显必须是磁盘真相。单编辑（work==original）原样返回；批内失败时
    一律对原始内容重探重渲染——若该 edit 在磁盘上本可命中，说明命中区被批内前序
    edit 覆盖，给出冲突专属文案。"""
    if original == work:
        return work_msg
    ok0, _c0, ln0, msg0 = _apply_edit(original, old, new, ra, edit_no)
    if ok0:
        n_lines = len(old.split("\n"))
        msg = (f"[Error] edit {edit_no}: old_string matches the on-disk file, but an earlier "
               f"edit in this batch already replaced that region. No changes were written.\n"
               f"On-disk content at the match:\n--- actual (on disk) ---\n"
               f"{_snippet(original, ln0, ln0 + n_lines - 1)}\n--- end ---\n"
               "Reorder the edits so this one runs before the one that consumes its target, "
               "or write its old_string to match the earlier edit's result.")
    else:
        msg = msg0
    return (msg + "\nNote: edits are applied to an in-memory copy; the file on disk is "
            "untouched. Retry by resending the WHOLE batch.")


def _diff_excerpt(old_content: str, new_content: str) -> str:
    diff = list(difflib.unified_diff(old_content.split("\n"), new_content.split("\n"),
                                     fromfile="before", tofile="after", lineterm="", n=2))
    diff = diff[2:]
    if not diff:
        return ""
    if len(diff) > _DIFF_MAX_LINES:
        diff = diff[:_DIFF_MAX_LINES] + [f"... (diff truncated, {len(diff) - _DIFF_MAX_LINES} lines omitted)"]
    return "\n".join(diff)


def _normalize_edits(edits: Any) -> Tuple[List[Tuple[str, str, bool]], str]:
    if isinstance(edits, str):
        try:
            edits = json.loads(edits)
        except Exception:
            return [], "[Error] edits is not valid JSON."
    if not isinstance(edits, list) or not edits:
        return [], "[Error] edits must be a non-empty array of {old_string, new_string}."
    out = []
    for i, e in enumerate(edits, 1):
        if not isinstance(e, dict):
            return [], f"[Error] edit {i}: must be an object with old_string/new_string."
        old = e.get("old_string")
        new = e.get("new_string", "")
        ra = bool(e.get("replace_all", False))
        if not isinstance(old, str) or not old:
            return [], (f"[Error] edit {i}: old_string missing or empty — use the "
                        "full-rewrite write tool for creating/wholesale replacement instead.")
        if not isinstance(new, str):
            return [], f"[Error] edit {i}: new_string must be a string (empty string deletes)."
        out.append((old, new, ra))
    return out, ""


def apply_edits(content: str, edits: Any) -> PatchResult:
    """在 content 上顺序应用 edits；任一失配返回 ok=False 且 content 为空（整体不落盘）。"""
    norm, err = _normalize_edits(edits)
    if err:
        return PatchResult(False, report=err)
    work = content
    summaries: List[str] = []
    edit_lines: List[int] = []
    for i, (old, new, ra) in enumerate(norm, 1):
        ok, newc, ln, msg = _apply_edit(work, old, new, ra, i)
        if not ok:
            return PatchResult(False, report=_failure_report(content, work, old, new, ra, i, msg))
        work = newc
        summaries.append(msg)
        edit_lines.append(ln or 0)
    if work == content:
        # S309 net-zero：逐条都"成功"但文件字节不变（fuzzy 把已写好的 new 当 old
        # 匹配再写回同样 new 的假成功，df2f8248 事故）→ 报 No-op，不产生落盘内容。
        return PatchResult(True, content="", edit_lines=edit_lines,
                           report="[No-op] All edits matched but produced ZERO net change — the file "
                                  "is ALREADY in the requested state. Nothing was written. Do NOT "
                                  "repeat this call; verify by running the program or reading the lines.")
    report = "; ".join(summaries)
    diff = _diff_excerpt(content, work)
    if diff:
        report += "\n" + diff
    return PatchResult(True, content=work, report=report, edit_lines=edit_lines)
