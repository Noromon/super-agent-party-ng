# -*- coding: utf-8 -*-
"""工具契约审计：schema 参数 <-> 真实函数签名 <-> server 派发表，附只读冒烟矩阵。

用法: .venv\\Scripts\\python.exe py\\audit_tools.py
安全: 冒烟仅调用只读 local 工具，绝不触碰 shell/edit/kill/net/docker_sandbox。
"""
import asyncio
import inspect
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cli_tool  # noqa: E402  (server 运行环境把 py/ 加入 sys.path)

SMOKE_WS = os.environ.get("SAP_AUDIT_WS", r"E:\AI\sap-workspace")


def audit_entry(reg_key, entry, problems, warns):
    fn_name = entry["function"]["name"]
    params = entry["function"].get("parameters", {}) or {}
    props = params.get("properties", {}) or {}
    required = params.get("required", []) or []
    fn = getattr(cli_tool, fn_name, None)
    if fn is None:
        problems.append(f"[{reg_key}] 函数缺失: {fn_name}")
        return
    sig = inspect.signature(fn)
    ps = sig.parameters
    for p in required:
        if p not in props:
            problems.append(f"[{reg_key}] {fn_name}: required 参数 '{p}' 不在 properties")
    for p in props:
        if p not in ps:
            problems.append(f"[{reg_key}] {fn_name}: schema 参数 '{p}' 不在函数签名 {list(ps)}")
    for name, p in ps.items():
        if name in ("self", "kwargs", "args"):
            continue
        if p.default is inspect.Parameter.empty and name not in required:
            problems.append(f"[{reg_key}] {fn_name}: 必填参数 '{name}' 未列入 schema required")
        if p.default is not inspect.Parameter.empty and name not in props:
            warns.append(f"[{reg_key}] {fn_name}: 可选参数 '{name}' 未暴露给 schema")
    for name, spec in props.items():
        if not (spec or {}).get("description"):
            warns.append(f"[{reg_key}] {fn_name}: 参数 '{name}' 缺 description")
    if not entry["function"].get("description", "").strip():
        warns.append(f"[{reg_key}] {fn_name}: 函数缺 description")


def audit_dispatch(problems, warns):
    src = open(os.path.join(ROOT, "server.py"), encoding="utf-8").read()
    hooks = set()
    for m in re.finditer(r'_TOOL_HOOKS\s*=\s*\{', src):
        start = m.end() - 1
        depth = 0
        for j in range(start, len(src)):
            if src[j] == "{":
                depth += 1
            elif src[j] == "}":
                depth -= 1
                if depth == 0:
                    hooks |= set(re.findall(r'"([A-Za-z_0-9]+)"\s*:', src[start:j]))
                    break
    if not hooks:
        problems.append("[dispatch] 未解析到任何 _TOOL_HOOKS 条目")
        return set()
    schema_names = {e["function"]["name"] for e in cli_tool.TOOLS_REGISTRY.values()} | \
                   {e["function"]["name"] for e in cli_tool.LOCAL_TOOLS_REGISTRY.values()}
    for n in sorted(schema_names - hooks):
        problems.append(f"[dispatch] schema 有而派发表无: {n}")
    other_module_schemas = hooks - schema_names
    if other_module_schemas:
        warns.append(f"[dispatch] 派发表另有 {len(other_module_schemas)} 项来自其他模块注册（web_search 等），非本审计范围")
    return hooks


async def smoke(problems):
    os.environ["SAP_AUDIT_FLAG"] = "1"
    cases = [
        ("glob_files_tool_local", dict(pattern="**.py"), lambda r: "No files matched." not in r and "[Error]" not in r),
        ("glob_files_tool_local", dict(pattern="**", exclude="**/*.png"), lambda r: "[Error]" not in r and len(r) > 10),
        ("glob_files_tool_local", dict(pattern="**.json"), lambda r: "No files matched." not in r),
        ("search_files_tool_local", dict(pattern=r"def \w+\("), lambda r: "No matches found." not in r),
        ("search_files_tool_local", dict(pattern="-dash"), lambda r: "[Error]" not in r),
        ("search_files_tool_local", dict(pattern=r"\d+"), lambda r: isinstance(r, str)),
        ("list_files_tool_local", dict(path="."), lambda r: "[Error]" not in r),
        ("read_file_tool_local", dict(path=SMOKE_WS and "qwen_edit_config.json"), lambda r: isinstance(r, str)),
    ]
    for name, kw, ok in cases:
        fn = getattr(cli_tool, name)
        try:
            r = await fn(**kw)
        except Exception as e:
            problems.append(f"[smoke] {name}({kw}): 抛出 {e!r}")
            continue
        r = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)[:200]
        status = "OK" if ok(r) else "FAIL"
        if status == "FAIL":
            problems.append(f"[smoke] {name}({kw}): 结果异常 -> {r[:100]!r}")
        print(f"  [smoke] {status} {name}({', '.join(f'{k}={v!r}' for k, v in kw.items())})")


async def main():
    problems, warns = [], []
    for k, e in cli_tool.TOOLS_REGISTRY.items():
        audit_entry(f"docker:{k}", e, problems, warns)
    for k, e in cli_tool.LOCAL_TOOLS_REGISTRY.items():
        audit_entry(f"local:{k}", e, problems, warns)
    audit_dispatch(problems, warns)
    print("== 冒烟矩阵（只读, workspace=%s） ==" % SMOKE_WS)
    await smoke(problems)
    print("\n== 确定问题 (%d) ==" % len(problems))
    for p in problems:
        print("  !", p)
    print("== 提示 (%d) ==" % len(warns))
    for w in warns:
        print("  -", w)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
