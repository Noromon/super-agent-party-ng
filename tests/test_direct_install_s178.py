# S178: on the broken machine even APPROVED npm lifecycle scripts are silently
# skipped (Proxifier logged zero network during ci/rebuild while npm claimed
# success). The bootstrap must therefore never depend on npm lifecycle scripting
# for the Electron binary: it runs the official node_modules/electron/install.js
# directly (it uses __dirname, so cwd-independent), retries once via the
# npmmirror Electron mirror, and re-verifies integrity. Approval of the gate is
# downgraded to an optional hint because only esbuild/@serialport natives need it.
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = (ROOT / "setup_and_run.ps1").read_text(encoding="utf-8")
SH = (ROOT / "setup_and_run.sh").read_text(encoding="utf-8")

PS1_CALL = "& node (Join-Path $PROJECT 'node_modules\\electron\\install.js')"
SH_CALL = 'node "$PROJECT/node_modules/electron/install.js"'


class TestDirectOfficialInstall:
    def test_official_install_js_is_the_production_path(self):
        assert PS1_CALL in PS1
        assert SH_CALL in SH
        # zero dependence on npm lifecycle scripting for production
        for src in (PS1, SH):
            assert "npm rebuild" not in src
            assert "--foreground-scripts" not in src

    def test_integrity_recheck_after_production(self):
        # after the direct run, integrity decides success and gates the launch
        assert "if (-not (Test-ElectronIntact)) {" in PS1
        assert PS1.rindex(PS1_CALL) < PS1.index("Node 依赖安装完成且 Electron 二进制完整")
        assert SH.rindex(SH_CALL) < SH.index("Node 依赖安装完成且 Electron 二进制完整")

    def test_mirror_is_env_scoped_retry_only(self):
        # ELECTRON_MIRROR is set only right before the direct re-run, never exported globally
        assert PS1.index("$env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'") \
            < PS1.rindex(PS1_CALL)
        assert SH.index('export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"') \
            < SH.rindex(SH_CALL)


class TestOptionalGateApproval:
    def test_approval_optional_with_honest_degrade_warning(self):
        for src in (PS1, SH):
            assert "仅供参考" in src
            assert "已跳过放行" in src
            assert "相应功能降级" in src

    def test_gate_ls_still_first_read_only_step(self):
        for src in (PS1, SH):
            assert src.index("install-scripts ls") < src.index("install-scripts approve")
            # command-level compare: the actual ci invocation line carries --no-audit
            assert src.index("install-scripts ls") < src.index("npm ci --no-audit")


class TestFailureWordingHonest:
    def test_three_causes_post_bypass(self):
        for src in (PS1, SH):
            assert "已直跑官方 install.js" in src
            assert "不依赖 npm 生命周期脚本" in src
            assert "离线修复" in src
            assert "打包版" in src

    def test_scripts_still_parse(self):
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "$e=$null; [System.Management.Automation.Language.Parser]::ParseFile("
             f"'{ROOT / 'setup_and_run.ps1'}', [ref]$null, [ref]$e) | Out-Null; $e.Count"],
            capture_output=True, text=True)
        assert r.returncode == 0 and r.stdout.strip() == "0", r.stdout + r.stderr
