# -*- coding: utf-8 -*-
"""S329：插件域与 cwd 解耦——拉起插件的授权走全局层、plan 解除连坐。

设计决定（用户）：插件不属于"计算机控制"域，框架从未要求"必须有工作区
才能用插件"。因此 start_extension_node_tool_local 的"总是允许"落
settings.globalAllowedTools（data 目录级，与 cwd 无关），并从
PLAN_BLOCKED_TOOLS 连坐中单独移除；default 模式审批弹窗保留。
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]  # 驱逐 site-packages 的 py 单体库（s323 同法）


from py import tool_hooks as TH  # noqa: E402
from py.approval_exec import record_always_allow  # noqa: E402
from py.routers import permissions as P  # noqa: E402
from py.tool_registry import (GLOBAL_APPROVAL_TOOLS, PLAN_BLOCKED_TOOLS,  # noqa: E402
                              SENSITIVE_TOOLS)

C = "start_extension_node_tool_local"


class TestRegistrySemantics:
    def test_c_sensitive_but_not_plan_blocked(self):
        assert C in SENSITIVE_TOOLS
        assert C in GLOBAL_APPROVAL_TOOLS
        assert C not in PLAN_BLOCKED_TOOLS
        assert "shell_tool_local" in PLAN_BLOCKED_TOOLS

    def test_plan_blocked_keeps_rest_of_sensitive(self):
        rest = set(SENSITIVE_TOOLS) - GLOBAL_APPROVAL_TOOLS
        assert rest <= PLAN_BLOCKED_TOOLS


class TestRecordAlwaysAllow:
    def test_ext_tool_goes_global_no_cwd(self):
        calls = []

        async def fake_save(s):
            calls.append(list(s.get("globalAllowedTools") or []))
        s = {}
        ok, err = asyncio.run(record_always_allow(C, s, None, fake_save))
        assert ok and err is None
        assert s["globalAllowedTools"] == [C]
        assert calls == [[C]]

    def test_ext_tool_idempotent(self):
        calls = []

        async def fake_save(s):
            calls.append(1)
        s = {"globalAllowedTools": [C]}
        ok, _ = asyncio.run(record_always_allow(C, s, None, fake_save))
        assert ok
        assert calls == []  # 已在名单：不重复写盘

    def test_system_tool_needs_cwd(self, tmp_path):
        async def fake_save(s):
            pass
        ok, err = asyncio.run(record_always_allow("shell_tool_local", {}, None, fake_save))
        assert not ok and "No working directory" in err
        ok2, err2 = asyncio.run(record_always_allow(
            "shell_tool_local", {}, str(tmp_path), fake_save))
        assert ok2 and err2 is None
        from py import agent
        assert "shell_tool_local" in agent.get_project_config_data(str(tmp_path))["allowed_tools"]


class TestApprovalGlobalLayer:
    class _Srv:
        def cli_permission_mode_for(self, settings):
            return "default"

    def _settings(self, global_list):
        s = {"CLISettings": {"cc_path": "", "engine": "local"}}
        if global_list is not None:
            s["globalAllowedTools"] = global_list
        return s

    def test_global_list_allows_ext_tool(self, monkeypatch):
        monkeypatch.setattr(TH, "_srv", lambda: self._Srv())
        assert TH._sensitive_approval(C, {"ext_id": "x"}, self._settings([C])) is None

    def test_without_global_still_asks(self, monkeypatch):
        monkeypatch.setattr(TH, "_srv", lambda: self._Srv())
        out = TH._sensitive_approval(C, {"ext_id": "x"}, self._settings([]))
        assert out is not None and "__sap_approval_v1__" in out

    def test_global_list_does_not_leak_to_system_tools(self, monkeypatch):
        monkeypatch.setattr(TH, "_srv", lambda: self._Srv())
        out = TH._sensitive_approval(
            "shell_tool_local", {"command": "ls"}, self._settings([C]))
        assert out is not None and "__sap_approval_v1__" in out


class TestRouterTwoTier:
    def _store(self, monkeypatch, cwd=""):
        store = {"CLISettings": {"cc_path": cwd}, "globalAllowedTools": []}

        async def fake_load():
            return store

        async def fake_save(s):
            pass
        monkeypatch.setattr(P, "load_settings", fake_load)
        monkeypatch.setattr(P, "save_settings", fake_save)
        return store

    def test_get_no_cwd_no_400(self, monkeypatch):
        self._store(monkeypatch, cwd="")
        out = asyncio.run(P.get_allowlist())
        assert out["cwd"] == ""
        assert C in out["global_pool"]
        assert C not in out["tools_pool"]

    def test_set_ext_tool_global_roundtrip_no_cwd(self, monkeypatch):
        store = self._store(monkeypatch, cwd="")
        r = asyncio.run(P.set_tool_perm(P.ToolPermReq(name=C, allowed=True)))
        assert r["scope"] == "global" and store["globalAllowedTools"] == [C]
        asyncio.run(P.set_tool_perm(P.ToolPermReq(name=C, allowed=False)))
        assert store["globalAllowedTools"] == []


class TestCopySimplified:
    """tip 精简 + 新键四处同步（locale zh/en + __TF_FALLBACK zh/en）。"""

    def _read(self, *parts):
        return (_ROOT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_tip_short_all_four(self):
        zh = self._read("static/js/locales/zh-CN.js")
        en = self._read("static/js/locales/en-US.js")
        vm = self._read("static/js/vue_methods.js")
        assert "'allowAiStartExtensionTip': '拉起仍需审批'" in zh
        assert "'allowAiStartExtensionTip': 'Starts still need your approval'" in en
        assert vm.count("'allowAiStartExtensionTip': '拉起仍需审批'") >= 1
        assert vm.count("'allowAiStartExtensionTip': 'Starts still need your approval'") >= 1
        assert "每次拉起仍需你审批" not in zh  # 长版清场

    def test_perm_global_title_registered(self):
        zh = self._read("static/js/locales/zh-CN.js")
        en = self._read("static/js/locales/en-US.js")
        vm = self._read("static/js/vue_methods.js")
        for src in (zh, en, vm):
            assert "'permGlobalTitle'" in src
