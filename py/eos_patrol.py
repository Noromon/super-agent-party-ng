# -*- coding: utf-8 -*-
"""S160: eos-contamination patrol engine (shared by scripts/scrub_special_tokens.py CLI
and the /api/eos_guard GUI panel; topic notes: doc/quarantine/, deletable wholesale).

Masked by design: reports carry store labels and counts only, never matched text - a scan
or its output must never become a contamination source itself.

Safety contract (GUI shows the plan + warnings before any of this):
- nothing is modified unless apply=True;
- every file about to change is first copied into <qdir>/backup-<ts>/ (dbs together with
  their -wal/-shm siblings);
- replaced rows/entries are appended to <qdir>/eos-contamination-<ts>.json before rewrite,
  giving a row-level restore path (run_restore) as the regret pill;
- FAISS/pkl binaries are reported only - rebuild via the documented memory-repair flow.
"""
import json
import os
import shutil
import sqlite3
import time

from py.token_guard import detect, neutralize

APP_NAME = "Super-Agent-Party"
_DB_SIDECAR_SUFFIXES = (".db", ".db-wal", ".db-shm")


def resolve_data_dir(cli_dir=None):
    if cli_dir:
        return os.path.abspath(cli_dir)
    env = os.environ.get("SAP_DATA_DIR")
    cands = []
    if env:
        cands.append(os.path.abspath(env))
    appdata = os.environ.get("APPDATA")
    if appdata:
        outer = os.path.join(appdata, APP_NAME)
        cands.extend([os.path.join(outer, APP_NAME), outer])
    for c in cands:
        if os.path.isdir(c) and (os.path.exists(os.path.join(c, "super_agent_party.db"))
                                 or os.path.exists(os.path.join(c, "conversations.db"))):
            return c
    for c in cands:
        if os.path.isdir(c):
            return c
    raise RuntimeError("SAP data dir not found; pass data_dir explicitly")


def _mem0_history_db():
    """mem0 审计库路径；EOS_MEM0_DB 可覆盖（测试/多实例隔离用，置空串=跳过该库）。"""
    env = os.environ.get("EOS_MEM0_DB")
    if env is not None:
        return env
    return os.path.join(os.path.expanduser("~"), ".mem0", "history.db")


