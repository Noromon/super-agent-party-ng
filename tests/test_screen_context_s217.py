# -*- coding: utf-8 -*-
"""S217: 旁观对话注入——意图命中 → 屏幕观察上下文进入系统提示。

钉三层：①screen_memory.build_context_block 纯函数（词表门控/检索命中/时间线
兜底/无数据不注入/摘要附带/行长截断）②server._inject_screen_context 门控与
安全（ast 抽取+假 self：enabled/is_sub_agent/空块都不注入；注入必过
neutralize(store=screen-context)——屏幕文字是外部不可信源）③e2e：真实 /v1
链路里 mock LLM 实收的 system prompt 含 [屏幕旁观]，旁观关闭时不含。
"""
import ast
import asyncio
import datetime
import json
import logging
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import screen_memory as sm  # noqa: E402

_SERVER_SRC = (_ROOT / "server.py").read_text(encoding="utf-8-sig")


def _ts(y, mo, d, h, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def _ev(ts, summary="打开了页面", activity="browsing", importance=1, title="Chrome"):
    return {"ts": ts, "iso": "x", "title": title, "summary": summary,
            "activity": activity, "importance": importance, "took_s": 0.3}


def _write_log(path, events):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
                    encoding="utf-8")


NOW = _ts(2026, 11, 14, 15)


class TestBuildContextBlock:
    def test_intent_gate(self):
        assert sm.intent_hit("我屏幕上刚弹了个报错")
        assert sm.intent_hit("What Am I Looking At")
        assert sm.intent_hit("旁观模式看到什么了")
        assert not sm.intent_hit("帮我写个排序函数")
        assert not sm.intent_hit("")

    def test_no_intent_no_block(self, tmp_path):
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(NOW - 600, summary="编译错误")])
        assert sm.build_context_block("帮我写排序函数", now=NOW,
                                      out_dir=tmp_path, log_path=p) == ""

    def test_search_hit_injected(self, tmp_path):
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(NOW - 700, summary="VSCode 弹出编译错误",
                           activity="coding", importance=4, title="Visual Studio Code"),
                       _ev(NOW - 600, summary="无关的聊天窗口", activity="chatting")])
        block = sm.build_context_block("我屏幕上刚才那个编译错误是什么", now=NOW,
                                       out_dir=tmp_path, log_path=p)
        assert "[屏幕旁观 - 近期上下文]" in block
        assert "VSCode 弹出编译错误" in block
        assert "无关的聊天窗口" not in block
        assert "不是用户本人的陈述" in block
        assert "importance 4" in block

    def test_timeline_fallback_and_no_data(self, tmp_path):
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(NOW - 900, summary="浏览文档", activity="browsing"),
                       _ev(NOW - 10 * 3600, summary="太旧的不要")])
        block = sm.build_context_block("旁观一下我刚才在干嘛", now=NOW,
                                       out_dir=tmp_path, log_path=p)
        assert "近 6 小时屏幕时间线" in block and "浏览文档" in block
        assert "太旧的不要" not in block
        empty = tmp_path / "none.jsonl"
        assert sm.build_context_block("屏幕", now=NOW,
                                      out_dir=tmp_path, log_path=empty) == ""

    def test_digest_attached_and_line_truncate(self, tmp_path):
        p = tmp_path / "screen_log.jsonl"
        _write_log(p, [_ev(NOW - 600, summary="长" * 300, activity="coding")])
        (tmp_path / "screen_digest_2026-11-13.md").write_text("# 昨日摘要内容", encoding="utf-8")
        block = sm.build_context_block("屏幕", now=NOW, out_dir=tmp_path, log_path=p)
        assert "昨日观察摘要" in block and "# 昨日摘要内容" in block
        body = [ln for ln in block.splitlines() if ln.startswith("- ")]
        assert len(body[0]) < 200  # 摘要行截断


