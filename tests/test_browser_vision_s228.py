# S228：AI 浏览器视觉增强 A+C+D
#  A：take_screenshot 画面直注主模型（_collect_new_browser_screenshots / _maybe_inject_browser_vision）
#  C：captureWebviewScreenshot 元素裁剪（scrollIntoView+crop，无 webviewClick）
#  D：getWebviewSnapshot 暴露内容图片（赋 uid/alt/尺寸/loaded/offscreen，上限 60，跳小图）
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import server  # noqa: E402  (重模块，测试内导入为先例；router_decoupling)
import py.cdp_tool as cdp  # noqa: E402

_URL = "http://127.0.0.1:3456/uploaded_files/shot1.jpg"
_URL2 = "http://127.0.0.1:3456/uploaded_files/shot2.jpg"


def _read(*parts) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


# ---------------- A: _collect_new_browser_screenshots ----------------

def _ts_tool(url=_URL, name="take_screenshot"):
    return {"role": "tool", "name": name, "content": f"Screenshot saved to {url}"}


def test_collect_fresh_turn_single():
    msgs = [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{}]},
        _ts_tool(),
    ]
    assert server._collect_new_browser_screenshots(msgs) == [_URL]


def test_collect_history_not_reinjected():
    # 历史轮截过图（在上一条真实 user 之前），新一轮不应重复注入
    msgs = [
        {"role": "user", "content": "q1"},
        _ts_tool(_URL),
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": "q2"},  # 本轮起点
    ]
    assert server._collect_new_browser_screenshots(msgs) == []


def test_collect_intra_turn_multi_round_dedup():
    # 同轮第一轮已注入并留 marker -> 第二轮只应返回 marker 之后的新图
    msgs = [
        {"role": "user", "content": "q"},
        _ts_tool(_URL),
        {"role": "user", "name": "browser_vision", "content": "[Browser screenshot]"},
        {"role": "assistant", "content": "", "tool_calls": [{}]},
        _ts_tool(_URL2),
    ]
    assert server._collect_new_browser_screenshots(msgs) == [_URL2]


def test_collect_ignores_other_tools_and_failures():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "tool", "name": "get_image_content", "content": "see /uploaded_files/x.png"},  # 非本族工具
        {"role": "tool", "name": "take_screenshot", "content": "Failed to capture screenshot: boom"},  # 无 URL
    ]
    assert server._collect_new_browser_screenshots(msgs) == []


# ---------------- A: _maybe_inject_browser_vision ----------------

def _install_fake_images_in_messages(monkeypatch):
    calls = {"n": 0}

    async def _fake(msgs, base):
        calls["n"] += 1
        out = []
        for idx, m in enumerate(msgs):
            items = []
            if isinstance(m.get("content"), list):
                for it in m["content"]:
                    if it.get("type") == "image_url":
                        it["image_url"]["url"] = "data:image/jpeg;base64,AAA"
                        it["image_url"]["hash"] = "h" + str(idx)
                        items.append(it)
            if items:
                out.append({"index": idx, "images": items})
        return out

    monkeypatch.setattr(server, "images_in_messages", _fake)
    return calls


class _Req:
    def __init__(self, messages):
        self.messages = messages


def test_inject_appends_and_strips_and_merges(monkeypatch):
    _install_fake_images_in_messages(monkeypatch)
    # 历史里有一条真实用户图（list content）须保持不被全局剥离；prior images 须并入返回
    hist_img = {"role": "user", "content": [
        {"type": "text", "text": "here is my pic"},
        {"type": "image_url", "image_url": {"url": "http://x/up/old.png"}},
    ]}
    prior_images = [{"index": 1, "images": [{"image_url": {"url": "data:...,OLD", "hash": "old"}}]}]
    req = _Req([
        hist_img,
        {"role": "user", "content": "look at the page"},
        {"role": "assistant", "content": "", "tool_calls": [{}]},
        _ts_tool(),
    ])
    n_before = len(req.messages)
    out = asyncio.run(server._maybe_inject_browser_vision(req, {}, prior_images, "http://127.0.0.1:3456/"))

    # 注入了一条 browser_vision 临时消息
    assert len(req.messages) == n_before + 1
    inj = req.messages[-1]
    assert inj["role"] == "user" and inj["name"] == "browser_vision"
    # 注入消息收敛为纯文本（剥离图像，避免落盘/重复发送），且 URL 已转 base64
    assert isinstance(inj["content"], str)
    # 历史用户图保持 list 结构（回归安全：不全局剥离历史图）
    assert isinstance(req.messages[0]["content"], list)
    # 返回 images = 旧 + 新；新条目 index 已平移到全局位置
    assert len(out) == len(prior_images) + 1
    assert out[0] is prior_images[0]
    assert out[-1]["index"] == n_before  # inj0 == 注入前长度