class Patrol:
    def __init__(self, apply_changes=False, data_dir=None, extras=()):
        self.apply = bool(apply_changes)
        self.data_dir = resolve_data_dir(data_dir)
        self.extras = list(extras or [])
        self.ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        self.qdir = os.path.join(self.data_dir, "quarantine")
        self.backup_dir = os.path.join(self.qdir, f"backup-{self.ts}") if self.apply else None
        self.hits = {}
        self.records = []
        self._backed_up = set()

    # ---------------- bookkeeping ----------------
    def note(self, label, s, n):
        if s or n:
            slot = self.hits.setdefault(label, [0, 0])
            slot[0] += s
            slot[1] += n

    def _backup_file(self, path):
        if not self.apply or path in self._backed_up:
            return
        os.makedirs(self.backup_dir, exist_ok=True)
        for suffix in ("", "-wal", "-shm"):
            src = path + suffix
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(self.backup_dir, os.path.basename(src)))
        self._backed_up.add(path)

    # ---------------- stores ----------------
    def scan_db(self, path, scrub):
        if not os.path.exists(path):
            return
        try:
            if scrub:
                con = sqlite3.connect(path)
            else:
                con = sqlite3.connect("file:///" + path.replace("\\", "/") + "?mode=ro", uri=True)
        except Exception as e:
            print(f"ERR  {os.path.basename(path)}: {e}")
            return
        cur = con.cursor()
        try:
            tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type=?", ("table",))]
        except Exception as e:
            print(f"ERR  {os.path.basename(path)}: {e}")
            con.close()
            return
        touched = False
        for t in tables:
            try:
                rows = cur.execute(f'SELECT rowid,* FROM "{t}"').fetchall()
                cols = [d[0] for d in cur.description][1:]
            except Exception:
                continue
            for r in rows:
                rid, vals = r[0], list(r[1:])
                cleaned = {}
                s_all = n_all = 0
                for i, v in enumerate(vals):
                    if not isinstance(v, str):
                        continue
                    s, n = detect(v)
                    if s or n:
                        s_all += s
                        n_all += n
                        cleaned[i] = neutralize(v, f"scrub:{t}")
                self.note(f"{os.path.basename(path)}:{t}", s_all, n_all)
                if cleaned and scrub:
                    self._backup_file(path)
                    touched = True
                    self.records.append({
                        "kind": "db", "db": path, "table": t, "rowid": rid,
                        "originals": {cols[i]: vals[i] for i in cleaned},
                    })
                    sets = ", ".join(f'"{cols[i]}"=?' for i in cleaned)
                    cur.execute(f'UPDATE "{t}" SET {sets} WHERE rowid=?',
                                [cleaned[i] for i in cleaned] + [rid])
        if scrub and touched:
            con.commit()
        con.close()

    def scan_json_file(self, path, scrub):
        if not os.path.exists(path):
            return
        try:
            text = open(path, "rb").read().decode("utf-8", "ignore")
        except Exception:
            return
        s, n = detect(text)
        self.note(os.path.relpath(path, self.data_dir).replace("\\", "/"), s, n)
        if not (s or n) or not scrub:
            return
        try:
            data = json.loads(text)
        except Exception:
            print(f"SKIP {os.path.basename(path)}: JSON unparseable, manual review")
            return
        originals = []

        def walk(obj):
            if isinstance(obj, dict):
                return {k: walk(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [walk(x) for x in obj]
            if isinstance(obj, str):
                hit = detect(obj)
                if hit[0] or hit[1]:
                    originals.append(obj)
                    return neutralize(obj, "scrub:json")
                return obj
            return obj

        scrubbed = walk(data)
        self._backup_file(path)
        self.records.append({"kind": "file", "path": path, "originals": originals})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(scrubbed, f, ensure_ascii=False, indent=4)

    def scan_binary_report_only(self, path):
        try:
            text = open(path, "rb").read().decode("utf-8", "ignore")
        except Exception:
            return
        s, n = detect(text)
        if s or n:
            self.note(os.path.basename(path) + " (report-only)", s, n)

    # ---------------- sweep ----------------
    def run(self):
        for p in (os.path.join(self.data_dir, "super_agent_party.db"),
                  os.path.join(self.data_dir, "conversations.db"),
                  _mem0_history_db()):
            self.scan_db(p, self.apply)
        for sub in ("diary", "backups"):
            root = os.path.join(self.data_dir, sub)
            if not os.path.isdir(root):
                continue
            for dp, dn, fn in os.walk(root):
                for f in fn:
                    p = os.path.join(dp, f)
                    if f.endswith(".json") and not f.endswith(".bak"):
                        self.scan_json_file(p, self.apply)
                    elif f.endswith(".db"):
                        self.scan_db(p, self.apply)
                    elif f.endswith((".pkl", ".faiss")):
                        self.scan_binary_report_only(p)
        mc = os.path.join(self.data_dir, "memory_cache")
        if os.path.isdir(mc):
            for dp, dn, fn in os.walk(mc):
                for f in fn:
                    p = os.path.join(dp, f)
                    if f.endswith(".db"):
                        self.scan_db(p, self.apply)
                    elif f.endswith((".pkl", ".faiss")):
                        self.scan_binary_report_only(p)
        for p in self.extras:
            if os.path.isdir(p):
                for dp, dn, fn in os.walk(p):
                    dn[:] = [x for x in dn if x.lower() not in ("node_modules", ".venv", "__pycache__")]
                    for f in fn:
                        fp = os.path.join(dp, f)
                        try:
                            if os.path.getsize(fp) > 64 * 1024 * 1024:
                                continue
                        except OSError:
                            continue
                        if f.endswith(".json"):
                            self.scan_json_file(fp, self.apply)
                        elif f.endswith(".db"):
                            self.scan_db(fp, self.apply)
                        else:
                            self.scan_binary_report_only(fp)
            elif os.path.isfile(p):
                self.scan_binary_report_only(p)

    def report(self):
        total = sum(s + n for s, n in self.hits.values())
        out = {"ts": self.ts, "mode": "apply" if self.apply else "dry-run",
               "stores": self.hits, "total": total,
               "backup_dir": None, "quarantine_file": None}
        os.makedirs(self.qdir, exist_ok=True)
        with open(os.path.join(self.qdir, "stats.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": self.ts, "mode": out["mode"],
                                "stores": self.hits, "total": total}, ensure_ascii=False) + "\n")
        if self.apply and self.records:
            qf = os.path.join(self.qdir, f"eos-contamination-{self.ts}.json")
            with open(qf, "w", encoding="utf-8") as f:
                json.dump(self.records, f, ensure_ascii=False, indent=2)
            out["backup_dir"] = self.backup_dir
            out["quarantine_file"] = qf
            out["records"] = len(self.records)
        return out


def scan(data_dir=None, extras=()):
    p = Patrol(False, data_dir, extras)
    p.run()
    return p.report()


def apply_scrub(data_dir=None, extras=()):
    p = Patrol(True, data_dir, extras)
    p.run()
    return p.report()


# ---------------- quarantine inventory & row-level restore ----------------

def _qdir(data_dir=None):
    return os.path.join(resolve_data_dir(data_dir), "quarantine")


def list_quarantine(data_dir=None):
    qd = _qdir(data_dir)
    out = {"quarantine_dir": qd, "backups": [], "quarantine_files": [], "stats_runs": 0}
    if not os.path.isdir(qd):
        return out
    for name in sorted(os.listdir(qd)):
        full = os.path.join(qd, name)
        if os.path.isdir(name and full) and name.startswith("backup-"):
            out["backups"].append({"ts": name[len("backup-"):],
                                   "dir": name,
                                   "files": sorted(os.listdir(full))})
        elif name.startswith("eos-contamination-") and name.endswith(".json"):
            try:
                with open(full, encoding="utf-8") as f:
                    recs = json.load(f)
                out["quarantine_files"].append({"name": name, "ts": name[len("eos-contamination-"):-len(".json")],
                                                "records": len(recs)})
            except Exception:
                out["quarantine_files"].append({"name": name, "ts": None, "records": -1})
    stats = os.path.join(qd, "stats.jsonl")
    if os.path.exists(stats):
        with open(stats, encoding="utf-8") as f:
            out["stats_runs"] = sum(1 for _ in f)
    return out


def _load_ts_pair(qd, backup_ts):
    bdir = os.path.join(qd, f"backup-{backup_ts}")
    qf = os.path.join(qd, f"eos-contamination-{backup_ts}.json")
    records = []
    if os.path.exists(qf):
        with open(qf, encoding="utf-8") as f:
            records = json.load(f)
    return bdir, qf, records


def plan_restore(backup_ts, data_dir=None):
    """What 灌回 would do: row-level UPDATEs from quarantine + file copies from backup."""
    qd = _qdir(data_dir)
    bdir, qf, records = _load_ts_pair(qd, backup_ts)
    if not records and not os.path.isdir(bdir):
        raise FileNotFoundError(f"no quarantine/backup with ts {backup_ts}")
    db_rows = {}
    for rec in records:
        if rec.get("kind") == "db":
            key = f"{os.path.basename(rec['db'])}:{rec['table']}"
            db_rows[key] = db_rows.get(key, 0) + 1
    files = []
    if os.path.isdir(bdir):
        for name in sorted(os.listdir(bdir)):
            if name.endswith(_DB_SIDECAR_SUFFIXES):
                continue  # dbs restore row-level, never by file swap
            files.append(name)
    return {"ts": backup_ts, "quarantine_file": qf if records else None,
            "db_row_updates": db_rows, "file_copies": files,
            "total_rows": sum(db_rows.values()), "total_files": len(files)}


def run_restore(backup_ts, data_dir=None):
    """Execute the regret pill. Row-level UPDATE restores (live-safe: same per-call
    connection pattern as the scrub itself); non-db files copied back after snapshotting
    the current versions into backup-pre-restore-<ts>."""
    qd = _qdir(data_dir)
    bdir, qf, records = _load_ts_pair(qd, backup_ts)
    result = {"ts": backup_ts, "rows_restored": 0, "rows_missing": 0,
              "files_restored": 0, "pre_restore_backup": None}
    by_db = {}
    for rec in records:
        if rec.get("kind") == "db":
            by_db.setdefault(rec["db"], []).append(rec)
    for dbpath, recs in by_db.items():
        if not os.path.exists(dbpath):
            result["rows_missing"] += len(recs)
            continue
        con = sqlite3.connect(dbpath)
        cur = con.cursor()
        try:
            for rec in recs:
                cols = list(rec["originals"].keys())
                if not cols:
                    continue
                sets = ", ".join(f'"{c}"=?' for c in cols)
                cur.execute(f'UPDATE "{rec["table"]}" SET {sets} WHERE rowid=?',
                            [rec["originals"][c] for c in cols] + [rec["rowid"]])
                if cur.rowcount:
                    result["rows_restored"] += 1
                else:
                    result["rows_missing"] += 1
            con.commit()
        finally:
            con.close()
    if os.path.isdir(bdir):
        copy_back = [n for n in sorted(os.listdir(bdir)) if not n.endswith(_DB_SIDECAR_SUFFIXES)]
        if copy_back:
            pre = os.path.join(qd, "backup-pre-restore-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
            os.makedirs(pre, exist_ok=True)
            result["pre_restore_backup"] = pre
            # figure out original targets from records (kind=file) by basename
            target_by_name = {}
            for rec in records:
                if rec.get("kind") == "file":
                    target_by_name[os.path.basename(rec["path"])] = rec["path"]
            for name in copy_back:
                src = os.path.join(bdir, name)
                target = target_by_name.get(name)
                if not target:
                    continue  # unknown target (e.g. sidecar of backup dbs) - never blind-copy
                if os.path.exists(target):
                    shutil.copy2(target, os.path.join(pre, name))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(src, target)
                result["files_restored"] += 1
    return result
