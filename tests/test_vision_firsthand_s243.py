# S243：一手/二手视觉工具族分层
#  A: secondhand_* 改名引用面全同步（schema∩dispatch∩path_scope 一致哨兵）+ 二手警示描述
#  B: view_images 一手工具：执行登记(本地路径转URL/内部URL校验) + _collect 多图 findall + 注入
import asyncio
import base64
import sys
from pathlib import Path

_WEBP_B64 = base64.b64encode(b"RIFF\x04\x00\x00\x00WEBPVP8 ").decode()

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import server  # noqa: E402
import py.load_files as lf  # noqa: E402
import py.path_scope as ps  # noqa: E402
import py.tool_taxonomy as tx  # noqa: E402

NEW = {"secondhand_describe_image", "secondhand_describe_images", "secondhand_review_image"}
FIRST = "view_images"


def _read(*parts) -> str:
    return (ROOT.joinpath(*parts)).read_text(encoding="utf-8")


# ---------------- A: 改名引用面零残留 + 三集合一致 ----------------

def test_no_old_tool_name_strings():
    for f in ("py/load_files.py", "py/path_scope.py", "py/tool_assembly.py"):
        src = _read(*f.split("/"))
        for old in ('"analyze_image"', '"analyze_images"', '"review_image"'):
            assert old not in src, f"{f} 残留旧工具名 {old}"
    cdp = _read("py/cdp_tool.py")
    assert "without a separate analyze_image call" not in cdp
    s = _read("server.py")
    assert '"analyze_image":' not in s and '"review_image":' not in s and '"analyze_images":' not in s
    assert "s207-analyze_image" not in s and "s207-review_image" not in s


def test_schema_dispatch_pathscope_consistent():
    for schema in (lf.analyze_image_tool, lf.review_image_tool, lf.analyze_images_tool, lf.view_images_tool):
        name = schema["function"]["name"]
        assert name in NEW or name == FIRST
        s = _read("server.py")
        assert f'"{name}":' in s, f"dispatch 缺 {name}"
        assert s.count(f'"{name}":') >= 2, f"{name} 应出现在两处 dispatch 表"
        assert name in ps.PATH_SCOPED_TOOLS, f"path_scope 缺 {name}"
    assert tx.classify("secondhand_describe_image") == "media_analysis"
    assert tx.classify("secondhand_review_image") == "media_analysis"
    assert tx.classify("view_images") == "media_analysis"


def test_registry_contains_view_images_and_assembly_orders_first():
    reg = _read("server.py")
    assert '"view_images_tool": view_images_tool' in reg
    asm = _read("py/tool_assembly.py")
    i_first = asm.index('tk["view_images_tool"]')
    i_second = asm.index('tk["analyze_image_tool"]')
    assert i_first < i_second, "一手工具应先于二手公告"


def test_descriptions_secondhand_warnings_and_first_hand():
    for schema, key in ((lf.analyze_image_tool, "secondhand_describe_image"),
                        (lf.review_image_tool, "secondhand_review_image"),
                        (lf.analyze_images_tool, "secondhand_describe_images")):
        fn = schema["function"]
        assert fn["name"] == key
        d = fn["description"]
        assert "SECOND-HAND" in d and "一手" in d and "view_images" in d, key
    d = lf.view_images_tool["function"]["description"]
    assert "FIRST-HAND" in d and "secondhand_describe_image" in d and "最多" in d
    cdp = next(t["function"] for t in __import__("py.cdp_tool", fromlist=["x"]).all_cdp_tools
               if t.get("function", {}).get("name") == "take_screenshot")
    assert "FIRST-HAND" in cdp["description"]


# ---------------- B: _collect 多图 findall + 来源双文案 ----------------

def _vi_tool(*urls):
    return {"role": "tool", "name": "view_images",
            "content": f"Images attached for direct viewing: {' '.join(urls)}\n（FIRST-HAND…）"}


_V1 = "http://127.0.0.1:3456/uploaded_files/a.png"
_V2 = "http://127.0.0.1:3456/uploaded_files/b.jpg"
_EXT = "https://cdn.example.com/img/pic.png"


def test_collect_view_images_multi_urls_with_source():
    msgs = [{"role": "user", "content": "q"}, _vi_tool(_V1, _V2)]
    assert server._collect_new_vision_requests(msgs) == [(_V1, "view_images"), (_V2, "view_images")]


