# S315: 写路径 No-op 预检真修（旧 async 用法每次抛错被跳过=agent"没落盘"绕圈病因）
# + delete_file_tool_local（入 trash 可找回）全链注册 + 契约收尾清理句。
import asyncio
import pathlib
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _ct(tmp_path, monkeypatch):
    import py.cli_tool as ct

    async def _cwd():
        return str(tmp_path)
    monkeypatch.setattr(ct, "_get_current_cwd", _cwd)
    return ct


CLI_SRC = (_ROOT / "py" / "cli_tool.py").read_text(encoding="utf-8")


class TestNoopPrecheck:
    def test_second_identical_write_is_noop(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        f = tmp_path / "x.py"
        body = "print('a')\nprint('b')\n"
        r1 = asyncio.run(ct.edit_file_tool_local("x.py", body))
        assert r1.startswith("[OK] Saved") and f.read_text(encoding="utf-8") == body
        r2 = asyncio.run(ct.edit_file_tool_local("x.py", body))
        assert r2.startswith("[No-op]")
        assert not (tmp_path / "x.py.bak").exists()  # No-op 不产生备份

    def test_crlf_equivalence_is_noop(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        (tmp_path / "y.py").write_text("l1\r\nl2\r\n", encoding="utf-8", newline="")
        r = asyncio.run(ct.edit_file_tool_local("y.py", "l1\nl2\n"))
        assert r.startswith("[No-op]")

    def test_real_change_still_saves_with_backup(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        f = tmp_path / "z.py"
        asyncio.run(ct.edit_file_tool_local("z.py", "v1\n"))
        r = asyncio.run(ct.edit_file_tool_local("z.py", "v2\n"))
        assert r.startswith("[OK] Saved") and "Backup" in r
        assert f.read_text(encoding="utf-8") == "v2\n"

    def test_source_no_old_broken_pattern(self):
        assert "_existing = await aiofiles.open" not in CLI_SRC
        assert ("async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace', newline='')"
                in CLI_SRC)


class TestDeleteTool:
    def _trash_home(self, monkeypatch, tmp_path):
        import py.get_setting as gs
        monkeypatch.setattr(gs, "USER_DATA_DIR", str(tmp_path / "data"))
        return tmp_path / "data" / "trash"

    def test_delete_moves_to_trash(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        trash = self._trash_home(monkeypatch, tmp_path)
        f = tmp_path / "tmp_check.py"
        f.write_text("scratch\n", encoding="utf-8")
        r = asyncio.run(ct.delete_file_tool_local("tmp_check.py"))
        assert r.startswith("[OK] Deleted")
        assert not f.exists()
        moved = list(trash.glob("*tmp_check.py*"))
        assert len(moved) == 1 and moved[0].read_text(encoding="utf-8") == "scratch\n"

    def test_redelete_not_found_discourages_retry(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        self._trash_home(monkeypatch, tmp_path)
        (tmp_path / "one.py").write_text("x", encoding="utf-8")
        asyncio.run(ct.delete_file_tool_local("one.py"))
        r = asyncio.run(ct.delete_file_tool_local("one.py"))
        assert r.startswith("[Error] File not found") and "do NOT retry" in r

    def test_directory_refused(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        self._trash_home(monkeypatch, tmp_path)
        (tmp_path / "adir").mkdir()
        r = asyncio.run(ct.delete_file_tool_local("adir"))
        assert "directory" in r and (tmp_path / "adir").exists()

    def test_symlink_refused(self, tmp_path, monkeypatch):
        ct = _ct(tmp_path, monkeypatch)
        self._trash_home(monkeypatch, tmp_path)
        src = tmp_path / "real.txt"
        src.write_text("r", encoding="utf-8")
        link = tmp_path / "link.txt"
        try:
            link.symlink_to(src)
        except OSError:
            import pytest
            pytest.skip("symlink privilege unavailable")
        r = asyncio.run(ct.delete_file_tool_local("link.txt"))
        assert "symlink" in r and src.exists()


class TestRegistrationPins:
    def test_schema_and_mode_lists(self):
        import py.cli_tool as ct
        reg = ct.LOCAL_TOOLS_REGISTRY["delete_file_local"]
        assert reg["function"]["name"] == "delete_file_tool_local"
        for mode in ("auto-approve", "yolo"):
            names = [t["function"]["name"] for t in ct.get_local_tools_for_mode(mode)]
            assert "delete_file_tool_local" in names
        names = [t["function"]["name"] for t in ct.get_local_tools_for_mode("default")]
        assert "delete_file_tool_local" not in names  # 只读档不含删除

    def test_permission_and_dispatch_surfaces(self):
        from py.tool_registry import SENSITIVE_TOOLS, PLAN_BLOCKED_TOOLS
        assert "delete_file_tool_local" in SENSITIVE_TOOLS
        assert "delete_file_tool_local" in PLAN_BLOCKED_TOOLS

    def test_maps_and_taxonomy_source(self):
        for f in ("py/tool_hooks.py", "py/approval_exec.py"):
            src = (_ROOT / f).read_text(encoding="utf-8")
            assert '"delete_file_tool_local": delete_file_tool_local' in src
        ts = (_ROOT / "py" / "tool_taxonomy.py").read_text(encoding="utf-8")
        assert "delete_file_tool_local" in ts
        ps = (_ROOT / "py" / "path_scope.py").read_text(encoding="utf-8")
        assert '"delete_file_tool_local": ("fs", ["path"])' in ps

    def test_contract_hygiene_clause(self):
        ap = (_ROOT / "py" / "agent_prompt.py").read_text(encoding="utf-8")
        assert "End-of-task hygiene" in ap and "recoverable trash" in ap
