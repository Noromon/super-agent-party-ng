# build=S299
# S270：network_watch start 一体化编排（挂钩→自动滚 N 轮触发列表接口→收割首批）。
# 背景：SAP 会话复盘第二堵点——"进列表页第一动作永远是挂钩"全靠 agent 自觉，
# 且 start→滚动→read 三步往返易漏序。本票把时序错误变成不可能（一步走完）。
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


def _fake_vue(calls, reply=None):
    async def fake(method, args=None, timeout=None):
        calls.append((method, args, timeout))
        if callable(reply):
            r = reply(method, args)
            if asyncio.iscoroutine(r):
                r = await r
            return r
        return reply if reply is not None else "armed"
    return fake


def test_start_without_trigger_keeps_old_wire():
    calls = []
    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(calls)
    try:
        out = _run(cdp.network_watch("start"))
    finally:
        cdp.call_vue_method = orig
    m, args, to = calls[0]
    assert m == "networkWatch" and args[0] == "start"
    assert args[4] is None and to == 30
    assert out == "armed"


def test_trigger_clamp_and_budget():
    calls = []
    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(calls)
    try:
        _run(cdp.network_watch("start", include_body=True, trigger_scrolls=99, wait_ms=50))
    finally:
        cdp.call_vue_method = orig
    _, args, to = calls[0]
    trig = args[4]
    assert trig == {"scrolls": 20, "wait_ms": 300}
    # 预算：30 + 20*(300+1500)//1000 + 20 = 30+36+20 = 86
    assert to == 86
    # read/stop 模式忽略 trigger
    calls2 = []
    cdp.call_vue_method = _fake_vue(calls2, "{}")
    try:
        _run(cdp.network_watch("read", trigger_scrolls=5))
    finally:
        cdp.call_vue_method = orig
    assert calls2[0][1][4] is None


def test_start_trigger_read_postprocessed():
    # 首批收割里 blen>2048 的条目应触发 pull→落盘→body_path（复用 S257 通道）
    big = "y" * 5000
    read_payload = {"ok": True, "armed": "armed", "triggered_rounds": 2,
                    "scroller_mode": "wheel",
                    "read": {"total": 1, "new_items": 1, "returned": 1, "origin": "https://tieba.baidu.com",
                             "items": [{"gi": 0, "u": "https://tieba.baidu.com/newpostlist", "s": 200,
                                        "b": big[:2048], "blen": len(big)}]}}

    async def reply(method, args):
        if args and args[0] == "pull":
            return big
        return json.dumps(read_payload, ensure_ascii=False)

    calls = []
    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(calls, reply)
    try:
        out = _run(cdp.network_watch("start", pattern="newpostlist", include_body=True,
                                     trigger_scrolls=2))
    finally:
        cdp.call_vue_method = orig
    d = json.loads(out)
    assert d["ok"] and d["triggered_rounds"] == 2
    it = d["read"]["items"][0]
    # 落盘可能因目录权限等失败——但至少 pull 已发生且 b 预览被瘦身或给出 b_err
    assert any(a[1][0] == "pull" for a in calls)
    assert "body_path" in it or "b_err" in it


def test_start_trigger_over_limit_whole_dump(monkeypatch, tmp_path):
    items = [{"gi": i, "u": "https://x/" + str(i) * 30, "s": 200, "b": "z" * 1800} for i in range(30)]
    payload = {"ok": True, "armed": "armed", "triggered_rounds": 2,
               "read": {"total": 30, "new_items": 30, "returned": 30, "items": items}}
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path / "up"))

    async def reply(method, args):
        return json.dumps(payload, ensure_ascii=False)

    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue([], reply)
    try:
        out = _run(cdp.network_watch("start", include_body=True, trigger_scrolls=3))
    finally:
        cdp.call_vue_method = orig
    d = json.loads(out)
    assert len(out.encode("utf-8")) < 17000
    note = d["read"]["note"]
    # 内层 read helper 已把超限收割清单整体落盘（net_read_*），外层载荷自然被压回限额内
    assert "net_read_" in note
    dumped = list((tmp_path / "up").glob("net_read_*.json"))
    assert dumped and len(json.loads(dumped[0].read_text(encoding="utf-8"))["items"]) == 30


def test_read_mode_still_works_via_helper(monkeypatch, tmp_path):
    # 重构回归：read 模式行为与 S257 等价（items 直通 + note 拼装）
    payload = {"total": 2, "new_items": 2, "returned": 2, "origin": "https://a.com",
               "items": [{"gi": 0, "u": "https://a/x", "s": 200}, {"gi": 1, "u": "https://a/y", "s": 404}]}
    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue([], json.dumps(payload, ensure_ascii=False))
    try:
        out = _run(cdp.network_watch("read"))
    finally:
        cdp.call_vue_method = orig
    d = json.loads(out)
    assert len(d["items"]) == 2 and "a.com" in d.get("note", "")


def _nw_schema():
    return next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")["function"]


def test_schema_guidance_first_action_rule():
    fn = _nw_schema()
    assert "trigger_scrolls" in fn["parameters"]["properties"]
    assert "wait_ms" in fn["parameters"]["properties"]
    d = fn["description"]
    assert "第一动作" in d and "trigger_scrolls=2" in d
    # collect_list 互补指引（接口命中就不走 DOM 收割）
    assert "collect_list" in d


def test_guest_trigger_orchestration_static_lock():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    assert "networkWatch(mode = \"start\", pattern = \"\", includeBody = false, pullIdx = -1, trigger = null)" in js
    i = js.index("S270：一体化编排")
    seg = js[i:i + 1800]
    # 先滚后收割；收割走 read 表达式；arm_err 时跳过触发
    assert "sc.scrollOnce()" in seg and "await sleep(trigWait)" in seg
    assert "JSON.parse(await this._wvExec(wv, read)" in seg
    assert "arm_err" in seg
    assert seg.index("scrollOnce") < seg.index("_wvExec(wv, read)")
