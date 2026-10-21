# -*- coding: utf-8 -*-
"""vue_methods 域切分工具（批 3 F2）。

按对象顶层键范围提取方法块，从 static/js/vue_methods.js 搬移到
static/js/methods/NN_<domain>.js（Object.assign(vue_methods, {...}) 形式，
classic script，加载于 vue_methods.js 之后、renderer.js 之前）。

用法：
  列举:      .venv\\Scripts\\python.exe scripts/extract_methods.py --list
  搜索:      ... --grep bot
  搬移:      ... --move js/methods/40_bots.js key1 key2 ...
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OBJ = "vue_methods"  # --object vue_data 时覆盖
SRC = ROOT / "static" / "js" / "vue_methods.js"


def top_level_entries(src: str):
    """返回 [(key, start_line, end_line)]（1-based，含键所在行到块结束行）。"""
    m = re.search(r"(?:let|const|var)\s+" + OBJ + r"\s*=\s*\{", src)
    if not m:
        raise ValueError("vue_methods anchor not found")
    i = m.end()
    depth = 1
    n = len(src)
    entries = []
    pending = None
    prev_sig = ""
    while i < n and depth > 0:
        c = src[i]
        if c in "\"'":
            q = c
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == q:
                    break
                i += 1
            prev_sig = q
            i += 1
            continue
        if c == "`":
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == "`":
                    break
                if src[i] == "$" and i + 1 < n and src[i + 1] == "{":
                    d = 1
                    i += 2
                    while i < n and d:
                        if src[i] == "{":
                            d += 1
                        elif src[i] == "}":
                            d -= 1
                        i += 1
                    continue
                i += 1
            prev_sig = "`"
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i)
            i = n if j < 0 else j + 2
            continue
        if c == "/" and (prev_sig in "(,=:[!&|?{};\n" or not prev_sig):
            j = i + 1
            in_cls = False
            while j < n:
                cj = src[j]
                if cj == "\\":
                    j += 2
                    continue
                if cj == "[":
                    in_cls = True
                elif cj == "]":
                    in_cls = False
                elif cj == "/" and not in_cls:
                    break
                elif cj == "\n":
                    break
                j += 1
            if j < n and src[j] == "/":
                i = j + 1
                prev_sig = "/"
                continue
        if c in "{[(":
            depth += 1
            if depth == 2 and pending:
                pending["body_started"] = True
            prev_sig = c
            i += 1
            continue
        if c in "}])":
            depth -= 1
            if depth == 1 and pending:
                # 键值结束（方法体 } 或值对象 } 或数组 ] 或 顶层逗号前）
                if pending.get("body_started"):
                    entries.append((pending["key"], pending["start"], src[:i].count("\n") + 1))
                    pending = None
            prev_sig = c
            i += 1
            continue
        if c == "," and depth == 1 and pending:
            if pending.get("body_started"):
                entries.append((pending["key"], pending["start"], src[:i].count("\n") + 1))
                pending = None
            i += 1
            continue
        if depth == 1 and (c.isalpha() or c in "_$"):
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            ident = src[i:j]
            k = j
            while k < n and src[k] in " \t\r\n":
                k += 1
            if k < n and src[k] in "(:":
                if pending is None:
                    pending = {"key": ident, "start": src[:i].count("\n") + 1,
                               "body_started": False}
                prev_sig = src[k]
                i = k + 1
                if src[k] == "(":
                    depth += 1
                    pending["body_started"] = False
                continue
            prev_sig = ident[-1]
            i = j
            continue
        if not c.isspace():
            prev_sig = c
        i += 1
    return entries


def _line_end(src_lines, ln):
    return ln


def move(dest_rel: str, keys):
    src = SRC.read_text(encoding="utf-8")
    src_lines = src.splitlines(keepends=True)
    entries = top_level_entries(src)
    index = {}
    for key, a, b in entries:
        index.setdefault(key, (a, b))
    keys = list(dict.fromkeys(keys))
    for k in keys:
        if k not in index:
            print("MISSING:", k)
            sys.exit(1)
    # 收集块（含其上紧邻注释行：向上吃注释/空行直到空行+非注释）
    blocks = []
    ranges = []
    for k in keys:
        a, b = index[k]
        aa = a
        while aa - 2 >= 0:
            prev = src_lines[aa - 2].strip()
            if prev.startswith("//") or prev.startswith("*") or prev.startswith("/*"):
                aa -= 1
            elif prev == "" and src_lines[aa - 2 if aa - 2 < len(src_lines) else 0].strip().startswith("//"):
                aa -= 1
            else:
                break
        # 尾随逗号行处理：块含到 b 行，若 b+1 行是纯 ',' 已含在 b
        blocks.append((aa, b, k))
        ranges.append((aa, b))
    # 源文件删除（从后往前）
    out = src_lines[:]
    for aa, b, k in sorted(blocks, key=lambda t: -t[0]):
        del out[aa - 1:b]
    SRC.write_text("".join(out), encoding="utf-8", newline="")
    # 目标文件
    blocks.sort(key=lambda t: t[0])
    parts = []
    for aa, b, k in blocks:
        seg = "".join(src_lines[aa - 1:b])
        # 去尾随逗号
        seg = seg.rstrip()
        if seg.endswith(","):
            seg = seg[:-1]
        parts.append(seg)
    dest = ROOT / "static" / "js" / dest_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    host = "vue_methods.js" if OBJ == "vue_methods" else "vue_data.js"
    content = ("// 批 3 F2：自 %s 搬移的 %s 域（Object.assign 装配，\n"
               "// 加载顺序在宿主之后、renderer 之前）。\n"
               "Object.assign(%s, {\n" % (host, dest_rel, OBJ))
    content += ",\n\n".join(parts) + "\n});\n"
    dest.write_text(content, encoding="utf-8", newline="")
    print(f"moved {len(keys)} keys -> {dest} ({content.count(chr(10))} lines)")


def main():
    global OBJ, SRC
    if "--object" in sys.argv:
        i = sys.argv.index("--object")
        OBJ = sys.argv[i + 1]
        SRC = ROOT / "static" / "js" / ("vue_data.js" if OBJ == "vue_data" else "vue_methods.js")
        sys.argv = sys.argv[:i] + sys.argv[i + 2:]
    src = SRC.read_text(encoding="utf-8")
    if "--move" in sys.argv:
        i = sys.argv.index("--move")
        dest = sys.argv[i + 1]
        keys = sys.argv[i + 2:]
        move(dest, keys)
        return
    entries = top_level_entries(src)
    if "--grep" in sys.argv:
        pat = sys.argv[sys.argv.index("--grep") + 1]
        for key, a, b in entries:
            if re.search(pat, key, re.I):
                print(f"{key}  L{a}-{b}")
        print("matched:", sum(1 for key, a, b in entries if re.search(pat, key, re.I)), "/", len(entries))
    else:
        for key, a, b in entries:
            print(f"{key}  L{a}-{b}")
        print("total:", len(entries))


if __name__ == "__main__":
    main()
