# -*- coding: utf-8 -*-
"""S161: 长期记忆 + 日记 导出/跨角色卡导入。

实体模型：角色=记忆卡=日记本 三位一体（book_id == memories[].id，
日记系统为每张记忆卡自动建本），故导入目标=一张记忆卡，两类数据各归其位。

- 导出=文本级 JSON 包（不搬 faiss 索引 → 跨设备/跨 embedding 模型可移植；
  mem0 history.db 审计不回灌）。
- 导入=用户显式选择目标卡（必选，不预选）；合并=按目标卡现有内容去重；
  覆盖=job 锁内清库重建（含 _m0_cache 失效），前端已做量化二次确认。
- 记忆批量写入=单发 submit_memory_job 内部循环 add(infer=False)：
  逐条投递会被 debounce 互相吞掉（只跑最新一条），禁止。
"""
import asyncio
import json
import logging
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter()

PACK_MARK = 1
PACK_VERSION = 1
MAX_TEXTS = 20000      # 包内记忆文本总条数上限
MAX_TEXT_LEN = 2000    # 单条文本截断
MAX_DIARY_PER_SOURCE = 5000  # 每源日记条数上限
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _valid_id(v) -> bool:
    return isinstance(v, str) and bool(_ID_RE.fullmatch(v))


def _mem_cfg(settings: dict, card_id: str) -> Optional[dict]:
    return next((m for m in (settings.get("memories") or [])
                 if isinstance(m, dict) and m.get("id") == card_id), None)


def _entry_key(e: dict):
    return str(e.get("id") or f"{e.get('time', '')}|{e.get('content', '')}")


