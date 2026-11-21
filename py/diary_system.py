import os
import re
import json
import asyncio
import logging
import shortuuid
from datetime import datetime
from py.get_setting import USER_DATA_DIR
from py.token_guard import neutralize

# 存放所有日记本的目录（独立于系统配置文件，每个角色一个 JSON 文件）
DIARY_DIR = os.path.join(USER_DATA_DIR, 'diary')

# 兜底日记本（无角色 / 未启用角色卡时使用）
DEFAULT_BOOK_ID = 'default'

# 旧版单文件日记（用于一次性迁移到 default 日记本）
LEGACY_DIARY_FILE = os.path.join(DIARY_DIR, 'diary_data.json')

# 每个日记本默认保留的条目数量（S266：实际上限改为可设置——
# diarySettings.diaryMaxEntries，0=无上限；本常量仅作默认值/兼容旧引用）
MAX_ENTRIES = 500


async def get_diary_policy():
    """S266：读取 (上限, 自动归档)。上限 0=无上限；设置缺失/异常回退默认(500, 开)。"""
    try:
        from py.get_setting import load_settings
        s = await load_settings()
        ds = s.get("diarySettings") or {}
        raw = ds.get("diaryMaxEntries", MAX_ENTRIES)
        try:
            limit = max(0, int(raw))
        except (TypeError, ValueError):
            limit = MAX_ENTRIES
        archive_on = ds.get("diaryArchiveEnabled", True)
        return limit, bool(archive_on)
    except Exception:
        return MAX_ENTRIES, True


def merge_entries(base_entries, extra_entries):
    """S266 合并原语：按条目 id 去重（base 优先），按 time 升序排列。"""
    seen, out = set(), []
    for e in list(base_entries) + list(extra_entries):
        if not isinstance(e, dict):
            continue
        eid = e.get("id") or (str(e.get("time", "")) + "|" + str(e.get("title", ""))[:60])
        if eid in seen:
            continue
        seen.add(eid)
        out.append(e)
    out.sort(key=lambda e: str(e.get("time", "")))
    return out


def _safe_book_id(book_id) -> str:
    """把角色 id 规整成安全的文件名片段"""
    bid = str(book_id or '').strip()
    if not bid:
        return DEFAULT_BOOK_ID
    bid = re.sub(r'[^A-Za-z0-9_\-]', '_', bid)
    return bid or DEFAULT_BOOK_ID


def _book_file(book_id) -> str:
    return os.path.join(DIARY_DIR, f'{_safe_book_id(book_id)}.json')


# S208：日记/摘要注入时刻的中文 12 小时制（配 24h 字符串双格式下发，防本地模型
# 换算失守——实锤：11-11 当天 21:29 被写成「快11点半」、22:46 写成「11点快四十五分」）
_CN_DIGITS = "零一二三四五六七八九"


def _cn_minutes(m: int) -> str:
    if m == 0:
        return "整"
    if m == 15:
        return "一刻"
    if m == 30:
        return "半"
    tens, ones = divmod(m, 10)
    if tens == 0:
        return _CN_DIGITS[ones] + "分"
    if tens == 1:  # 十八分 / 十一分（不归并成一十八分）
        return "十" + (_CN_DIGITS[ones] if ones else "") + "分"
    if ones == 0:
        return _CN_DIGITS[tens] + "十分"
    return _CN_DIGITS[tens] + "十" + _CN_DIGITS[ones] + "分"


def cn_clock_time(now=None) -> str:
    """中文时刻，如「晚上九点二十九分 / 凌晨十二点半 / 下午一点整」。"""
    now = now or datetime.now()
    h, m = now.hour, now.minute
    if h < 5:
        period, hh = "凌晨", (h % 12) or 12
    elif h < 8:
        period, hh = "早上", h
    elif h < 11:
        period, hh = "上午", h
    elif h < 13:
        period, hh = "中午", (h % 12) or 12
    elif h < 17:
        period, hh = "下午", h - 12
    elif h < 19:
        period, hh = "傍晚", h - 12
    else:
        period, hh = "晚上", h - 12
    if hh <= 9:
        hs = _CN_DIGITS[hh]
    elif hh == 10:
        hs = "十"
    else:
        hs = "十" + _CN_DIGITS[hh - 10]
    return f"{period}{hs}点{_cn_minutes(m)}"


