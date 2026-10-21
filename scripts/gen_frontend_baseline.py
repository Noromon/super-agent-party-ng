# -*- coding: utf-8 -*-
"""生成前端结构基线 tests/data/frontend_keys_baseline.json（批 3 F0）。

看护 vue_methods/vue_data 的顶层键名集合（拆分=键名零增删的保险）、
index/chat 的 script 加载顺序、console.log 计数与 styles.css 行数。
F2/F3 迁移过程中键名/页面名不应变化；确有方法增删时评审后重跑本脚本
更新基线。

用法：.venv\\Scripts\\python.exe scripts/gen_frontend_baseline.py [--check]
  --check: 与现有基线比对并报告差异，不写文件。
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "data" / "frontend_keys_baseline.json"


def _scan_object(src: str, i: int, depth: int):
    """从对象字面量 '{' 之后按深度扫描，收集深度 1 的键名。
    跳过字符串/模板字面量/注释/正则字面量。"""
    keys = []
    prev_sig = ""        # 上一个可见字符（正则字面量启发用）
    n = len(src)
    ident = ""
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
        if c == "/" and prev_sig in "(,=:[!&|?{};\n" or (c == "/" and not prev_sig):
            # 正则字面量启发：/ 出现在期望操作数的位置
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
            prev_sig = c
            i += 1
            continue
        if c in "}])":
            depth -= 1
            prev_sig = c
            i += 1
            continue
        if depth == 1 and (c.isalpha() or c in "_$"):
            j = i
            while j < n and (src[j].isalnum() or src[j] in "_$"):
                j += 1
            ident = src[i:j]
            # 键判定：ident 后（越过空白/注释）是 ( 或 : 且本层尚未定键
            k = j
            while k < n and src[k] in " \t\r\n":
                k += 1
            if k < n and src[k] in "(:":
                if not ident.startswith("__"):
                    keys.append(ident)
                # 跳到键值：'(' 即方法参数表，直接计入一层深度并跳过该字符
                prev_sig = src[k]
                i = k + 1
                if src[k] == "(":
                    depth += 1
                continue
            prev_sig = ident[-1]
            i = j
            continue
        if not c.isspace():
            prev_sig = c
        i += 1
    return keys


def scan_top_level_keys(src: str, open_after: str):
    m = re.search(open_after, src)
    if not m:
        raise ValueError("anchor not found: %s" % open_after)
    return _scan_object(src, m.end(), 1)


def scan_assign_keys(src: str, obj_name: str = "vue_methods"):
    """收集 Object.assign(<obj>, { ... }) 的顶层键（F2 分片文件）。"""
    keys = []
    pat = r"Object\.assign\(\s*" + obj_name + r"\s*,\s*\{"
    for m in re.finditer(pat, src):
        keys += _scan_object(src, m.end(), 1)
    return keys


def collect():
    idx = (ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    chat = (ROOT / "static" / "chat.html").read_text(encoding="utf-8-sig")
    src_re = re.compile(r"<script[^>]*\bsrc=\"([^\"]+)\"")

    vm = (ROOT / "static" / "js" / "vue_methods.js").read_text(encoding="utf-8-sig")
    vd = (ROOT / "static" / "js" / "vue_data.js").read_text(encoding="utf-8-sig")

    methods = scan_top_level_keys(vm, r"(?:let|const|var)\s+vue_methods\s*=\s*\{")
    data = scan_top_level_keys(vd, r"(?:let|const|var)\s+vue_data\s*=\s*\{")
    # F2 分片：js/methods/*.js 按文件名序装配进同一键集合
    methods_dir = ROOT / "static" / "js" / "methods"
    if methods_dir.exists():
        for f in sorted(methods_dir.glob("*.js")):
            methods += scan_assign_keys(f.read_text(encoding="utf-8-sig"))
    data_dir = ROOT / "static" / "js" / "data"
    if data_dir.exists():
        for f in sorted(data_dir.glob("*.js")):
            data += scan_assign_keys(f.read_text(encoding="utf-8-sig"), "vue_data")

    logs = {}
    total_logs = 0
    for f in sorted((ROOT / "static" / "js").rglob("*.js")):
        c = len(re.findall(r"\bconsole\.log\s*\(", f.read_text(encoding="utf-8-sig")))
        if c:
            logs[str(f.relative_to(ROOT / "static" / "js")).replace("\\", "/")] = c
        total_logs += c

    css_lines = len((ROOT / "static" / "css" / "styles.css").read_text(encoding="utf-8-sig").splitlines())

    dup = [k for k in set(methods) if methods.count(k) > 1]
    return {
        "script_order": {
            "index.html": src_re.findall(idx),
            "chat.html": src_re.findall(chat),
        },
        "vue_methods_keys": sorted(set(methods)),
        "vue_data_keys": sorted(set(data)),
        "_dup_methods": sorted(dup),
        "console_log_counts": logs,
        "console_log_total": total_logs,
        "styles_css_lines": css_lines,
    }


def main():
    check = "--check" in sys.argv
    cur = collect()
    if check and BASELINE.exists():
        old = json.loads(BASELINE.read_text(encoding="utf-8"))
        for k in ("script_order", "vue_methods_keys", "vue_data_keys"):
            a, b = old.get(k), cur[k]
            if a != b:
                if isinstance(a, dict):
                    for page in b:
                        if a.get(page) != b[page]:
                            print(f"DIFF {k}.{page}:\n  old={a.get(page)}\n  new={b[page]}")
                else:
                    print(f"DIFF {k}: -{sorted(set(a) - set(b))} +{sorted(set(b) - set(a))}")
        if old.get("console_log_total") != cur["console_log_total"]:
            print("console total:", old.get("console_log_total"), "->", cur["console_log_total"])
        if old.get("styles_css_lines") != cur["styles_css_lines"]:
            print("css lines:", old.get("styles_css_lines"), "->", cur["styles_css_lines"])
        print("check done")
        return
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
    print("baseline written:", BASELINE)
    print("methods:", len(cur["vue_methods_keys"]), "data:", len(cur["vue_data_keys"]),
          "dups:", cur["_dup_methods"][:10],
          "console total:", cur["console_log_total"], "css:", cur["styles_css_lines"])
    print("index scripts:", len(cur["script_order"]["index.html"]),
          "chat scripts:", len(cur["script_order"]["chat.html"]))


if __name__ == "__main__":
    main()
