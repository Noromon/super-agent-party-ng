# S176 (updated by S178): the install-scripts allowlist gate caused "half-installed"
# machines (electron/esbuild/@serialport/bindings-cpp postinstall skipped -> binaries
# never produced). S178 evidence: on such machines even approved lifecycle scripts stay
# silently skipped, so Electron no longer depends on npm scripting (official install.js
# is run directly) and approval is now an OPTIONAL, consented step for esbuild/@serialport
# natives only. Gate state is still surfaced read-only first; failure wording stays honest.
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = (ROOT / "setup_and_run.ps1").read_text(encoding="utf-8")
SH = (ROOT / "setup_and_run.sh").read_text(encoding="utf-8")
START = (ROOT / "start.js").read_text(encoding="utf-8")


def _first_code_line(src: str, marker: str) -> int:
    for idx, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith("#") or not s:
            continue
        if marker in line:
            return idx
    return -1


class TestGateDiagnosticsBeforeAnyInstall:
    def test_scripts_check_gate_read_only_first(self):
        for src in (PS1, SH):
            assert "install-scripts ls" in src
        # gate check precedes every approval and every installer
        for src, consent in ((PS1, "Read-Host"), (SH, "read -r -p")):
            c = _first_code_line(src, consent)
            assert c > 0
            assert c < _first_code_line(src, "install-scripts ls")
            assert c < _first_code_line(src, "install-scripts approve")
            assert c < _first_code_line(src, "npm ci")
            assert _first_code_line(src, "install-scripts ls") < _first_code_line(src, "install-scripts approve")

    def test_required_packages_named_for_approval(self):
        for src in (PS1, SH):
            for pkg in ("electron", "esbuild", "@serialport/bindings-cpp"):
                assert pkg in src, pkg
            assert "postinstall" in src

    def test_declining_approval_warns_and_continues(self):
        # S178: Electron no longer depends on npm scripting, so declining approval
        # must only warn (natives degrade) instead of aborting the flow.
        for src in (PS1, SH):
            assert "已跳过放行" in src
            assert "不影响 Electron 二进制产出" in src


class TestHonestDualCauseWording:
    def test_failure_messages_list_download_and_offline_causes(self):
        for src in (PS1, SH):
            assert "原因只有三类" in src
            assert "不依赖 npm 生命周期脚本" in src
            assert "npmmirror 下载均不可达" in src
        # mirror coverage for the download path is still present
        assert "$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'" in PS1
        assert 'ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"' in SH


class TestIntegrityAndLaunchStillGated:
    def test_integrity_helpers_unchanged(self):
        assert "function Test-ElectronIntact" in PS1
        assert "electron_intact() {" in SH

    def test_start_js_integrity_gate_and_parity(self):
        assert "localElectronComplete" in START
        assert "process.exit(1)" in START
        assert "chcp 65001" in START
        assert START.index("'node_modules'") < START.index("cmd = 'electron';")

    def test_start_js_parses(self):
        import subprocess

        r = subprocess.run(["node", "--check", str(ROOT / "start.js")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
