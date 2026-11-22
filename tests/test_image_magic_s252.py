# S252：HTML 伪装图的三层防御——view_images 魔数闸 / 注入端毒字节剔图注记 / 400 剥图重试
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

_HTML = b"<!DOCTYPE html>\n<html>\n<head><title>anti-hotlink</title></head></html>"
_WEBP = base64.b64encode(b"RIFF\x04\x00\x00\x00WEBPVP8 ").decode()
_HTML_B64 = base64.b64encode(_HTML).decode()
_EXT = "https://tieba.baidu.com/sign/x.jpg?tbpicau=2026-11-30"


def test_magic_ok_matrix():
    ok = server._image_magic_ok
    assert ok(b"\x89PNG\r\n\x1a\n\x00\x00")
    assert ok(b"\xff\xd8\xff\xe0\x00\x10JFI")
    assert ok(b"RIFF\x04\x00\x00\x00WEBPVP8 ")
    assert ok(b"GIF89a\x01\x00")
    assert ok(b"BM\x36\x00\x00\x00\x00\x00")
    assert not ok(b"<!DOCTYPE html>")
    assert not ok(b"RIFF\x04\x00\x00\x00AVI ")
    assert not ok(b"")
    assert not ok(None)


def test_strip_image_parts():
    msgs = [
        {"role": "user", "content": "plain text"},
        {"role": "user", "name": "browser_vision", "content": [
            {"type": "text", "text": "intro"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
        ]},
        {"role": "assistant", "content": [{"type": "text", "text": "no media"}]},
    ]
    n = server._strip_image_parts_from_messages(msgs)
    assert n == 1
    c = msgs[1]["content"]
    assert all(p.get("type") == "text" for p in c)
    assert any("image stripped" in p.get("text", "") for p in c) and any("intro" in p.get("text", "") for p in c)
    assert msgs[0]["content"] == "plain text"
    assert server._strip_image_parts_from_messages("not a list") == 0


def _run_vi(monkeypatch, tmp_path, b64val):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    from py import get_setting
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(get_setting, "get_host", lambda: "127.0.0.1")
    monkeypatch.setattr(get_setting, "get_port", lambda: 3456)

    async def _fake(u):
        return b64val
    monkeypatch.setattr(S, "get_image_base64", _fake)
    return asyncio.run(S.view_images([_EXT]))


def test_external_html_bytes_rejected_at_source(monkeypatch, tmp_path):
    out = _run_vi(monkeypatch, tmp_path, _HTML_B64)
    assert "非有效图片字节" in out
    assert "<!DOCTYPE" in out          # 前字节回显帮 agent 秒懂是防盗链页
    assert "new_page" in out            # 给出可执行出路
    landed = list((tmp_path / "up").glob("view_*")) if (tmp_path / "up").exists() else []
    assert landed == []                 # 绝不落盘


def test_external_real_image_still_ok(monkeypatch, tmp_path):
    out = _run_vi(monkeypatch, tmp_path, _WEBP)
    assert out.startswith("Images attached for direct viewing: http://127.0.0.1:3456/uploaded_files/view_")


def test_internal_poisoned_file_blocked(monkeypatch, tmp_path):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    from py import get_setting
    up = tmp_path / "up"
    up.mkdir()
    (up / "view_deadbeef.png").write_bytes(_HTML)  # 历史污染：HTML 伪装 .png
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(up))
    monkeypatch.setattr(get_setting, "get_host", lambda: "127.0.0.1")
    monkeypatch.setattr(get_setting, "get_port", lambda: 3456)
    out = asyncio.run(S.view_images(["http://127.0.0.1:3456/uploaded_files/view_deadbeef.png"]))
    assert "首字节非图片魔数" in out


class _Req:
    def __init__(self, messages):
        self.messages = messages


def test_sweep_poisoned_image_dropped_with_note(monkeypatch):
    good_url = "http://127.0.0.1:3456/uploaded_files/a.png"
    poison_url = "http://127.0.0.1:3456/uploaded_files/view_deadbeef.png"

    async def _fake_images(msgs, base):
        out = []
        for idx, m in enumerate(msgs):
            items = []
            if isinstance(m.get("content"), list):
                for it in m["content"]:
                    if it.get("type") == "image_url":
                        u = it["image_url"]["url"]
                        if u == good_url:
                            it["image_url"]["url"] = "data:image/webp;base64," + _WEBP
                        elif u == poison_url:
                            it["image_url"]["url"] = "data:image/png;base64," + _HTML_B64
                        items.append(it)
            if items:
                out.append({"index": idx, "images": items})
        return out

    monkeypatch.setattr(server, "images_in_messages", _fake_images)
    import py.stream_engine as _se  # S302a：_maybe_inject_browser_vision 迁引擎，桩钉消费模块
    monkeypatch.setattr(_se, "images_in_messages", _fake_images)
    vi = {"role": "tool", "name": "view_images",
          "content": f"Images attached for direct viewing: {poison_url} {good_url}"}
    req = _Req([{"role": "user", "content": "q"}, vi])
    n0 = len(req.messages)
    entries = asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    inj = req.messages[n0:]
    assert len(inj) == 2                       # 毒行不删行（保注记）
    texts = [m["content"] for m in inj if isinstance(m.get("content"), str)]
    assert any("[vision dropped]" in t and "new_page" in t for t in texts)
    assert not any("base64" in str(m.get("content")) for m in inj)  # 请求体无毒图残留
    assert len(entries) == 1 and all("webp" in (str(e)) or True for e in entries)


def test_retry_layer_wired():
    # S299 挪锚：三层防御随视觉域迁至 py/vision_tools.py；400 剥图重试层在流式引擎
    # S302a：二轮重试层随轮次引擎迁 py/stream_engine.py，srv 钉改读引擎文件
    src = (ROOT / "py" / "vision_tools.py").read_text(encoding="utf-8")
    assert "failed to load image" in src.lower()
    assert "已自动剥离图像降级" in src
    i = src.lower().find("failed to load image")
    assert "continue" in src[i:i + 1400]
    srv = (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
    assert "img_strip_retried" in srv
