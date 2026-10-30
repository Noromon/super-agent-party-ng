# S180: the win32 launch path in start.js (cmd /c "chcp 65001 >nul && "<path>" .") was
# universally broken: Node escapes embedded quotes to \", cmd.exe cannot unescape them,
# and the classic '"..." is not recognized' reproduced even on a perfectly HEALTHY
# machine (probed live). Local launches must spawn the real dist binary directly -
# no shell, no quoting layer. These tests probe both directions for real:
# direct spawn of the dist binary must succeed, the cmd-wrapper form must fail.
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
START = (ROOT / "start.js").read_text(encoding="utf-8")


def _dist_binary():
    pkg = ROOT / "node_modules" / "electron"
    try:
        rel = (pkg / "path.txt").read_text(encoding="utf-8").strip()
    except OSError:
        rel = ""
    if not rel:
        rel = "electron.exe" if os.name == "nt" else "electron"
    return pkg / "dist" / rel


def _need_binary():
    b = _dist_binary()
    if not b.exists() or b.stat().st_size < 52428800:
        pytest.skip("local electron binary unavailable")
    return b


class TestBrokenQuotingRemoved:
    def test_no_quoted_cmd_wrapper_for_local_launch(self):
        assert '&& "${' not in START
        assert "electron.cmd" not in START
        assert "resolveElectron" not in START

    def test_direct_binary_resolution_present(self):
        assert "localElectronBinary" in START
        assert "52428800" in START


class TestRealSpawnProbes:
    def test_direct_spawn_of_dist_binary_works(self):
        binary = _need_binary()
        js = ("const{spawn}=require('child_process');"
              "const c=spawn(process.argv[1],['--version'],"
              "{stdio:['ignore','pipe','pipe']});"
              "let o='';c.stdout.on('data',d=>o+=d);"
              "c.on('close',s=>console.log(JSON.stringify({status:s,out:o.trim()})));")
        r = subprocess.run(["node", "-e", js, str(binary)],
                           capture_output=True, text=True, timeout=120)
        payload = json.loads(r.stdout)
        assert payload["status"] == 0, payload
        assert payload["out"].startswith("v"), payload

    @pytest.mark.skipif(os.name != "nt", reason="cmd.exe quoting is windows-only")
    def test_cmd_wrapper_quoting_still_provably_broken(self):
        # guards the WHY: if this ever stops failing, the regression pin loses its
        # justification and the wrapper debate may resume - until then, direct spawn only.
        binary = _need_binary()
        js = ("const{spawn}=require('child_process');"
              "const q=String.fromCharCode(34);"
              "const c=spawn('cmd.exe',['/c','chcp 65001 >nul && '+q+process.argv[1]+q+' --version'],"
              "{stdio:['ignore','pipe','pipe']});"
              "let e='';c.stderr.on('data',d=>e+=d);"
              "c.on('close',s=>console.log(JSON.stringify({status:s,err:e.trim()})));")
        r = subprocess.run(["node", "-e", js, str(binary)],
                           capture_output=True, text=True, timeout=120)
        payload = json.loads(r.stdout)
        assert payload["status"] != 0, payload
        assert "not recognized" in payload["err"], payload

    def test_start_js_parses(self):
        r = subprocess.run(["node", "--check", str(ROOT / "start.js")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