def _empty_book(character_id=None, character_name=""):
    return {
        "characterId": character_id,
        "characterName": character_name or "",
        "entries": [],
    }


async def _migrate_legacy_if_needed():
    """把旧版 diary_data.json 迁移为 default 日记本（仅一次）"""
    default_file = _book_file(DEFAULT_BOOK_ID)
    if os.path.exists(default_file) or not os.path.exists(LEGACY_DIARY_FILE):
        return
    try:
        def _do():
            with open(LEGACY_DIARY_FILE, 'r', encoding='utf-8') as f:
                old = json.load(f)
            entries = old.get("entries", []) if isinstance(old, dict) else []
            book = _empty_book()
            book["entries"] = entries
            with open(default_file, 'w', encoding='utf-8') as f:
                json.dump(book, f, ensure_ascii=False, indent=4)
        await asyncio.to_thread(_do)
        logging.getLogger("app").info("📔 [日记系统] 已将旧版日记迁移到默认日记本")
    except Exception as e:
        logging.getLogger("app").error(f"[Diary] 迁移旧版日记失败: {e}")


async def load_diary_data(book_id: str = DEFAULT_BOOK_ID):
    """读取某个日记本，返回 {"characterId":..., "characterName":..., "entries":[...]}"""
    os.makedirs(DIARY_DIR, exist_ok=True)
    if _safe_book_id(book_id) == DEFAULT_BOOK_ID:
        await _migrate_legacy_if_needed()
    path = _book_file(book_id)
    if not os.path.exists(path):
        return _empty_book()
    try:
        def _read():
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        data = await asyncio.to_thread(_read)
        if not isinstance(data, dict):
            return _empty_book()
        if "entries" not in data or not isinstance(data["entries"], list):
            data["entries"] = []
        data.setdefault("characterId", None)
        data.setdefault("characterName", "")
        return data
    except Exception as e:
        logging.getLogger("app").error(f"[Diary] 读取日记本 {book_id} 失败: {e}")
        return _empty_book()


async def save_diary_data(data, book_id: str = DEFAULT_BOOK_ID):
    """全量保存某个日记本"""
    os.makedirs(DIARY_DIR, exist_ok=True)
    if not isinstance(data, dict):
        data = _empty_book()
    if "entries" not in data or not isinstance(data["entries"], list):
        data["entries"] = []
    data.setdefault("characterId", None)
    data.setdefault("characterName", "")
    # S266：上限可设置（0=无上限）；溢出不再静默丢弃——自动归档开启时旧条目
    # 追加进本日记本的归档文件（按 id 去重），关闭时才维持旧丢弃行为。
    limit, archive_on = await get_diary_policy()
    if limit and len(data["entries"]) > limit:
        overflow = data["entries"][:-limit]
        data["entries"] = data["entries"][-limit:]
        if archive_on:
            try:
                await append_archive(book_id, overflow)
            except Exception as e:
                logging.getLogger("app").warning("[Diary] 自动归档失败(保持旧行为丢弃溢出): %r", e)
    # S160：写侧收口——自主日记与 chatSummary 都经此落盘，控制 token 形状不得入本
    for entry in data["entries"]:
        if isinstance(entry, dict):
            for key in ("title", "content"):
                if isinstance(entry.get(key), str) and entry[key]:
                    entry[key] = neutralize(entry[key], "diary")
    path = _book_file(book_id)
    try:
        def _write():
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
        await asyncio.to_thread(_write)
    except Exception as e:
        logging.getLogger("app").error(f"[Diary] 保存日记本 {book_id} 失败: {e}")


