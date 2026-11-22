# build=S302
# S296：相似调用绕圈熔断（贴吧探索事故对症）。纯逻辑单测 + 双侧接线静态锁。
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_mod = sys.modules.get("py")
if _mod is not None and not hasattr(_mod, "__path__"):
    del sys.modules["py"]

from py.tool_spiral import SpiralWatch, signature  # noqa: E402

SRV = ((ROOT / "server.py").read_text(encoding="utf-8") + (ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8") + (ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8"))  # S302a：流式域迁 stream_prep/stream_engine，源读合并（体逐字未动）


def test_percent_variants_converge():
    a = signature("navigate_page", {"url": "https://www.baidu.com/s?wd=%E6%9C%89%E7%94%B7%E4%B8%8D%E7%8E%A9"})
    b = signature("navigate_page", {"url": "https://www.baidu.com/s?wd=%E6%AF%8F%E7%94%B7%E4%B8%8D%E7%8E%A9"})
    assert a == b, "手敲编码错体（毫/每混编）必须收敛为同签名（事故主形态）"
    assert a != signature("navigate_page", {"url": "https://www.baidu.com/s?wd=%E6%9C%89%E7%94%B7ml"})
    assert signature("navigate_page", {"url": "https://tieba.baidu.com/f?kw=x"}) != a


def test_trips_once_then_escalates():
    w = SpiralWatch(window=8, repeat=3)
    hints = [w.observe("new_page", {"url": f"https://s.example/?q=%E6%97%A0%E6%96%99{i:02d}"}) for i in range(4)]
    assert hints[0] is None and hints[1] is None
    assert hints[2] and "绕圈检测" in hints[2]
    assert hints[3] is None, "同签名只炸一次"
    more = [w.observe("evaluate_script", {"script_code": f"function(){{scan({i})}}"}) for i in range(2)]
    assert more[1] is None
    trig2 = w.observe("evaluate_script", {"script_code": "function(){scan(99999)}"})
    assert trig2 and "最后提醒" in trig2, "第二签名应出升级文案"


def test_window_slide_and_exempt_and_damping():
    w = SpiralWatch(window=8, repeat=3)
    for i in range(6):
        w.observe("new_page", {"url": "https://x.test/a"})
        assert w.observe("take_snapshot", {}) is None  # 豁免：无参观测
    w2 = SpiralWatch(window=8, repeat=4)
    out = []
    for i in range(12):  # 真·相同调用穿插其他不同调用，最终仍应炸（窗口滑不掉）
        out.append(w2.observe("browser_lookup", {"query": "同样的查询"}))
        w2.observe("close_page", {"pageIdx": i})
    assert any(h for h in out), "分散在窗口内的重复也应计数触发"


def test_server_wiring_both_paths():
    assert "from py.tool_spiral import SpiralWatch" in SRV
    assert '_st.get("_spiral")' in SRV and '_st.setdefault("_spiral", SpiralWatch())' in SRV
    assert SRV.count('{"role": "user", "content": _sp_hint, "name": "system_note"}') == 2, "流式+非流式都要注入"
    assert "spiral=_ns_spiral" in SRV and "_ns_spiral = SpiralWatch()" in SRV
    assert "EXEMPT" in Path(ROOT / "py" / "tool_spiral.py").read_text(encoding="utf-8")


def test_inject_only_after_pair_closure():
    # 注入 helper 必须紧跟 append_missing_results（tool_calls 对闭合后才有 user 消息容身）
    assert '_spiral_drain(request, _st)' in SRV
    assert '_spiral_drain_ns(request, _sp_hints)' in SRV
    assert SRV.count('{"role": "user", "content": _sp_hint, "name": "system_note"}') == 2
    for anchor in ("assistant_tool_calls, acked_ids)", "ns_tool_calls_meta, ns_acked_ids)"):
        i = SRV.index(anchor)
        assert "_spiral_drain" in SRV[i:i + 220], "绕圈注入必须紧随对闭合"