def test_collect_allows_external_image_extension_urls():
    msgs = [{"role": "user", "content": "q"}, _vi_tool(_EXT)]
    assert server._collect_new_vision_requests(msgs) == [(_EXT, "view_images")]


def test_collect_screenshot_still_works_and_mixed():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "tool", "name": "take_screenshot", "content": f"Screenshot saved to {_V1}"},
        _vi_tool(_V2),
    ]
    assert server._collect_new_vision_requests(msgs) == [(_V1, "take_screenshot"), (_V2, "view_images")]
    assert server._collect_new_browser_screenshots(msgs) == [_V1, _V2]  # 旧接口薄壳


def test_collect_ignores_non_image_and_failures():
    msgs = [
        {"role": "user", "content": "q"},
        {"role": "tool", "name": "view_images", "content": "错误：没有可附上的图片。/uploaded_files/x.png"},
        {"role": "tool", "name": "view_images", "content": f"see https://e.com/f.pdf {_V1}"},
    ]
    assert server._collect_new_vision_requests(msgs) == [(_V1, "view_images")]


def test_inject_view_images_text_and_cap3(monkeypatch):
    async def _fake(msgs, base):
        out = []
        for idx, m in enumerate(msgs):
            if isinstance(m.get("content"), list):
                items = [it for it in m["content"] if it.get("type") == "image_url"]
                for it in items:  # 真实语义：就地重写 url 为 data URI（S252: 需真魔数过毒字节判定）
                    it["image_url"]["url"] = "data:image/webp;base64," + _WEBP_B64
                if items:
                    out.append({"index": idx, "images": items})
        return out

    monkeypatch.setattr(server, "images_in_messages", _fake)

    class _Req:
        def __init__(self, messages):
            self.messages = messages

    req = _Req([{"role": "user", "content": "q"}, _vi_tool(_V1, _V2)])
    asyncio.run(server._maybe_inject_browser_vision(req, {}, [], "http://h/"))
    inj = [m for m in req.messages if m.get("name") == "browser_vision"]
    assert len(inj) == 2
    assert all("First-hand image" in m["content"] for m in inj)  # 注入后被剥离为纯文本(S228 既有行为)
    # 4 张请求 -> 注入上限 3
    req2 = _Req([{"role": "user", "content": "q"},
                 _vi_tool(_V1, _V2, _EXT, "http://127.0.0.1:3456/uploaded_files/d.png")])
    asyncio.run(server._maybe_inject_browser_vision(req2, {}, [], "http://h/"))
    assert len([m for m in req2.messages if m.get("name") == "browser_vision"]) == 3


# ---------------- B: view_images 执行登记 ----------------

def _img(tmp, name="p.png"):
    p = tmp / name
    p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 64)
    return p


def test_view_images_local_path_registered(monkeypatch, tmp_path):
    from py import get_setting
    monkeypatch.setattr(get_setting, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(get_setting, "get_host", lambda: "127.0.0.1")
    monkeypatch.setattr(get_setting, "get_port", lambda: 3456)
    src = _img(tmp_path)
    out = asyncio.run(server.view_images([str(src)]))
    assert out.startswith("Images attached for direct viewing: http://127.0.0.1:3456/uploaded_files/view_")
    assert out.count("http://") == 1
    assert (tmp_path / "up").is_dir()


def test_view_images_rejects_bad_inputs(monkeypatch, tmp_path):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    txt = tmp_path / "a.txt"
    txt.write_text("hi")
    out = asyncio.run(server.view_images([str(txt)]))
    assert out.startswith("错误") and "非图片格式" in out
    assert asyncio.run(server.view_images([])).startswith("错误")
    assert asyncio.run(server.view_images([str(tmp_path / "no.png")])).startswith("错误")


def test_view_images_zero_byte_internal_url_rejected(monkeypatch, tmp_path):
    import py.vision_tools as S  # S299：view_images 迁出后桩须钉消费模块
    up = tmp_path / "up"
    up.mkdir()
    (up / "e.png").write_bytes(b"")
    monkeypatch.setattr(S, "UPLOAD_FILES_DIR", str(up))
    out = asyncio.run(server.view_images(["http://127.0.0.1:3456/uploaded_files/e.png"]))
    assert "0字节" in out  # S238 教训：0 字节图不得进入注入
