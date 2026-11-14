# -*- coding: utf-8 -*-
"""S214: markdown 图片的工作区相对路径外发（XMPP）。

事故口径：模型在工作区内生图后用 ![图](output/a.png) 外发，旧版只扫绝对路径——
相对目标不进管道静默丢失；更糟的是绝对路径正则缺左界定，把 http://x/a.png 抓成
"p://x/a.png"、把 out/a.png 抓成 "/a.png"，造成 URL 误拦与"图已发出+⚠误报"并存。
本文件钉桩：①resolve_workspace_rel 四态+逃逸；②_send_local_images 相对成功/
逃逸/缺失/工作区未启用走 S164 闭环，URL 零打扰，绝对 markdown 不双发，
绝对正则 lookbehind 不再抓 URL/词中相对片段。ast 抽取 + fake self 全隔离。
"""
import ast
import asyncio
import logging
import os
import re
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.xmpp_client import resolve_workspace_rel  # noqa: E402

_SRC = (_ROOT / "py" / "xmpp_client.py").read_text(encoding="utf-8-sig")


def _load_method(existing_files):
    tree = ast.parse(_SRC)
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "_send_local_images")

    class _PathShim:
        isfile = staticmethod(lambda p: p in existing_files)
        basename = staticmethod(os.path.basename)
        getsize = staticmethod(os.path.getsize)

    shim_os = types.ModuleType("os")
    shim_os.path = _PathShim
    shim_os.getcwd = os.getcwd
    ns = {"re": re, "os": shim_os, "logging": logging,
          "IMAGE_EXTS": [".png", ".jpg"], "resolve_workspace_rel": resolve_workspace_rel}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<slimgs>", "exec"), ns)
    return ns["_send_local_images"]


class FakeXmpp:
    def __init__(self, ws="", allowed_prefix="/allowed", existing=()):
        self.ws = ws
        self.allowed_prefix = allowed_prefix
        self.existing = set(existing)
        self.sent = []
        self.uploaded = []
        self.persisted = 0
        self.memoryList = {}
        self._xep0363_supported = True

    async def _fence_roots(self):
        return [self.allowed_prefix]

    def _fence_ok(self, path, extra_roots=()):
        return path.startswith(self.allowed_prefix)

    async def _workspace_root(self):
        return self.ws

    async def _send_text(self, jid, text):
        self.sent.append(text)

    async def _upload_and_share(self, jid, path):
        self.uploaded.append(path)
        return "https://host/httpfileupload/x.png"

    async def _persist_conv(self, jid):
        self.persisted += 1


def _run(fake, text, jid="u@x"):
    method = _load_method(fake.existing)
    asyncio.run(method(fake, jid, text))


