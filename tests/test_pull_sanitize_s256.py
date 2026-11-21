# build=S271
# S256：network_watch 落盘链路加固（pull 截断网关绕过、污染门禁、origin 附注）
# + scroll_and_find 命中强化（innerText 规范化匹配 + 可点祖先上溯）。
# 动因：agent 实测贴吧报告——pull 落盘拿到"Vue 包装返回"伪文件、feed 相对路径图片缺 base、
# 标题文本 4 次 found:false。
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

JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_vue_pull_bypasses_truncation_gateway():
    # S106 网关默认 60000 字符——pull 曾漏传 maxLen，大响应落盘成碎 JSON
    i = JS.index('mode === "pull"')
    assert "_wvExec(wv, pull, 524288)" in JS[i - 200:i + 300]


def test_vue_read_includes_origin():
    assert "origin:String(location.origin||'')" in JS


def test_vue_find_normalizes_and_uses_clickable_ancestor():
    i = JS.index("const findExpr")
    seg = JS[i:i + 1800]
    assert "nf=function" in seg and "mm=nf(m)" in seg and "nf(c.innerText" in seg  # 规范化匹配
    assert "clk=function" in seg and "el=clk(el)" in seg  # 可点祖先上溯
    assert "onclick" in seg and "/card|item|post|thread|topic|row/i" in seg


def test_pull_polluted_gate():
    assert cdp._pull_polluted("")
    assert cdp._pull_polluted("浏览器操作超时：渲染主线程繁忙——……")
    assert cdp._pull_polluted("Error executing networkWatch: boom")
    assert cdp._pull_polluted('{"jsonrpc":"2.0","id":7}')
    assert cdp._pull_polluted("[Unknown Tool] 工具不存在")
    assert cdp._pull_polluted("x" * 5000 + "...[S106 truncated 300 chars]")
    assert cdp._pull_polluted("Operation completed (Type: object)")
    assert not cdp._pull_polluted('{"posts": [{"id": 1}]}')
    assert not cdp._pull_polluted("plain response text, fine")


def _read_payload():
    return json.dumps({"total": 2, "new_items": 1, "returned": 1,
                       "origin": "https://tieba.baidu.com",
                       "items": [{"gi": 1, "u": "http://x/f", "s": 200,
                                  "b": "prev", "blen": 90000}]})


def test_pull_error_text_not_dumped(tmp_path, monkeypatch):
    async def fake(method, args, timeout=None, **kw):
        if args[0] == "read":
            return _read_payload()
        return "浏览器操作超时：渲染主线程繁忙——处置见提示"
    monkeypatch.setattr(cdp, "call_vue_method", fake)
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path))
    out = asyncio.run(cdp.network_watch("read", "f", True))
    d = json.loads(out)
    it = d["items"][0]
    assert "b_err" in it and "body_url" not in it
    assert "全文拉取失败" in d["note"] and "tieba.baidu.com" in d["note"]  # origin 附注不受影响
    assert list(tmp_path.iterdir()) == []  # 污染文本未落盘


def test_pull_ok_note_carries_origin_hint(tmp_path, monkeypatch):
    body = json.dumps({"posts": [{"tid": i, "t": "标题" * 200} for i in range(50)]}, ensure_ascii=False)

    async def fake(method, args, timeout=None, **kw):
        return _read_payload() if args[0] == "read" else body
    monkeypatch.setattr(cdp, "call_vue_method", fake)
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cdp, "get_port", lambda: 3456)
    out = asyncio.run(cdp.network_watch("read", "f", True))
    d = json.loads(out)
    it = d["items"][0]
    assert "body_url" in it and "b_err" not in it
    assert (tmp_path / it["body_url"].rsplit("/", 1)[-1]).read_text(encoding="utf-8") == body
    assert "拼该域名" in d["note"] and "https://tieba.baidu.com" in d["note"]
