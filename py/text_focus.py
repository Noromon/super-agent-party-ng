# S250：聚焦提取——从长文本中按关键词抽取 ±context 行命中块并附位置定位，
# 供 simple_fetch / web_render 的 focus 参数使用（"大海捞针"一步到位，免全文回传再自查）。


def focus_blocks(text: str, focus: str, context: int = 6, max_hits: int = 10, ci: bool = True):
    """返回 (blocks_text, hit_line_total)。focus 为字面子串（非正则）。

    命中行按 ±context 行扩块并合并重叠区间；每块头部标注块序/总命中/全文百分比/行号区间。
    无命中返回 ("", 0)。
    """
    text = text or ""
    focus = (focus or "").strip()
    if not focus or not text.strip():
        return "", 0
    try:
        context = max(0, min(int(context), 30))
    except (TypeError, ValueError):
        context = 6
    try:
        max_hits = max(1, min(int(max_hits), 25))
    except (TypeError, ValueError):
        max_hits = 10
    lines = text.splitlines()
    if not lines:
        return "", 0
    line_start = []
    pos = 0
    for ln in lines:
        line_start.append(pos)
        pos += len(ln) + 1
    total = len(text) or 1
    needle = focus.lower() if ci else focus
    hit_idx = []
    for i, ln in enumerate(lines):
        hay = ln.lower() if ci else ln
        hay = hay.replace("\\", "")  # markdown 转义(TARGET\_X)不阻塞字面匹配
        if needle in hay:
            hit_idx.append(i)
    if not hit_idx:
        return "", 0
    spans = []
    for i in hit_idx:
        s, e = max(0, i - context), min(len(lines) - 1, i + context)
        if spans and s <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], e)
        else:
            spans.append([s, e])
    out = []
    shown = spans[:max_hits]
    for bi, (s, e) in enumerate(shown, 1):
        hits_in = sum(1 for h in hit_idx if s <= h <= e)
        pct = int(line_start[s] * 100 / total)
        out.append(f"--- match {bi}/{len(shown)} (+{hits_in} hit line(s) in block) @text {pct}% L{s + 1}-L{e + 1} ---")
        out.append("\n".join(lines[s:e + 1]))
        out.append("")
    if len(spans) > len(shown):
        out.append(f"[focus] …另有 {len(spans) - len(shown)} 个命中块未显示（共 {len(hit_idx)} 行命中 / {len(spans)} 块，"
                   "可加大 context 或 refine focus）")
    head = f"[focus] '{focus}' 命中 {len(hit_idx)} 行，聚为 {len(spans)} 块，展示前 {len(shown)} 块：\n"
    return head + "\n".join(out), len(hit_idx)
