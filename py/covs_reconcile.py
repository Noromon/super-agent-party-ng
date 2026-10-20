# -*- coding: utf-8 -*-
"""M4b three-way reconciliation (READ-ONLY): conversations blob vs
conversation_rows shadow table vs turn_log presence traces.

Usage:
    python py/covs_reconcile.py [--db path/to/conversations.db] [--out report.md]
Exit code: 0 = fully consistent, 1 = mismatch found, 2 = cannot read.
"""

import logging
import argparse
import json
import os
import sqlite3
import sys


def default_db_path():
    cands = []
    if os.environ.get("SAP_DATA_DIR"):
        cands.append(os.environ["SAP_DATA_DIR"])
    appdata = os.environ.get("APPDATA")
    if appdata:
        cands.append(os.path.join(appdata, "super-agent-party", "Super-Agent-Party"))
        cands.append(os.path.join(appdata, "Super-Agent-Party"))
    cands.append(os.path.expanduser("~/.local/share/Super-Agent-Party"))
    for d in cands:
        p = os.path.join(d, "conversations.db")
        if os.path.isfile(p):
            return p
    return None


def load_maps(db_path):
    con = sqlite3.connect("file:{}?mode=ro".format(db_path.replace("?", "%3f")), uri=True)
    try:
        blob_map, rows_map, traces = {}, {}, {}
        row = con.execute("SELECT data FROM settings WHERE id=1").fetchone()
        if row:
            for conv in (json.loads(row[0]).get("conversations") or []):
                if isinstance(conv, dict) and conv.get("id") is not None:
                    blob_map[str(conv["id"])] = conv
        try:
            # bot:* rows are the phone-channel namespace, not blob shadows
            for cid, data in con.execute(
                    "SELECT conv_id, data FROM conversation_rows WHERE conv_id NOT LIKE 'bot:%'"):
                rows_map[cid] = json.loads(data)
        except sqlite3.OperationalError:
            pass  # shadow table absent -> everything blob-only
        try:
            for cid, n in con.execute(
                    "SELECT conversation_id, COUNT(*) FROM turn_log GROUP BY conversation_id"):
                traces[str(cid)] = n
        except sqlite3.OperationalError:
            pass
        return blob_map, rows_map, traces
    finally:
        con.close()


def reconcile(blob_map, rows_map, traces):
    blob_ids, row_ids = set(blob_map), set(rows_map)
    blob_only = sorted(blob_ids - row_ids)
    rows_only = sorted(row_ids - blob_ids)
    mismatch = sorted(
        cid for cid in blob_ids & row_ids
        if json.dumps(blob_map[cid], sort_keys=True, ensure_ascii=False)
        != json.dumps(rows_map[cid], sort_keys=True, ensure_ascii=False))
    ghost_traces = {cid: traces[cid] for cid in sorted(set(traces) - blob_ids - row_ids)}
    ok = not (blob_only or rows_only or mismatch)
    return {
        "consistent": ok,
        "blob_conversations": len(blob_map),
        "shadow_rows": len(rows_map),
        "turn_log_conversations": len(traces),
        "blob_only": blob_only,
        "rows_only": rows_only,
        "content_mismatch": mismatch,
        "turn_log_orphans": ghost_traces,
    }


def to_markdown(r, db_path):
    lines = [
        "# covs reconciliation report",
        "",
        "- db: `{}`".format(db_path),
        "- verdict: **{}**".format("CONSISTENT" if r["consistent"] else "MISMATCH"),
        "- blob conversations: {} | shadow rows: {} | turn_log conversations: {}".format(
            r["blob_conversations"], r["shadow_rows"], r["turn_log_conversations"]),
        "",
    ]
    for key, label in (("blob_only", "blob-only (missing in shadow rows)"),
                       ("rows_only", "shadow-only (ghost rows)"),
                       ("content_mismatch", "content mismatch (blob != row)")):
        lines.append("## {} — {} id(s)".format(label, len(r[key])))
        lines += ["- `{}`".format(i) for i in r[key][:50]]
        lines.append("")
    lines.append("## turn_log conversations absent from both stores (deleted-chat traces) — {} id(s)".format(
        len(r["turn_log_orphans"])))
    lines += ["- `{}` ({} msgs)".format(i, r["turn_log_orphans"][i]) for i in list(r["turn_log_orphans"])[:50]]
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    db_path = args.db or default_db_path()
    if not db_path or not os.path.isfile(db_path):
        print("conversations.db not found (use --db)", file=sys.stderr)
        return 2
    blob_map, rows_map, traces = load_maps(db_path)
    r = reconcile(blob_map, rows_map, traces)
    text = to_markdown(r, db_path)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print("report ->", args.out)
    else:
        logging.getLogger("app").info(text)
    return 0 if r["consistent"] else 1


if __name__ == "__main__":
    sys.exit(main())
