# -*- coding: utf-8 -*-
"""S235：进程热度取证 + 浏览器动作对账线 + 截图编解码移出主线程（源码断言）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


MAIN = _read("main.js")
CDP = _read("py", "cdp_tool.py")
WV = _read("static", "js", "methods", "80_webview_agent.js")


def test_mainjs_proc_heat():
    assert "app.getAppMetrics({ captureValue: 'cpu' })" in MAIN
    assert "[ProcHeat]" in MAIN
    assert "getOSProcessId" in MAIN          # pid→标签 URL 关联
    assert "15000" in MAIN                   # 同 pid 节流 15s
    assert "pct <= 75" in MAIN               # 单核 75% 阈值
    assert "evidenceAppend('[ProcHeat]" in MAIN


def test_cdp_wvact_accounting_line():
    assert "WVACT_SLOW_MS = 2000" in CDP
    assert "[WvAct]" in CDP
    assert "LOG_DIR" in CDP.splitlines()[11] or "from py.get_setting import UPLOAD_FILES_DIR, LOG_DIR" in CDP
    assert "out = await _call_vue_method_impl(method_name, args_list, timeout)" in CDP
    assert "async def _call_vue_method_impl(" in CDP
    assert 'frontend-evidence.log' in CDP
    # 公开入口仍是 wrapper（外部 import 不受改名影响）
    assert "async def call_vue_method(" in CDP


def test_screenshot_pipeline_off_main_thread():
    assert "createImageBitmap(pngBlob" in WV
    assert "OffscreenCanvas" in WV
    assert "convertToBlob" in WV
    # 异步主管线必须排在同步兜底之前
    assert WV.index("createImageBitmap") < WV.index("S235-fallback")
    # 兜底保留旧三连（最终保底可用）
    fb = WV[WV.index("S235-fallback"):WV.index("S235-fallback") + 700]
    assert "toJPEG(70)" in fb
    # 同步 resize/toJPEG 不得再出现在主管线（只允许在 fallback 段）
    main_pipe = WV[WV.index("captureWebviewScreenshot"):WV.index("S235-fallback")]
    assert "target.resize(" not in main_pipe
    assert ".toJPEG(" not in main_pipe


def test_stamp_s235():
    assert "build=S256" in _read("static", "js", "renderer.js")
