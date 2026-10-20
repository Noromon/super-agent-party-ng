# -*- coding: utf-8 -*-
"""T-2: shell_tool_local must kill the process tree on EVERY exit path
(cancel-fence break / client-disconnect GeneratorExit / timeout), not only
on the timeout branch like before the fix."""
import asyncio
import platform
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.cli_tool as ct

IS_WIN = platform.system() == "Windows"
HANG_CMD = 'Write-Output "hi"; Start-Sleep -Seconds 30' if IS_WIN else 'echo hi; sleep 30'


@pytest.fixture
def env(monkeypatch, tmp_path):
    async def fake_load_settings():
        return {"CLISettings": {"cc_path": str(tmp_path)},
                "localEnvSettings": {"permissionMode": "accept_edits"}}
    monkeypatch.setattr(ct, "load_settings", fake_load_settings)
    monkeypatch.setattr(ct, "validate_bash_command", lambda c, w, mode=None: (True, ""))
    captured = {}
    real = asyncio.create_subprocess_exec

    async def spy(*a, **kw):
        p = await real(*a, **kw)
        captured["p"] = p
        return p

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spy)
    return captured


class TestProcessTreeKill:
    def test_cancellation_kills_tree(self, env):
        async def main():
            gen = ct.shell_tool_local(HANG_CMD, timeout=60)
            first = ""
            while "hi" not in first:
                first = await gen.__anext__()
            await gen.aclose()  # GeneratorExit at the yield point = cancel-fence scenario
            p = env["p"]
            for _ in range(50):
                if p.returncode is not None:
                    break
                await asyncio.sleep(0.1)
            assert p.returncode is not None, "process must be killed+reaped after aclose"
        asyncio.run(main())

    def test_timeout_kills_tree(self, env):
        async def main():
            chunks = []
            async for c in ct.shell_tool_local(HANG_CMD, timeout=1):
                chunks.append(c)
            assert any("[TIMEOUT]" in c for c in chunks)
            assert env["p"].returncode is not None
        asyncio.run(main())

    def test_kill_helper_idempotent(self):
        async def main():
            proc = await asyncio.create_subprocess_shell(
                "ping -n 30 127.0.0.1 >nul" if IS_WIN else "sleep 30")
            await ct._kill_process_tree(proc)
            await asyncio.wait_for(proc.wait(), timeout=5)
            assert proc.returncode is not None
            await ct._kill_process_tree(proc)  # second call must be a no-op
        asyncio.run(main())
