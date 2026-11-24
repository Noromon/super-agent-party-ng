# -*- coding: utf-8 -*-
"""S309a：重复调用熔断 + net-zero No-op 检测 + llmRetryMax 迁移。

事故背景（df2f8248/pcr）：同一参数 patch 连发 6 次，fuzzy 把已写好的 new
当 old 再写回同样 new（net-zero 假成功 ratio=1.00），模型退化复读。
"""
import json
import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # pytest 预导入的 site-packages py.py shim 让位给仓库包

from py import agent_loop_guard as alg  # noqa: E402
from py import patch_match  # noqa: E402


def _tc(tid, name, args_dict):
    return {"id": tid, "function": {"name": name,
                                    "arguments": json.dumps(args_dict, ensure_ascii=False)}}


def _req(results):
    """一条 assistant(tool_calls) + N 条 tool 结果的链尾。"""
    msgs = [{"role": "assistant", "content": "", "tool_calls": []}]
    for i, r in enumerate(results):
        msgs.append({"role": "tool", "tool_call_id": "t%d" % i, "content": r})
    return types.SimpleNamespace(messages=msgs)


def _calls(names_args):
    return [_tc("t%d" % i, n, a) for i, (n, a) in enumerate(names_args)]


def _tool_texts(req):
    return {m["tool_call_id"]: m["content"] for m in req.messages if m["role"] == "tool"}


EDIT = "edit_file_patch_tool_local"
ARGS = {"path": "a.py", "old_string": "x", "new_string": "y"}
OK_TXT = "Patched 'a.py'.\n1 replacement(s) at line 3"
FAIL_TXT = "[Error] edit 1: old_string not found (closest region similarity 0.65). No changes were made."


class TestLoopGuardSameCall:
    def test_first_call_quiet(self):
        st = {}
        req = _req([OK_TXT])
        assert alg.observe_round(st, req, _calls([(EDIT, ARGS)])) is False
        assert "LoopGuard" not in _tool_texts(req)["t0"]

    def test_second_identical_warns(self):
        st = {}
        for i in range(2):
            req = _req([OK_TXT])
            force = alg.observe_round(st, req, _calls([(EDIT, ARGS)]))
        assert force is False
        assert "[LoopGuard] WARNING" in _tool_texts(req)["t0"]

    def test_fourth_identical_forces(self):
        st = {}
        force = False
        for _ in range(4):
            req = _req([OK_TXT])
            force = alg.observe_round(st, req, _calls([(EDIT, ARGS)]))
        assert force is True
        assert "Repetition limit" in _tool_texts(req)["t0"]

    def test_different_args_not_flagged(self):
        st = {}
        for v in range(4):
            req = _req([OK_TXT])
            force = alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, new_string="v%d" % v))]))
        assert force is False

    def test_arg_order_insensitive(self):
        st = {}
        a = {"path": "a.py", "new_string": "y", "old_string": "x"}
        for _ in range(2):
            req = _req([OK_TXT])
            alg.observe_round(st, req, _calls([(EDIT, a)]))
        assert "[LoopGuard] WARNING" in _tool_texts(req)["t0"]


class TestLoopGuardEditStreak:
    def test_three_fails_injects_directive(self):
        st = {}
        for _ in range(3):
            req = _req([FAIL_TXT])
            force = alg.observe_round(st, req, _calls([(EDIT, ARGS)]))
        assert force is False
        txt = _tool_texts(req)["t0"]
        assert "read_file_range_tool_local" in txt and "Do NOT retry" in txt

    def test_five_fails_force(self):
        st = {}
        force = False
        for _ in range(5):
            req = _req([FAIL_TXT])
            force = alg.observe_round(st, req, _calls([(EDIT, ARGS)]))
        assert force is True

    def test_success_resets_streak(self):
        st = {}
        for i in range(2):
            req = _req([FAIL_TXT])
            alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, old_string="bad%d" % i))]))
        assert st["lg_edit_fail"]["a.py"] == 2
        req = _req([OK_TXT])
        alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, old_string="fixed"))]))
        req = _req([FAIL_TXT])
        alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, old_string="bad_again"))]))
        assert st["lg_edit_fail"]["a.py"] == 1
        assert "[LoopGuard]" not in _tool_texts(req)["t0"]

    def test_per_path_streaks_independent(self):
        st = {}
        for _ in range(3):
            req = _req([FAIL_TXT])
            alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, path="a.py"))]))
        req = _req([FAIL_TXT])
        alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, path="b.py"))]))
        assert "[LoopGuard]" not in _tool_texts(req)["t0"]

    def test_noop_counts_as_success(self):
        st = {}
        req = _req([FAIL_TXT])
        alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, old_string="bad"))]))
        req = _req(["'a.py' — [No-op] All edits matched but produced ZERO net change"])
        alg.observe_round(st, req, _calls([(EDIT, dict(ARGS, old_string="already_applied"))]))
        assert st["lg_edit_fail"]["a.py"] == 0