class TestServerInjection:
    """ast 抽取 server._inject_screen_context，ns 桩隔离（真 screen_memory 模块，
    build_context_block 用 monkeypatch 换返回）。"""

    def _load(self, monkeypatch):
        tree = ast.parse(_SERVER_SRC)
        node = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.AsyncFunctionDef)
                    and n.name == "_inject_screen_context")
        appends, neutralized = [], []
        ns = {
            "asyncio": asyncio, "logging": logging,
            "screen_memory": sm,
            "content_append": lambda msgs, role, text: appends.append((role, text)),
            "_neutralize": lambda text, store="": neutralized.append(store) or text,
        }
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<inj>", "exec"), ns)
        monkeypatch.setitem(ns, "screen_memory", sm)
        return ns["_inject_screen_context"], appends, neutralized

    class _Req:
        def __init__(self):
            self.messages = []
            self.is_sub_agent = False

    def _run(self, fn, req, settings):
        asyncio.run(fn(req, settings, "我屏幕上的报错"))

    def test_disabled_or_subagent_zero_action(self, monkeypatch):
        fn, appends, _ = self._load(monkeypatch)
        self._run(fn, self._Req(), {"screenWatchSettings": {"enabled": False}})
        req = self._Req()
        req.is_sub_agent = True
        self._run(fn, req, {"screenWatchSettings": {"enabled": True}})
        assert appends == []

    def test_no_block_no_append(self, monkeypatch):
        monkeypatch.setattr(sm, "build_context_block", lambda *a, **k: "")
        fn, appends, neutralized = self._load(monkeypatch)
        self._run(fn, self._Req(), {"screenWatchSettings": {"enabled": True}})
        assert appends == [] and neutralized == []

    def test_block_neutralized_into_system(self, monkeypatch):
        monkeypatch.setattr(sm, "build_context_block", lambda *a, **k: "[屏幕旁观] 事件…")
        fn, appends, neutralized = self._load(monkeypatch)
        req = self._Req()
        self._run(fn, req, {"screenWatchSettings": {"enabled": True}})
        assert appends == [("system", "[屏幕旁观] 事件…")]
        assert neutralized == ["screen-context"]  # 安全路钉：不过 neutralize 不算注入

    def test_failure_swallowed(self, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("disk gone")
        monkeypatch.setattr(sm, "build_context_block", boom)
        fn, appends, _ = self._load(monkeypatch)
        self._run(fn, self._Req(), {"screenWatchSettings": {"enabled": True}})
        assert appends == []


class TestWiringPins:
    def test_mounted_after_diary_before_tools(self):
        seg = _SERVER_SRC[_SERVER_SRC.find("[日记集成] 提取日记失败"):]
        seg = seg[:seg.find("tools_change_messages(request, settings)")]
        assert "_inject_screen_context(request, settings" in seg


# ---------------- e2e：真实 /v1 链路 ----------------

from test_contract_sse import post_chat, collect, sse  # noqa: E402
from test_tool_assembly_parity import _mutate_settings, _restore_settings  # noqa: E402


def _system_prompt_of(history):
    for call in history:
        for m in call.get("messages") or []:
            if m.get("role") == "system":
                return str(m.get("content") or "")
    return ""


def _seed_watch(sap, events):
    d = Path(sap.data_dir) / "screen_watch"
    d.mkdir(parents=True, exist_ok=True)
    _write_log(d / "screen_log.jsonl", events)
    return d / "screen_log.jsonl"


def _rm_watch(sap):
    import shutil
    shutil.rmtree(Path(sap.data_dir) / "screen_watch", ignore_errors=True)


def test_e2e_screen_context_reaches_llm(sap, mock_llm):
    now = __import__("time").time()
    log = _seed_watch(sap, [_ev(now - 900, summary="VSCode 编译错误弹窗",
                                activity="coding", importance=5, title="Visual Studio Code")])
    original = _mutate_settings(
        sap.data_dir, lambda d: d.setdefault("screenWatchSettings", {}).update({"enabled": True}))
    try:
        mock_llm.script([{"kind": "text", "content": "ok"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "我屏幕上刚才的编译错误是什么情况"}]})
        assert r.status_code == 200
        collect(sse(r))
        sys_prompt = _system_prompt_of(mock_llm.history)
        assert "[屏幕旁观 - 近期上下文]" in sys_prompt
        assert "VSCode 编译错误弹窗" in sys_prompt
    finally:
        _restore_settings(sap.data_dir, original)
        log.unlink(missing_ok=True)
        _rm_watch(sap)


def test_e2e_observer_off_no_injection(sap, mock_llm):
    now = __import__("time").time()
    log = _seed_watch(sap, [_ev(now - 900, summary="编译错误弹窗")])
    try:
        mock_llm.script([{"kind": "text", "content": "ok"}])
        r = post_chat(sap, {"messages": [{"role": "user", "content": "我屏幕上刚才的编译错误是什么情况"}]})
        assert r.status_code == 200
        collect(sse(r))
        assert "[屏幕旁观" not in _system_prompt_of(mock_llm.history)
    finally:
        log.unlink(missing_ok=True)
        _rm_watch(sap)
