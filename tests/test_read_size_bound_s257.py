# build=S301
# S257：network_watch read 返回必须压在 S184 工具输出限额（20000B）之下——曾被
# _bound_tool_output 截断成 .agent/tool_output 相对路径 marker，把 body_url 引用一起弄丢
# （agent 三轮反馈"body_url 是相对路径"的真因）。落盘条目另附本地 body_path（免 token）。
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

S184_LIMIT = 20000  # tool_output_store 默认 maxOutputBytes


def _hook(monkeypatch, tmp_path, read_payload, pull_body=None):
    calls = []

    async def fake(method, args, timeout=None, **kw):
        calls.append(args[0])
        if args[0] == "read":
            return read_payload
        if args[0] == "pull":
            return pull_body if pull_body is not None else ""
        return "armed"
    monkeypatch.setattr(cdp, "call_vue_method", fake)
    monkeypatch.setattr(cdp, "UPLOAD_FILES_DIR", str(tmp_path))
    monkeypatch.setattr(cdp, "get_port", lambda: 8765)
    return calls


def test_oversize_read_dumps_whole_list(tmp_path, monkeypatch):
    items = [{"gi": i, "u": "http://x/f" + str(i), "s": 200, "b": "数" * 2048}
             for i in range(40)]
    payload = json.dumps({"total": 40, "new_items": 40, "returned": 40,
                          "origin": "https://tieba.baidu.com", "items": items})
    _hook(monkeypatch, tmp_path, payload)
    out = asyncio.run(cdp.network_watch("read", "", True))
    assert len(out.encode("utf-8")) < S184_LIMIT  # 不再触发 S184 截断接管
    d = json.loads(out)
    assert "超返回限额" in d["note"] and "tieba.baidu.com" in d["note"]
    assert len(d["items"]) <= 8 and all("u" in it for it in d["items"])
    dumps = list(tmp_path.glob("net_read_*.json"))
    assert len(dumps) == 1
    full = json.loads(dumps[0].read_text(encoding="utf-8"))
    assert len(full["items"]) == 40 and full["items"][0]["b"]


def test_small_read_passthrough(tmp_path, monkeypatch):
    payload = json.dumps({"total": 2, "new_items": 2, "returned": 2,
                          "items": [{"gi": 0, "u": "http://x/a", "s": 200},
                                    {"gi": 1, "u": "http://x/b", "s": 404}]})
    _hook(monkeypatch, tmp_path, payload)
    out = asyncio.run(cdp.network_watch("read", "", False))
    d = json.loads(out)
    assert len(d["items"]) == 2 and "超返回限额" not in d.get("note", "")
    assert list(tmp_path.glob("net_read_*")) == []


def test_saved_item_body_path_and_short_b(tmp_path, monkeypatch):
    body = json.dumps({"posts": list(range(800))})
    payload = json.dumps({"total": 1, "new_items": 1, "returned": 1,
                          "origin": "https://tieba.baidu.com",
                          "items": [{"gi": 5, "u": "http://x/feed", "s": 200,
                                     "b": "P" * 2048, "blen": 90000}]})
    calls = _hook(monkeypatch, tmp_path, payload, pull_body=body)
    out = asyncio.run(cdp.network_watch("read", "feed", True))
    d = json.loads(out)
    it = d["items"][0]
    assert it["body_path"] and Path(it["body_path"]).is_absolute()
    assert Path(it["body_path"]).read_text(encoding="utf-8") == body
    assert it["body_url"].startswith("http://127.0.0.1:8765/uploaded_files/")
    assert len(it["b"]) <= 200  # 已落盘条目预览瘦身
    assert "body_path" in it["b_note"] and "免鉴权" in it["b_note"]
    assert ("read", "pull") == (calls[0], calls[1])


def test_schema_mentions_body_path():
    nw = next(t for t in cdp.all_cdp_tools if t["function"]["name"] == "network_watch")
    assert "body_path" in nw["function"]["description"]
