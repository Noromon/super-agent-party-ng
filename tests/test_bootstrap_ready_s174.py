# S174: bootstrap scripts must launch WITHOUT prompts once the environment is
# fully ready (verified: project .venv present + dependencies importable +
# Electron in node_modules), and must resolve Electron from the local
# node_modules before falling back to any global command. Install steps on the
# not-ready path keep their one-by-one confirmation gates.
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = (ROOT / "setup_and_run.ps1").read_text(encoding="utf-8")
SH = (ROOT / "setup_and_run.sh").read_text(encoding="utf-8")
BAT = (ROOT / "setup_and_run.bat").read_text(encoding="utf-8")
START = (ROOT / "start.js").read_text(encoding="utf-8")


class TestReadyFastPath:
    def test_ps1_declares_full_switch_and_ready_check(self):
        assert "param([switch]$Full)" in PS1
        assert "function Test-EnvironmentReady" in PS1
        assert "import fastapi" in PS1
        assert "node_modules\\electron" in PS1

    def test_ps1_fast_path_launches_without_prompting(self):
        i = PS1.index("# ---------- Step 0: ready fast path (S174)")
        j = PS1.index("exit $LASTEXITCODE", i)
        seg = PS1[i:j]
        assert "Test-EnvironmentReady" in seg and "start.js" in seg
        assert "Read-Host" not in seg and "Ask " not in seg

    def test_sh_fast_path_launches_without_prompting(self):
        i = SH.index("# ---------- Step 0: ready fast path (S174)")
        j = SH.index('exec node "$PROJECT/start.js"', i)
        seg = SH[i:j]
        assert "--full" in seg and "import fastapi" in seg
        assert "ask " not in seg

    def test_intro_consent_question_removed_both_platforms(self):
        # the old blanket pre-install consent question is gone (run = authorization;
        # per-action confirmation on the not-ready path is pinned separately below)
        for src in (PS1, SH):
            assert "Proceed with the guided setup?" not in src
            assert "本向导将按需安装" not in src

    def test_bat_still_hands_off_to_powershell_launcher(self):
        assert "-NoProfile" in BAT and "-ExecutionPolicy Bypass" in BAT
        assert "setup_and_run.ps1" in BAT


class TestInstallGatesRemain:
    @staticmethod
    def _first_code_line(src: str, marker: str) -> int:
        # first NON-comment line containing the marker (comments never authorize installs)
        for idx, line in enumerate(src.splitlines(), 1):
            s = line.strip()
            if s.startswith("#") or not s:
                continue
            if marker in line:
                return idx
        return -1

    def test_readhost_precedes_every_installer(self):
        first = self._first_code_line(PS1, "Read-Host")
        assert first > 0
        for marker in ("winget install", "pip install", "npm ci", "uv sync"):
            pos = self._first_code_line(PS1, marker)
            assert pos > 0 and first < pos, marker

    def test_sh_read_precedes_every_installer(self):
        first = self._first_code_line(SH, "read -r -p")
        assert first > 0
        for marker in ("pkg_install", "pip install", "npm ci", "uv sync"):
            pos = self._first_code_line(SH, marker)
            assert pos > 0 and first < pos, marker

    def test_official_source_defaults_kept(self):
        assert "https://www.python.org/downloads/" in PS1
        assert "https://nodejs.org" in PS1


class TestStartJsLocalElectronResolution:
    def test_local_node_modules_resolved_before_global_fallback(self):
        # S180: local resolution now means the direct dist-binary path (no .bin shim, no cmd wrapper)
        assert "localElectronBinary" in START
        assert START.index("'node_modules'") < START.index("cmd = 'electron';")
        assert "fs.existsSync(p)" in START

    def test_bundled_global_fallback_and_utf8_wrapper_kept(self):
        assert "electron ." in START
        assert "chcp 65001" in START
        assert "NODE_ENV" in START


class TestNodeSyntax:
    def test_start_js_parses(self):
        import subprocess

        r = subprocess.run(["node", "--check", str(ROOT / "start.js")],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
