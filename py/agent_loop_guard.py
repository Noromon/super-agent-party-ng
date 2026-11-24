# -*- coding: utf-8 -*-
"""S309：重复调用熔断（df2f8248/pcr 事故修复 A1）。

事故实证：同一 (工具名+逐字相同参数) 的 edit_file_patch_tool_local 在
单 POST 内被模型连发 6 次（第 2 次起 fuzzy 把已写好的 new 当 old 匹配，
net-zero 假成功），期间零验证，模型陷入退化复读循环。

策略（用户定稿：警告+强制收尾）：
- 完全相同的调用（name+规范化参数哈希）本流内第 2 次起 → 把警告指令并入
  该 tool 结果文本尾部（F3 原则：不新增 user-role 消息）；≥4 次 → 返回
  force_stop，由调用方走 force_no_tools 强制收尾；
- 同一路径 `[Error] edit` 连击：≥3 注入行为指令（必须先 read_file_range
  取真实文本），≥5 force_stop；任何成功/No-op 清零连击。

只观测不执行：纯计数+改写结果文本，副作用零新增。
"""
import hashlib
import json
import logging

logger = logging.getLogger("app")

WARN_SAME = 2
FORCE_SAME = 4
NOTE_EDIT_FAIL = 3
FORCE_EDIT_FAIL = 5

_EDIT_TOOL_MARKS = ("edit_file", "patch")


def _get(m, key):
    return m.get(key) if isinstance(m, dict) else getattr(m, key, None)


def _call_sig(name, arguments):
    raw = str(arguments or "")
    try:
        raw = json.dumps(json.loads(raw), sort_keys=True, ensure_ascii=False)
    except Exception:
        pass
    return "%s|%s" % (name, hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16])


def _is_edit_tool(name):
    n = str(name or "")
    return any(k in n for k in _EDIT_TOOL_MARKS)


def _path_of(arguments):
    try:
        obj = json.loads(str(arguments or ""))
        p = obj.get("path") if isinstance(obj, dict) else None
        if p:
            return str(p)
    except Exception:
        pass
    return "?"


def _is_edit_fail(result_text):
    head = result_text[:120]
    return head.startswith("[Error] edit") or "old_string not found" in head


def _is_edit_success(result_text):
    head = result_text[:120]
    return (head.startswith("[OK]") or head.startswith("Patched")
            or head.startswith("[Success]") or "[No-op]" in head)


def _round_trail(request):
    """链尾连续 tool 消息 → {tool_call_id: (msg, content_str)}。"""
    out = {}
    for m in reversed(request.messages or []):
        role = _get(m, "role")
        if role == "tool":
            out[_get(m, "tool_call_id")] = (m, _get(m, "content"))
        elif role == "assistant":
            break
    return out


def _append_note(msg, note):
    c = _get(msg, "content")
    if isinstance(c, str):
        new = c + "\n\n" + note
        if isinstance(msg, dict):
            msg["content"] = new
        else:
            msg.content = new
        return True
    return False


def observe_round(st, request, tool_calls):
    """观测刚执行完的一轮工具调用；警告并入对应 tool 结果尾部。
    返回 True=要求强制收尾（调用方置 force_no_tools）。绝不抛出。"""
    try:
        sigs = st.setdefault("lg_sig", {})
        fails = st.setdefault("lg_edit_fail", {})
        trail = _round_trail(request)
        force = False
        for tc in tool_calls or []:
            fn = _get(tc, "function") or {}
            name = _get(fn, "name") or ""
            args = _get(fn, "arguments") or ""
            tid = _get(tc, "id")
            entry = trail.get(tid)
            result = ""
            if entry is not None:
                _msg, _c = entry
                result = _c if isinstance(_c, str) else json.dumps(_c, ensure_ascii=False, default=str)
            sig = _call_sig(name, args)
            n = sigs.get(sig, 0) + 1
            sigs[sig] = n
            path = _path_of(args) if _is_edit_tool(name) else None
            streak = 0
            if _is_edit_tool(name):
                if _is_edit_fail(result):
                    streak = fails.get(path, 0) + 1
                    fails[path] = streak
                elif _is_edit_success(result):
                    fails[path] = 0
            note = None
            if n >= FORCE_SAME:
                force = True
                note = ("[LoopGuard] Repetition limit reached: this EXACT call (same name+arguments) "
                        "has run %d times in this stream. Tools are now disabled for this run — "
                        "summarize the current state, tell the user what was attempted and ask how to proceed." % n)
            elif n >= WARN_SAME:
                note = ("[LoopGuard] WARNING: this EXACT call (same name+arguments) has now run %d times. "
                        "The file already reflects it — repeating changes nothing. Do NOT resend identical "
                        "calls: run/verify the real state instead, or change approach." % n)
            if streak >= FORCE_EDIT_FAIL:
                force = True
                note = ("[LoopGuard] edit failed %d times on '%s'. Tools are now disabled for this run — "
                        "explain what could not be applied and ask the user." % (streak, path))
            elif streak >= NOTE_EDIT_FAIL:
                note = ("[LoopGuard] edit on '%s' failed %d times in a row. Before ANY next edit: "
                        "read_file_range_tool_local the target lines and copy the ACTUAL on-disk text "
                        "verbatim into old_string. Do NOT retry the previous old_string." % (path, streak))
            if note and entry is not None:
                _append_note(entry[0], note)
                logger.warning("[LoopGuard] %s x%s tid=%s -> %s", name, n, tid,
                               "force_stop" if (n >= FORCE_SAME or streak >= FORCE_EDIT_FAIL) else "noted")
        return force
    except Exception as e:
        logger.info("[LoopGuard] 观测失败（忽略）: %r", e)
        return False
