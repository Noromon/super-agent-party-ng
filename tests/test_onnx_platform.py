# -*- coding: utf-8 -*-
"""S82（C1/B10-1）：onnxruntime 平台拆分声明 + 流完成 backend_content 不再冻结。"""
import io
import os
import re
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_onnx_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def test_pyproject_platform_markers():
    txt = _read("pyproject.toml")
    assert re.search(r'onnxruntime-directml>=\d[^"\n]* ; sys_platform == .win32.', txt)
    assert re.search(r"onnxruntime>=\d[\d.]* ; sys_platform == 'darwin'", txt)
    assert re.search(r"onnxruntime-gpu>=\d[\d.]* ; sys_platform != 'darwin' and sys_platform != 'win32'", txt)
    assert re.search(r"onnxruntime>=\d[\d.]* ; sys_platform == 'linux' and platform_machine == 'aarch64'", txt)
    bare = re.search(r'^\s*"onnxruntime>=\d[^";]*",\s*$', txt, re.M)
    assert bare is None                                  # 不允许再存在无标记裸依赖


def test_lock_contains_platform_packages():
    lock = _read("uv.lock")
    assert 'name = "onnxruntime-directml"' in lock
    assert 'name = "onnxruntime-gpu"' in lock
    assert 'name = "onnxruntime"' in lock                # darwin/linux-aarch64 仍需 CPU 包


def test_stream_finished_no_backend_freeze():
    src = _read("static/js/methods/10_chat_stream.js")
    m = re.search(r"backend_content\.forEach\(item => \{[\s\S]{0,80}?Object\.freeze\(item\)", src)
    assert m is None                                     # B10-1：finally 浅冻结已删
    assert "Object.freeze(block)" in src                 # displayBlocks 冻结保留（纯展示）


def test_onnx_cpu_provider_runtime():
    ort = pytest.importorskip("onnxruntime")
    assert "CPUExecutionProvider" in ort.get_available_providers()


@pytest.mark.skipif(sys.platform != "win32", reason="win32 only")
def test_directml_provider_after_sync():
    ort = pytest.importorskip("onnxruntime")
    if "DmlExecutionProvider" not in ort.get_available_providers():
        pytest.skip("onnxruntime-directml 尚未同步进当前 venv（uv sync 后复验）")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
