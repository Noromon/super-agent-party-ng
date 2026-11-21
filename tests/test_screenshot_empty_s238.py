# -*- coding: utf-8 -*-
"""S238：截图 0 字节→上游 400 修复——base64 跨桥/拒空/注入防御（静态断言）。"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


WV = _read("static", "js", "methods", "80_webview_agent.js")
MAIN = _read("main.js")
LF = _read("py", "load_files.py")


def test_js_screenshot_base64_and_empty_guard():
    assert WV.count('return "Screenshot Error: empty"') == 2  # 主管线+fallback 双校验
    assert "saveScreenshotDirect(b64)" in WV
    assert "btoa(bin)" in WV                                   # 主链 base64 编码
    assert "toString('base64')" in WV                          # fallback Buffer→base64
    # 不再把 typed array 直接递过 contextBridge
    assert "saveScreenshotDirect(buffer)" not in WV
    assert "saveScreenshotDirect(new Uint8Array" not in WV


def test_mainjs_decodes_and_rejects_empty():
    assert "Buffer.from(buffer, 'base64')" in MAIN
    assert "empty screenshot payload" in MAIN                  # 空=抛错，不给假 URL
    assert "fs.writeFileSync(filePath, buf)" in MAIN
    assert "fs.writeFileSync(filePath, Buffer.from(buffer))" not in MAIN


def test_loadfiles_empty_internal_artifact_rejected():
    assert "The internal file is empty (0 bytes)" in LF
    assert "except RuntimeError:" in LF                        # 空文件错不被宽获重包装
    i = LF.index("def handle_url")
    seg = LF[i:i + 2600]
    assert "data = await response.read()" in seg
    assert "if not data:" in seg


def test_stamp_s238():
    assert "build=S272" in _read("static", "js", "renderer.js")
