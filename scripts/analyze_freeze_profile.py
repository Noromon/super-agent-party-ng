r"""S98: 解析 CDP CPU profile（%TEMP%\\sap-freeze-profile-*.json），输出自耗时 Top 函数。

用法: python scripts/analyze_freeze_profile.py <profile.json> [topN=20]
"""
import json
import sys
from collections import defaultdict


def analyze(path: str, top_n: int = 20) -> str:
    with open(path, encoding="utf-8") as f:
        prof = json.load(f)
    nodes = {n["id"]: n for n in prof.get("nodes", [])}
    samples = prof.get("samples", [])
    deltas = prof.get("timeDeltas", [])
    self_us = defaultdict(int)
    where_us = defaultdict(int)
    for i, nid in enumerate(samples):
        dt = deltas[i] if i < len(deltas) and deltas[i] > 0 else 0
        node = nodes.get(nid)
        if not node:
            continue
        cf = node.get("callFrame", {})
        fn = cf.get("functionName") or "(anonymous)"
        url = (cf.get("url") or "").replace("file:///", "").replace("http://127.0.0.1:3456/", "")
        loc = f"{url}:{cf.get('lineNumber', -1) + 1}:{cf.get('columnNumber', 0)}"
        self_us[f"{fn} @ {loc}"] += dt
        key = url.split("/")[-1] if url else "(program)"
        where_us[key] += dt
    total = sum(self_us.values()) or 1
    lines = [f"profile={path} total={total / 1e6:.2f}s samples={len(samples)}"]
    lines.append("--- self-time by location ---")
    for k, v in sorted(self_us.items(), key=lambda kv: -kv[1])[:top_n]:
        lines.append(f"{v / 1e6:7.2f}s {100.0 * v / total:5.1f}%  {k}")
    lines.append("--- self-time by file ---")
    for k, v in sorted(where_us.items(), key=lambda kv: -kv[1])[:top_n]:
        lines.append(f"{v / 1e6:7.2f}s {100.0 * v / total:5.1f}%  {k}")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(2)
    print(analyze(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 20))
