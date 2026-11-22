# -*- coding: utf-8 -*-
"""S192 opencode 对齐：prune token 预算制、contextWindow auto 探测、轮边界 L1 复查。

覆盖：预算内保尾/超预算修剪/保底条数、budget=0 旧行为、get_context_settings
auto 与容错、探测解析与缓存/回退、_boundary_l1_recheck 行为、source 钉。
"""
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _tool(i, size=0):
    return {"role": "tool", "tool_call_id": f"t{i}", "name": "x",
            "content": "z" * size}


class TestPruneBudget:
    def test_budget_prunes_over_limit(self):
        from py.context_manager import prune_tool_results
        # 每条 4000 字符 ≈1000 tok；预算 2500 → 只保最新 2 条，其余修剪
        msgs = [_tool(i, 4000) for i in range(6)]
        out, n = prune_tool_results(msgs, keep_recent_tools=1, tool_output_budget=2500)
        assert n == 4
        kept = [m for m in out if not str(m["content"]).startswith("[pruned")]
        assert len(kept) == 2
        assert kept[0]["tool_call_id"] == "t4" and kept[-1]["tool_call_id"] == "t5"

    def test_floor_keeps_recent_even_over_budget(self):
        from py.context_manager import prune_tool_results
        msgs = [_tool(i, 400000) for i in range(5)]  # 每条 ~100k tok
        out, n = prune_tool_results(msgs, keep_recent_tools=4, tool_output_budget=1000)
        assert n == 1  # 只有第 5 新之外的非保底条被剪（保尾 4 条永不剪）
        assert "[pruned" in out[0]["content"]
        assert all("[pruned" not in m["content"] for m in out[1:])

    def test_zero_budget_legacy(self):
        from py.context_manager import prune_tool_results
        msgs = [_tool(i, 4000) for i in range(6)]
        out, n = prune_tool_results(msgs, keep_recent_tools=2, tool_output_budget=0)
        assert n == 4
        assert all("[pruned" not in m["content"] for m in out[-2:])
        # 短内容不进预算也不剪（存根不比原文短）
        msgs2 = [_tool(i, 5) for i in range(6)]
        assert prune_tool_results(msgs2, 2, 2500)[1] == 0


class TestGetContextSettings:
    def test_auto_dispatch_and_invalid(self, monkeypatch):
        from py import context_manager as cm_mod
        from py import ctx_window_probe
        monkeypatch.setattr(ctx_window_probe, "resolve_auto_window",
                            lambda s: 131072)
        s = {"contextManagement": {"contextWindow": "auto"}}
        assert cm_mod.get_context_settings(s)["context_window"] == 131072
        s2 = {"contextManagement": {"contextWindow": "乱七八糟"}}
        assert cm_mod.get_context_settings(s2)["context_window"] == 32000
        assert cm_mod.get_context_settings({})["tool_output_budget"] == 40000
        s3 = {"contextManagement": {"toolOutputBudget": 0}}
        assert cm_mod.get_context_settings(s3)["tool_output_budget"] == 0


class TestWindowProbe:
    def setup_method(self):
        from py import ctx_window_probe as cp
        cp.reset_for_tests()

    def test_scan_nested_and_root_strip(self, monkeypatch):
        from py import ctx_window_probe as cp
        seen = []

        def fake(url):
            seen.append(url)
            if url.endswith("/props"):
                return {"general": {"n_ctx": 262144}, "slots": []}
            raise RuntimeError("no")
        monkeypatch.setattr(cp, "_http_json", fake)
        assert cp.probe_window("http://127.0.0.1:8080/v1") == 262144
        assert seen == ["http://127.0.0.1:8080/props"]
        assert cp._engine_root("http://h:1/v1") == "http://h:1"

    def test_fallback_then_stale_cache(self, monkeypatch, tmp_path):
        from py import ctx_window_probe as cp
        monkeypatch.setattr(cp, "_cache_path", lambda: str(tmp_path / "cw.json"))
        monkeypatch.setattr(cp, "probe_window", lambda b: 0)
        assert cp.resolve_auto_window({"base_url": "http://e/v1", "model": "m"}) == 32000
        # 模拟此前成功过的缓存：探测失败时沿用旧值而非回退
        import json
        (tmp_path / "cw.json").write_text(json.dumps(
            {"http://e/v1|m": {"n": 200000, "ts": 0}}), encoding="utf-8")
        cp.reset_for_tests()
        assert cp.resolve_auto_window({"base_url": "http://e/v1", "model": "m"}) == 200000

    def test_success_writes_cache(self, monkeypatch, tmp_path):
        from py import ctx_window_probe as cp
        import json
        monkeypatch.setattr(cp, "_cache_path", lambda: str(tmp_path / "cw.json"))
        monkeypatch.setattr(cp, "probe_window", lambda b: 131072)
        assert cp.resolve_auto_window({"base_url": "http://f/v1", "model": "x"}) == 131072
        d = json.loads((tmp_path / "cw.json").read_text(encoding="utf-8"))
        assert d["http://f/v1|x"]["n"] == 131072


class TestBoundaryRecheck:
    def _req(self):
        msgs = [{"role": "system", "content": "契约"}]
        msgs += [{"role": "tool", "tool_call_id": f"t{i}", "name": "x",
                  "content": "w" * 40000} for i in range(6)]
        return types.SimpleNamespace(messages=msgs)

    def test_prunes_when_over_budget(self):
        import server
        req = self._req()
        settings = {"contextManagement": {"contextWindow": 4096, "compactRatio": 0.8,
                                          "keepRecentTools": 2, "toolOutputBudget": 2000}}
        n = server._boundary_l1_recheck(req, settings)
        assert n >= 3
        stubbed = [m for m in req.messages if "[pruned" in str(m.get("content"))]
        assert len(stubbed) == n

    def test_noop_when_within_budget(self):
        import server
        req = types.SimpleNamespace(messages=[{"role": "user", "content": "hi"}])
        before = list(req.messages)
        assert server._boundary_l1_recheck(req, {"contextManagement": {}}) == 0
        assert req.messages == before


class TestSourcePins:
    def test_wiring(self):
        s = ((_ROOT / "server.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_prep.py").read_text(encoding="utf-8") + (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
 + (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8")
 + (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8"))  # S304：响应装配/批复执行域迁出，合并面守恒（体逐字未动）  # S302a：流式域迁 stream_prep/stream_engine，文本钉合并扫描（体逐字未动）
        assert "_boundary_l1_recheck(request, settings, tools)" in s
        seg = s[s.find("async def _run_context_pipeline"):][:1600]
        assert 'cm["tool_output_budget"]' in seg
        html = (_ROOT / "static/templates/page_model-config.html").read_text(encoding="utf-8")
        assert "ctxWindowAuto" in html
        for loc in ("zh-CN", "en-US"):
            assert "ctxWindowAuto" in (_ROOT / f"static/js/locales/{loc}.js").read_text(encoding="utf-8")
