# -*- coding: utf-8 -*-
"""S216 旁观记忆层：事件明细滚动清理 / 每日本地摘要 / 检索。独立模块，纯本地零 LLM。

数据（S215 契约）：<SCREEN_WATCH_DIR>/screen_log.jsonl 每行一个事件
{ts, iso, title, summary, activity, importance, took_s}。
保留策略（settings.screenWatchSettings 可配，均有默认）：明细 retentionHours=48，
摘要 screen_digest_YYYYMMDD.md 保留 digestRetentionDays=30。摘要为确定性规则聚合
（时段概览/活动分布/高重要度清单/高频窗口），LLM 风格化留给 S217 注入时的主模型。
调度入口 maintain() 由 screen_watcher tick 挂钩（每小时节流，不受 enabled 支配：
旁观停用后存量数据照常到期清理）。
"""
import datetime
import io
import json
import logging
import os
import re
import time
from collections import Counter

from py.get_setting import SCREEN_WATCH_DIR

LOG_NAME = "screen_log.jsonl"
DIGEST_PREFIX = "screen_digest_"
DIGEST_SUFFIX = ".md"
_IMPORTANCE_LINE = 4  # ≥4 进摘要"值得关注"清单


def _log_path(log_path=None):
    return log_path or os.path.join(SCREEN_WATCH_DIR, LOG_NAME)


def _digest_dir(out_dir=None):
    return out_dir or SCREEN_WATCH_DIR


def _cfg_num(cfg, name, default):
    try:
        v = int((cfg or {}).get(name, default) or default)
        return v if v > 0 else default
    except (TypeError, ValueError):
        return default


def load_events(since_ts=None, until_ts=None, log_path=None):
    """按时间窗 [since_ts, until_ts) 读事件（文件序=时间序）；坏行跳过。"""
    p = _log_path(log_path)
    if not os.path.exists(p):
        return []
    out = []
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            if not isinstance(ev, dict):
                continue
            ts = ev.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            if since_ts is not None and ts < since_ts:
                continue
            if until_ts is not None and ts >= until_ts:
                continue
            out.append(ev)
    return out


def prune_old_events(retention_hours=48, now=None, log_path=None):
    """只保留保留窗内的事件并重写文件（顺带清除坏行）。返回删除行数。"""
    p = _log_path(log_path)
    if not os.path.exists(p):
        return 0
    floor = (now if now is not None else time.time()) - max(1, retention_hours) * 3600
    keep, dropped = [], 0
    with io.open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            ok = False
            if line:
                try:
                    ev = json.loads(line)
                    if (isinstance(ev, dict)
                            and isinstance(ev.get("ts"), (int, float))
                            and ev["ts"] >= floor):
                        keep.append(json.dumps(ev, ensure_ascii=False))
                        ok = True
                except Exception:
                    pass
            if not ok:
                dropped += 1
    if dropped:
        with io.open(p, "w", encoding="utf-8") as f:
            for k in keep:
                f.write(k + "\n")
    return dropped


def prune_old_digests(retention_days=30, now=None, out_dir=None):
    """按文件名日期删除过期每日摘要。返回删除文件数。"""
    d = _digest_dir(out_dir)
    if not os.path.isdir(d):
        return 0
    today = datetime.datetime.fromtimestamp(
        now if now is not None else time.time()).date()
    removed = 0
    for name in os.listdir(d):
        if not (name.startswith(DIGEST_PREFIX) and name.endswith(DIGEST_SUFFIX)):
            continue
        try:
            day = datetime.date.fromisoformat(
                name[len(DIGEST_PREFIX):-len(DIGEST_SUFFIX)])
        except ValueError:
            continue
        if (today - day).days > retention_days:
            try:
                os.remove(os.path.join(d, name))
                removed += 1
            except OSError:
                pass
    return removed


def _events_of_date(events, date_str):
    return [e for e in events
            if datetime.datetime.fromtimestamp(e["ts"]).date().isoformat() == date_str]


