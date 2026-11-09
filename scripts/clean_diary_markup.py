# -*- coding: utf-8 -*-
"""S205 日记脏数据清洗：把正文/标题里的工具调用尸块还原成人类文本。

背景：S204 前生成的个别日记条目整段是模型编造的调用块（write_diary/
mimic_human_interaction 等并不存在的工具），标题被写成 '<tool_call>'。本脚本
从调用块的 <parameter=...> 中提取人类可读参数还原条目，绝不盲删。

安全：默认 --dry-run 仅预览；--apply 先写同目录 .bak-s205-<ts> 备份（sha256
校验）再临时文件原子替换；替换前完成全部校验（JSON 合法、条目数不变、只有
计划内 id 变化、非目标条目逐字段一致、全库零残留），任何失败中止且不触原文件；
--restore 可从任意备份回滚（回滚前亦备份现状）。pushedTo 等其余字段原样保留。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime

MARKUP = re.compile(r"</?tool_call|</?tool_call|<function=|</function>|<parameter=|</parameter>")
BLOCK = re.compile(r"<(?:tool_call|tool_call)>\s*<function=[^>\n]*>(.*?)</function>\s*</(?:tool_call|tool_call)>", re.S)
PARAM = re.compile(r"<parameter=([A-Za-z_][\w-]*)>\s*\n?(.*?)\n?\s*</parameter>", re.S)
TAG_STRIP = re.compile(r"</?(?:tool_call|tool_call)>|</?(?:function|parameter)[^>\n]*>?")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def is_pure_block(text: str) -> bool:
    t = (text or "").strip()
    return t.startswith(("<tool_call>", "<tool_call>")) and t.endswith(("</tool_call>", " <tool_call>"))


def parse_call_block(text: str) -> dict:
    """调用块 -> {参数名: 值}（多块合并，后块同名不覆盖先块）。"""
    out: dict = {}
    for inner in BLOCK.findall(text or ""):
        for name, value in PARAM.findall(inner):
            out.setdefault(name.strip(), value.strip())
    return out


def _title_from(content: str) -> str:
    lines = [ln for ln in (content or "").strip().splitlines() if ln.strip()]
    return lines[0][:24] if lines else ""


def clean_entry(entry: dict) -> tuple:
    """返回 (是否变化, 说明)。仅改 title/content 两字段，其余原样。"""
    title = entry.get("title") or ""
    content = entry.get("content") or ""
    if not MARKUP.search(title) and not MARKUP.search(content):
        return False, ""
    if is_pure_block(content):
        params = parse_call_block(content)
        new_content = ""
        for key in ("content", "message", "text", "body"):
            if params.get(key):
                new_content = params[key]
                break
        if not new_content:
            return False, "SKIP 纯块但无可还原参数（需人工处理）"
        new_title = params.get("title") or _title_from(new_content)
        if MARKUP.search(new_title) or MARKUP.search(new_content):
            return False, "SKIP 提取结果仍含标记（需人工处理）"
        entry["title"] = new_title
        entry["content"] = new_content
        return True, f"RECOVER 纯调用块→参数还原（title {len(new_title)}字/content {len(new_content)}字）"
    new_content = TAG_STRIP.sub("", BLOCK.sub("", content)).strip()
    new_title = TAG_STRIP.sub("", title).strip()
    if MARKUP.search(new_content) or MARKUP.search(new_title):
        return False, "SKIP 残留无法安全剥离（需人工处理）"
    if not new_content and not new_title:
        return False, "SKIP 剥离后为空（需人工处理）"
    if not new_title:
        new_title = _title_from(new_content)
    entry["title"], entry["content"] = new_title, new_content
    return True, "STRIP 人话保留、标记剥离"


def build_plan(data: dict) -> list:
    plan = []
    for i, e in enumerate(data.get("entries") or []):
        snapshot = dict(e)
        changed, note = clean_entry(snapshot)
        if changed:
            plan.append({"index": i, "id": e.get("id"), "note": note,
                         "before": {"title": e.get("title"), "content": e.get("content")},
                         "after": {"title": snapshot["title"], "content": snapshot["content"]}})
    return plan


def _verify(before_entries: list, after_text: str, plan_ids: set) -> list:
    errors = []
    try:
        after = json.loads(after_text)
    except Exception as exc:
        return [f"JSON 解析失败: {exc}"]
    a_entries = after.get("entries") or []
    if len(a_entries) != len(before_entries):
        errors.append(f"条目数变化 {len(before_entries)}->{len(a_entries)}")
    if MARKUP.search(after_text):
        errors.append("清洗后全库仍有标记残留")
    for b, a in zip(before_entries, a_entries):
        if a.get("id") in plan_ids:
            for k in b:
                if k not in ("title", "content") and b.get(k) != a.get(k):
                    errors.append(f"目标条目 {a.get('id')} 非计划字段 {k} 变化")
            continue
        if b != a:
            errors.append(f"非目标条目 {b.get('id')} 发生变化")
    return errors


def apply_file(path: str, do_apply: bool) -> int:
    raw = open(path, "rb").read()
    digest = sha256_bytes(raw)
    data = json.loads(raw.decode("utf-8"))
    plan = build_plan(data)
    print(f"file: {path}\nsha256(before): {digest}\nentries: {len(data.get('entries') or [])}")
    if not plan:
        print("计划: 无脏条目，零改动。")
        return 0
    for item in plan:
        print(f"- IDX{item['index']} id={item['id']} {item['note']}")
        print(f"    title: {item['before']['title']!r} -> {item['after']['title']!r}")
        print(f"    content: {len(item['before']['content'] or '')}字 -> {len(item['after']['content'])}字")
    if not do_apply:
        print("模式: dry-run（未写盘）。确认无误后用 --apply。")
        return 0
    for item in plan:
        e = data["entries"][item["index"]]
        e["title"], e["content"] = item["after"]["title"], item["after"]["content"]
    new_text = json.dumps(data, ensure_ascii=False, indent=4).replace("\n", "\r\n")
    errors = _verify(json.loads(raw.decode("utf-8"))["entries"], new_text,
                     {p["id"] for p in plan})
    if errors:
        print("校验失败，原文件未动:")
        [print("  !", msg) for msg in errors]
        return 2
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak-s205-{ts}"
    shutil.copy2(path, bak)
    if sha256_bytes(open(bak, "rb").read()) != digest:
        print("备份校验失败，原文件未动。")
        return 2
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(new_text)
        if sha256_bytes(open(tmp, "rb").read()) != sha256_bytes(new_text.encode("utf-8")):
            raise RuntimeError("临时文件写入校验失败")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print(f"备份: {bak}\nsha256(after): {sha256_bytes(open(path, 'rb').read())}\n已应用 {len(plan)} 条清洗。")
    return 0


def restore_file(path: str, backup: str) -> int:
    braw = open(backup, "rb").read()
    bdata = json.loads(braw.decode("utf-8"))
    assert isinstance(bdata.get("entries"), list), "备份不是合法日记库"
    cur = open(path, "rb").read()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    pre = f"{path}.pre-restore-{ts}"
    open(pre, "wb").write(cur)
    open(path, "wb").write(braw)
    if sha256_bytes(open(path, "rb").read()) != sha256_bytes(braw):
        open(path, "wb").write(cur)
        print(f"回滚写盘校验失败，已还原现状（现状另存 {pre}）")
        return 2
    print(f"已回滚: {backup} -> {path}（回滚前现状另存 {pre}）")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", required=True, help="日记 JSON 路径")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="仅预览（默认）")
    g.add_argument("--apply", action="store_true", help="备份后写盘清洗")
    g.add_argument("--restore", metavar="BACKUP", help="从备份 JSON 回滚")
    args = ap.parse_args(argv)
    if args.restore:
        return restore_file(args.file, args.restore)
    return apply_file(args.file, do_apply=bool(args.apply))


if __name__ == "__main__":
    sys.exit(main())
