# -*- coding: utf-8 -*-
"""S145：IM 对端身份名录（registry + 提示词注入 + 已见 id 登记）。

roster 存储于 settings.imPeerSettings：
  {"injectEnabled": true,
   "roster": {platform: {peer_id: {"alias":str,"roleDesc":str,"approver":bool,"notes":str}}}}
approver 位供 S146 IM 审批门禁复用；seen 登记落 data/peers_seen.json 供 UI「已见未登记」提示。
"""
import json
import os
import threading
import time

from py.get_setting import USER_DATA_DIR

PEERS_SEEN_FILE = os.path.join(USER_DATA_DIR, "peers_seen.json")
_FLUSH_INTERVAL = 60.0

_lock = threading.Lock()
_seen = {}
_last_flush = 0.0
_dirty = False


def _load():
    global _seen
    try:
        with open(PEERS_SEEN_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            _seen = {k: v for k, v in data.items() if isinstance(v, dict)}
    except Exception:
        _seen = {}


def _flush(force=False):
    global _last_flush, _dirty
    with _lock:
        if not _dirty or (not force and time.time() - _last_flush < _FLUSH_INTERVAL):
            return
        snapshot = json.dumps(_seen, ensure_ascii=False)
        _dirty = False
        _last_flush = time.time()
    tmp = PEERS_SEEN_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(snapshot)
        os.replace(tmp, PEERS_SEEN_FILE)
    except Exception:
        pass


def record_seen(platform, peer_id):
    """记录（throttled 写盘）某平台见过的对端 id。"""
    global _dirty
    if not platform or not peer_id:
        return
    with _lock:
        bucket = _seen.setdefault(platform, {})
        ent = bucket.setdefault(str(peer_id), {"last_seen": 0})
        ent["last_seen"] = time.time()
        _dirty = True
    _flush()


def get_seen():
    with _lock:
        return json.loads(json.dumps(_seen))


def resolve_entry(platform, peer_id, settings):
    roster = ((settings or {}).get("imPeerSettings") or {}).get("roster") or {}
    ent = (roster.get(platform) or {}).get(str(peer_id))
    return ent if isinstance(ent, dict) else None


def display_name(platform, peer_id, settings):
    ent = resolve_entry(platform, peer_id, settings)
    if ent and (ent.get("alias") or "").strip():
        return ent["alias"].strip()
    return str(peer_id)


def build_peer_identity_block(platform, peer_id, settings):
    """当前对端详块 + 其他登记名录简表。injectEnabled=false 或未带 peer_id → 空串。"""
    cfg = (settings or {}).get("imPeerSettings") or {}
    if not cfg.get("injectEnabled", True):
        return ""
    if not platform or not peer_id:
        return ""
    roster = cfg.get("roster") or {}
    plat = roster.get(platform) or {}
    ent = plat.get(str(peer_id))
    ent = ent if isinstance(ent, dict) else None
    lines = ["\n\n【对端名录】对端一律以别名称呼、以平台 ID 为准识别（ID 是权威标识）："]
    if ent:
        alias = (ent.get("alias") or "").strip() or str(peer_id)
        role = (ent.get("roleDesc") or "").strip() or "未注明"
        appr = "可批准工具调用" if ent.get("approver") else "无审批权限"
        lines.append(f"当前对话对端：{alias}（{platform} ID: {peer_id}）｜身份：{role}｜审批：{appr}")
        notes = (ent.get("notes") or "").strip()
        if notes:
            lines.append(f"备注：{notes}")
    else:
        lines.append(f"未知对端（{platform} ID: {peer_id}）未登记；可提示用户在设置页「IM 对端名录」中登记。")
    others = [(pid, e) for pid, e in plat.items()
              if pid != str(peer_id) and isinstance(e, dict)]
    if others:
        parts = []
        for pid, e in others:
            a = (e.get("alias") or "").strip() or pid
            parts.append(f"{a}={pid}" + ("(可审批)" if e.get("approver") else ""))
        lines.append("其他已登记对端：" + "；".join(parts))
    return "\n".join(lines) + "\n"


_load()
