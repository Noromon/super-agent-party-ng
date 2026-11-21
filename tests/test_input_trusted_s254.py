# build=S267
# S254：CDP 真输入事件（isTrusted wheel/click，命中测试路由=人机等价）+ network_watch 全量 body 落盘
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

MAIN = (ROOT / "main.js").read_text(encoding="utf-8")
PRELOAD = (ROOT / "static/js/preload.js").read_text(encoding="utf-8")
JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_main_cdp_input_handlers():
    assert "ipcMain.handle('cdp-input-wheel'" in MAIN
    assert "ipcMain.handle('cdp-input-click'" in MAIN
    assert "Input.dispatchMouseEvent" in MAIN
    assert "'mouseWheel'" in MAIN and "'mousePressed'" in MAIN and "'mouseReleased'" in MAIN
    assert "devtools-busy" in MAIN  # DevTools 占用调试器 → 渲染层自动回退旧通道


def test_preload_bridges():
    assert "cdpInputWheel" in PRELOAD and "cdpInputClick" in PRELOAD


def test_vue_scroll_uses_trusted_wheel_with_fallback_chain():
    i = JS.index("scrollAndFind")
    seg = JS[i:i + 9000]
    assert "api.cdpInputWheel" in seg and 'mode = "wheel"' in seg  # 真滚轮优先
    assert "data-sap-sc" in seg  # 内层可滚容器探测打标（container 回退模式）
    assert "window.scrollBy(0," in seg  # window 兜底
    assert "scroller_mode" in seg
    assert "api.cdpInputClick" in seg and '"trusted"' in seg  # 真点击优先
    assert "__sapInner" in seg  # URL 不变时改点卡内 a/标题子目标


def test_vue_network_watch_full_body_and_pull():
    i = JS.index("_netwArmExpr(bodyOn)")  # S258: arm 上提后自此处起覆盖钩子+read+pull 全域
    seg = JS[i:i + 6400]  # S260 后 networkWatch 再度加长（等待加载+自愈块）
    assert "307200" in seg  # 全量 body 留 guest（≤300KB/条）
    assert "gi:i" in seg and "it.blen=full.length" in seg  # 全局索引+超长标记
    assert 'mode === "pull"' in seg and "slice(0,524288)" in seg  # pull 全文通道


def test_tab_id_error_explains_long_id():
    async def fake(method, args, timeout=None, **kw):
        return json.dumps([{"id": 1234567, "index": 0}])
    orig = cdp.call_vue_method
    cdp.call_vue_method = fake
    try:
        idx, err = asyncio.run(cdp._resolve_tab_index(9))  # 0 起下标误用当 tab_id
    finally:
        cdp.call_vue_method = orig
    assert idx is None and err
    assert "长整型 id" in err and "pageIdx" in err


def test_network_watch_body_url_dump(tmp_path, monkeypatch):
    big = "F" * 5000
    calls = []

    async def fake(method, args, timeout=None, **kw):
        calls.append((method, list(args)))
        if args[0] == "read":
            return json.dumps({"total": 5, "new_items": 1, "returned": 1,
                               "items": [{"gi": 3, "u": "http://x/feed", "s": 200,
                                          "b": "preview", "blen": 5000}]})
        if args[0] == "pull":
            assert args[3] == 3
            return big
        return "armed"
    monkeypatch.setattr(cdp, "call_vue_method", fake)
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cdp, "get_port", lambda: 3456)
    out = asyncio.run(cdp.network_watch("read", "feed", True))
    d = json.loads(out)
    it = d["items"][0]
    fn = it["body_url"].rsplit("/", 1)[-1]
    assert fn.startswith("net_") and fn.endswith(".json")
    assert (tmp_path / fn).read_text(encoding="utf-8") == big
    assert "body_url" in d["note"]
    assert ("networkWatch", ["pull", "", False, 3]) in calls


def test_network_watch_small_body_no_pull(monkeypatch):
    calls = []

    async def fake(method, args, timeout=None, **kw):
        calls.append(args[0])
        return json.dumps({"total": 1, "new_items": 1, "returned": 1,
                           "items": [{"gi": 0, "u": "http://x/a", "s": 200, "b": "short"}]})
    monkeypatch.setattr(cdp, "call_vue_method", fake)
    out = asyncio.run(cdp.network_watch("read", "", True))
    d = json.loads(out)
    assert "body_url" not in d["items"][0] and "note" not in d
    assert calls == ["read"]  # 无超长条目不触发 pull


def test_schemas_document_trusted_and_body_url():
    sf = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "scroll_and_find")
    d = sf["function"]["description"]
    assert "scroller_mode" in d and "isTrusted" in d
    nw = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")
    assert "body_url" in nw["function"]["description"]
