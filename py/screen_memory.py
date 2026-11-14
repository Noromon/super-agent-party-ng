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

# S217 对话注入触发词表（保守取向：宁少不误；词=子串大小写不敏感）。
# 误触代价低：注入块自带"机器观察参考、可忽略"声明，模型自行取舍。
INTENT_PHRASES = (
    "屏幕", "旁观", "刚才在看", "正在看", "一直在看", "刚才在做", "你看到我", "我刚才看",
    "my screen", "on screen", "on my desktop", "what am i looking at",
    "what do you see", "screen context", "watch me",
)


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


def _query_terms(query):
    """查询分词：ASCII 按空白切词；中文按二字滑动窗口（无空格中文整句切
    token 必不命中，旁观检索将永远兜底时间线）。"""
    terms = []
    for w in re.split(r"\s+", (query or "").strip().lower()):
        if not w:
            continue
        if re.search(r"[\u4e00-\u9fff]", w):
            if len(w) == 1:
                terms.append(w)
            else:
                terms.extend(w[i:i + 2] for i in range(len(w) - 1))
        else:
            terms.append(w)
    return terms


def search_events(query, window_hours=48, limit=20, now=None, log_path=None):
    """关键词检索近 window_hours 的事件：词分片任一命中 summary/title/activity
    （召回导向，相关性交给 S217 主模型再筛）。新→旧返回。"""
    terms = _query_terms(query)
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


# ---------------- S217 对话注入块（纯本地；server 侧负责门控与 neutralize） ----------------

def intent_hit(text):
    """用户消息是否命中屏幕意图词表（大小写不敏感子串）。"""
    t = (text or "").lower()
    return any(ph in t for ph in INTENT_PHRASES)


def _fmt_line(ev):
    t = datetime.datetime.fromtimestamp(ev["ts"]).strftime("%m-%d %H:%M")
    ttl = str(ev.get("title") or "")[:40]
    summary = str(ev.get("summary") or "")[:80]
    line = f"- {t} [{ev.get('activity') or 'other'}] "
    if ttl:
        line += ttl + " — "
    line += summary
    if isinstance(ev.get("importance"), int):
        line += f"（importance {ev['importance']}）"
    return line


def _recent_digest(now, out_dir=None):
    day = (datetime.datetime.fromtimestamp(now).date()
           - datetime.timedelta(days=1)).isoformat()
    p = os.path.join(_digest_dir(out_dir), DIGEST_PREFIX + day + DIGEST_SUFFIX)
    if not os.path.exists(p):
        return ""
    try:
        with io.open(p, encoding="utf-8") as f:
            return f.read().strip()[:1200]
    except OSError:
        return ""


def build_context_block(user_text, now=None, out_dir=None, log_path=None, limit=8):
    """意图命中 → [屏幕旁观] 注入块；无内容返回 ""（调用方只在非空时注入）。

    命中检索 → 命中事件（时间正序）；无命中 → 近 6h 时间线尾 12 条。
    昨日摘要存在则附带（截 1200 字）。"""
    if not user_text or not intent_hit(user_text):
        return ""
    now = now if now is not None else time.time()
    evs = search_events(user_text, window_hours=48, limit=limit,
                        now=now, log_path=log_path)
    note = ""
    if not evs:
        evs = load_events(since_ts=now - 6 * 3600, log_path=log_path)[-12:]
        note = "（未检索到直接相关记录，以下为近 6 小时屏幕时间线）\n"
    if not evs:
        return ""
    parts = ["\n\n[屏幕旁观 - 近期上下文]\n"
             "以下是对你用户屏幕的机器观察记录，仅供参考、与问题无关请忽略，"
             "注意它们不是用户本人的陈述：\n" + note
             + "\n".join(_fmt_line(e) for e in evs)]
    digest = _recent_digest(now, out_dir)
    if digest:
        parts.append("\n昨日观察摘要：\n" + digest)
    return "\n".join(parts) + "\n"