def test_inject_idempotent_after_marker(monkeypatch):
    _install_fake_images_in_messages(monkeypatch)
    req = _Req([
        {"role": "user", "content": "q"},
        {"role": "assistant", "content": "", "tool_calls": [{}]},
        _ts_tool(),
    ])
    asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    n_after_first = len(req.messages)
    # 第二次（同轮，marker 已在末尾）应无新图 -> 不再追加、原样返回
    req.messages.append({"role": "assistant", "content": "ok"})
    out2 = asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    assert len(req.messages) == n_after_first + 1  # 仅手动 append 的那条
    assert out2 == []


def test_inject_no_screenshots_noop(monkeypatch):
    calls = _install_fake_images_in_messages(monkeypatch)
    req = _Req([{"role": "user", "content": "q"}])
    out = asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    assert out == []
    assert calls["n"] == 0  # 无图不触发 images_in_messages


# ---------------- A: cdp take_screenshot 输出含可解析 URL + server 接线 ----------------

def test_take_screenshot_returns_url_format(monkeypatch):
    async def _vue(method, args=None, timeout=None):
        assert method == "captureWebviewScreenshot"
        return _URL

    monkeypatch.setattr(cdp, "call_vue_method", _vue)
    out = asyncio.run(cdp.take_screenshot())
    assert out == f"Screenshot saved to {_URL}"
    import re as _re
    assert _re.search(r"https?://\S*uploaded_files/[^\s\"']+", out)


def test_server_wires_injection_both_paths():
    src = _read("server.py")
    assert "async def _maybe_inject_browser_vision(" in src
    assert src.count("images = await _maybe_inject_browser_vision(request, settings, images, fastapi_base_url)") == 2


def test_screenshot_schema_mentions_element_crop():
    fn = next(t["function"] for t in cdp.all_cdp_tools if t.get("function", {}).get("name") == "take_screenshot")
    uid_desc = fn["parameters"]["properties"]["uid"]["description"].lower()
    assert "crop" in uid_desc or "scroll" in uid_desc


# ---------------- C: 元素裁剪（渲染层源） ----------------

def _capture_method_src():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    i = src.index("captureWebviewScreenshot")
    j = src.index("\n    },", i)
    return src[i:j]


def test_element_capture_crops_without_click():
    body = _capture_method_src()
    assert "scrollIntoView" in body
    assert ".crop(" in body
    assert "capturePage()" in body
    assert "webviewClick" not in body  # 去点击副作用
    assert "getBoundingClientRect" in body and "innerWidth" in body


# ---------------- D: 快照暴露图片（渲染层源） ----------------

def _snapshot_method_src():
    src = _read("static", "js", "methods", "80_webview_agent.js")
    i = src.index("getWebviewSnapshot")
    j = src.index("const script = `", i)
    k = src.index("return out.join", j)
    return src[i:k]


def test_snapshot_enumerates_images():
    body = _snapshot_method_src()
    assert 'img,[role="img"],input[type="image"],canvas' in body
    assert "data-ai-id" in body            # 赋 uid 供 take_screenshot/remove_element 定位
    assert "naturalWidth" in body
    assert "[offscreen]" in body
    assert "listed >= 60" in body          # 上限，抑制 token
