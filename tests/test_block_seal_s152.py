# -*- coding: utf-8 -*-
"""S152：块级封口发送 + 工具进度摘要/详细模式（xmpp 先行）。

封口=正文块被 tool call 打断即全量发出；摘要=任务尾一条 🔧 汇总；
审批哨兵前缀回销未执行工具（续流重放后才记账）。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.xmpp_client as xc  # noqa: E402
from py.base_bot import ToolProgressLedger  # noqa: E402

SENTINEL = ('{"__sap_approval_v1__":1,"tool_name":"shell_exec",'
            '"tool_params":{},"reason":"not_allowed"}')


# ---------- ToolProgressLedger 单元 ----------

def test_ledger_call_and_summary():
    led = ToolProgressLedger("summary")
    assert led.on_call("a") is True
    assert led.on_call("a") is True  # 同名重复仍封口
    assert led.on_result("a", "ok") is None  # 摘要模式不发逐行
    assert led.on_call("b") is True  # b 无结果=后台
    assert led.summary_line() == "🔧 本次执行：a；b（后台运行中）"


def test_ledger_detail_mode():
    led = ToolProgressLedger("detail")
    led.on_call("a")
    assert led.on_result("a", "ok") == "✅ a 完成"
    assert led.summary_line() is None


def test_ledger_default_off_and_illegal_normalized():
    led = ToolProgressLedger()          # 默认 off（S152b）
    assert led.mode == "off"
    assert led.on_call("a") is True     # 封口信号与档位无关
    assert led.on_result("a", "ok") is None
    assert led.summary_line() is None
    assert ToolProgressLedger("bogus").mode == "off"  # 非法值归一最保守档


def test_ledger_approval_sentinel_rollback():
    led = ToolProgressLedger("summary")
    led.on_call("shell_exec")
    assert led.on_result("shell_exec", SENTINEL) is None
    assert led.summary_line() is None  # 未执行=不入账
    led.on_call("shell_exec")  # 续流重放后重新记账
    assert led.on_result("shell_exec", "done") is None
    assert led.summary_line() == "🔧 本次执行：shell_exec"


def test_ledger_field_dual_shape():
    assert ToolProgressLedger.field({"type": "call", "title": "a"}, "type") == "call"
    assert ToolProgressLedger.field(SimpleNamespace(type="tool_result"), "type") == "tool_result"
    assert ToolProgressLedger.field(None, "type") == ""
    assert ToolProgressLedger.field({"title": None}, "title", "x") == "x"


# ---------- xmpp 流集成 ----------

def _chunk(content="", tc=None, finish=None):
    delta = SimpleNamespace(content=content, reasoning_content="",
                            tool_link="", async_tool_id="", tool_content=tc)
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish, delta=delta)])


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __aiter__(self):
        async def _gen():
            for c in self._chunks:
                yield c
        return _gen()


class _FakeOpenAI:
    last = None

    def __init__(self, *a, **k):
        pass

    @property
    def chat(self):
        return self

    @property
    def completions(self):
        return self

    async def create(self, **kw):
        return _FakeStream(type(self).last)


def _client(mode):
    c = object.__new__(xc.XmppClient)
    c.XmppAgent = "super-model"
    c.reasoningVisible = False
    c.progress_mode = mode
    c.separators = ["。", "\n", "？", "！"]
    c.asyncToolsID = {"u@localhost": []}
    c.fileLinks = {"u@localhost": []}
    c.tools_mode = "inherit"
    c.tools_list = []
    c.sent = []

    async def _send(jid, text):
        c.sent.append(text)

    c._send_text = _send
    return c


def _run_stream(monkeypatch, chunks, mode):
    _FakeOpenAI.last = chunks
    monkeypatch.setattr(xc, "AsyncOpenAI", _FakeOpenAI)

    async def _settings():
        return {"tools": {"toolMemorandum": {"enabled": False}}}

    monkeypatch.setattr(xc, "load_settings", _settings)
    c = _client(mode)

    async def _go():
        return await c._agent_stream_to_peer("u@localhost", [{"role": "user", "content": "hi"}])

    res = asyncio.run(_go())
    return c, res


def test_block_seal_and_summary(monkeypatch):
    c, res = _run_stream(monkeypatch, [
        _chunk(content="先做第一步"),
        _chunk(tc={"type": "call", "title": "search_web", "content": "{}"}),
        _chunk(tc={"type": "tool_result", "title": "search_web", "content": "结果"}),
        _chunk(content="然后挂起"),
        _chunk(tc={"type": "call", "title": "shell_exec", "content": "{}"}),
        _chunk(tc={"type": "tool_result", "title": "shell_exec", "content": SENTINEL}),
    ], mode="summary")
    # 打断即封口：两次工具 call 前的半截块都立即发出（审批前文本不滞留）；
    # 审批哨兵工具不入账；摘要在流尾
    assert c.sent == ["先做第一步", "然后挂起", "🔧 本次执行：search_web"]
    assert res["out_buffer"] == ""
    assert res["assistant_text"] == "先做第一步然后挂起"


def test_block_seal_detail_mode(monkeypatch):
    c, res = _run_stream(monkeypatch, [
        _chunk(content="开工"),
        _chunk(tc={"type": "call", "title": "a", "content": "{}"}),
        _chunk(tc={"type": "tool_result", "title": "a", "content": "ok"}),
        _chunk(content="收尾"),
    ], mode="detail")
    assert c.sent == ["开工", "✅ a 完成"]  # 详细模式不发汇总
    assert res["out_buffer"] == "收尾"


def test_block_seal_off_mode(monkeypatch):
    # 默认档：封口照常（正文实时），但零工具行、零汇总
    c, res = _run_stream(monkeypatch, [
        _chunk(content="先做第一步"),
        _chunk(tc={"type": "call", "title": "search_web", "content": "{}"}),
        _chunk(tc={"type": "tool_result", "title": "search_web", "content": "结果"}),
        _chunk(content="收尾"),
    ], mode="off")
    assert c.sent == ["先做第一步"]
    assert res["out_buffer"] == "收尾"


def test_no_tools_no_progress_lines(monkeypatch):
    c, _ = _run_stream(monkeypatch, [
        _chunk(content="纯聊天"),
    ], mode="summary")
    assert c.sent == []  # 无工具=零打扰；缓冲由调用方收尾发出
