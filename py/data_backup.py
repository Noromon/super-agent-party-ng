# -*- coding: utf-8 -*-
"""M4-lite: 数据目录滚动快照 + 恢复演练（对话库/设置/记忆 = 数据丢失最后防线）。

设计约束：
- 只读源数据（sqlite backup API 对 WAL 安全），只写 <data_dir>/backups/ 子目录；
- 滚动清理严格围栏在 backups/ 内、仅 snap-* 目录；
- uploaded_files 默认不纳入（backupIncludeUploads 开关），asr/tts/ebd/ext/logs/tool_temp 属可再生/非对话数据不纳入；
- 恢复 UI 不做（演练/手工语义），生产恢复=显式 restore_snapshot(overwrite=True)。
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

BACKUP_SUBDIR = "backups"
_SNAP_PREFIX = "snap-"
_CORE_DIRS = ("memory_cache", "agents", "kb")
_PRUNE_KEEP_MIN = 2


def backups_root(data_dir: str) -> str:
    return os.path.join(os.path.abspath(data_dir), BACKUP_SUBDIR)


def _snap_name(now_dt=None) -> str:
    dt = now_dt or datetime.now(timezone.utc)
    return dt.strftime(_SNAP_PREFIX + "%Y%m%dT%H%M%S") + f"{dt.microsecond // 1000:03d}Z"


def list_snapshots(data_dir: str) -> list:
    """按时间升序返回 [{name,path,bytes,files,partial}]。"""
    root = backups_root(data_dir)
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        p = os.path.join(root, name)
        if not (name.startswith(_SNAP_PREFIX) and os.path.isdir(p)):
            continue
        total, count, partial = 0, 0, False
        for base, _dirs, files in os.walk(p):
            for f in files:
                if f == "manifest.json":
                    continue
                try:
                    total += os.path.getsize(os.path.join(base, f))
                    count += 1
                except OSError:
                    pass
        partial = not os.path.exists(os.path.join(p, "manifest.json"))
        out.append({"name": name, "path": p, "bytes": total, "files": count, "partial": partial})
    return out


def should_snapshot(data_dir: str, min_interval_sec: float = 3600.0, now: float = None) -> bool:
    if min_interval_sec <= 0:
        return True
    snaps = list_snapshots(data_dir)
    if not snaps:
        return True
    import time as _t
    newest = snaps[-1]["path"]
    last = _t.time() if now is None else now
    try:
        mtime = os.path.getmtime(newest)
    except OSError:
        return True
    return (last - mtime) >= min_interval_sec


def _iter_backup_sources(data_dir: str, include_uploads: bool):
    """(relpath, abspath, kind) 迭代器。kind: json|db|dir"""
    data_dir = os.path.abspath(data_dir)
    for entry in sorted(os.listdir(data_dir)):
        src = os.path.join(data_dir, entry)
        if not os.path.isfile(src):
            continue
        if entry.startswith(".") or entry.endswith((".tmp", ".log")):
            continue
        if ".tmp." in entry:  # 原子写残留（*.tmp.<rand>）
            continue
        ext = os.path.splitext(entry)[1].lower()
        if ext == ".json":
            yield entry, src, "json"
        elif ext == ".db":
            yield entry, src, "db"
    for d in _CORE_DIRS + (("uploaded_files",) if include_uploads else ()):
        src = os.path.join(data_dir, d)
        if os.path.isdir(src):
            yield d, src, "dir"


def _backup_one_db(src: str, dst: str) -> str:
    """返回 'sqlite' 或 'raw_copy'（db 打不开时降级文件级复制并在 manifest 标注）。"""
    uri = "file:{}?mode=ro".format(src.replace("?", "%3f"))
    try:
        srccon = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error:
        shutil.copy2(src, dst)
        return "raw_copy"
    try:
        dstcon = sqlite3.connect(dst)
        try:
            with dstcon:
                srccon.backup(dstcon)
        finally:
            dstcon.close()
    except sqlite3.Error:
        # backup API 失败（例如源已损坏）：文件级复制保留现场
        try:
            srccon.close()
        except Exception:
            pass
        shutil.copy2(src, dst)
        return "raw_copy"
    finally:
        try:
            srccon.close()
        except Exception:
            pass
    return "sqlite"


def _copy_one(src: str, dst: str) -> int:
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return os.path.getsize(dst)


def snapshot_data_dir(data_dir: str, keep: int = 5, include_uploads: bool = False,
                      throttle_min_sec: float = 3600.0, now: float = None) -> dict:
    """拍一份滚动快照。返回 {ok, snap|skipped, reason?, bytes, files}。"""
    if not should_snapshot(data_dir, throttle_min_sec, now=now):
        return {"ok": False, "skipped": True, "reason": "throttled"}
    root = backups_root(data_dir)
    snap = os.path.join(root, _snap_name())
    made = False
    for _try in range(6):
        try:
            os.makedirs(snap, exist_ok=False)
            made = True
            break
        except FileExistsError:
            snap = snap + "r"  # 同毫秒连续快照：加后缀重试
        except OSError as e:
            return {"ok": False, "reason": f"mkdir failed: {e}"}
    if not made:
        return {"ok": False, "reason": "snapshot name collision"}
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "include_uploads": bool(include_uploads), "files": {}, "notes": {}}
    total = 0
    had_error = False
    for rel, src, kind in _iter_backup_sources(data_dir, include_uploads):
        try:
            if kind == "db":
                how = _backup_one_db(src, os.path.join(snap, rel))
                manifest["notes"][rel] = how
                total += os.path.getsize(os.path.join(snap, rel))
                manifest["files"][rel] = os.path.getsize(os.path.join(snap, rel))
            elif kind == "json":
                total += _copy_one(src, os.path.join(snap, rel))
                manifest["files"][rel] = os.path.getsize(os.path.join(snap, rel))
            else:  # dir
                dir_bytes = 0
                for base, _dirs, files in os.walk(src):
                    relbase = os.path.relpath(base, src)
                    for f in files:
                        s = os.path.join(base, f)
                        d = os.path.join(snap, rel, relbase if relbase != "." else "", f)
                        try:
                            dir_bytes += _copy_one(s, d)
                            manifest["files"][os.path.join(rel, relbase if relbase != "." else "", f).replace("\\", "/")] = os.path.getsize(s)
                        except OSError as fe:
                            had_error = True
                            manifest["notes"][f"skip:{rel}/{relbase}/{f}"] = str(fe)
                total += dir_bytes
        except Exception as e:
            had_error = True
            manifest["notes"][f"error:{rel}"] = str(e)
    manifest["bytes"] = total
    manifest["partial"] = bool(had_error)
    with open(os.path.join(snap, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    pruned = _prune(data_dir, keep)
    return {"ok": not had_error, "partial": had_error, "snap": snap,
            "bytes": total, "files": len(manifest["files"]), "pruned": pruned}


def _prune(data_dir: str, keep: int) -> list:
    """滚动删除：只碰 backups/ 下 snap-* 目录，keep 下限 2 防手滑清零。"""
    keep = max(int(keep or 5), _PRUNE_KEEP_MIN)
    snaps = list_snapshots(data_dir)
    removed = []
    if len(snaps) > keep:
        root = os.path.abspath(backups_root(data_dir))
        for s in snaps[: len(snaps) - keep]:
            p = os.path.abspath(s["path"])
            if p.startswith(root + os.sep) and os.path.basename(p).startswith(_SNAP_PREFIX):
                try:
                    shutil.rmtree(p)
                    removed.append(s["name"])
                except OSError:
                    pass
    return removed


def verify_snapshot(snap_dir: str) -> dict:
    """恢复演练：sqlite integrity + JSON parse + manifest 尺寸比对。"""
    checks = []
    ok = True
    mf_path = os.path.join(snap_dir, "manifest.json")
    if not os.path.isfile(mf_path):
        return {"ok": False, "checks": [{"name": "manifest", "ok": False,
                                         "detail": "manifest.json 缺失（半截快照）"}]}
    try:
        with open(mf_path, encoding="utf-8") as f:
            mf = json.load(f)
        checks.append({"name": "manifest", "ok": True, "detail": f"{len(mf.get('files', {}))} files"})
    except Exception as e:
        return {"ok": False, "checks": [{"name": "manifest", "ok": False, "detail": str(e)}]}
    for rel, size in (mf.get("files") or {}).items():
        p = os.path.join(snap_dir, *rel.split("/"))
        if not os.path.isfile(p):
            ok = False
            checks.append({"name": f"file:{rel}", "ok": False, "detail": "missing"})
            continue
        if os.path.getsize(p) != size:
            ok = False
            checks.append({"name": f"file:{rel}", "ok": False,
                           "detail": f"size {os.path.getsize(p)} != manifest {size}"})
        if rel.lower().endswith(".json"):
            try:
                with open(p, encoding="utf-8") as f:
                    json.load(f)
            except Exception as e:
                ok = False
                checks.append({"name": f"json:{rel}", "ok": False, "detail": str(e)})
        elif rel.lower().endswith(".db"):
            try:
                con = sqlite3.connect("file:{}?mode=ro".format(p.replace("?", "%3f")),
                                      uri=True, timeout=5)
                try:
                    row = con.execute("PRAGMA integrity_check").fetchone()
                    if not row or row[0] != "ok":
                        ok = False
                        checks.append({"name": f"db:{rel}", "ok": False,
                                       "detail": str(row[0] if row else "no result")})
                finally:
                    con.close()
            except Exception as e:
                ok = False
                checks.append({"name": f"db:{rel}", "ok": False, "detail": str(e)})
    if not ok and all(c["ok"] for c in checks):
        ok = False
    return {"ok": ok, "checks": checks}


def restore_snapshot(snap_dir: str, target_dir: str, overwrite: bool = False) -> dict:
    """文件级回拷（演练/手工语义）。目标非空且未 overwrite → 拒绝。"""
    v = verify_snapshot(snap_dir)
    if not v["ok"]:
        return {"ok": False, "reason": "snapshot failed verification", "verify": v}
    mf = json.load(open(os.path.join(snap_dir, "manifest.json"), encoding="utf-8"))
    target_dir = os.path.abspath(target_dir)
    if not overwrite:
        for rel in (mf.get("files") or {}):
            if os.path.exists(os.path.join(target_dir, *rel.split("/"))):
                return {"ok": False, "reason": f"target exists: {rel}（需 overwrite=True）"}
    restored = 0
    for rel in (mf.get("files") or {}):
        s = os.path.join(snap_dir, *rel.split("/"))
        d = os.path.join(target_dir, *rel.split("/"))
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.copy2(s, d)
        restored += 1
    return {"ok": True, "restored": restored}
