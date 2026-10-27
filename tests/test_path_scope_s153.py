# -*- coding: utf-8 -*-
"""S153：外部路径权限门+读取族本地读钉桩（normalize/门/GRANTS/allowed_dirs/接线）。"""
import asyncio
import base64
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SENT = '{"__sap_approval_v1__":1,'


def _ps():
    import py.path_scope as ps
    return ps


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _settings(cwd, mode="default"):
    return {"CLISettings": {"cc_path": str(cwd), "engine": "local", "enabled": True},
            "localEnvSettings": {"permissionMode": mode}}


@pytest.fixture
def ws(tmp_path):
    ps = _ps()
    w = tmp_path / "ws"
    w.mkdir()
    (w / "a.txt").write_text("inside", encoding="utf-8")
    sub = w / "sub"
    sub.mkdir()
    (sub / "b.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
    out = tmp_path / "out"
    out.mkdir()
    (out / "secret.txt").write_text("outside", encoding="utf-8")
    ps.clear_grants()
    yield w, out
    ps.clear_grants()


class TestNormalize:
    def test_forms(self, ws):
        ps = _ps()
        w, out = ws
        r = ps.normalize_path(str(out / "secret.txt"))
        assert r["kind"] == "path" and r["exists"]
        r = ps.normalize_path("a.txt", str(w))
        assert r["kind"] == "path" and r["exists"] and ps.path_norm(r["resolved"]) == ps.path_norm(w / "a.txt")
        r = ps.normalize_path((out / "secret.txt").as_uri())
        assert r["kind"] == "path" and r["exists"]
        r = ps.normalize_path("./nope/miss.txt", str(w))
        assert r["kind"] == "path" and not r["exists"] and ps.path_within(r["resolved"], w)
        r = ps.normalize_path("https://x.example/y.png")
        assert r["kind"] == "url"
        r = ps.normalize_path("just some words")
        assert r["kind"] == "none"
        r = ps.normalize_path("~/definitely_missing_zz_qq")
        assert r["kind"] == "path" and not r["exists"]
        assert ps.normalize_path("uploaded_files/zz.png", str(w))["kind"] == "none"

    def test_path_within_boundary(self):
        ps = _ps()
        assert ps.path_within("/x/ws/a", "/x/ws")
        assert ps.path_within("/x/ws", "/x/ws")
        assert not ps.path_within("/x/ws2/f", "/x/ws")  # 前缀陷阱
        assert ps.path_within("/etc/passwd", "/")


class TestGateFs:
    def test_inside_free_outside_approval(self, ws):
        ps = _ps()
        w, out = ws
        assert ps.evaluate("read_file_tool_local", {"path": "a.txt"}, _settings(w)) is None
        d = ps.evaluate("read_file_tool_local", {"path": str(out / "secret.txt")}, _settings(w))
        assert d is not None and d.payload.startswith(SENT)
        obj = json.loads(d.payload)
        assert obj["scope"] == "local-path" and obj["tool_name"] == "read_file_tool_local"

    def test_yolo_bypass(self, ws):
        ps = _ps()
        w, out = ws
        d = ps.evaluate("read_file_tool_local", {"path": str(out / "secret.txt")}, _settings(w, "yolo"))
        assert d.block is None and d.grants == "*"

    def test_allowed_dirs(self, ws):
        from py.agent import add_dirs_to_project_config
        ps = _ps()
        w, out = ws
        add_dirs_to_project_config(str(w), [ps.path_norm(out)])
        try:
            d = ps.evaluate("read_file_tool_local", {"path": str(out / "secret.txt")}, _settings(w))
            assert d.block is None and ps.path_norm(out) in d.grants
        finally:
            ps.clear_grants()

    def test_missing_path_clear_error(self, ws):
        ps = _ps()
        w, _ = ws
        d = ps.evaluate("read_file_tool_local", {"path": "no_such_dir_zz/x.txt"}, _settings(w))
        assert d.error and "本地文件/目录不存在" in d.error and d.payload is None


class TestGateRead:
    def test_any_local_needs_approval(self, ws):
        ps = _ps()
        w, _ = ws
        d = ps.evaluate("analyze_image", {"image_url": str(w / "sub" / "b.png")}, _settings(w))
        assert d.payload.startswith(SENT)  # 工作区内也要批（用户决策①）

    def test_urls_free(self, ws):
        ps = _ps()
        w, _ = ws
        assert ps.evaluate("analyze_image", {"image_url": "http://a.b/c.png"}, _settings(w)) is None
        assert ps.evaluate("analyze_images", {"image_urls": ["https://a.b/c.png",
                                                             "http://d.e/f.png"]}, _settings(w)) is None
        assert ps.evaluate("custom_llm_tool", {"tool_name": "t", "query": "q"}, _settings(w)) is None

    def test_mixed_list_gated(self, ws):
        ps = _ps()
        w, _ = ws
        d = ps.evaluate("analyze_images", {"image_urls": ["https://a.b/c.png",
                                                          str(w / "sub" / "b.png")]}, _settings(w))
        assert d.payload.startswith(SENT)

    def test_file_url_scheme(self, ws):
        ps = _ps()
        w, _ = ws
        uri = (w / "sub" / "b.png").as_uri()
        d = ps.evaluate("get_image_content", {"image_url": uri}, _settings(w))
        assert d.payload.startswith(SENT)


class TestGrantsResolve:
    def test_abs_granted_and_denied(self, ws):
        from py.cli_tool import resolve_strict_path
        ps = _ps()
        w, out = ws
        target = resolve_strict_path(str(w), "a.txt")
        assert ps.path_norm(target) == ps.path_norm(w / "a.txt")  # 区内旧行为不变
        ps.set_grants((ps.path_norm(out),))
        got = resolve_strict_path(str(w), str(out / "secret.txt"))
        assert ps.path_norm(got) == ps.path_norm(out / "secret.txt")
        ps.clear_grants()
        with pytest.raises(PermissionError):
            resolve_strict_path(str(w), str(out / "secret.txt"))

    def test_traversal_messages_preserved(self, ws):
        from py.cli_tool import resolve_strict_path
        w, _ = ws
        with pytest.raises(PermissionError) as e1:
            resolve_strict_path(str(w), "sub/../../x")
        assert "Path traversal detected" in str(e1.value)
        with pytest.raises(PermissionError) as e2:
            resolve_strict_path(str(w), str(w.parent))
        assert "Absolute paths not allowed" in str(e2.value)

    def test_traversal_with_grant(self, ws):
        from py.cli_tool import resolve_strict_path
        ps = _ps()
        w, out = ws
        ps.set_grants((ps.path_norm(out),))
        got = resolve_strict_path(str(w), "sub/../../out/secret.txt")
        assert ps.path_norm(got) == ps.path_norm(out / "secret.txt")

    def test_grants_allow_helper(self, ws):
        ps = _ps()
        w, out = ws
        assert not ps.grants_allow(str(out / "secret.txt"))
        ps.set_grants("*")
        assert ps.grants_allow(str(out / "secret.txt"))


class TestAgentDirs:
    def test_isolation_and_matching(self, tmp_path):
        from py.agent import (add_dirs_to_project_config, add_tool_to_project_config,
                              is_dir_allowed_by_project_config,
                              is_tool_allowed_by_project_config)
        ps = _ps()
        cwd = tmp_path / "proj"
        cwd.mkdir()
        allowed = tmp_path / "allowed"
        sibling = tmp_path / "allowed2"
        add_tool_to_project_config(str(cwd), "read_file_tool_local")
        add_dirs_to_project_config(str(cwd), [ps.path_norm(allowed)])
        assert is_tool_allowed_by_project_config(str(cwd), "read_file_tool_local")
        assert is_dir_allowed_by_project_config(str(cwd), ps.path_norm(allowed / "sub"))
        assert not is_dir_allowed_by_project_config(str(cwd), ps.path_norm(sibling))  # 前缀陷阱
        assert not is_tool_allowed_by_project_config(str(cwd), "analyze_image")  # 目录不进工具表
        data = json.loads((cwd / ".party" / "config.json").read_text(encoding="utf-8"))
        assert set(data) >= {"allowed_tools", "allowed_dirs"}

    def test_missing_config(self, tmp_path):
        from py.agent import is_dir_allowed_by_project_config
        assert not is_dir_allowed_by_project_config(str(tmp_path / "none"), "C:\\x")


class TestApprovedCallGrants:
    def test_sets(self, ws):
        ps = _ps()
        w, out = ws
        assert ps.approved_call_grants("read_file_tool_local", {"path": "a.txt"}, str(w)) == ()
        g = ps.approved_call_grants("read_file_tool_local", {"path": str(out / "secret.txt")}, str(w))
        assert g == (ps.path_norm(out),)  # 文件→父目录粒度
        g = ps.approved_call_grants("analyze_image", {"image_url": str(w / "sub" / "b.png")}, str(w))
        assert g == (ps.path_norm(w / "sub"),)  # 读取族区内也要授权
        g = ps.approved_call_grants("list_files_tool_local", {"path": str(out)}, str(w))
        assert g == (ps.path_norm(out),)  # 目录工具=目标本身


class TestPermissionMode:
    def test_engines(self):
        ps = _ps()
        st = {"CLISettings": {"engine": "local"}, "localEnvSettings": {"permissionMode": "yolo"}}
        assert ps.permission_mode_for(st) == "yolo"
        assert ps.permission_mode_for({}) == "default"


class TestWiringS153:
    def test_server(self):
        s = _read("server.py")
        seg = s[s.find("# S153: 路径门（工作区外本地路径"):][:600]
        assert "path_scope.evaluate(" in seg and "set_grants" in seg
        ex = s[s.find("async def execute_approved_tool("):][:1600]
        assert "approved_call_grants" in ex and "add_dirs_to_project_config" in ex
        assert "from py.path_scope import permission_mode_for" in s

    def test_llm_tool(self):
        s = _read("py/llm_tool.py")
        seg = s[s.find("async def get_image_base64"):][:1900]
        assert "normalize_path" in seg and "本地文件不存在" in seg

    def test_agent(self):
        s = _read("py/agent.py")
        assert "allowed_dirs" in s and "def add_dirs_to_project_config" in s
        assert "def is_dir_allowed_by_project_config" in s


class TestGetImageBase64:
    def _run(self, monkeypatch, cwd, arg):
        import py.llm_tool as lt

        async def fake_settings():
            return {"CLISettings": {"cc_path": str(cwd)}}

        monkeypatch.setattr(lt, "load_settings", fake_settings)
        return asyncio.run(lt.get_image_base64(arg))

    def test_local_forms_and_missing(self, monkeypatch, ws):
        w, _out = ws
        raw = (w / "sub" / "b.png").read_bytes()
        for arg in (str(w / "sub" / "b.png"), (w / "sub" / "b.png").as_uri(), "sub/b.png"):
            assert base64.b64decode(self._run(monkeypatch, w, arg)) == raw
        with pytest.raises(RuntimeError) as e:
            self._run(monkeypatch, w, str(w / "gone_zz.png"))
        assert "本地文件不存在" in str(e.value)
