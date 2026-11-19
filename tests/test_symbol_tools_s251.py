# S251：多模式搜索 patterns[] + symbol 完整定义块读取（大括号配平/Python 缩进）
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cli_tool as ct  # noqa: E402
import py.symbol_tools as st  # noqa: E402

JAVA = '''public class A {
    void filler(int m) {
        this.pushNow(m);  // call, must not be taken as def
    }

    private void pushNow(Message m) {
        if (m.ok()) {
            log("doNotify } { brace in string");
            /* block } comment */
            for (int i = 0; i < 3; i++) {
                run(i);
            }
        }
    }

    void after_marker() {
    }
}
'''


def test_java_brace_block():
    lines = JAVA.splitlines()
    res = st.find_symbol_block(lines, "pushNow")
    assert res.start is not None
    assert lines[res.start].strip().startswith("private void pushNow")
    assert lines[res.end].strip() == "}" and res.end < lines.index("    void after_marker() {")
    assert "brace-balanced" in res.how
    seg = "\n".join(lines[res.start:res.end + 1])
    assert "run(i);" in seg and "after_marker" not in seg


def test_py_indent_block_and_miss():
    src = ("def helper():\n    x = {1: 2}\n    return x\n\n"
           "def target_fn(v):\n    if v:\n        return {\n            'a': 1,\n        }\n    return None\n\n"
           "def nxt():\n    pass\n")
    lines = src.splitlines()
    res = st.find_symbol_block(lines, "target_fn", is_py=True)
    assert lines[res.start].startswith("def target_fn")
    assert lines[res.end].strip() == "return None"
    assert "python-indent" in res.how
    miss = st.find_symbol_block(lines, "ghost_fn")
    assert miss.start is None and miss.candidates == []
    ref_only = st.find_symbol_block(["x = helper() + 1", "helper();"], "helper")
    assert ref_only.start is not None or ref_only.candidates  # 引用点必须至少给出


def test_tool_symbol_read(tmp_path, monkeypatch):
    (tmp_path / "A.java").write_text(JAVA, encoding="utf-8")

    async def _cwd():
        return str(tmp_path)
    monkeypatch.setattr(ct, "_get_current_cwd", _cwd)
    out = asyncio.run(ct.read_file_range_tool_local("A.java", symbol="pushNow"))
    assert out.startswith("[symbol] pushNow")
    assert "run(i);" in out and "after_marker" not in out
    out2 = asyncio.run(ct.read_file_range_tool_local("A.java", symbol="Message"))
    assert "未找到定义行" in out2 and "L6" in out2  # 仅引用点 → 候选列表
    out3 = asyncio.run(ct.read_file_range_tool_local("A.java", start_line=2, end_line=3))
    assert "filler" in out3 and not out3.startswith("[symbol]")  # 旧行为不变


def test_tool_patterns_search(tmp_path, monkeypatch):
    (tmp_path / "a.java").write_text("class A {\n  void pushNow(){}\n  void markLast(){}\n}\n", encoding="utf-8")
    (tmp_path / "b.java").write_text("class B {\n  void pushNow(){}\n}\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("markLast referenced here\n", encoding="utf-8")

    async def _cwd():
        return str(tmp_path)
    monkeypatch.setattr(ct, "_get_current_cwd", _cwd)
    from py import tool_output_store as tos
    monkeypatch.setattr(tos, "find_ripgrep", lambda: None)

    out = asyncio.run(ct.search_files_tool_local(patterns=["pushNow", "markLast"]))
    assert "=== [1/2] pattern: pushNow ===" in out and "=== [2/2] pattern: markLast ===" in out
    g1, g2 = out.split("=== [2/2]")[0], out.split("=== [2/2]")[1]
    assert "b.java" in g1 and "c.txt" not in g1
    assert "c.txt" in g2 and "b.java" not in g2

    solo = asyncio.run(ct.search_files_tool_local("pushNow"))
    assert "=== [" not in solo and solo.startswith("a.java:")  # 单模式旧格式
    empty = asyncio.run(ct.search_files_tool_local())
    assert empty.startswith("[Error]")
    many = asyncio.run(ct.search_files_tool_local(patterns=[f"p{i}" for i in range(12)]))
    assert "忽略 2 个" in many


def test_schemas_updated():
    rs = ct.LOCAL_TOOLS_REGISTRY["read_file_range_local"]["function"]
    assert "symbol" in rs["parameters"]["properties"]
    assert rs["parameters"]["required"] == ["path"]
    assert "definition block" in rs["description"]
    ss = ct.LOCAL_TOOLS_REGISTRY["search_files_local"]["function"]
    assert "patterns" in ss["parameters"]["properties"]
    assert ss["parameters"]["required"] == []
