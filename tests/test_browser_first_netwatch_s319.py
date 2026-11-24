# S319: 浏览器 SNS 懒加载页"早该用 network_watch"三层联防——
# B 描述前置（规矩第一句）/ A 先验规矩注入 / C BrowserLoopWatch 绕圈探测器。
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.tool_spiral import BrowserLoopWatch  # noqa: E402


def _cdp():
    from py import cdp_tool as m
    return m


def _fn(name):
    return next(t for t in _cdp().all_cdp_tools if t["function"]["name"] == name)["function"]


class TestDescFirstLine:
    def test_network_watch_rule_is_first(self):
        d = _fn("network_watch")["description"]
        assert d.startswith("S270 接口优先规矩")  # 规矩=第一句，不再埋第 10 行
        assert "第一动作" in d[:200] and "trigger_scrolls=2" in d[:220]
        assert "S253" in d and "自愈" in d  # 既有条款全保留

    def test_navigate_page_points_first_action(self):
        d = _fn("navigate_page")["description"]
        assert "S319" in d and "network_watch(mode=start, include_body=true, trigger_scrolls=2)" in d
        assert "慢路径" in d


class TestBrowserLoopWatch:
    def test_dom_family_accumulation_trips(self):
        w = BrowserLoopWatch(threshold=6)
        names = ["take_snapshot", "get_page_markdown", "scroll_and_find",
                 "evaluate_script", "take_snapshot", "collect_list"]
        assert all(w.observe(n, {}) is None for n in names[:5])
        h = w.observe(names[5], {})
        assert h and "network_watch" in h and "trigger_scrolls=2" in h

    def test_once_then_escalate_then_silence(self):
        w = BrowserLoopWatch(threshold=4)
        for _ in range(3):
            assert w.observe("take_snapshot", {}) is None
        assert w.observe("take_snapshot", {}).startswith("[系统·浏览器循环]")  # 第 4 次触发
        for _ in range(3):
            assert w.observe("take_snapshot", {}) is None
        assert "第2次" in w.observe("take_snapshot", {})  # 再满 4 次=升级文案
        for _ in range(12):
            assert w.observe("take_snapshot", {}) is None  # 至多两次，不轰炸

    def test_network_watch_disarms_permanently(self):
        w = BrowserLoopWatch(threshold=4)
        for _ in range(3):
            w.observe("take_snapshot", {})
        assert w.observe("network_watch", {"mode": "start"}) is None
        for _ in range(20):
            assert w.observe("take_snapshot", {}) is None
        assert w.armed is True

    def test_non_browser_tools_ignored(self):
        w = BrowserLoopWatch(threshold=4)
        for _ in range(10):
            assert w.observe("read_file_tool_local", {"path": "a"}) is None
        assert w.n == 0

    def test_engine_wiring(self):
        srv = (_ROOT / "py" / "stream_engine.py").read_text(encoding="utf-8")
        assert "BrowserLoopWatch" in srv and '_st.get("_bloop")' in srv
        assert '"_spiral_hints"' in srv  # 复用 S296 system_note 通道
        ce = (_ROOT / "py" / "complete_engine.py").read_text(encoding="utf-8")
        assert "_ns_bloop = BrowserLoopWatch()" in ce and "bloop=_ns_bloop" in ce
        assert "bloop=bloop)" in ce


class TestPromptRulesInjection:
    def _call(self, settings, is_sub=False):
        import py.prompt_builders as pb
        appends = []

        class R:
            is_sub_agent = is_sub_agent = None
        r = R()
        r.is_sub_agent = is_sub
        r.messages = []
        orig = pb.content_append
        pb.content_append = lambda msgs, role, content: (appends.append((role, content)), msgs.append({"role": role, "content": content}))
        try:
            pb._append_browser_rules(r, settings)
        finally:
            pb.content_append = orig
        return appends

    def test_gate_internal_enabled(self):
        on = self._call({"chromeMCPSettings": {"enabled": True, "type": "internal"}})
        assert len(on) == 1 and on[0][0] == "system"
        assert "接口优先" in on[0][1] and "network_watch" in on[0][1]
        assert "captcha" in on[0][1]

    def test_gate_off_cases(self):
        assert self._call({"chromeMCPSettings": {"enabled": False, "type": "internal"}}) == []
        assert self._call({"chromeMCPSettings": {"enabled": True, "type": "external"}}) == []
        assert self._call({}) == []
        assert self._call({"chromeMCPSettings": {"enabled": True, "type": "internal"}}, is_sub=True) == []

    def test_hook_at_confluence(self):
        srv = (_ROOT / "server.py").read_text(encoding="utf-8")
        assert "_append_browser_rules(request, settings)" in srv  # tools_change_messages 单点（stream/complete 汇流）
        assert "_append_browser_rules(request, settings)" not in (
            (_ROOT / "py" / "stream_response.py").read_text(encoding="utf-8"))  # 无双注入
