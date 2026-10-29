# -*- coding: utf-8 -*-
"""S160 潜龙勿用: EOS-contamination defense panel endpoints.

Two-step dangerous-action protocol (GUI 展示变更 → 警告 → 确认, enforced server-side too):
mutating actions (scrub apply, quarantine restore) require a one-shot confirm_token minted
by the preceding plan/scan call; applying with a stale token, or whose drift re-scan differs
from the confirmed report, is refused with 409 and a fresh report+token. The engine itself
(py/eos_patrol.py) always backs up before touching anything and keeps originals in the
quarantine dir for the row-level 灌回 restore.
"""
import asyncio
import logging
import secrets

from fastapi import APIRouter, Body, HTTPException

from py import eos_patrol
from py import token_guard
from py.get_setting import load_settings

logger = logging.getLogger("app")
router = APIRouter()

_pending_scan = {}     # {token, report}
_pending_restore = {}  # {token, ts, plan}


@router.get("/api/eos_guard/status")
async def eos_guard_status():
    settings = await load_settings()
    cfg = settings.get("eosGuard") or {}
    return {
        "eosGuard": {"enabled": bool(cfg.get("enabled", False)),
                     "sanitize": bool(cfg.get("sanitize", True)),
                     "softBias": cfg.get("softBias", -30),
                     "eosTokenIds": cfg.get("eosTokenIds", [])},
        "sanitizeActive": token_guard.is_sanitize_enabled(),
        "stats": token_guard.get_stats(),
        "lastScan": _pending_scan.get("report"),
    }


@router.post("/api/eos_guard/scan")
async def eos_guard_scan():
    try:
        report = await asyncio.to_thread(eos_patrol.scan)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"scan failed: {e}")
    token = secrets.token_hex(8)
    _pending_scan.clear()
    _pending_scan.update({"token": token, "report": report})
    return {"report": report, "confirm_token": token}


@router.post("/api/eos_guard/apply")
async def eos_guard_apply(payload: dict = Body(...)):
    token = (payload or {}).get("confirm_token") or ""
    if not _pending_scan or not secrets.compare_digest(str(_pending_scan.get("token", "")), str(token)):
        raise HTTPException(status_code=400, detail="confirm_token missing/stale; run scan first")
    confirmed = _pending_scan["report"]
    # drift guard: data must still look exactly like what the user confirmed
    fresh = await asyncio.to_thread(eos_patrol.scan)
    if fresh["total"] != confirmed["total"] or fresh["stores"] != confirmed["stores"]:
        new_token = secrets.token_hex(8)
        _pending_scan.clear()
        _pending_scan.update({"token": new_token, "report": fresh})
        raise HTTPException(status_code=409,
                            detail="data changed since scan; re-confirm required")
    _pending_scan.clear()
    result = await asyncio.to_thread(eos_patrol.apply_scrub)
    logger.info(f"[eos-guard] GUI apply ts={result['ts']} records={result.get('records', 0)}")
    return {"result": result}


@router.get("/api/eos_guard/quarantine")
async def eos_guard_quarantine():
    try:
        return await asyncio.to_thread(eos_patrol.list_quarantine)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"quarantine list failed: {e}")


@router.post("/api/eos_guard/restore/plan")
async def eos_guard_restore_plan(payload: dict = Body(...)):
    backup_ts = (payload or {}).get("backup_ts") or ""
    try:
        plan = await asyncio.to_thread(eos_patrol.plan_restore, backup_ts)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="unknown backup ts")
    token = secrets.token_hex(8)
    _pending_restore.clear()
    _pending_restore.update({"token": token, "ts": backup_ts, "plan": plan})
    return {"plan": plan, "confirm_token": token}


@router.post("/api/eos_guard/restore")
async def eos_guard_restore(payload: dict = Body(...)):
    token = (payload or {}).get("confirm_token") or ""
    if not _pending_restore or not secrets.compare_digest(str(_pending_restore.get("token", "")), str(token)):
        raise HTTPException(status_code=400, detail="confirm_token missing/stale; run restore/plan first")
    backup_ts = _pending_restore["ts"]
    _pending_restore.clear()
    try:
        result = await asyncio.to_thread(eos_patrol.run_restore, backup_ts)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"restore failed: {e}")
    logger.warning(f"[eos-guard] GUI restore executed ts={backup_ts} rows={result['rows_restored']}")
    return {"result": result}
