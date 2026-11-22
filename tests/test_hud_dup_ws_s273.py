# build=S281
# S273：HUD 重复弹出修复——ensureWS 在 __SAP_READY resolve 前 ws 恒 null 的防重入空窗
# （build+mergeCfg 双排队双建连，孤儿 socket 双 onNotify），加 opening 标志 + rec.id 去重。
# 用户现场：胶囊模式下旁观主动消息同刻弹出两条重复。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _js():
    return (ROOT / "static/js/hud-capsule.js").read_text(encoding="utf-8")


def test_opening_flag_closes_pending_window():
    js = _js()
    i = js.index("function ensureWS")
    seg = js[i:i + 1500]
    assert "if (ws || wsOpening || !cfg.enabled) return;" in seg
    assert "wsOpening = true;" in seg and "wsOpening = false;" in seg
    # open 内部二次 ws 判空（then 排队多任务时后者让位）
    assert seg.index("wsOpening = false;") < seg.index("if (ws) return;")


def test_stale_socket_close_guard():
    js = _js()
    i = js.index("function ensureWS")
    seg = js[i:i + 1500]
    # 陈旧 socket 的 close 不得清掉现行 ws 引用（否则孤儿会诱发重连翻倍）
    assert "if (ws !== this)" in seg


def test_notify_id_dedup_gate():
    js = _js()
    i = js.index("function isDup")
    seg = js[i:i + 500]
    assert "seenIds.length > 64" in seg
    n = js.index("function onNotify")
    nseg = js[n:n + 400]
    assert "isDup(rec && rec.id)" in nseg
    # 去重判定必须先于 badge++（重复投递不许双计）
    assert nseg.index("isDup(") < nseg.index("unread += 1")


def test_var_declared():
    js = _js()
    assert "var unread = 0, idleTimer = null, ws = null, wsRetry = null, wsOpening = false;" in js


def test_behavior_harness_covers_race_and_dup():
    h = (ROOT / "tests/data/hud_pop_harness_s272.js").read_text(encoding="utf-8")
    assert "__SAP_READY" in h and "wsCount - wsCountBefore === 1" in h
    assert "dup-msg" in h and "rec-dup-1" in h
