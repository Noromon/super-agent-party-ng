# -*- coding: utf-8 -*-
"""S160: eos-contamination patrol & scrub CLI (dry-run by default).

Thin wrapper over py/eos_patrol.py (the GUI 潜龙勿用 panel shares the same engine;
topic notes: doc/quarantine/, deletable wholesale). Output is MASKED by design:
locations and counts only, never matched text.

Usage:
  python scripts/scrub_special_tokens.py                # dry-run, exit 1 if hits found
  python scripts/scrub_special_tokens.py --apply        # backup + quarantine originals, scrub
  python scripts/scrub_special_tokens.py --data-dir DIR # override SAP data dir
  python scripts/scrub_special_tokens.py --extra PATH   # additionally scan a file/dir (repeatable)
  python scripts/scrub_special_tokens.py --list         # quarantine inventory
  python scripts/scrub_special_tokens.py --restore-plan TS / --restore TS

Stop the server before --apply / --restore.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from py.eos_patrol import (  # noqa: E402
    apply_scrub, list_quarantine, plan_restore, resolve_data_dir, run_restore, scan,
)


def _print_report(rep):
    print(f"mode={rep['mode']}  stores_with_hits={len(rep['stores'])}  total={rep['total']}")
    for label in sorted(rep["stores"], key=lambda k: -sum(rep["stores"][k])):
        s, n = rep["stores"][label]
        print(f"  shapes={s:<5} names={n:<5} {label}")
    if rep.get("backup_dir"):
        print(f"backups -> {rep['backup_dir']}")
    if rep.get("quarantine_file"):
        print(f"quarantined {rep['records']} originals -> {rep['quarantine_file']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="backup, quarantine, then scrub (stop server first)")
    ap.add_argument("--data-dir", default=None)
    ap.add_argument("--extra", action="append", default=[])
    ap.add_argument("--list", action="store_true", help="list quarantine inventory and exit")
    ap.add_argument("--restore-plan", metavar="TS", default=None, help="show restore plan for backup ts")
    ap.add_argument("--restore", metavar="TS", default=None, help="execute restore for backup ts (stop server first)")
    args = ap.parse_args()
    data_dir = resolve_data_dir(args.data_dir)
    print(f"data dir: {data_dir}")
    if args.list:
        inv = list_quarantine(data_dir)
        print(f"quarantine dir: {inv['quarantine_dir']}")
        for b in inv["backups"]:
            print(f"  backup {b['ts']}: {len(b['files'])} files")
        for q in inv["quarantine_files"]:
            print(f"  quarantine {q['name']}: {q['records']} records")
        print(f"  stats runs recorded: {inv['stats_runs']}")
        return
    if args.restore_plan:
        plan = plan_restore(args.restore_plan, data_dir)
        print(f"restore plan for {plan['ts']}:")
        print(f"  row updates: {plan['total_rows']} {plan['db_row_updates']}")
        print(f"  file copies ({plan['total_files']}): {plan['file_copies']}")
        print("  WARNING: overwrites current rows/files; run with the server stopped.")
        return
    if args.restore:
        res = run_restore(args.restore, data_dir)
        print(f"restored rows={res['rows_restored']} missing={res['rows_missing']} "
              f"files={res['files_restored']} pre_restore_backup={res['pre_restore_backup']}")
        return
    rep = apply_scrub(data_dir, args.extra) if args.apply else scan(data_dir, args.extra)
    _print_report(rep)
    sys.exit(1 if rep["total"] else 0)


if __name__ == "__main__":
    main()