class TestResolveWorkspaceRel:
    def test_inside_workspace_ok(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "output").mkdir(parents=True)
        f = ws / "output" / "a.png"
        f.write_bytes(b"x")
        got, why = resolve_workspace_rel("output/a.png", str(ws))
        assert why == "" and got == os.path.normpath(str(f))

    def test_escape_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        got, why = resolve_workspace_rel("../secret.png", str(ws))
        assert got == "" and why == "围栏外"

    def test_missing_file(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        got, why = resolve_workspace_rel("out/ghost.png", str(ws))
        assert got == "" and why == "文件不存在"

    def test_no_workspace(self):
        got, why = resolve_workspace_rel("a.png", "")
        assert got == "" and why.startswith("工作区未启用")

    def test_absolute_target_never_passes(self, tmp_path):
        # os.path.join 遇绝对 target 会直接返回 target——realpath 包含检查必须兜住
        got, why = resolve_workspace_rel(r"C:\Windows\fonts\a.png", str(tmp_path))
        assert got == "" and why == "围栏外"

    def test_symlink_outside_workspace_rejected(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        link = ws / "link.png"
        try:
            os.symlink(str(outside), str(link))
        except OSError:
            import pytest
            pytest.skip("无符号链接创建权限")
        got, why = resolve_workspace_rel("link.png", str(ws))
        assert got == "" and why == "围栏外"


class TestSendLocalImagesRel:
    def test_relative_upload_success(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "output").mkdir(parents=True)
        (ws / "output" / "a.png").write_bytes(b"x")
        fake = FakeXmpp(ws=str(ws))
        _run(fake, "交付完成 ![](output/a.png)")
        assert fake.uploaded == [os.path.normpath(os.path.join(str(ws), "output/a.png"))]
        assert fake.memoryList == {} and fake.sent == [] and fake.persisted == 0

    def test_relative_escape_goes_s164_loop(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        fake = FakeXmpp(ws=str(ws))
        _run(fake, "![](../secret.png)")
        assert fake.uploaded == []
        content = fake.memoryList["u@x"][0]["content"]
        assert "【系统提示】" in content and "围栏外" in content and "../secret.png" in content
        assert "工作区相对路径" in content  # S214 文案对齐：注记必须教会模型新能力
        assert fake.sent[0].startswith("⚠") and "相对路径" in fake.sent[0]
        assert fake.persisted == 1

    def test_relative_missing_and_no_workspace_feedback(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        fake = FakeXmpp(ws=str(ws))
        _run(fake, "![](out/ghost.png)")
        assert "文件不存在" in fake.memoryList["u@x"][0]["content"]
        fake2 = FakeXmpp(ws="")
        _run(fake2, "![](a.png)")
        assert "工作区未启用" in fake2.memoryList["u@x"][0]["content"]
        assert fake2.uploaded == [] and fake2.persisted == 1

    def test_url_markdown_zero_disturbance(self):
        # 旧正则缺左界定：https://cdn.net/img.png 被抓成 "s://cdn.net/img.png" 误拦；
        # 修复后 URL 全链路零打扰（不上传、不拦截、不注记、不简报）
        fake = FakeXmpp()
        _run(fake, "看图 ![x](https://cdn.net/img.png) 参考 http://a.com/y.png")
        assert fake.uploaded == [] and fake.memoryList == {} and fake.sent == []

    def test_bare_relative_mid_text_not_captured(self):
        # "dir/sub/a.png" 中的 /sub、/a.png 是词中相对片段，旧版误抓为绝对路径
        fake = FakeXmpp()
        _run(fake, "产物在 dir/sub/a.png 请查收")
        assert fake.uploaded == [] and fake.memoryList == {} and fake.sent == []

    def test_absolute_markdown_not_double_sent(self):
        fake = FakeXmpp(ws="", existing={"/allowed/good.png"})
        _run(fake, "看图 ![](/allowed/good.png)")
        assert fake.uploaded == ["/allowed/good.png"]  # 仅 pass1 一份，无相对遍重复
        assert fake.memoryList == {} and fake.sent == []

    def test_mixed_absolute_relative_url_each_once(self, tmp_path):
        ws = tmp_path / "ws"
        (ws / "output").mkdir(parents=True)
        (ws / "output" / "a.png").write_bytes(b"x")
        fake = FakeXmpp(ws=str(ws), allowed_prefix="/allowed", existing={"/allowed/good.png"})
        _run(fake, "![](/allowed/good.png) ![](output/a.png) ![r](https://x.io/z.png)")
        resolved = os.path.normpath(os.path.join(str(ws), "output/a.png"))
        assert fake.uploaded == ["/allowed/good.png", resolved]
        assert fake.memoryList == {} and fake.sent == []


class TestWiringPins:
    def test_abs_regex_has_left_boundary(self):
        seg = _SRC[_SRC.find("async def _send_local_images"):]
        seg = seg[:seg.find("async def _upload_and_share")]
        assert r"(?<![A-Za-z0-9_.:/\\-])" in seg

    def test_rel_pipeline_wired(self):
        seg = _SRC[_SRC.find("async def _send_local_images"):]
        seg = seg[:seg.find("async def _upload_and_share")]
        assert "md_targets" in seg and "resolve_workspace_rel(" in seg
        assert "await self._workspace_root()" in seg

    def test_helper_uses_strict_containment(self):
        assert "def resolve_workspace_rel(" in _SRC
        assert "path_under(cand, [workspace])" in _SRC

    def test_feedback_briefing_mentions_rel_capability(self):
        assert "工作区内图片可用相对路径" in _SRC
