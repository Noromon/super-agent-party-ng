# -*- coding: utf-8 -*-
"""S205 日记尸块清洗脚本：参数还原、非目标零改动、备份/原子替换/回滚。"""
import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location(
    "clean_diary_markup", _ROOT / "scripts" / "clean_diary_markup.py")
cm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cm)

THINK_BLOCK = ('<tool_call>\n<function=write_diary>\n<parameter=title>\n傍晚的火苗\n</parameter>\n'
               '<parameter=content>\n正文第一段\n\n第二段\n</parameter>\n<parameter=entry_type>\nthink\n</parameter>\n'
               '</function>\n</tool_call>')
IM_BLOCK = ('<tool_call>\n<function=mimic_human_interaction>\n<parameter=type>\ntext\n</parameter>\n'
            '<parameter=message>\n主人早安呀～今天周一诶，出门记得带伞，路上别刷手机。\n</parameter>\n'
            '</function>\n</tool_call>')


def _lib(entries):
    return {"characterId": "cid", "characterName": "主人", "entries": entries}


def _write_lib(path, entries):
    text = json.dumps(_lib(entries), ensure_ascii=False, indent=4).replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def _entries_of(path):
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


ENTRY_DIRTY = {"id": "d1", "type": "think", "time": "t1", "title": "<tool_call>",
               "content": THINK_BLOCK, "pushedTo": []}
ENTRY_IM = {"id": "d2", "type": "imMessage", "time": "t2", "title": "<tool_call>",
            "content": IM_BLOCK, "pushedTo": ["xmpp"]}
ENTRY_CLEAN = {"id": "c1", "type": "think", "time": "t0", "title": "正常标题",
               "content": "正常正文，含尖括号安全内容 a < b。", "pushedTo": []}


class TestCleanEntry:
    def test_pure_block_recovered(self):
        e = dict(ENTRY_DIRTY)
        changed, note = cm.clean_entry(e)
        assert changed and "RECOVER" in note
        assert e["title"] == "傍晚的火苗" and e["content"].startswith("正文第一段")
        assert e["id"] == "d1" and e["time"] == "t1" and e["type"] == "think"

    def test_im_title_from_message(self):
        e = dict(ENTRY_IM)
        assert cm.clean_entry(e)[0]
        assert e["content"].startswith("主人早安呀")
        assert e["title"] == e["content"].strip().splitlines()[0][:24]
        assert e["pushedTo"] == ["xmpp"]  # 诚实性另议，字段不动

    def test_partial_strip_keeps_human_text(self):
        e = {"id": "p1", "type": "think", "time": "t", "title": "人话标题",
             "content": "前面是人话。\n<tool_call>\n<function=x>\n<parameter=a>\nzz\n</parameter>\n</function>\n</tool_call>",
             "pushedTo": []}
        changed, note = cm.clean_entry(e)
        assert changed and "STRIP" in note
        assert e["content"] == "前面是人话。" and "tool_call" not in e["content"]

    def test_clean_untouched_and_paramless_skipped(self):
        assert cm.clean_entry(dict(ENTRY_CLEAN))[0] is False
        e = {"id": "x", "type": "think", "title": "<tool_call>", "content":
             "<tool_call>\n<function=y>\n<parameter=nope>\nvv\n</parameter>\n</function>\n</tool_call>",
             "time": "t", "pushedTo": []}
        changed, note = cm.clean_entry(e)
        assert changed is False and "SKIP" in note


class TestApplyRestore:
    def test_dry_run_then_apply_then_restore(self, tmp_path, capsys):
        f = tmp_path / "book.json"
        _write_lib(f, [ENTRY_CLEAN, ENTRY_DIRTY, ENTRY_IM])
        raw0 = f.read_bytes()
        assert cm.main(["--file", str(f)]) == 0  # 默认 dry-run
        assert f.read_bytes() == raw0 and "--apply" in capsys.readouterr().out
        assert cm.main(["--file", str(f), "--apply"]) == 0
        out = capsys.readouterr().out
        assert "已应用 2 条清洗" in out and "备份" in out
        ents = _entries_of(f)
        assert ents[1]["content"].startswith("正文第一段") and ents[2]["title"] != "<tool_call>"
        assert ents[0] == ENTRY_CLEAN  # 非目标条目逐字段一致
        assert b"\r\n" in f.read_bytes()  # 原格式 CRLF 保持
        baks = list(tmp_path.glob("book.json.bak-s205-*"))
        assert len(baks) == 1 and baks[0].read_bytes() == raw0
        assert cm.main(["--file", str(f), "--apply"]) == 0  # 幂等
        assert "无脏条目" in capsys.readouterr().out
        assert cm.main(["--file", str(f), "--restore", str(baks[0])]) == 0
        assert f.read_bytes() == raw0

    def test_verify_catches_non_target_mutation(self):
        before = [dict(ENTRY_CLEAN), dict(ENTRY_DIRTY)]
        after = json.dumps(_lib([dict(ENTRY_CLEAN, title="被篡改"), dict(ENTRY_DIRTY)]),
                           ensure_ascii=False)
        errs = cm._verify(before, after, {"d1"})
        assert any("非目标条目" in m for m in errs)

    def test_verify_catches_markup_residue(self):
        before = [dict(ENTRY_CLEAN)]
        after = json.dumps(_lib([dict(ENTRY_CLEAN, content="藏 <tool_call>") ]), ensure_ascii=False)
        assert any("残留" in m for m in cm._verify(before, after, set()))
