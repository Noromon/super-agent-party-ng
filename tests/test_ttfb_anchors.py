# -*- coding: utf-8 -*-
"""S123(拆分后仅存探针): TTFB 分段锚点。

S124 说明：S123 原提交的 mem0 预热与提取线程降优先级属性能改善非探针，
用户决定回滚（留案台账，R2 后可重做）；本文件只保留取证锚点断言。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(p):
    return (ROOT / p).read_text(encoding="utf-8")


def test_ttfb_anchors_present():
    sp = _read("server.py")
    assert "_TTFB_T0 = contextvars.ContextVar" in sp
    assert "[TTFBbrk] endpoint-enter +" in sp
    assert "[TTFBbrk] pre-stream +" in sp
    # 中间件在 call_next 之前 set（内层 task 继承 context）
    assert "if request.url.path.endswith(\"/chat/completions\"):\n        _TTFB_T0.set(_tt0)\n    response = await call_next(request)" in sp


def test_s124_perf_blades_reverted():
    # 回滚自证：预热/降优先级不得残留；套件页 v-if 分支内禁 v-for-v-memo
    # （S122/S122b 卡死事故红线，前缀必要不充分已实证）
    sp = _read("server.py")
    assert "_mem0_prewarm" not in sp
    assert "_lower_thread_priority" not in _read("py/llm_gate.py")
    for f in ("page_api-group.html", "page_deploy-bot.html",
              "page_model-config.html", "page_role.html"):
        assert "v-memo" not in _read("static/templates/" + f), f
