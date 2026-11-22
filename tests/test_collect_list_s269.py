# build=S282
# S269：collect_list 虚拟列表收割原语——参数钳制/opts 组装/大结果落盘（S257 同款通道）/
# schema 与 guest 实现静态锁。行为背景：agent 刷贴吧手搓"滚N屏+逐屏取DOM+去重"5轮往返，
# SAP 自评的头号堵点（2026-11-21 会话复盘），本工具一次调用替代。
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


class _Calls(list):
    pass


def _fake_vue(calls, reply="{}"):
    async def fake(method, args=None, timeout=None):
        calls.append((method, args, timeout))
        return reply
    return fake


def test_opts_clamp_and_budget():
    calls = _Calls()
    orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(calls)
    try:
        _run(cdp.collect_list(".card", {"t": ".title"}, max_items=9999, max_scrolls=999,
                              pause_ms=1, no_new_rounds=99))
    finally:
        cdp.call_vue_method = orig
    m, args, to = calls[0]
    assert m == "collectList"
    opts = args[0]
    assert opts["item"] == ".card" and opts["fields"] == {"t": ".title"}
    assert opts["max_items"] == 500 and opts["max_scrolls"] == 80
    assert opts["pause_ms"] == 200 and opts["no_new_rounds"] == 10
    # 预算：轮数×(停顿+400ms 往返开销)+45s 封顶 300——这里 80×(200+400)/1000+45=93
    assert to == 93


def test_small_result_passthrough_and_error_text():
    calls = _Calls()
    body = json.dumps({"collected": 2, "rounds": 1, "stop_reason": "no_new_rounds",
                       "items": [{"t": "a"}, {"t": "b"}]}, ensure_ascii=False)
    cdp_orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(calls, body)
    try:
        out = _run(cdp.collect_list(".c", {"t": ".x"}))
        assert json.loads(out)["collected"] == 2
        err_calls = _Calls()
        cdp.call_vue_method = _fake_vue(err_calls, "Error: collect_list 需要 item（卡片根 CSS 选择器")
        out2 = _run(cdp.collect_list("", {"t": ".x"}))
        assert out2.startswith("Error:")
    finally:
        cdp.call_vue_method = cdp_orig


def test_big_result_lands_to_disk(monkeypatch, tmp_path):
    items = [{"t": "x" * 300, "h": "/p/" + str(i)} for i in range(120)]  # ~40KB
    body = json.dumps({"collected": 120, "rounds": 30, "stop_reason": "max_items",
                       "items": items}, ensure_ascii=False)
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path / "up"))
    monkeypatch.setattr(cdp, "get_port", lambda: 12345)
    cdp_orig = cdp.call_vue_method
    cdp.call_vue_method = _fake_vue(_Calls(), body)
    try:
        out = _run(cdp.collect_list(".c", {"t": ".x", "h": "a@href"}))
    finally:
        cdp.call_vue_method = cdp_orig
    d = json.loads(out)
    assert d["items"] is None and len(d["preview_first10"]) == 10
    assert d["body_path"] and Path(d["body_path"]).exists()
    assert "127.0.0.1:12345" in d["body_url"]
    full = json.loads(Path(d["body_path"]).read_text(encoding="utf-8"))
    assert len(full["items"]) == 120


def _schema():
    return next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "collect_list")


def test_schema_shape_and_guidance():
    fn = _schema()["function"]
    assert set(fn["parameters"]["required"]) == {"item", "fields"}
    props = fn["parameters"]["properties"]
    assert {"item", "fields", "key", "older_than", "date_field", "no_new_rounds"} <= set(props)
    d = fn["description"]
    # 关键引导：until 语义、@属性语法、落盘通道、接口优先提示
    assert "@href" in d and "older_than" in d and "body_path" in d
    assert "network_watch" in d


def test_guest_impl_static_locks():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    i = js.index("async collectList(")
    seg = js[i:i + 5200]
    for anchor in ("max_items", "no_new_rounds", "older_than", "bottom", "max_scrolls",
                   "map.has(k)", "getAttribute", "_makeScroller"):
        assert anchor in seg, f"collectList 缺锚点 {anchor}"
    # 循环内先抽取后滚动（首屏必须能直接收割）
    assert seg.index("extractExpr) ||") < seg.index("scrollOnce()")
    # S261 事故族防线：拼接脚本里 try 必配 catch——粗查本段 guest 表达式 try/catch 数量对等
    assert seg.count("try{") <= seg.count("catch")


def test_scroller_channel_probe_present():
    js = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")
    i = js.index("async _makeScroller(")
    seg = js[i:i + 4200]
    # 真轮询优先 → container 打标 → window 兜底（与 scrollAndFind 同款人机通道）
    assert "cdpInputWheel" in seg and "data-sap-sc" in seg and "window.scrollBy" in seg