def build_daily_digest(date_str, now=None, out_dir=None, log_path=None, force=False):
    """把某天的事件聚合为 screen_digest_<date>.md（本地规则，零 LLM）。

    无事件或文件已存在（且非 force）→ 返回 None（幂等，maintain 每小时重查无副作用）。
    """
    p = os.path.join(_digest_dir(out_dir), DIGEST_PREFIX + date_str + DIGEST_SUFFIX)
    if os.path.exists(p) and not force:
        return None
    events = _events_of_date(load_events(log_path=log_path), date_str)
    if not events:
        return None
    blocks = ["# 屏幕观察每日摘要 " + date_str, ""]
    imp = [e for e in events if isinstance(e.get("importance"), int)
           and e["importance"] >= _IMPORTANCE_LINE]
    blocks.append(f"- 事件总数: {len(events)}（高重要度≥{_IMPORTANCE_LINE}: {len(imp)}）")
    acts = Counter(str(e.get("activity") or "other") for e in events)
    blocks.append("- 活动分布: " + ", ".join(f"{a}×{n}" for a, n in acts.most_common(6)))
    parts = []
    for b0 in range(0, 24, 6):
        seg = [e for e in events if b0 <= datetime.datetime.fromtimestamp(e["ts"]).hour < b0 + 6]
        if seg:
            top = Counter(str(e.get("activity") or "other") for e in seg).most_common(1)[0]
            parts.append(f"{b0:02d}-{b0 + 6:02d} {top[0]}×{len(seg)}")
    if parts:
        blocks.append("- 时段概览: " + "; ".join(parts))
    if imp:
        blocks.append("- 值得关注:")
        for e in sorted(imp, key=lambda x: x["ts"])[:20]:
            t = datetime.datetime.fromtimestamp(e["ts"]).strftime("%H:%M")
            blocks.append(f"  - {t} [{e.get('activity') or 'other'}] {e.get('summary') or ''}"
                          f"（importance {e['importance']}）")
    wins = Counter(str(e.get("title") or "")[:40] for e in events if e.get("title"))
    if wins:
        blocks.append("- 高频窗口: " + ", ".join(f"{w}×{n}" for w, n in wins.most_common(5)))
    with io.open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(blocks) + "\n")
    return p


def search_events(query, window_hours=48, limit=20, now=None, log_path=None):
    """关键词检索近 window_hours 的事件：词分片任一命中 summary/title/activity
    （召回导向，相关性交给 S217 主模型再筛）。新→旧返回。"""
    terms = [t for t in re.split(r"\s+", (query or "").strip().lower()) if t]
    if not terms:
        return []
    floor = (now if now is not None else time.time()) - max(1, window_hours) * 3600
    out = []
    for ev in reversed(load_events(since_ts=floor, log_path=log_path)):
        hay = (f"{ev.get('summary') or ''} {ev.get('title') or ''} "
               f"{ev.get('activity') or ''}").lower()
        if any(t in hay for t in terms):
            out.append(ev)
            if len(out) >= limit:
                break
    return out


def maintain(cfg, now=None, out_dir=None, log_path=None):
    """记忆层维护总入口（watcher tick 每小时调用）：清明细→清旧摘要→生成昨日摘要。"""
    now = now if now is not None else time.time()
    res = {
        "pruned": prune_old_events(_cfg_num(cfg, "retentionHours", 48),
                                   now=now, log_path=log_path),
        "digests_pruned": prune_old_digests(_cfg_num(cfg, "digestRetentionDays", 30),
                                            now=now, out_dir=out_dir),
    }
    dt = datetime.datetime.fromtimestamp(now)
    if dt.hour >= _cfg_num(cfg, "digestHour", 4):
        yesterday = (dt.date() - datetime.timedelta(days=1)).isoformat()
        made = build_daily_digest(yesterday, now=now, out_dir=out_dir, log_path=log_path)
        if made:
            res["digest"] = os.path.basename(made)
            logging.getLogger("app").info(f"[ScreenMemory] 已生成每日摘要: {made}")
    return res
