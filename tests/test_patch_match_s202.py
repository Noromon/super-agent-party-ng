# -*- coding: utf-8 -*-
"""S202 补丁工具实测反馈修复：回显=磁盘真相 + 第1级 CRLF 换行保护。

模型自测报告实锤两 bug：①批内 edit2 失配时『No changes were made』却回显 edit1
已应用的内存预览（按它复制 VERBATIM 必二次失配）；②CRLF 文件第 1 级精确替换把
带裸 \\n 的 new 直接插入，挤走该行原有 \\r → 混合换行 + diff 同文 -/+ 噪音对。
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.patch_match import apply_edits  # noqa: E402


def _e(old, new, **kw):
    return dict(old_string=old, new_string=new, **kw)


class TestFailureEchoIsDiskTruth:
    def test_batch_failure_snippet_shows_disk_not_preview(self):
        content = "A1 one\nA2 two\n"
        r = apply_edits(content, [_e("one", "ONE"),
                                  _e("A2 twoX and more words here", "X")])
        assert not r.ok
        assert "A1 one" in r.report        # 磁盘原文
        assert "A1 ONE" not in r.report    # 内存预览（旧 bug 的假状态）
        assert "WHOLE batch" in r.report

    def test_edit_targets_region_consumed_by_earlier_edit(self):
        r = apply_edits("A1 one\nA2 two\n",
                        [_e("one", "ONE"), _e("A1 one", "whatever")])
        assert not r.ok
        assert "earlier" in r.report and "already replaced that region" in r.report
        assert "A1 one" in r.report  # 冲突现场=磁盘内容

    def test_single_edit_failure_unchanged(self):
        r = apply_edits("alpha\nbeta\n", [_e("zzz nine here", "X")])
        assert not r.ok and "WHOLE batch" not in r.report  # 单编辑无批内注记


class TestCrlfProtection:
    def test_exact_hit_in_crlf_file_adapts_new(self):
        content = "L9 yankee\r\nL10 zulu\r\n"
        r = apply_edits(content, [_e("L10 zulu", "L10 zulu\nL11 hotel")])
        assert r.ok
        assert not re.search(r"(?<!\r)\n", r.content)  # 无混合换行
        assert "-L10 zulu" not in r.report             # 同文 -/+ 噪音对根除
        assert "+L11 hotel" in r.report

    def test_crlf_new_not_double_converted(self):
        content = "a\r\nb\r\n"
        r = apply_edits(content, [_e("b", "c\r\nd")])
        assert r.ok and "\r\r\n" not in r.content


class TestDiskTruthToolLevel:
    def test_local_tool_batch_failure_file_untouched_and_disk_echo(self, tmp_path, monkeypatch):
        import asyncio
        import py.cli_tool as ct
        f = tmp_path / "atomic_probe.txt"
        f.write_text("A1 one\nA2 two\n", encoding="utf-8")
        monkeypatch.setattr(ct, "_get_current_cwd", lambda: asyncio.sleep(0, str(tmp_path)))
        out = asyncio.run(ct.edit_file_patch_tool_local(
            path="atomic_probe.txt",
            edits=[{"old_string": "one", "new_string": "ONE"},
                   {"old_string": "A2 twoX and more words here", "new_string": "Z"}]))
        assert out.startswith("[Error]") and "A1 one" in out and "A1 ONE" not in out
        assert f.read_text(encoding="utf-8") == "A1 one\nA2 two\n"
