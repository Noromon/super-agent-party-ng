"""S324：「总是允许」授权管理面板——白名单存取/收回/再授权。

白名单=.party/config.json（T-10 锁+原子写）。面板=授权主控制台：
工具双向（收回→再授权无需等下次弹批）；目录至少可收回。
"""
import asyncio
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

from py import agent  # noqa: E402
from py.routers import permissions as P  # noqa: E402

SRV_SRC = (_ROOT / "server.py").read_text(encoding="utf-8")


class TestProjectConfigRevoke:
    def test_add_remove_roundtrip(self, tmp_path):
        cwd = str(tmp_path)
        agent.add_tool_to_project_config(cwd, "shell_tool_local")
        data = agent.get_project_config_data(cwd)
        assert "shell_tool_local" in data["allowed_tools"]
        assert agent.remove_tool_from_project_config(cwd, "shell_tool_local") is True
        assert agent.get_project_config_data(cwd)["allowed_tools"] == []
        assert agent.remove_tool_from_project_config(cwd, "shell_tool_local") is False

    def test_remove_preserves_other_fields(self, tmp_path):
        cwd = str(tmp_path)
        agent.add_tool_to_project_config(cwd, "t1")
        agent.add_tool_to_project_config(cwd, "t2")
        assert agent.remove_tool_from_project_config(cwd, "t1") is True
        cfg = json.loads((tmp_path / ".party" / "config.json").read_text(encoding="utf-8"))
        assert cfg["allowed_tools"] == ["t2"]

    def test_no_config_no_crash(self, tmp_path):
        assert agent.get_project_config_data(str(tmp_path)) == {"allowed_tools": [], "allowed_dirs": []}
        assert agent.remove_tool_from_project_config(str(tmp_path), "x") is False


class TestPermissionsEndpoints:
    def _cwd(self, monkeypatch, tmp_path):
        store = {"CLISettings": {"cc_path": str(tmp_path)}}

        async def fake_load():
            return store
        monkeypatch.setattr(P, "load_settings", fake_load)
        return str(tmp_path)

    def test_tool_grant_revoke_grant(self, monkeypatch, tmp_path):
        cwd = self._cwd(monkeypatch, tmp_path)
        r = asyncio.run(P.set_tool_perm(P.ToolPermReq(name="shell_tool_local", allowed=True)))
        assert r["allowed"] is True
        data = agent.get_project_config_data(cwd)
        assert "shell_tool_local" in data["allowed_tools"]
        asyncio.run(P.set_tool_perm(P.ToolPermReq(name="shell_tool_local", allowed=False)))
        assert agent.get_project_config_data(cwd)["allowed_tools"] == []
        asyncio.run(P.set_tool_perm(P.ToolPermReq(name="shell_tool_local", allowed=True)))
        assert "shell_tool_local" in agent.get_project_config_data(cwd)["allowed_tools"]

    def test_get_allowlist_pool_union(self, monkeypatch, tmp_path):
        cwd = self._cwd(monkeypatch, tmp_path)
        agent.add_tool_to_project_config(cwd, "legacy_custom_tool")
        out = asyncio.run(P.get_allowlist())
        assert out["cwd"] == cwd
        assert "legacy_custom_tool" in out["allowed_tools"]
        assert "legacy_custom_tool" in out["tools_pool"]      # 已授权并入池=可收回
        assert "start_extension_node_tool_local" in out["tools_pool"]  # 敏感池恒在

    def test_invalid_inputs_rejected(self, monkeypatch, tmp_path):
        from fastapi import HTTPException
        self._cwd(monkeypatch, tmp_path)
        for bad in ("../x", "a/b", ".hidden", ""):
            with pytest.raises(HTTPException):
                asyncio.run(P.set_tool_perm(P.ToolPermReq(name=bad, allowed=True)))
        with pytest.raises(HTTPException):
            asyncio.run(P.set_dir_perm(P.DirPermReq(dir="relative/path", allowed=True)))

    def test_no_cwd_400(self, monkeypatch, tmp_path):
        from fastapi import HTTPException

        async def fake_load():
            return {"CLISettings": {"cc_path": ""}}
        monkeypatch.setattr(P, "load_settings", fake_load)
        with pytest.raises(HTTPException) as ei:
            asyncio.run(P.set_tool_perm(P.ToolPermReq(name="shell_tool_local", allowed=True)))
        assert ei.value.status_code == 400


class TestWiringPins:
    def test_router_registered(self):
        assert "permissions" in SRV_SRC.split("from py.routers import")[1][:200]
        assert "app.include_router(permissions.router)" in SRV_SRC

    def test_panel_template_and_locales(self):
        html = (_ROOT / "static" / "templates" / "page_system.html").read_text(encoding="utf-8")
        assert "loadAllowlist" in html and "setToolPerm" in html and "permManageTitle" in html
        for loc in ("zh-CN", "en-US"):
            src = (_ROOT / "static" / "js" / "locales" / f"{loc}.js").read_text(encoding="utf-8")
            assert "'permManageTitle':" in src and "'permToolDesc':" in src
        m = (_ROOT / "static" / "js" / "methods" / "60_system_settings.js").read_text(encoding="utf-8")
        assert "/api/permissions/allowlist" in m
