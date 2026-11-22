# -*- coding: utf-8 -*-
"""M4-lite: 数据目录滚动快照 + 恢复演练（对话库/设置/记忆 = 数据丢失最后防线）。

设计约束：
- 只读源数据（sqlite backup API 对 WAL 安全），只写 <data_dir>/backups/ 子目录；
- 滚动清理严格围栏在 backups/ 内、仅 snap-* 目录，且 S280 起只对 auto 快照计数/删除
  ——手动快照（trigger=manual）永久保留、永不自动清理或覆盖；
- 备份内容=S280 内容项目录（BACKUP_ITEMS，10 项，见 item_of_rel），asr/tts/ebd/logs/
  tool_temp/screen_watch 等可再生数据不纳入；include 集合可按项裁剪；
- 恢复 UI 不做（演练/手工语义），生产恢复=显式 restore_snapshot(overwrite=True)。
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone

BACKUP_SUBDIR = "backups"
_SNAP_PREFIX = "snap-"
# S267 审计：diary 曾被 500 上限 FIFO 挤压 yet 完全不在快照内（丢失不可恢复，
# 仅靠手工 bak 救回 85 条）；ext 含用户自装/自建扩展数据。均纳入核心目录。
_CORE_DIRS = ("memory_cache", "agents", "kb", "diary", "ext")
_PRUNE_KEEP_MIN = 2

# ---- S280：备份内容项目录（前端"备份内容与容量"面板共用同一 id 集）----
BACKUP_ITEM_IDS = ("settings", "appdb", "convdb", "txtidx",
                   "memory_cache", "agents", "kb", "diary", "ext", "uploads")
# 目录项 id → 数据目录内实际目录名
_ITEM_DIRS = {"memory_cache": "memory_cache", "agents": "agents", "kb": "kb",
              "diary": "diary", "ext": "ext", "uploads": "uploaded_files"}


def item_of_rel(rel: str) -> str:
    """快照内相对路径 → 内容项 id。顶层 json=设置与状态；两个具名 db 独立成项
    （会话历史体量最大、用户最需要单独控制）；其余 db 归应用库；txt=工作区索引。"""
    rel = str(rel).replace("\\", "/")
    head, _, rest = rel.partition("/")
    if rest:
        for item_id, dname in _ITEM_DIRS.items():
            if head == dname:
                return item_id
        return "other"
    if head == "conversations.db":
        return "convdb"
    if head.endswith(".db"):
        return "appdb"
    if head.endswith(".txt"):
        return "txtidx"
    return "settings"


def backups_root(data_dir: str) -> str:
    return os.path.join(os.path.abspath(data_dir), BACKUP_SUBDIR)


def _snap_name(now_dt=None) -> str:
    dt = now_dt or datetime.now(timezone.utc)
    return dt.strftime(_SNAP_PREFIX + "%Y%m%dT%H%M%S") + f"{dt.microsecond // 1000:03d}Z"


def _manifest_brief(snap_path: str) -> tuple:
    """S280：读 manifest → (trigger, items 聚合)。缺失/损坏一律按 auto、空构成——
    与历史旧快照（皆为启动自动产生）一致，可被正常修剪。"""
    mf = os.path.join(snap_path, "manifest.json")
    if not os.path.isfile(mf):
        return "auto", {}
    try:
        with open(mf, encoding="utf-8") as f:
            m = json.load(f)
        trigger = "manual" if m.get("trigger") == "manual" else "auto"
        agg = {}
        for rel, sz in (m.get("files") or {}).items():
            k = item_of_rel(rel)
            try:
                agg[k] = agg.get(k, 0) + int(sz or 0)
            except (TypeError, ValueError):
                pass
        return trigger, agg
    except Exception:
        return "auto", {}


def list_snapshots(data_dir: str) -> list:
    """按时间升序返回 [{name,path,bytes,files,partial,trigger,items}]。"""
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
        trigger, items = _manifest_brief(p)
        out.append({"name": name, "path": p, "bytes": total, "files": count,
                    "partial": partial, "trigger": trigger, "items": items})
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


def _iter_backup_sources(data_dir: str, include_uploads: bool, include=None):
    """(relpath, abspath, kind) 迭代器。kind: json|db|txt|dir。

    S280：include=内容项 id 集合时以其为准（include_uploads 被覆盖；uploads 项
    直接对应 uploaded_files 目录）；include=None 保持库层旧语义（核心目录 + 按
    include_uploads 决定是否带上传文件），旧调用方零破坏。"""
    data_dir = os.path.abspath(data_dir)
    sel = None if include is None else set(include)
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
            kind = "json"
        elif ext == ".db":
            kind = "db"
        elif ext == ".txt":
            # S267: tool_output_workspaces.txt（工作区注册表）曾被扩展白名单漏掉
            kind = "txt"
        else:
            continue
        if sel is not None and item_of_rel(entry) not in sel:
            continue
        yield entry, src, kind
    dirs = tuple(_CORE_DIRS) + (("uploaded_files",) if include_uploads else ())
    if sel is not None:
        want = {d for d in dirs if d in {v for k, v in _ITEM_DIRS.items() if k in sel}}
        if "uploads" in sel:
            want.add("uploaded_files")
        # 保序输出
        order = tuple(_CORE_DIRS) + ("uploaded_files",)
        dirs = tuple(d for d in order if d in want)
    for d in dirs:
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
                      throttle_min_sec: float = 3600.0, now: float = None,
                      trigger: str = "auto", include=None) -> dict:
    """拍一份滚动快照。trigger='manual' 的快照永久保留（S280）：修剪只碰 auto。
    include=内容项 id 列表时按其裁剪（见 _iter_backup_sources）。
    返回 {ok, snap|skipped, reason?, bytes, files, trigger}。"""
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
    trig = "manual" if trigger == "manual" else "auto"
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(),
                "include_uploads": bool(include_uploads), "trigger": trig,
                "files": {}, "notes": {}}
    total = 0
    had_error = False
    for rel, src, kind in _iter_backup_sources(data_dir, include_uploads, include):
        try:
            if kind == "db":
                how = _backup_one_db(src, os.path.join(snap, rel))
                manifest["notes"][rel] = how
                total += os.path.getsize(os.path.join(snap, rel))
                manifest["files"][rel] = os.path.getsize(os.path.join(snap, rel))
            elif kind in ("json", "txt"):
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
    # 实际生效的内容项构成（从落盘清单反推，任何调用路径都真实）
    manifest["include"] = sorted({item_of_rel(k) for k in manifest["files"]})
    with open(os.path.join(snap, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=1)
    pruned = _prune(data_dir, keep)
    return {"ok": not had_error, "partial": had_error, "snap": snap,
            "bytes": total, "files": len(manifest["files"]), "pruned": pruned,
            "trigger": trig, "include": manifest["include"]}


def _prune(data_dir: str, keep: int) -> list:
    """滚动删除：只碰 backups/ 下 snap-* 目录，keep 下限 2 防手滑清零。
    S280：keep 只约束 auto 快照；手动快照（manifest.trigger=manual）永久保留；
    无 manifest/无 trigger 的旧快照按 auto 处理（历史皆启动自动产生）。"""
    keep = max(int(keep or 5), _PRUNE_KEEP_MIN)
    snaps = list_snapshots(data_dir)
    autos = [s for s in snaps if s.get("trigger") != "manual"]
    removed = []
    if len(autos) > keep:
        root = os.path.abspath(backups_root(data_dir))
        for s in autos[: len(autos) - keep]:
            p = os.path.abspath(s["path"])
            if p.startswith(root + os.sep) and os.path.basename(p).startswith(_SNAP_PREFIX):
                try:
                    shutil.rmtree(p)
                    removed.append(s["name"])
                except OSError:
                    pass
    return removed


def estimate_sizes(data_dir: str) -> dict:
    """S280：备份前评估——按内容项统计当前占地（字节/文件数）+ 预计合计 + 磁盘余量。

    注意：SQLite 以 db+wal+shm 实际文件尺寸估算；快照经 backup API 重写后尺寸会
    因空闲页回收略有出入，此处是上限近似的规划值，非承诺值。"""
    data_dir = os.path.abspath(data_dir)
    agg = {i: {"bytes": 0, "files": 0} for i in BACKUP_ITEM_IDS}

    def add(item, size, n=1):
        if item in agg:
            agg[item]["bytes"] += int(size)
            agg[item]["files"] += n

    try:
        entries = sorted(os.listdir(data_dir))
    except OSError:
        entries = []
    for entry in entries:
        src = os.path.join(data_dir, entry)
        if os.path.isfile(src):
            if entry.startswith(".") or entry.endswith((".tmp", ".log")) or ".tmp." in entry:
                continue
            ext = os.path.splitext(entry)[1].lower()
            if ext not in (".json", ".db", ".txt"):
                continue
            try:
                sz = os.path.getsize(src)
            except OSError:
                continue
            if ext == ".db":
                for suf in ("-wal", "-shm"):  # WAL 未合并数据也在快照内（backup API）
                    try:
                        if os.path.isfile(src + suf):
                            sz += os.path.getsize(src + suf)
                    except OSError:
                        pass
            add(item_of_rel(entry), sz)
        elif os.path.isdir(src):
            for item_id, dname in _ITEM_DIRS.items():
                if entry != dname:
                    continue
                for base, _dirs, files in os.walk(src):
                    for f in files:
                        try:
                            add(item_id, os.path.getsize(os.path.join(base, f)))
                        except OSError:
                            pass
    try:
        free = int(shutil.disk_usage(data_dir).free)
    except OSError:
        free = -1
    return {"items": [{"id": i, "bytes": agg[i]["bytes"], "files": agg[i]["files"]}
                      for i in BACKUP_ITEM_IDS],
            "total": sum(v["bytes"] for v in agg.values()),
            "disk_free": free, "data_dir": data_dir}


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
