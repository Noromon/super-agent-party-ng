# S245：view_images 外链落地化 + 注入失败不留病
#  ① view_images 外链预读后落盘 uploaded_files 返回内部 URL（不再透传远程 url）
#  ② _maybe_inject_browser_vision：images_in_messages 异常整段回滚；
#     成功后「http 残留/空 base64」注入行整行剔除并重排 index
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

_WEBP = base64.b64encode(b"RIFF\x04\x00\x00\x00WEBPVP8 ").decode()
_EXT_URL = "https://tieba-ares.cdn.bcebos.com/mis/2025-8/1756441589187/ae8536f7610f.webp"
_INT = "http://127.0.0.1:3456/uploaded_files/shot.jpg"


def _vi_tool(*urls):
    return {"role": "tool", "name": "view_images",
            "content": f"Images attached for direct viewing: {' '.join(urls)}"}


class _Req:
    def __init__(self, messages):
        self.messages = messages


def _no_http_images(msgs):
    for m in msgs:
        c = m.get("content")
        if isinstance(c, list):
            for it in c:
                if isinstance(it, dict) and it.get("type") in ("image_url", "video_url"):
                    if (it.get(it["type"]) or {}).get("url", "").startswith("http"):
                        return False
    return True


# ---------------- ① 外链落地化 ----------------

def test_view_images_external_url_lands_internally(monkeypatch, tmp_path):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    from py import get_setting
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(get_setting, "get_host", lambda: "127.0.0.1")
    monkeypatch.setattr(get_setting, "get_port", lambda: 3456)

    async def _fake_b64(u):
        return _WEBP
    monkeypatch.setattr(S, "get_image_base64", _fake_b64)

    out = asyncio.run(server.view_images([_EXT_URL]))
    assert out.startswith("Images attached for direct viewing: http://127.0.0.1:3456/uploaded_files/view_")
    assert _EXT_URL not in out  # 外链不再透传
    fname = out.split("/uploaded_files/")[1].split()[0]
    assert (tmp_path / "up" / fname).stat().st_size > 0

    # 幂等：同字节二次调用命中内容寻址，不产生第二个文件
    out2 = asyncio.run(server.view_images([_EXT_URL]))
    assert out2.split("/uploaded_files/")[1].split()[0] == fname


def test_view_images_external_download_failure_reported(monkeypatch, tmp_path):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(tmp_path / "up"))

    async def _fail(u):
        return ""
    monkeypatch.setattr(S, "get_image_base64", _fail)
    out = asyncio.run(server.view_images([_EXT_URL]))
    assert out.startswith("错误") and "读取失败" in out


# ---------------- ② 注入事务化 ----------------

def test_inject_rollback_on_conversion_exception(monkeypatch):
    async def _boom(msgs, base):
        raise RuntimeError("cdn down")
    monkeypatch.setattr(server, "images_in_messages", _boom)
    import py.stream_engine as _se  # S302a：_maybe_inject_browser_vision 迁引擎，桩钉消费模块
    monkeypatch.setattr(_se, "images_in_messages", _boom)
    req = _Req([{"role": "user", "content": "q"}, {"role": "assistant", "content": "", "tool_calls": [{}]},
                _vi_tool(_INT)])
    n0 = len(req.messages)
    out = asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    assert len(req.messages) == n0  # 整段回滚，不带病
    assert out == []
    assert _no_http_images(req.messages)


def test_inject_second_line_sweeps_http_and_empty_residue(monkeypatch):
    good = _INT
    bad_http = "http://127.0.0.1:3456/uploaded_files/gone.png"

    async def _partial(msgs, base):
        out = []
        for idx, m in enumerate(msgs):
            items = []
            if isinstance(m.get("content"), list):
                for it in m["content"]:
                    if it.get("type") == "image_url":
                        u = it["image_url"]["url"]
                        if u == good:  # 只有一张转换成功（S252: 需真图像魔数，否则被毒字节判定剔除）
                            it["image_url"]["url"] = "data:image/webp;base64," + _WEBP
                        items.append(it)
            if items:
                out.append({"index": idx, "images": items})
        return out

    monkeypatch.setattr(server, "images_in_messages", _partial)
    import py.stream_engine as _se  # S302a：_maybe_inject_browser_vision 迁引擎，桩钉消费模块
    monkeypatch.setattr(_se, "images_in_messages", _partial)
    req = _Req([{"role": "user", "content": "q"}, _vi_tool(bad_http, good)])
    n0 = len(req.messages)
    out = asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    inj = req.messages[n0:]
    assert len(inj) == 1  # 坏行整行剔除
    assert all(isinstance(m["content"], str) for m in inj)  # 已剥离为纯文本
    assert len(out) == 1 and out[0]["index"] == n0  # entry 剔除+重排
    assert _no_http_images(req.messages)
