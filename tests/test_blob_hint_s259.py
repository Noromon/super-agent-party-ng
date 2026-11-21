# build=S266
# S259：blob 图反馈修复——view_images 对 blob:/javascript: 给专错指引（曾落本地路径分支
# 报"文件不存在0字节"误导），file:// 正确解析；take_snapshot 非 http 源不吐 URL 本体。
import asyncio
import base64
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import server  # noqa: E402
import py.cdp_tool as cdp  # noqa: E402

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")

_WEBP_B64 = base64.b64encode(b"RIFF\x04\x00\x00\x00WEBPVP8 ").decode()


def test_view_images_blob_gives_pixel_path_hint():
    out = asyncio.run(server.view_images(["blob:https://tieba.baidu.com/8a3d-uuid"]))
    assert "页面内存" in out and "take_screenshot" in out
    assert "文件不存在" not in out  # 不再伪装成本地文件问题


def test_view_images_javascript_scheme_prefetch():
    out = asyncio.run(server.view_images(["javascript:void(0)"]))
    assert "非资源协议" in out and "take_screenshot" in out


def test_view_images_file_url_goes_local_channel(tmp_path, monkeypatch):
    img = tmp_path / "shot.webp"
    img.write_bytes(base64.b64decode(_WEBP_B64) + b"\x00" * 8)
    monkeypatch.setattr(server, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    out = asyncio.run(server.view_images([img.as_uri()]))
    assert "view_" in out  # 已登记为内部 URL
    assert "文件不存在" not in out and "非图片格式" not in out
    landed = list((tmp_path / "up").glob("view_*.webp"))
    assert landed and landed[0].read_bytes()[:4] == b"RIFF"


def test_snapshot_nonhttp_no_url_body():
    i = JS.index("S259: blob:/data:")
    seg = JS[i:i + 400]
    assert "已渲染但无外部URL" in seg and "iurl = ''" in seg


def test_schema_documents_blob_dead_end():
    ts = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "take_snapshot")
    d = ts["function"]["description"]
    assert "blob:" in d and "do NOT hand blob" in d
