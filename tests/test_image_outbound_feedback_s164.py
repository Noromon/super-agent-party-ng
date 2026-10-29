# -*- coding: utf-8 -*-
"""S164: XMPP 图片外发闭环——拦截必须反馈给模型与用户。

事故（backend.log 2026-10-29 16:43）：模型用发明的根路径 ![](/iter_01_*.png)
发交付图，外发围栏拒绝但**仅记日志**，模型以为图已发出直接收尾，用户干等
到 16:51 追问才拿到图。本文件钉桩：围栏拒绝/文件缺失两类拦截——注入
【系统提示】到会话记忆（下一轮自愈）+ 用户侧简报；正常外发零打扰。
ast 抽取 _send_local_images，fake self 全隔离（零网络/零用户数据）。
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
    ns = {"re": re, "os": shim_os, "logging": logging, "IMAGE_EXTS": [".png", ".jpg"]}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<slimgs>", "exec"), ns)
    return ns["_send_local_images"]


class FakeXmpp:
    def __init__(self, existing=(), allowed_prefix="/allowed"):
        self.existing = set(existing)
        self.allowed_prefix = allowed_prefix
        self.sent = []
        self.uploaded = []
        self.persisted = 0
        self.memoryList = {}
        self._xep0363_supported = True

    async def _fence_roots(self):
        return [self.allowed_prefix]

    def _fence_ok(self, path, extra_roots=()):
        return path.startswith(self.allowed_prefix)

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


class TestBlockedFeedback:
    def test_fence_rejected_injects_and_briefs(self):
        fake = FakeXmpp()
        _run(fake, "交付完成 ![](/iter_01_delivery_9e1db4a1.png)")
        assert fake.uploaded == []
        mem = fake.memoryList["u@x"]
        assert len(mem) == 1 and mem[0]["role"] == "user"
        assert "【系统提示】" in mem[0]["content"]
        assert "/iter_01_delivery_9e1db4a1.png" in mem[0]["content"]
        assert "围栏外" in mem[0]["content"] and "绝对路径" in mem[0]["content"]
        assert fake.persisted == 1
        assert len(fake.sent) == 1 and fake.sent[0].startswith("⚠")
        assert "iter_01_delivery_9e1db4a1.png" in fake.sent[0]

    def test_missing_file_also_feedback(self):
        fake = FakeXmpp(existing=set())
        _run(fake, "![](/allowed/ghost.png)")
        assert "文件不存在" in fake.memoryList["u@x"][0]["content"]
        assert fake.uploaded == [] and fake.persisted == 1

    def test_dedup_same_path_multiple_mentions(self):
        fake = FakeXmpp()
        _run(fake, "![](/bad/a.png) 再提 ![](/bad/a.png) 还提 /bad/a.png")
        assert len(fake.memoryList["u@x"]) == 1
        assert fake.memoryList["u@x"][0]["content"].count("/bad/a.png") == 1
        assert len(fake.sent) == 1 and "1 个" in fake.sent[0]

    def test_feedback_capped_at_four_with_overflow_note(self):
        fake = FakeXmpp()
        text = " ".join(f"/bad/f{i}.png" for i in range(6))
        _run(fake, text)
        content = fake.memoryList["u@x"][0]["content"]
        assert "另有若干" in content
        assert "6 个" in fake.sent[0]


class TestHappyPathUntouched:
    def test_valid_upload_no_injection_no_brief(self):
        fake = FakeXmpp(existing={"/allowed/good.png"})
        _run(fake, "看图 ![](/allowed/good.png)")
        assert fake.uploaded == ["/allowed/good.png"]
        assert fake.memoryList == {} and fake.sent == [] and fake.persisted == 0

    def test_no_image_paths_at_all(self):
        fake = FakeXmpp()
        _run(fake, "本轮没有图片")
        assert fake.memoryList == {} and fake.sent == []

    def test_xep_unsupported_blocked_path_still_feedback(self):
        fake = FakeXmpp()
        fake._xep0363_supported = False
        _run(fake, "![](/bad/x.png)")   # 围栏外：与 XEP 支持与否无关
        assert len(fake.memoryList["u@x"]) == 1


class TestWiringPins:
    def test_no_silent_fence_continue(self):
        seg = _SRC[_SRC.find("async def _send_local_images"):]
        seg = seg[:seg.find("async def _upload_and_share")]
        assert 'blocked.append(("围栏外", raw))' in seg
        assert 'blocked.append(("文件不存在", raw))' in seg
        assert "【系统提示】" in seg and "_persist_conv" in seg
        assert "S164 外发闭环" in seg
