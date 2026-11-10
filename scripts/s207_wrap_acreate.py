# -*- coding: utf-8 -*-
"""S207 一次性接线脚本：把裸 create 调用包进 acreate（瞬断退避重试）。
dry-run 默认；--apply 写盘（自动 .bak-s207 备份）。"""
import io
import re
import shutil
import sys

PATH = "server.py"
APPLY = "--apply" in sys.argv
OP = re.compile(r"^(\s*)(\w+) = await (\w+)\.chat\.completions\.create\($")

src = io.open(PATH, encoding="utf-8").read()
lines = src.splitlines(keepends=True)

# 函数归属（任意缩进的 def）
defs = [(ix, ln) for ix, ln in enumerate(lines) if re.match(r"^\s*(async\s+)?def\s+\w+", ln)]


def enclosing(i):
    best = ("?", 0)
    for di, dl in defs:
        if di < i:
            best = (re.search(r"def\s+(\w+)", dl).group(1), di)
        else:
            break
    return best


out = list(lines)
edits = []  # (open_idx, close_idx, indent, var, client, fn, has_settings)
for i, ln in enumerate(lines):
    m = OP.match(ln.rstrip("\n"))
    if not m:
        continue
    look = "".join(lines[max(0, i - 45):i])
    if "_lr_attempt" in look or "acreate(" in look:
        print(f"SKIP(已接线) L{i+1}")
        continue
    # 配对右括号
    depth = 0
    close = -1
    for j in range(i, len(lines)):
        depth += lines[j].count("(") - lines[j].count(")")
        if depth == 0:
            close = j
            break
    fn, fi = enclosing(i)
    def_line = lines[fi]
    has_settings = "settings" in def_line
    edits.append((i, close, m.group(1), m.group(2), m.group(3), fn, has_settings))

# 从后往前替换避免位移
for (i, close, ind, var, client, fn, has_settings) in sorted(edits, key=lambda x: -x[0]):
    att = "llm_retry_cfg(settings)[0]" if has_settings else "2"
    dly = "llm_retry_cfg(settings)[1]" if has_settings else "1.0"
    open_new = (f"{ind}{var} = await acreate(\n"
                f"{ind}    lambda: {client}.chat.completions.create(\n")
    close_new = (f"{ind}), attempts={att}, base_delay={dly}, "
                 f'label="s207-{fn}")\n')
    out[i] = open_new
    out[close] = close_new
    print(f"WRAP L{i+1}..L{close+1} {fn} settings={has_settings}")

if APPLY:
    shutil.copy(PATH, PATH + ".bak-s207")
    io.open(PATH, "w", encoding="utf-8", newline="").write("".join(out))
    import py_compile
    py_compile.compile(PATH, doraise=True)
    print("APPLIED + py_compile OK")
else:
    print("dry-run done")
