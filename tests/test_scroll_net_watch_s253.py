# S253：scroll_and_find 虚拟列表滚动搜索原语 + network_watch 内置网络观察
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cdp_tool as cdp  # noqa: E402

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def _spy():
    calls = []

    async def fake(method, args, timeout=None, **kw):
        calls.append((method, args, timeout))
        return '{"found": true}'
    return calls, fake


def _run(calls, fake, fn):
    orig = cdp.call_vue_method
    cdp.call_vue_method = fake
    try:
        return asyncio.run(fn())
    finally:
        cdp.call_vue_method = orig


def test_scroll_and_find_params_and_budget():
    calls, fake = _spy()
    out = _run(calls, fake, lambda: cdp.scroll_and_find("让CMG把控教育", action="click", max_scrolls=200, pause_ms=50))
    assert out == '{"found": true}'
    m, args, tmo = calls[-1]
    assert m == "scrollAndFind"
    assert args[1] == "click" and args[2] == 100 and args[3] == 200  # clamp 100 轮 / 200ms
    assert tmo == min(100 * 200 // 1000 + 45, 300)
    _run(calls, fake, lambda: cdp.scroll_and_find("x"))
    assert calls[-1][1] == ["x", "none", 30, 700, ""]


def test_network_watch_validation_and_dispatch():
    calls, fake = _spy()
    assert cdp and asyncio.run(cdp.network_watch(mode="bogus")).startswith("[Error]")
    _run(calls, fake, lambda: cdp.network_watch(mode="READ", pattern="newpostlist", include_body=True))
    m, args, tmo = calls[-1]
    assert m == "networkWatch" and args == ["read", "newpostlist", True, 0, None] and tmo == 30  # S254: 第4参 pull idx / S270: 第5参 trigger(read 模式恒 None)


def test_vue_scroll_and_find_impl():
    i = JS.index("scrollAndFind")
    seg = JS[i:i + 12000]  # S254/S256 后方法变长（真输入回退链+规范化匹配）
    assert "scrollIntoView" in seg and ".click()" in seg
    assert "url_changed" in seg and "url_after" in seg
    assert "window.scrollBy(0," in seg
    assert "innerText" in seg and "t.length>1200" in seg  # 最小含文本小块匹配
    assert "stable" in seg and "scrollHeight" in seg      # 到底早退


def test_vue_network_watch_impl():
    i = JS.index("_netwArmExpr(bodyOn)")  # S258: arm 主体上提为方法（start 与自动重挂共用）
    seg = JS[i:i + 4600]
    assert "__netw" in seg and "window.fetch" in seg and "XMLHttpRequest.prototype.open" in seg
    assert "slice(0,2048)" in seg and "E.length>=CAP" in seg
    assert "w.c=lastHit>=0?lastHit+1:from;" in seg and "o.u.indexOf(pat)<0" in seg  # 游标增量（S295：只前进至末位命中）+pattern 过滤
    assert "not armed" in seg and "导航" in seg  # 导航丢钩子提示
    j = JS.index("_netwArmExpr(bodyOn)")
    assert "return 'armed'" in JS[j:j + 2200]


def test_schemas_registered_and_guided():
    # S255 教训：schema 注册≠可执行，dispatch 表注册由 test_tool_registry_parity_s255.py 把关
    sys_src = ((ROOT / "server.py").read_text(encoding="utf-8") + (ROOT / "py" / "approval_exec.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）
    assert '"scroll_and_find": scroll_and_find' in sys_src and '"network_watch": network_watch' in sys_src
    names = {t["function"]["name"] for t in cdp.all_cdp_tools}
    assert {"scroll_and_find", "network_watch"} <= names
    sf = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "scroll_and_find")
    assert sf["function"]["parameters"]["required"] == ["match"]
    assert "click" in sf["function"]["description"] and "贴吧" in sf["function"]["description"]
    nw = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")
    assert nw["function"]["parameters"]["required"] == ["mode"]
    ts = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "take_snapshot")
    d = ts["function"]["description"]
    assert "scroll_and_find" in d and "network_watch" in d and "risk-control" in d
