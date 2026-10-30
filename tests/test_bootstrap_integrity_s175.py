# S175: half-installed Electron must never launch. Readiness and launch paths must
# verify the Electron BINARY and its path.txt marker exist and are non-empty (a
# fresh git clone with a failed binary download is NOT "ready"), a package that is
# present but incomplete must trigger a confirmed repair install instead of being
# skipped, and start.js must fail friendly (bilingual) instead of spawning anything.
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


class TestIntegrityCheckDefinedFirst:
    def test_ps1_integrity_helper_exists(self):
        assert "function Test-ElectronIntact" in PS1
        assert "electron\\dist\\electron.exe" in PS1
        assert "node_modules\\electron\\path.txt" in PS1
        # integrity helper precedes every installer command
        h = _first_code_line(PS1, "function Test-ElectronIntact")
        assert h > 0
        assert h < _first_code_line(PS1, "npm ci")

    def test_ps1_ready_and_launch_require_integrity(self):
        assert "if (-not (Test-ElectronIntact)) { return $false }" in PS1
        r = _first_code_line(PS1, "function Test-EnvironmentReady")
        assert 0 < r < _first_code_line(PS1, "& node")

    def test_sh_integrity_helper_exists_and_gates_everything(self):
        assert "electron_intact()" in SH
        assert "dist/electron" in SH and "path.txt" in SH
        h = _first_code_line(SH, "electron_intact() {")
        assert 0 < h < _first_code_line(SH, "npm ci")
        # fast-path launch condition includes the integrity check
        assert "&& electron_intact \\" in SH


class TestHalfInstallRepair:
    def test_both_scripts_detect_incomplete_install_and_demand_repair(self):
        for src in (PS1, SH):
            assert "需重装修复" in src
        # repair flow is consent-gated and its success is re-verified
        assert "Node 依赖完整，跳过安装" in PS1 and "Node 依赖完整，跳过安装" in SH
        assert "Electron 二进制仍未产出" in PS1 and "Electron 二进制仍未产出" in SH

    def test_mirror_retry_still_covers_electron_binary(self):
        assert "$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'" in PS1
        assert 'ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"' in SH


class TestStartJsFriendlyFail:
    def test_gate_before_any_spawn(self):
        g = _first_code_line(START, "localElectronComplete")
        assert g > 0
        assert g < _first_code_line(START, "boot();")
        assert "process.exit(1)" in START

    def test_friendly_help_points_at_setup_scripts(self):
        assert "setup_and_run.bat" in START and "setup_and_run.sh" in START
        assert "child.on('error'" in START

    def test_local_resolution_and_bundled_fallback_kept(self):
        assert START.index("'node_modules'") < START.index("cmd = 'electron';")
        assert "electron ." in START
        assert "chcp 65001" in START
        assert "NODE_ENV" in START

    def test_start_js_parses(self):
        import subprocess

        r = subprocess.run(["node", "--check", str(ROOT / "start.js")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
