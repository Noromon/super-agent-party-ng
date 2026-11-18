# -*- coding: utf-8 -*-
"""S233：工具轮数上限可调 + 破限开关（轮边界动态生效）。"""
import ast
import os
import pathlib
import sys
import tempfile

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s233_")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py import tool_cap  # noqa: E402

ROOT = _ROOT
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _restore_hot():
    saved = (tool_cap.unlimited, tool_cap.limit)
    yield
    tool_cap.unlimited, tool_cap.limit = saved


# ---------------- 热值语义 ----------------

def test_new_key_and_restore():
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 300}})
    assert tool_cap.effective_limit() == 300
    assert not tool_cap.unlimited


def test_legacy_top_level_key_compat():
    tool_cap.apply_setting({"max_tool_iterations": 50})
    assert tool_cap.effective_limit() == 50
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 20}, "max_tool_iterations": 50})
    assert tool_cap.effective_limit() == 20  # 新键优先


def test_defaults_and_clamp_and_garbage():
    tool_cap.apply_setting({})
    assert tool_cap.effective_limit() == 100
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 0}})
    assert tool_cap.effective_limit() == 1  # 下限 1
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 10 ** 9}})
    assert tool_cap.effective_limit() == 100000  # 钳制
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": "abc"}})
    assert tool_cap.effective_limit() == 100  # 垃圾值回落默认


def test_unlimited_flag():
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 100, "toolCapUnlimited": True}})
    assert tool_cap.unlimited
    assert tool_cap.effective_limit() > 10 ** 9
    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 100, "toolCapUnlimited": False}})
    assert not tool_cap.unlimited
    assert tool_cap.effective_limit() == 100


def _func_src(name):
    tree = ast.parse(SERVER_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return ast.get_source_segment(SERVER_SRC, node)
    raise AssertionError(f"function {name} not found in server.py")


def test_round_cap_endless_after_restore(monkeypatch):
    """破限跑通宵累计 350 轮 → 关破限恢复 100 → 下一轮边界 _drs_round_cap 判超限退出收尾。"""
    src = _func_src("_drs_round_cap")
    import logging
    ns = {"logging": logging}
    exec(compile(src, "<drs>", "exec"), ns)
    drs = ns["_drs_round_cap"]

    tool_cap.apply_setting({"systemSettings": {"toolCapUnlimited": True}})
    cap = tool_cap.effective_limit()
    assert drs(350, cap, False, [{"id": 1}], "test") is True  # 破限时继续

    tool_cap.apply_setting({"systemSettings": {"maxToolIterations": 100, "toolCapUnlimited": False}})
    cap = tool_cap.effective_limit()
    assert drs(351, cap, False, [{"id": 1}], "test") is True  # 纯工具轮交收尾提示路径
    assert drs(351, cap, False, [], "test") is False  # 无工具轮 → 结束循环


# ---------------- 服务端接线 ----------------

def test_dynamic_cap_wired():
    assert "from py import tool_cap as _tool_cap" in SERVER_SRC
    assert SERVER_SRC.count("_max_tool_iterations = _tool_cap.effective_limit()") == 1
    assert SERVER_SRC.count("_ns_max_iterations = _tool_cap.effective_limit()") == 1
    # 旧请求级快照清零
    assert 'int(settings.get("max_tool_iterations"' not in SERVER_SRC
    # 热同步与启动初始化
    assert "_tool_cap.apply_setting(current)" in SERVER_SRC
    assert "_tool_cap.apply_setting(await _gs.load_settings())" in SERVER_SRC


def test_defaults_ui_i18n_stamp():
    tpl = _read("config", "settings_template.json")
    assert '"maxToolIterations": 100' in tpl
    assert '"toolCapUnlimited": false' in tpl
    data = _read("static", "js", "data", "20_brain_settings.js")
    assert "maxToolIterations: 100" in data and "toolCapUnlimited: false" in data
    page = _read("static", "templates", "page_system.html")
    assert 'v-model="systemSettings.maxToolIterations"' in page
    assert 'v-model="systemSettings.toolCapUnlimited"' in page
    for loc in ("zh-CN", "en-US"):
        s = _read("static", "js", "locales", f"{loc}.js")
        for k in ("maxToolIterationsDesc", "maxToolIterationsHint",
                  "toolCapUnlimitedDesc", "toolCapUnlimitedHint"):
            assert k in s, (loc, k)
    assert "build=S246" in _read("static", "js", "renderer.js")