async def append_diary_entry(entry_type: str, content: str, title: str = "", pushed_to=None,
                             book_id: str = DEFAULT_BOOK_ID, character_id=None, character_name=""):
    """向指定日记本追加一条日记，返回新条目"""
    if not content:
        return None
    data = await load_diary_data(book_id)
    # 同步本子的角色信息（角色可能改名）
    if character_id is not None:
        data["characterId"] = character_id
    if character_name:
        data["characterName"] = character_name
    entry = {
        "id": str(shortuuid.ShortUUID().random(length=10)),
        "time": datetime.now().isoformat(),
        "type": entry_type,
        "title": title or "",
        "content": content,
        "pushedTo": pushed_to or [],
    }
    data["entries"].append(entry)
    await save_diary_data(data, book_id)
    logging.getLogger("app").info(f"📔 [日记系统] 新增日记 [{book_id}/{entry_type}]: {(title or content)[:30]}")
    return entry


# ---- S266：归档与导出 ----


def _archive_file(book_id) -> str:
    return os.path.join(DIARY_DIR, 'archive', f'{_safe_book_id(book_id)}.json')


async def load_archive(book_id: str = DEFAULT_BOOK_ID):
    """读归档条目（文件不存在返回空表）。"""
    path = _archive_file(book_id)
    if not os.path.exists(path):
        return []

    def _read():
        with open(path, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return d.get("entries", []) if isinstance(d, dict) else []
    try:
        return await asyncio.to_thread(_read)
    except Exception as e:
        logging.getLogger("app").error("[Diary] 读归档失败 %s: %s", book_id, e)
        return []


async def append_archive(book_id, entries):
    """把溢出条目并入归档（id 去重 + time 升序，原子写）。"""
    if not entries:
        return 0
    base = await load_archive(book_id)
    merged = merge_entries(base, entries)
    path = _archive_file(book_id)

    def _write():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({"entries": merged}, f, ensure_ascii=False)
        os.replace(tmp, path)
    await asyncio.to_thread(_write)
    logging.getLogger("app").info("[Diary] S266 自动归档 %s: +%d 条 → 共 %d 条",
                                  book_id, len(entries), len(merged))
    return len(merged)


def _entries_to_markdown(entries, book_id, archived=None):
    lines = [f"# 日记本导出 · {book_id}", "",
             f"共 {len(entries)} 条"
             + (f"（含归档 {archived} 条）" if archived else ""), ""]
    for e in entries:
        if not isinstance(e, dict):
            continue
        t = str(e.get("time", "")).replace("T", " ")[:16]
        title = str(e.get("title") or "").strip()
        if title:
            lines.append(f"## {t} · {title}")
        else:
            lines.append(f"## {t}")
        lines.append(f"_type: {e.get('type', '')}_")
        lines.append("")
        lines.append(str(e.get("content") or "").strip())
        lines.append("")
    return "\n".join(lines)


async def export_book(book_id: str = DEFAULT_BOOK_ID, fmt: str = "json", include_archive: bool = False):
    """导出 (filename, media_type, bytes)。fmt: json|md；include_archive 时合并归档。"""
    data = await load_diary_data(book_id)
    entries = list(data.get("entries", []))
    archived_n = 0
    if include_archive:
        arch = await load_archive(book_id)
        archived_n = sum(1 for e in arch if e.get("id") not in {x.get("id") for x in entries})
        entries = merge_entries(arch, entries)
    bid = _safe_book_id(book_id)
    stamp = datetime.now().strftime("%Y%m%d")
    if fmt == "md":
        text = _entries_to_markdown(entries, bid, archived_n if include_archive else 0)
        return f"diary_{bid}_{stamp}.md", "text/markdown; charset=utf-8", text.encode("utf-8")
    payload = {
        "book_id": bid,
        "characterId": data.get("characterId"),
        "characterName": data.get("characterName", ""),
        "exported_at": datetime.now().isoformat(),
        "includes_archive": bool(include_archive),
        "entries": entries,
    }
    return (f"diary_{bid}_{stamp}.json", "application/json; charset=utf-8",
            json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8"))


# ---- S268：导入（文件/归档并入）+ 超限投影预检 ----

_IMPORT_MAX_PER_CALL = 5000


def plan_import(current_entries, incoming_entries, limit, archive_on):
    """S268 纯函数：不落盘地投影导入结果。
    返回 {added, total, overflow, dropped_mode}：
    - added：按 id 去重后净新增条数
    - total：合并后总条数
    - overflow：limit>0 时超出上限的条数（=落盘时被挤走的旧条目数）；limit=0 恒 0
    - dropped_mode：挤走条目的去向——archive=自动归档；drop=永久删除"""
    merged = merge_entries(current_entries, incoming_entries)
    total = len(merged)
    added = total - len([e for e in current_entries if isinstance(e, dict)])
    overflow = max(0, total - limit) if limit else 0
    return {"added": max(0, added), "total": total, "overflow": overflow,
            "dropped_mode": "archive" if archive_on else "drop"}


async def import_entries(book_id, incoming_entries, dry_run=False):
    """S268 导入端点后端：dry_run 只做 plan 投影；否则按当前策略落盘。"""
    if not isinstance(incoming_entries, list) or not incoming_entries:
        raise ValueError("entries 需为非空数组")
    if len(incoming_entries) > _IMPORT_MAX_PER_CALL:
        raise ValueError(f"单次导入上限 {_IMPORT_MAX_PER_CALL} 条")
    clean = [e for e in incoming_entries if isinstance(e, dict) and (e.get("content") or e.get("title"))]
    if not clean:
        raise ValueError("entries 中无有效条目（需含 content 或 title）")
    # 外部文件条目缺 id/time 时补发（删除/:key/去重都按 id 寻址，缺位会失稳）
    for e in clean:
        if not e.get("id"):
            e["id"] = shortuuid.uuid()[:10]
        if not e.get("time"):
            e["time"] = datetime.now().isoformat()
    current = await load_diary_data(book_id)
    limit, archive_on = await get_diary_policy()
    plan = plan_import(current.get("entries", []), clean, limit, archive_on)
    if dry_run:
        return {"ok": True, "dry_run": True, **plan}
    merged = merge_entries(current.get("entries", []), clean)
    current["entries"] = merged
    await save_diary_data(current, book_id)  # 截断/归档策略在 save 内统一执行
    return {"ok": True, "dry_run": False, **plan}


async def delete_diary_entry(entry_id: str, book_id: str = DEFAULT_BOOK_ID):
    """从指定日记本删除一条日记"""
    data = await load_diary_data(book_id)
    before = len(data["entries"])
    data["entries"] = [e for e in data["entries"] if e.get("id") != entry_id]
    if len(data["entries"]) != before:
        await save_diary_data(data, book_id)
        return True
    return False


async def list_diary_books():
    """列出所有日记本，自动：新建角色本 / 同名重联 / 清空无日记的孤儿本"""
    os.makedirs(DIARY_DIR, exist_ok=True)
    await _migrate_legacy_if_needed()

    # 1. 加载当前角色卡列表
    memories = []
    memory_by_name = {}
    try:
        from py.get_setting import load_settings
        settings = await load_settings()
        memories = (settings or {}).get("memories", []) or []
        for mem in memories:
            mn = (mem.get("name") or "").strip()
            if mn:
                memory_by_name[mn.lower()] = mem
    except Exception:
        pass

    memory_ids = {mem.get("id") for mem in memories if mem.get("id")}

    # 2. 扫描已有本子文件
    books = []
    existing_files = set()
    try:
        fnames = await asyncio.to_thread(lambda: os.listdir(DIARY_DIR))
    except Exception:
        fnames = []
    for fname in fnames:
        if not fname.endswith('.json'):
            continue
        if fname == os.path.basename(LEGACY_DIARY_FILE):
            continue
        book_id = fname[:-len('.json')]
        existing_files.add(fname)
        data = await load_diary_data(book_id)
        entries = data.get("entries", [])
        char_id = data.get("characterId")
        char_name = data.get("characterName", "")

        if char_id and char_id in memory_ids:
            # 角色仍存在 → 同步名称
            mem = next((m for m in memories if m.get("id") == char_id), None)
            if mem and data.get("characterName") != (mem.get("name") or ""):
                data["characterName"] = mem.get("name", "")
                await save_diary_data(data, book_id)
                char_name = data["characterName"]
        elif char_id:
            # 角色已删除
            if char_name and char_name.lower() in memory_by_name:
                # 同名角色重建 → 重联
                mem = memory_by_name[char_name.lower()]
                data["characterId"] = mem.get("id")
                data["characterName"] = mem.get("name", "")
                await save_diary_data(data, book_id)
                char_id = data["characterId"]
                char_name = data["characterName"]
            elif len(entries) == 0:
                # 无日记的孤儿本 → 删除文件并跳过
                try:
                    await asyncio.to_thread(lambda: os.remove(_book_file(book_id)))
                except Exception:
                    pass
                logging.getLogger("app").info(f"📔 [日记系统] 已清理孤儿日记本: {char_name or book_id}")
                continue
            # 有日记的孤儿本 → 保留

        last_time = ""
        if entries:
            try:
                last_time = max(e.get("time", "") for e in entries)
            except Exception:
                last_time = entries[-1].get("time", "")
        books.append({
            "bookId": book_id,
            "characterId": char_id,
            "characterName": char_name,
            "count": len(entries),
            "lastTime": last_time,
            "isDefault": book_id == DEFAULT_BOOK_ID,
        })

    # 3. 为还没有本子的角色自动创建空本
    for mem in memories:
        mid = mem.get("id")
        if not mid:
            continue
        fname = f'{_safe_book_id(mid)}.json'
        if fname not in existing_files:
            await save_diary_data(_empty_book(mid, mem.get("name", "")), mid)
            books.append({
                "bookId": mid,
                "characterId": mid,
                "characterName": mem.get("name", ""),
                "count": 0,
                "lastTime": "",
                "isDefault": False,
            })
            existing_files.add(fname)

    # 4. 确保默认兜底本
    if not any(b["bookId"] == DEFAULT_BOOK_ID for b in books):
        books.append({
            "bookId": DEFAULT_BOOK_ID,
            "characterId": None,
            "characterName": "",
            "count": 0,
            "lastTime": "",
            "isDefault": True,
        })

    # 5. 安全过滤：移除所有死标签（非默认 + 角色已删 + 无日记）
    books = [b for b in books if (
        b["isDefault"] or
        b["characterId"] in memory_ids or
        b["count"] > 0
    )]

    # 6. 排序：默认本 → 有日记的按最近更新倒序 → 空本按名字正序
    default_b = [b for b in books if b["isDefault"]]
    with_entries = sorted(
        [b for b in books if b["lastTime"] and not b["isDefault"]],
        key=lambda b: b["lastTime"], reverse=True,
    )
    empty_b = sorted(
        [b for b in books if not b["lastTime"] and not b["isDefault"]],
        key=lambda b: b.get("characterName", ""),
    )
    return default_b + with_entries + empty_b


async def query_diary_entries(query: str = "", book_id: str = DEFAULT_BOOK_ID,
                              start_time: str = "", end_time: str = "",
                              max_results: int = 5, entry_type: str = ""):
    """按时间范围和关键词搜索日记条目，返回匹配列表"""
    data = await load_diary_data(book_id)
    entries = data.get("entries", [])
    results = []
    query_lower = query.lower() if query else ""
    for e in reversed(entries):
        etime = e.get("time", "")
        if start_time and etime < start_time:
            continue
        if end_time and etime > end_time:
            continue
        if entry_type and e.get("type", "") != entry_type:
            continue
        if query_lower:
            title = (e.get("title", "") or "").lower()
            content = (e.get("content", "") or "").lower()
            if query_lower not in title and query_lower not in content:
                continue
        results.append(e)
        if max_results > 0 and len(results) >= max_results:
            break
    return results


async def get_recent_diary_entries(book_id: str = DEFAULT_BOOK_ID, n: int = 5):
    """获取最近 N 条日记条目"""
    data = await load_diary_data(book_id)
    entries = data.get("entries", [])
    return entries[-n:] if n > 0 else []