def _pack_sources_bytes(sources: List[dict]) -> Response:
    payload = {"sap_backup": PACK_MARK, "version": PACK_VERSION,
               "exported_at": time.time(), "sources": sources}
    fname = f"sap-backup-{time.strftime('%Y%m%d-%H%M%S')}.json"
    return Response(
        content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'})


@router.get("/api/transfer/export")
async def transfer_export(scope: str = "all", card_id: str = ""):
    """导出记忆+日记为 JSON 包。scope=all 全部卡；scope=card 单卡（须存在）。"""
    from py import diary_system
    from py.get_setting import load_settings
    from py.routers.memories import _m0_crud_lock
    import py.llm_gate as llm_gate

    settings = await load_settings()
    cards = settings.get("memories") or []
    if scope == "card":
        if not _valid_id(card_id) or _mem_cfg(settings, card_id) is None:
            raise HTTPException(status_code=404, detail="card not found")
        cards = [m for m in cards if m.get("id") == card_id]

    sources: List[dict] = []
    for mem in cards:
        mid = mem.get("id")
        if not _valid_id(mid):
            continue
        items: List[dict] = []
        memory_error = False
        if mem.get("providerId"):
            try:
                def _read(_mid=mid, _mem=mem):
                    with _m0_crud_lock:
                        m0 = llm_gate.get_mem0_instance(_mid, _mem, settings)
                        return m0.get_all(user_id=_mid, limit=10000)
                results = await asyncio.to_thread(_read)
                raw = results.get("results", []) if isinstance(results, dict) else (results or [])
                for it in raw:
                    text = (it.get("memory") or "").strip()
                    if text:
                        items.append({"text": text[:MAX_TEXT_LEN],
                                      "created_at": it.get("created_at", "")})
            except Exception as e:
                memory_error = True
                logging.getLogger("app").warning("[Transfer] 导出记忆 %s 失败: %r", mid, e)
        book = await diary_system.load_diary_data(mid)
        entries = (book.get("entries") or [])[-MAX_DIARY_PER_SOURCE:]
        if not items and not entries and not memory_error:
            continue  # 全空卡不进包
        sources.append({"card_id": mid, "card_name": mem.get("name", ""),
                        "memories": items, "diary_entries": entries,
                        "memory_error": memory_error})
    return _pack_sources_bytes(sources)


@router.get("/api/transfer/target_stats")
async def transfer_target_stats(card_id: str):
    """覆盖策略二次确认的量化警示数据。记忆读数失败=返回 -1（未知，不阻断）。"""
    from py import diary_system
    from py.get_setting import load_settings
    from py.routers.memories import _m0_crud_lock
    import py.llm_gate as llm_gate

    if not _valid_id(card_id):
        raise HTTPException(status_code=400, detail="invalid card_id")
    settings = await load_settings()
    mem = _mem_cfg(settings, card_id)
    if mem is None:
        raise HTTPException(status_code=404, detail="card not found")
    memories_n = -1
    if mem.get("providerId"):
        try:

            def _read():
                with _m0_crud_lock:
                    m0 = llm_gate.get_mem0_instance(card_id, mem, settings)
                    return m0.get_all(user_id=card_id, limit=10000)
            results = await asyncio.to_thread(_read)
            raw = results.get("results", []) if isinstance(results, dict) else (results or [])
            memories_n = len(raw)
        except Exception:
            pass
    book = await diary_system.load_diary_data(card_id)
    return {"card_id": card_id, "card_name": mem.get("name", ""),
            "memories": memories_n, "diary": len(book.get("entries") or [])}


class ImportReq(BaseModel):
    payload: Dict[str, Any]
    target_card: str
    strategy: str = "merge"              # merge | replace
    source_ids: Optional[List[str]] = None  # None=包内全部源


@router.post("/api/transfer/import")
async def transfer_import(req: ImportReq):
    from py import diary_system, notification_center
    from py.get_setting import load_settings
    import py.llm_gate as llm_gate

    if req.strategy not in ("merge", "replace"):
        raise HTTPException(status_code=400, detail="strategy 需为 merge/replace")
    payload = req.payload or {}
    if payload.get("sap_backup") != PACK_MARK or payload.get("version") != PACK_VERSION:
        raise HTTPException(status_code=400, detail="不是有效的 SAP 备份包（sap_backup/version 缺失）")
    if not _valid_id(req.target_card):
        raise HTTPException(status_code=400, detail="target_card 非法")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise HTTPException(status_code=400, detail="包内无 sources")
    if req.source_ids is not None:
        sel = set(req.source_ids)
        sources = [s for s in sources if isinstance(s, dict) and s.get("card_id") in sel]

    settings = await load_settings()
    target = _mem_cfg(settings, req.target_card)
    if target is None:
        raise HTTPException(status_code=404, detail="目标角色卡不存在，请先创建或重新选择")

    # ---- 收集/校验包内数据 ----
    texts: List[str] = []
    seen_text = set()
    diary_in: List[dict] = []
    for s in sources:
        if not isinstance(s, dict):
            continue
        for it in (s.get("memories") or []):
            if isinstance(it, dict) and isinstance(it.get("text"), str):
                t = it["text"].strip()[:MAX_TEXT_LEN]
                if t and t not in seen_text:
                    seen_text.add(t)
                    texts.append(t)
            if len(texts) >= MAX_TEXTS:
                break
        for e in (s.get("diary_entries") or []):
            if isinstance(e, dict) and (e.get("content") or "").strip():
                diary_in.append(e)
            if len(diary_in) >= MAX_DIARY_PER_SOURCE * max(1, len(sources)):
                break
    if len(texts) >= MAX_TEXTS:
        raise HTTPException(status_code=400, detail=f"包内记忆文本超过上限 {MAX_TEXTS} 条")

    # ---- 日记：同步写（save_diary_data 既有收口：截尾+净化） ----
    book = await diary_system.load_diary_data(req.target_card)
    target_name = target.get("name", "")
    if req.strategy == "replace":
        merged = list(diary_in)
    else:
        book.setdefault("characterId", req.target_card)
        book.setdefault("characterName", target_name)
        have = {_entry_key(e) for e in (book.get("entries") or []) if isinstance(e, dict)}
        have.update(f"{e.get('time', '')}|{e.get('content', '')}"
                    for e in (book.get("entries") or []) if isinstance(e, dict))
        merged = list(book.get("entries") or [])
        for e in diary_in:
            k = _entry_key(e)
            if k in have or f"{e.get('time', '')}|{e.get('content', '')}" in have:
                continue
            have.add(k)
            merged.append(e)
    try:
        merged.sort(key=lambda e: str(e.get("time") or ""))
    except Exception:
        pass
    from py.diary_system import MAX_ENTRIES
    truncated = max(0, len(merged) - MAX_ENTRIES)
    book_out = {"characterId": req.target_card, "characterName": target_name,
                "entries": merged}
    await diary_system.save_diary_data(book_out, req.target_card)
    diary_added = (len(merged) if req.strategy == "replace"
                   else len(merged) - len(book.get("entries") or []))

    # ---- 记忆：异步批量（单发 job；逐条投会被 debounce 互相吞） ----
    memory_queued = 0
    memory_dup_skipped = 0
    if texts:
        if req.strategy == "merge":
            if not target.get("providerId"):
                raise HTTPException(status_code=400,
                                    detail="目标卡未配置 embedding 服务，无法导入记忆（可只导日记）")
            from py.routers.memories import _m0_crud_lock

            def _existing():
                with _m0_crud_lock:
                    m0 = llm_gate.get_mem0_instance(req.target_card, target, settings)
                    return m0.get_all(user_id=req.target_card, limit=10000)
            try:
                results = await asyncio.to_thread(_existing)
                raw = results.get("results", []) if isinstance(results, dict) else (results or [])
                have_text = {(it.get("memory") or "").strip() for it in raw}
            except Exception as e:
                raise HTTPException(status_code=500,
                                    detail=f"读取目标卡现有记忆失败：{e}")
            before = len(texts)
            texts = [t for t in texts if t not in have_text]
            memory_dup_skipped = before - len(texts)

        if texts:
            replace = req.strategy == "replace"
            card_name = target_name

            def _bulk_add(_texts=texts, _card=req.target_card, _mem=target, _st=settings):
                ok = fail = 0
                try:
                    if replace:
                        llm_gate.invalidate_memory_cache(_card)
                        from py.get_setting import MEMORY_CACHE_DIR
                        d = os.path.join(MEMORY_CACHE_DIR, _card)
                        if os.path.commonpath([MEMORY_CACHE_DIR, d]) == MEMORY_CACHE_DIR:
                            shutil.rmtree(d, ignore_errors=True)
                    m0 = llm_gate.get_mem0_instance(_card, _mem, _st)
                    for t in _texts:
                        try:
                            m0.add(t, user_id=_card, infer=False)
                            ok += 1
                        except Exception:
                            fail += 1
                except Exception as e:
                    logging.getLogger("app").error("[Transfer] 记忆导入任务失败: %r", e)
                    notification_center.emit(
                        "error", f"记忆导入到 [{card_name}] 失败: {e}", level="error")
                    return
                msg = f"记忆导入完成 [{card_name}]：{ok}/{len(_texts)}"
                if fail:
                    notification_center.emit("error", f"{msg}，失败 {fail} 条", level="error")
                else:
                    notification_center.emit("system", msg)

            llm_gate.submit_memory_job(req.target_card, _bulk_add,
                                       name="transfer-import", debounce=0)
            memory_queued = len(texts)

    parts = []
    if diary_in:
        parts.append(f"日记 +{diary_added}" + (f"（超容量截尾 {truncated}）" if truncated else ""))
    if memory_queued:
        parts.append(f"记忆 {memory_queued} 条已排队导入")
    if memory_dup_skipped:
        parts.append(f"重复记忆跳过 {memory_dup_skipped}")
    return {"success": True,
            "diary_added": diary_added, "diary_truncated": truncated,
            "memory_queued": memory_queued, "memory_dup_skipped": memory_dup_skipped,
            "message": "；".join(parts) or "包内无可导入数据"}