class TestLoopGuardRobustness:
    def test_never_raises_on_junk(self):
        st = {}
        req = types.SimpleNamespace(messages=None)
        assert alg.observe_round(st, req, None) is False

    def test_object_style_messages(self):
        st = {}
        msg = types.SimpleNamespace(role="tool", tool_call_id="t0", content=OK_TXT)
        req = types.SimpleNamespace(messages=[msg])
        force = alg.observe_round(st, req, _calls([(EDIT, ARGS)]))
        assert force is False
        req2 = types.SimpleNamespace(messages=[msg])
        alg.observe_round(st, req2, _calls([(EDIT, ARGS)]))
        assert "[LoopGuard] WARNING" in msg.content


class TestPatchNetZero:
    def test_exact_noop_zero_content(self):
        res = patch_match.apply_edits("A\nB\n", [{"old_string": "A", "new_string": "A"}])
        assert res.ok is True
        assert res.content == ""
        assert "[No-op]" in res.report and "ZERO net change" in res.report

    def test_fuzzy_ratio100_net_zero(self):
        line = 'print("hello world", flush=True)'
        res = patch_match.apply_edits(line + "\n",
                                      [{"old_string": line.replace('", ', '",  '), "new_string": line}])
        assert res.ok is True and res.content == ""
        assert "[No-op]" in res.report

    def test_real_edit_still_ok(self):
        res = patch_match.apply_edits("A\nB\n", [{"old_string": "A", "new_string": "Z"}])
        assert res.ok is True and res.content == "Z\nB\n"
        assert "[No-op]" not in res.report

    def test_partial_batch_net_zero_detected(self):
        content = "X\nY\n"
        res = patch_match.apply_edits(content, [
            {"old_string": "X", "new_string": "Q"},
            {"old_string": "Q", "new_string": "X"},
        ])
        assert res.ok is True and res.content == ""


class TestMigration:
    def _fn(self):
        from py.get_setting import _migrate_agent_robustness_v2
        return _migrate_agent_robustness_v2

    def test_stale_two_upgraded_once(self):
        d = {"agentRobustness": {"llmRetryMax": 2}}
        assert self._fn()(d) is True
        assert d["agentRobustness"]["llmRetryMax"] == 4
        assert d["agentRobustness"]["llmRetryMigratedV2"] is True
        assert self._fn()(d) is False
        d["agentRobustness"]["llmRetryMax"] = 2
        assert self._fn()(d) is False and d["agentRobustness"]["llmRetryMax"] == 2

    def test_user_value_preserved_flag_written(self):
        d = {"agentRobustness": {"llmRetryMax": 3}}
        assert self._fn()(d) is True
        assert d["agentRobustness"] == {"llmRetryMax": 3, "llmRetryMigratedV2": True}

    def test_missing_block_noop(self):
        assert self._fn()({}) is False
        assert self._fn()({"agentRobustness": "junk"}) is False


class TestWiringPins:
    def read(self, p):
        import io
        return io.open(p, encoding="utf-8-sig").read()

    def test_stream_response_hooked(self):
        src = self.read("py/stream_response.py")
        assert "agent_loop_guard" in src
        assert "_loop_guard.observe_round(_st, request, tool_calls)" in src
        assert src.index("observe_round") > src.index("results = _st.get(\"results\")")

    def test_patch_match_reports_noop(self):
        src = self.read("py/patch_match.py")
        assert "ZERO net change" in src
        assert "NEVER resend the same old_string" in self.read("py/patch_match.py")

    def test_cli_callers_honour_noop(self):
        src = self.read("py/cli_tool.py")
        assert src.count("if not res.content:") == 2
        assert "[No-op] '" in src and "already contains EXACTLY this content" in src

    def test_migration_called_in_load(self):
        src = self.read("py/get_setting.py")
        assert "_migrate_agent_robustness_v2(user_settings)" in src
