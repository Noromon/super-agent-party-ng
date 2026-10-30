# S177/S178: one-click bootstrap must work from ANY empty or half-state machine.
# The decisive lesson (verified on a fresh machine): with npm 11.x's default
# allowScripts gate, "npm ci" may report success while silently skipping
# postinstall - and because ci wipes node_modules, it also DESTROYS binaries a
# previous step had produced. S178 evidence: even after install-scripts approve,
# this npm silently skips lifecycle scripts (Proxifier saw ZERO network) while
# claiming success. Therefore: install and binary production are separated -
# npm ci always runs with --ignore-scripts, and the Electron binary is produced
# exclusively by running the OFFICIAL node_modules/electron/install.js directly
# (official source, then confirmed npmmirror Electron mirror retry), fully
# bypassing npm lifecycle scripting. Failure wording lists exactly three honest
# causes including offline repair. .venv must be verified to be Python 3.12.
import subprocess
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


class TestInstallAndProductionSeparated:
    def test_ci_always_ignore_scripts(self):
        assert "npm ci --no-audit --no-fund --ignore-scripts" in PS1
        assert "npm ci --no-audit --no-fund --ignore-scripts --registry=https://registry.npmmirror.com" in PS1
        assert "npm ci --no-audit --no-fund --ignore-scripts" in SH
        assert "npm ci --no-audit --no-fund --ignore-scripts --registry=https://registry.npmmirror.com" in SH
        # no script-running ci invocation left anywhere (command lines only)
        for src in (PS1, SH):
            for line in src.splitlines():
                s = line.strip()
                if s.startswith("#") or "npm ci --no-audit" not in s:
                    continue
                assert "--ignore-scripts" in s, s

    def test_binary_produced_by_direct_official_install_js_only(self):
        # S178: the official install.js run via node is the ONLY production path;
        # npm lifecycle scripting (rebuild) is entirely out of the critical path.
        assert "npm rebuild" not in PS1 and "npm rebuild" not in SH
        assert "--foreground-scripts" not in PS1 and "--foreground-scripts" not in SH
        for marker, src in (
            ("& node (Join-Path $PROJECT 'node_modules\\electron\\install.js')", PS1),
            ('node "$PROJECT/node_modules/electron/install.js"', SH),
        ):
            assert marker in src
            # install (ci) strictly precedes production (direct install.js run)
            assert _first_code_line(src, "npm ci --no-audit --no-fund --ignore-scripts") \
                < _first_code_line(src, marker)

    def test_mirror_retry_feeds_direct_install_rerun(self):
        # mirror assignment only feeds the direct install.js re-run, never a ci that runs scripts
        PS1_CALL = "& node (Join-Path $PROJECT 'node_modules\\electron\\install.js')"
        SH_CALL = 'node "$PROJECT/node_modules/electron/install.js"'
        assert PS1.count(PS1_CALL) >= 2
        assert PS1.index("$env:ELECTRON_MIRROR") < PS1.rindex(PS1_CALL)
        assert 'export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"' in SH
        assert SH.count(SH_CALL) >= 2
        assert SH.index('export ELECTRON_MIRROR') < SH.rindex(SH_CALL)


class TestThreeCauseHonestGuidance:
    def test_offline_repair_guidance_present(self):
        for src in (PS1, SH):
            assert "原因只有三类" in src
            assert "静默跳过生命周期脚本" in src
            assert "不依赖 npm 生命周期脚本" in src
            assert "path.txt" in src and "打包版" in src
            assert "package-lock.json" in src

    def test_venv_python312_verification_and_gated_recreation(self):
        for src in (PS1, SH):
            assert "sys.version_info[:2]==(3,12)" in src
            assert "删除现有 .venv" in src
            assert "并非 Python 3.12" in src


class TestPriorSemanticsPreserved:
    def test_fast_path_integrity_gate_unchanged(self):
        assert "if (-not $Full -and (Test-EnvironmentReady)) {" in PS1
        assert "if (-not (Test-ElectronIntact)) { return $false }" in PS1
        assert "electron_intact" in SH

    def test_start_js_unchanged_behaviour(self):
        assert "localElectronComplete" in START
        assert "chcp 65001" in START
        assert START.index("'node_modules'") < START.index("cmd = 'electron';")
        r = subprocess.run(["node", "--check", str(ROOT / "start.js")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
