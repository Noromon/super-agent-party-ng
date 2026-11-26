"""S324：扩展「允许AI主动拉起该插件」开关的 agent 侧门控。

规则钉：关闭态可见性=用户显式授权（A 注入/B 列表/C 资格门三方一致）；
running（页面开着，用户亲手打开=桥路径）不受开关限制；C 对未授权扩展
连存在性都不透露；双重保护=资格门之后 SENSITIVE 审批层照常。
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

from py import agent_ext_tools as A  # noqa: E402
from py import extensions as EXT  # noqa: E402


@pytest.fixture(autouse=True)
def _cache_reset():
    A.invalidate_cache()
    yield
    A.invalidate_cache()


def _mkext(root: Path, name: str, *, node=True):
    d = root / name
    d.mkdir(parents=True)
    (d / "index.js" if node else d / "index.html").write_text("x", encoding="utf-8")
    (d / "package.json").write_text(json.dumps({"name": name, "description": "d"}),
                                    encoding="utf-8")


def _ext_entry(eid, port=None):
    return {"id": eid, "name": eid, "version": "1", "category": "", "description": "",
            "node": True, "ui": True, "running_port": port, "mcp_tools": []}


class TestVisibleFilter:
    def test_rules(self):
        exts = [_ext_entry("open-running", 9), _ext_entry("allowed-off"),
                _ext_entry("secret-off")]
        vis, hidden = A._visible_exts(exts, {"allowed-off": True})
        ids = {e["id"] for e in vis}
        assert ids == {"open-running", "allowed-off"}  # running 不限；未授权=隐藏
        assert hidden == 1

    def test_empty_access_conservative(self):
        vis, hidden = A._visible_exts([_ext_entry("x")], None)
        assert vis == [] and hidden == 1


class TestHostContext:
    def test_launch_note_and_hidden_count(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        monkeypatch.setattr(A, "get_port", lambda: 3456)
        _mkext(tmp_path, "allowed-off")
        _mkext(tmp_path, "secret-off")
        A.invalidate_cache()
        ctx = A.build_host_context({"allowed-off": True})
        assert "allowed-off" in ctx and "agent-start: allowed" in ctx
        assert "secret-off" not in ctx
        assert "+ 1 more installed extensions hidden" in ctx
        assert "start_extension_node_tool_local" in ctx  # 可见时才给拉起指引

    def test_running_shown_without_access_note(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        monkeypatch.setattr(A, "get_port", lambda: 3456)
        _mkext(tmp_path, "run-x")

        class _P:
            returncode = None
        ne = type("NE", (), {"proc": _P(), "port": 7})()
        monkeypatch.setattr("py.node_runner.node_mgr",
                            type("M", (), {"exts": {"run-x": ne}})())
        ctx = A.build_host_context({})
        assert "run-x" in ctx and "running(port 7)" in ctx
        assert "agent-start" not in ctx  # 桥路径≠拉起授权，不误导


class TestToolGating:
    def _access(self, monkeypatch, table):
        async def fake():
            return table
        monkeypatch.setattr(A, "_load_agent_access", fake)

    def test_list_hides_unauthorized(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "pub")
        _mkext(tmp_path, "priv")
        A.invalidate_cache()
        self._access(monkeypatch, {"pub": True})
        out = asyncio.run(A.list_extensions_tool_local())
        assert "pub" in out and "priv" not in out and "+ 1 more" in out

    def test_start_denied_before_existence(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "ghost-target")
        A.invalidate_cache()
        self._access(monkeypatch, {})
        out = asyncio.run(A.start_extension_node_tool_local("ghost-target"))
        assert out.startswith("[Error]") and "agent access not enabled" in out
        # 存在性不透露：拒绝话术与对不存在扩展完全同构（都是 not enabled）
        out2 = asyncio.run(A.start_extension_node_tool_local("never-existed"))
        assert "agent access not enabled" in out2

    def test_start_allowed_proceeds(self, monkeypatch, tmp_path):
        monkeypatch.setattr(A, "EXT_DIR", str(tmp_path))
        _mkext(tmp_path, "nodey", node=False)  # static → 走到 static 分支=资格门已过
        A.invalidate_cache()
        self._access(monkeypatch, {"nodey": True})
        out = asyncio.run(A.start_extension_node_tool_local("nodey"))
        assert "static extension" in out


class TestAgentAccessEndpoint:
    def _fake_settings(self, monkeypatch, store):
        async def fake_load():
            return store

        async def fake_save(s):
            merged = dict(s)  # s 可能就是 store 本体——先浅拷贝再换血
            store.clear()
            store.update(merged)
        monkeypatch.setattr(EXT, "load_settings", fake_load)
        monkeypatch.setattr(EXT, "save_settings", fake_save)

    def test_put_roundtrip_and_validation(self, monkeypatch, tmp_path):
        _mkext(tmp_path, "e1")
        monkeypatch.setattr(EXT, "EXT_DIR", str(tmp_path))
        store = {}
        self._fake_settings(monkeypatch, store)
        r = asyncio.run(EXT.put_agent_access("e1", EXT.AgentAccessRequest(enabled=True)))
        assert r == {"ext_id": "e1", "enabled": True}
        assert store["extensionAgentAccess"] == {"e1": True}
        r2 = asyncio.run(EXT.get_agent_access("e1"))
        assert r2["enabled"] is True
        asyncio.run(EXT.put_agent_access("e1", EXT.AgentAccessRequest(enabled=False)))
        assert store["extensionAgentAccess"] == {}  # 关=键移除，不留 False

    def test_put_unknown_ext_404_and_escape_400(self, monkeypatch, tmp_path):
        from fastapi import HTTPException
        monkeypatch.setattr(EXT, "EXT_DIR", str(tmp_path))
        self._fake_settings(monkeypatch, {})
        with pytest.raises(HTTPException) as ei:
            asyncio.run(EXT.put_agent_access("nope", EXT.AgentAccessRequest(enabled=True)))
        assert ei.value.status_code == 404
        with pytest.raises(HTTPException) as ei2:
            asyncio.run(EXT.put_agent_access("..", EXT.AgentAccessRequest(enabled=True)))
        assert ei2.value.status_code == 400

    def test_all_endpoint_shape(self, monkeypatch):
        self._fake_settings(monkeypatch, {"extensionAgentAccess": {"a": True}})
        assert asyncio.run(EXT.get_agent_access_all()) == {"access": {"a": True}}


class TestPins:
    def test_ui_and_locale_wired(self):
        html = (_ROOT / "static" / "templates" / "page_api-group.html").read_text(encoding="utf-8")
        assert "toggleAgentAccess" in html and "allowAiStartExtension" in html
        for loc in ("zh-CN", "en-US"):
            src = (_ROOT / "static" / "js" / "locales" / f"{loc}.js").read_text(encoding="utf-8")
            assert "'allowAiStartExtension':" in src
        m = (_ROOT / "static" / "js" / "methods" / "88_extensions.js").read_text(encoding="utf-8")
        assert "agent-access/all" in m and "loadExtAgentAccess" in m
