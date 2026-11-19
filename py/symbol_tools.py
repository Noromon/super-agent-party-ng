# S251：符号级代码块定位——按方法/函数名找到完整定义块（大括号配平，引号/注释感知；
# Python 走缩进），供 read_file_range_tool_local(symbol=...) 使用，代码考古一步到位。
import re
from dataclasses import dataclass
from typing import List, Optional

_KW_TMPL = r"\b(?:def|fun|func|fn|function)\s+{name}\s*\("
_MODIFIERS = ("public|private|protected|static|final|abstract|synchronized|native|override|virtual|"
              "reoverride|constexpr|async|suspend|inline|readonly|open|sealed|external|"
              "void|int|long|boolean|bool|float|double|byte|char|short|unsigned|signed|auto|string|"
              "str|Task|Promise|void\\*|QString|var|let|const")


@dataclass
class SymbolBlock:
    start: Optional[int]          # 0-based；None = 未找到
    end: Optional[int]
    how: str = ""                 # 定位方式说明
    candidates: List[int] = None  # 未找到定义时的引用行候选

    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []


def find_symbol_def(lines: List[str], symbol: str) -> Optional[int]:
    name = re.escape(symbol)
    kw = re.compile(_KW_TMPL.format(name=name))
    typed = re.compile(rf"^\s*(?:@\w+\s+)*(?:(?:{_MODIFIERS})[\w<>\[\],\.\*&\s]+)+{name}\s*\(")
    plain = re.compile(rf"^(?:@\w+\s+)*(?:async\s+|declare\s+)?{name}\s*\([^)]*\)\s*(?::[^{{]*)?\{{$")
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or s.startswith(("//", "*", "/*", "<")):
            continue
        if kw.search(ln):
            return i
        if "." in s.split(symbol)[0].split("(")[0] and not typed.search(ln):
            continue  # this.foo( / obj.foo( 调用
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        has_brace = s.endswith("{") or (s.endswith(")") and nxt.startswith("{")) or "{" in s.split(symbol, 1)[-1].split(")")[-1]
        if (typed.search(ln) or plain.match(s) or kw.search(ln)) and has_brace:
            return i
    # 第二遍：无 brace 的定义形态（接口/抽象方法，返回签名行单行）
    for i, ln in enumerate(lines):
        s = ln.strip()
        if (typed.search(ln) or plain.match(s)) and re.search(rf"{name}\s*\([^)]*\)\s*(;|$)", s):
            return i
    return None


def block_end(lines: List[str], start: int, is_py: bool) -> int:
    if is_py:
        base = len(lines[start]) - len(lines[start].lstrip())
        j = start + 1
        last = start
        while j < len(lines):
            s = lines[j]
            if s.strip():
                if (len(s) - len(s.lstrip())) <= base:
                    break
                last = j
            j += 1
        return last
    depth = 0
    started = False
    in_s = in_d = in_bt = in_bc = False
    in_lc = False
    for j in range(start, len(lines)):
        ln = lines[j]
        k = 0
        in_lc = False
        while k < len(ln):
            c = ln[k]
            n2 = ln[k:k + 2]
            if in_bc:
                if n2 == "*/":
                    in_bc = False
                    k += 1
                k += 1
                continue
            if in_lc:
                k += 1
                continue
            if in_s:
                if c == "\\":
                    k += 1
                elif c == "'":
                    in_s = False
                k += 1
                continue
            if in_d:
                if c == "\\":
                    k += 1
                elif c == '"':
                    in_d = False
                k += 1
                continue
            if in_bt:
                if c == "\\":
                    k += 1
                elif c == "`":
                    in_bt = False
                k += 1
                continue
            if n2 == "//":
                in_lc = True
                break
            if n2 == "/*":
                in_bc = True
                k += 1
                continue
            if c == "'":
                in_s = True
            elif c == '"':
                in_d = True
            elif c == "`":
                in_bt = True
            elif c == "{":
                depth += 1
                started = True
            elif c == "}":
                depth -= 1
                if started and depth <= 0:
                    return j
            k += 1
    return min(start, len(lines) - 1)  # 没配平（接口单行/解析失败）→ 视为单行


def find_symbol_block(lines: List[str], symbol: str, is_py: bool = False, max_lines: int = 400) -> SymbolBlock:
    start = find_symbol_def(lines, symbol)
    if start is None:
        pat = re.compile(rf"\b{re.escape(symbol)}\b")
        cands = [i for i, ln in enumerate(lines) if pat.search(ln)][:6]
        return SymbolBlock(None, None, candidates=cands)
    end = block_end(lines, start, is_py)
    how = "python-indent" if is_py else "brace-balanced"
    if end - start + 1 > max_lines:
        end = start + max_lines - 1
        how += f", capped at {max_lines} lines"
    return SymbolBlock(start, end, how)
