# S231：日记主动消息事实化 + mem0 角色锚定
# 取证动因：16:12 imMessage「今天一整天都没听见你说话」与 16:10 对话矛盾；
# mem0 被喂「用户说…---你说…」压平字符串导致记忆角色漂移/反转。
import asyncio
import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.diary_engine as de  # noqa: E402

TODAY = datetime.datetime(2026, 11, 16, 16, 30)


def _t(hm):
    return f"2026-11-16T{hm}:00"


def _srv_src():
    return (ROOT / "server.py").read_text(encoding="utf-8")


# ---------------- B1: mem0 角色锚定 ----------------

def test_mem0_structured_messages():
    src = _srv_src()
    assert 'f"用户说：' not in src  # 旧压平格式已移除
    assert src.count('{"role": "assistant", "content": _neutralize') >= 2  # 流式+非流式


def test_mem0_prompts_have_attribution_rules():
    from py.llm_gate import _MEM0_FACT_PROMPT, _MEM0_UPDATE_PROMPT
    assert "role=user" in _MEM0_FACT_PROMPT and "严禁把助手" in _MEM0_FACT_PROMPT
    assert "归属主体" in _MEM0_UPDATE_PROMPT and "不得互换" in _MEM0_UPDATE_PROMPT


def test_diary_platform_excluded_from_mem0_and_buffers():
    # 2×mem0 提交 + 2×chatSummary 缓冲（S231）都须排除 diary 自调用
    src = _srv_src()
    assert src.count('platform", "") != "diary"') >= 4


# ---------------- A1: 今日概况事实化 ----------------

def _patch_entries(monkeypatch, entries):
    async def _entries(book_id, n=40):
        return entries

    async def _mems():
        return []

    monkeypatch.setattr(de, "get_recent_diary_entries", _entries)
    monkeypatch.setattr(de, "_fetch_today_new_memories", _mems)


def test_overview_strips_date_head_and_marks_chat(monkeypatch):
    _patch_entries(monkeypatch, [
        {"type": "chatSummary", "time": _t("10:59"),
         "content": "**2026年11月16日 星期一 晴**\n\n主人今天没让我查新的东西，而是让我把话说清楚"},
        {"type": "imMessage", "time": _t("13:43"), "content": "下午好呀"},
    ])
    block = asyncio.run(de.build_today_context("book-a", TODAY))
    assert "对话记录（用户与你实际说过话）" in block
    assert "你单方面发出的主动消息" in block
    assert "**2026年" not in block            # markdown 日期头已剥，预算落在正文
    assert "主人今天没让我查新的东西" in block
    assert "严禁采用" in block                 # has_user_chat 硬提示在场


def test_has_today_user_interaction_gate(monkeypatch):
    _patch_entries(monkeypatch, [{"type": "think", "time": _t("09:00"), "content": "发呆"}])
    assert asyncio.run(de.has_today_user_interaction("b", TODAY)) is False
    _patch_entries(monkeypatch, [{"type": "chatSummary", "time": _t("16:10"), "content": "聊了浏览器"}])
    assert asyncio.run(de.has_today_user_interaction("b", TODAY)) is True


def test_overview_no_chat_no_hard_hint(monkeypatch):
    _patch_entries(monkeypatch, [
        {"type": "think", "time": _t("09:00"), "content": "思考一"},
        {"type": "think", "time": _t("10:00"), "content": "思考二"},
    ])
    block = asyncio.run(de.build_today_context("b", TODAY))
    assert "还没有与用户交流的记录" in block and "2 篇思考" in block
    assert "严禁采用" not in block


def test_overview_empty_day_unchanged(monkeypatch):
    _patch_entries(monkeypatch, [])
    assert "确实尚未互动" in asyncio.run(de.build_today_context("b", TODAY))


# ---------------- A2: 语义校对 pass ----------------

def _fake_client(payload_json=None, raise_err=None):
    class _Resp:
        def raise_for_status(self):
            if raise_err:
                raise raise_err
            return None

        def json(self):
            return payload_json

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json=None):
            return _Resp()

    return _Client


def _review(monkeypatch, out=None, payload_json=None, raise_err=None):
    if payload_json is None and out is not None:
        payload_json = {"choices": [{"message": {"content": out}}]}
    monkeypatch.setattr(de.httpx, "AsyncClient", _fake_client(payload_json, raise_err))
    eng = de.DiaryEngine.__new__(de.DiaryEngine)
    return asyncio.run(eng._truthful_review_im(
        "主人～今天一整天都没听见你说话。", "【今日概况】…（含对话记录）…"))


def test_review_fixed_returns_rewrite(monkeypatch):
    got = _review(monkeypatch, out='{"fixed": true, "text": "主人～下午好，今天忙什么呢？"}')
    assert got == "主人～下午好，今天忙什么呢？"


def test_review_not_fixed_returns_draft(monkeypatch):
    # _review 的固定草稿应原样返回
    got = _review(monkeypatch, out='{"fixed": false, "text": "随便改写"}')
    assert got == "主人～今天一整天都没听见你说话。"


def test_review_fence_and_loose_json_still_works(monkeypatch):
    got = _review(monkeypatch, out='```json\n{"fixed": true, "text": "改写版"}\n```')
    assert got == "改写版"


def test_review_garbage_fail_open(monkeypatch):
    draft = "主人～今天一整天都没听见你说话。"
    assert _review(monkeypatch, out="我觉得没什么问题") == draft


def test_review_call_error_fail_open(monkeypatch):
    draft = "主人～今天一整天都没听见你说话。"
    assert _review(monkeypatch, raise_err=RuntimeError("boom")) == draft


def test_review_fixed_empty_means_drop(monkeypatch):
    assert _review(monkeypatch, out='{"fixed": true, "text": ""}') == ""


def test_run_action_wires_truth_gate():
    src = (ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
    assert "await has_today_user_interaction(book_id)" in src
    assert "_truthful_review_im(content, _tb)" in src
    assert "已丢弃（归档 think）" in src


# ---------------- A2b: 防重复 ----------------

def test_im_prev_message_dedupe_wired():
    src = (ROOT / "py" / "diary_engine.py").read_text(encoding="utf-8")
    assert "24 小时内上一条主动消息" in src
    assert "换一个全新的由头" in src
