# S179 (LOCAL-ONLY iteration; deployment work is deliberately not pushed):
# the broken machine disproved every environmental theory one by one - clean
# install-scripts gate, zero Electron/proxy env vars, official SHA256-exact
# package files, healthy node AND healthy network - yet the official
# install.js exited instantly with code 0, no output, no traffic. The only
# silent paths that fit are its isInstalled() misjudgement (existence-only
# check: zero-byte/garbage electron.exe passes it) or a poisoned/empty local
# download cache (cache hit -> zero-network "success"). So production must be
# evidence-driven: print the on-site facts, purge zero-byte residue, re-run
# the official script with force_no_cache, then fall back to a native
# verified download (SHASUMS256-checked zip unpacked in place, no node/npm at
# all). Integrity now demands a >=50MB binary so stubs can never pass.
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PS1 = (ROOT / "setup_and_run.ps1").read_text(encoding="utf-8")
SH = (ROOT / "setup_and_run.sh").read_text(encoding="utf-8")


class TestEvidenceDrivenProduction:
    def test_scene_evidence_printed(self):
        for src in (PS1, SH):
            assert "现场证据 / on-site evidence:" in src
            assert "path.txt" in src

    def test_zero_byte_residue_purged_before_production(self):
        for src in (PS1, SH):
            assert "0 字节残留" in src
        # purge happens strictly before the first install.js run
        i = PS1.index("0 字节残留")
        j = PS1.index("& node (Join-Path $PROJECT 'node_modules\\electron\\install.js')")
        assert i < j

    def test_official_script_runs_with_cache_bypass_and_exit_code(self):
        for src in (PS1, SH):
            assert "force_no_cache" in src
            assert "install.js 退出码 / exit code" in src


class TestNativeVerifiedFallback:
    def test_fallback_exists_in_both_scripts(self):
        for src in (PS1, SH):
            assert "SHASUMS256" in src
            assert "拒绝安装未校验二进制" in src
            assert "期望 SHA256 / expected:" in src
            assert "实际 SHA256 / actual:" in src

    def test_fallback_prefers_mirror_then_github(self):
        for src in (PS1, SH):
            assert src.index("npmmirror.com/mirrors/electron") < src.index(
                "github.com/electron/electron/releases")

    def test_fallback_runs_only_after_official_paths_fail(self):
        i = PS1.rindex("& node (Join-Path $PROJECT 'node_modules\\electron\\install.js')")
        j = PS1.rindex("Get-PsNativeElectronFallback")
        assert i < j
        i = SH.rindex('node "$PROJECT/node_modules/electron/install.js"')
        j = SH.rindex("verify_fallback_electron")
        assert i < j


class TestIntegrityHardened:
    def test_binary_size_floor_blocks_stubs(self):
        # a garbage/stub electron.exe must never pass the integrity gate
        for src in (PS1, SH):
            assert "52428800" in src

    def test_three_cause_wording_updated(self):
        for src in (PS1, SH):
            assert "原因只有三类" in src
            assert "已直跑官方 install.js" in src
            assert "npmmirror 下载均不可达" in src
            assert "损坏缓存" in src
            assert "离线修复" in src


class TestS178SemanticsPreserved:
    def test_no_npm_rebuild_dependency(self):
        for src in (PS1, SH):
            assert "npm rebuild" not in src
            assert "--foreground-scripts" not in src

    def test_ci_still_always_ignore_scripts(self):
        for src in (PS1, SH):
            assert "npm ci --no-audit --no-fund --ignore-scripts" in src
