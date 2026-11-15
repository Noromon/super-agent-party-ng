# -*- coding: utf-8 -*-
"""S218 旁观主动发言：屏幕事件 → 防骚扰闸门 → 平台行为事件通道。

决策全为纯函数（本模块零网络零 LLM，可测）；发送复用 behavior_engine 的
平台 handler 契约 handler(chat_id, BehaviorItem)——传空 chat_id 让平台展开
用户配置的行为目标（S71 语义），频道配置体验与行为系统一致。合成 item
tools_mode 默认 none（S73：旁观发言绝不携带工具）。
闸门：speak.enabled（默认 False）→ importance≥minImportance(4) →
cooldownSeconds(600) → dailyLimit(5) → 静默时段 quietStart/End(0-8 支持跨夜)。
状态持久化 screen_watch/speak_state.json：重启不丢当日额度与冷却。
"""
import datetime
import io
import json
import os

from py.get_setting import SCREEN_WATCH_DIR

STATE_NAME = "speak_state.json"


def _num(cfg, name, default):
    try:
        return float((cfg or {}).get(name, default))
    except (TypeError, ValueError):
        return float(default)


def _state_path(path=None):
    return path or os.path.join(SCREEN_WATCH_DIR, STATE_NAME)


def load_state(path=None):
    p = _state_path(path)
    try:
        with io.open(p, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def save_state(state, path=None):
    p = _state_path(path)
    try:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except OSError:
        pass  # 状态写失败只影响额度持久化，不炸发言链路


def _in_quiet(hour, start, end):
    start, end = int(start), int(end)
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _today(now):
    return datetime.datetime.fromtimestamp(now).date().isoformat()


def should_speak(cfg, ev, state, now):
    """(允许?, 原因)。state 会被跨天归零原地修改（与持久化状态同一对象）。"""
    if not (cfg or {}).get("enabled", False):
        return False, "speak 未启用"
    imp = (ev or {}).get("importance")
    if not isinstance(imp, int) or imp < _num(cfg, "minImportance", 4):
        return False, "importance 未达阈值"
    if now - float(state.get("last_ts") or 0) < _num(cfg, "cooldownSeconds", 600):
        return False, "冷却中"
    today = _today(now)
    if state.get("date") != today:
        state["date"] = today
        state["count"] = 0
    if int(state.get("count") or 0) >= _num(cfg, "dailyLimit", 5):
        return False, "今日额度用尽"
    dt = datetime.datetime.fromtimestamp(now)
    if _in_quiet(dt.hour, _num(cfg, "quietStart", 0), _num(cfg, "quietEnd", 8)):
        return False, "静默时段"
    return True, ""


def record_sent(state, now):
    state["date"] = _today(now)
    state["count"] = int(state.get("count") or 0) + 1
    state["last_ts"] = now


def target_platforms(cfg, registered):
    """speak.platforms（默认 ["all"]）与已注册 handler 平台求交。"""
    want = (cfg or {}).get("platforms") or ["all"]
    if not isinstance(want, list):
        want = ["all"]
    if "all" in want:
        return list(registered)
    return [p for p in dict.fromkeys(want) if p in registered]


def build_behavior_item(ev):
    """合成一次性行为事件：S73 默认无工具；空回复（单个空格 strip 后）由
    平台既有空回复过滤吞掉——模型判断不值得打扰时的静默出口。"""
    from py.behavior_engine import BehaviorAction, BehaviorItem, BehaviorTrigger
    fact = f"{(ev or {}).get('title') or '画面'} — {(ev or {}).get('summary') or ''}"
    prompt = (
        f"【屏幕旁观】你刚在用户屏幕上观察到一个可能值得关注的情况：{fact}"
        f"（活动 {ev.get('activity') or 'other'}，重要度 {ev.get('importance')}）。"
        "如果值得让用户知道，请以自然、贴合你与该用户关系的口吻简短提一句；"
        "如果不值得打断，只回复一个空格（空消息会被自动吞掉，用户不会收到）。"
    )
    return BehaviorItem(enabled=True, trigger=BehaviorTrigger(type="screenEvent"),
                        action=BehaviorAction(type="prompt", prompt=prompt),
                        platforms=[], screen_fact=fact)


def is_busy_reason(reason):
    """非永久性拒绝（下次同类事件还可能通过）才值得记 info 日志。"""
    return reason in ("冷却中", "今日额度用尽", "静默时段")
