# build=S255
# S255：schema↔dispatch 一致性防线——S253 把 scroll_and_find/network_watch 注册进 schema
# 却漏了 server.py 两张 _TOOL_HOOKS 映射，模型看得见却一调就 [Unknown Tool]（幽灵工具），
# 整套测试却全绿。本测试静态解析 server.py 的 _TOOL_HOOKS 块，断言每个 cdp schema 名
# 都真实注册（主循环 + 审批执行两张表都要有）。
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

SRC = (ROOT / "server.py").read_text(encoding="utf-8").replace("\r\n", "\n")

# 两处 _TOOL_HOOKS 注册表：_build_tool_hooks() 与 execute_approved_tool()。
# （L510 还有模块级空占位 `_TOOL_HOOKS = {}`，非注册表，按含 cdp 注册过滤掉）
_ALL_BLOCKS = re.findall(r"_TOOL_HOOKS\s*=\s*\{(.*?)\n    \}", SRC, re.S)
_BLOCKS = [b for b in _ALL_BLOCKS if '"take_snapshot"' in b]


def _keys(block):
    return set(re.findall(r"[\x22\x27]([A-Za-z_][A-Za-z0-9_]*)[\x22\x27]\s*:", block))


def test_two_hooks_tables_found():
    assert len(_BLOCKS) == 2, f"应恰好解析到 2 张 _TOOL_HOOKS 表，实际 {len(_BLOCKS)}（server.py 结构变了要同步本测试）"


def test_all_cdp_schema_tools_are_dispatchable():
    names = [t["function"]["name"] for t in cdp.all_cdp_tools]
    assert len(names) >= 20
    for i, block in enumerate(_BLOCKS):
        keys = _keys(block)
        missing = [n for n in names if n not in keys]
        assert not missing, (
            f"_TOOL_HOOKS 表#{i}（{'主循环' if i == 0 else '审批路径'}）漏注册: {missing} —— "
            "schema 有而 dispatch 无 = 幽灵工具，模型一调就 [Unknown Tool]")


def test_s253_ghost_tools_now_registered():
    for i, block in enumerate(_BLOCKS):
        keys = _keys(block)
        assert {"scroll_and_find", "network_watch"} <= keys, f"表#{i} 仍缺 S253 工具"


def test_hooks_imports_match_mapping():
    # 映射值引用的函数名必须在同文件有对应 import/定义（防"注册了名字但没 import"）
    for i, block in enumerate(_BLOCKS):
        for m in re.finditer(r"[\x22\x27]([A-Za-z_][A-Za-z0-9_]*)[\x22\x27]\s*:\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,}\n]", block):
            key, val = m.group(1), m.group(2)
            if val in ("_fb",):  # 工厂包装另算
                continue
            assert re.search(r"\b" + re.escape(val) + r"\b", SRC), (
                f"表#{i} 键 {key} 引用 {val} 但 server.py 无此符号（import 漏了？）")
