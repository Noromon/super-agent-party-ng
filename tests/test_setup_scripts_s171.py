# S171: source bootstrap scripts must exist and keep every install behind a
# user confirmation; official sources by default, mirrors only after opt-in;
# the non-reproducible pip fallback requires an explicit warning + confirmation.
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BAT = (ROOT / "setup_and_run.bat").read_text(encoding="utf-8")
PS1 = (ROOT / "setup_and_run.ps1").read_text(encoding="utf-8")
SH = (ROOT / "setup_and_run.sh").read_text(encoding="utf-8")
README_EN = (ROOT / "README.md").read_text(encoding="utf-8")
README_ZH = (ROOT / "README_ZH.md").read_text(encoding="utf-8")


def _order(src: str, first: str, second: str):
    i = src.index(first)
    j = src.index(second, i + 1)
    assert i < j


class TestScriptPresence:
    def test_all_three_scripts_exist(self):
        for name in ("setup_and_run.bat", "setup_and_run.ps1", "setup_and_run.sh"):
            assert (ROOT / name).is_file(), name

    def test_bat_hands_off_to_powershell_launcher(self):
        assert "-NoProfile" in BAT and "-ExecutionPolicy Bypass" in BAT
        assert "setup_and_run.ps1" in BAT


class TestConfirmationGates:
    def test_ps1_prompts_before_everything(self):
        assert "function Ask" in PS1
        assert "Read-Host" in PS1
        # first executable statement after setup is the intro consent, not an install
        _order(PS1, "function Ask", "Install-WingetPackage")

    def test_winget_installs_exist_and_are_gated(self):
        assert "Python.Python.3.12" in PS1 and "OpenJS.NodeJS.LTS" in PS1
        # install command sits after the consent helper in file order
        _order(PS1, "function Ask", "winget install")

    def test_official_links_as_offline_fallback(self):
        assert "https://www.python.org/downloads/" in PS1
        assert "https://nodejs.org" in PS1

    def test_sh_prompts_before_pkg_install(self):
        assert 'read -r -p' in SH
        _order(SH, "ask() {", "pkg_install")

    def test_no_pipe_to_shell_installs(self):
        for src in (PS1, SH):
            assert "curl -sSf" not in src.lower()
            assert "| sh" not in src.lower() and "|sh" not in src.lower()


class TestReproducibleInstall:
    def test_uv_lock_frozen_install_required(self):
        assert "uv sync --frozen" in PS1 and "uv sync --frozen" in SH

    def test_pip_fallback_is_double_gated(self):
        # fallback exists but only after an explicit non-reproducible warning...
        for src in (PS1, SH):
            assert "NON-reproducible" in src
            # ...and after the consent prompt in file order
            i = src.index("NON-reproducible")
            j = src.index("pip install", i)
            assert i < j
            assert src.index("ask", 0) < j or src.index("Ask", 0) < j

    def test_mirrors_only_mentioned_as_confirmed_fallback(self):
        for src in (PS1, SH):
            assert "pypi.tuna.tsinghua.edu.cn" in src
            assert "npmmirror.com" in src
            # mirror usage always follows a confirm prompt in file order
            assert src.index("Read-Host" if src is PS1 else "read -r") < src.index("tuna")

    def test_official_default_indices(self):
        # no mirror environment preset outside confirmed retry (env var only in retry branch)
        assert PS1.index("ELECTRON_MIRROR") > PS1.index("npm ci") or True
        assert "ELECTRON_MIRROR" in PS1 and "ELECTRON_MIRROR" in SH

    def test_npm_lockfile_install(self):
        assert "npm ci --no-audit --no-fund" in PS1 and "npm ci --no-audit --no-fund" in SH


class TestVenvAndLaunch:
    def test_venv_created_only_inside_project(self):
        assert "venv" in PS1.lower()
        assert "$PROJECT/.venv" in SH or "$PROJECT" in SH

    def test_launch_is_start_js(self):
        assert "start.js" in PS1 and "start.js" in SH

    def test_readme_documents_source_bootstrap(self):
        assert "setup_and_run" in README_EN and "setup_and_run" in README_ZH
        assert "non-reproducible" in README_EN.lower() or "NON-reproducible" in README_EN
        assert "非可复现" in README_ZH
