# -*- coding: utf-8 -*-
"""S297 静态锁：验证码域级熔断（贴吧事故——验证页被撞几十次仍反复点击）。

行为回归见 tests/data/captcha_freeze_s297_harness.js；这里锁结构与语义：
硬熔断（非提示语自觉）、六交互全守卫、干净快照自解除、导航只读不受累。
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = (ROOT / "static" / "js" / "methods" / "80_webview_agent.js").read_text(encoding="utf-8")


def test_freezer_state_and_guard_exist():
    assert "const _captchaFrozen = new Set();" in JS
    assert "function _captchaGuard(wv)" in JS
    # 按 hostname 记账（域级），不是整页/整标签
    assert "new URL(" in JS.split("function _captchaHostOf")[1][:200]


def test_all_six_interactions_guarded():
    for m in ("webviewClick", "webviewFill", "webviewFillForm",
              "webviewDrag", "webviewHover", "webviewPressKey"):
        seg = JS.split("async %s(" % m, 1)[1][:400]
        assert "_captchaGuard(wv)" in seg, "%s missing captcha guard" % m
        assert "return _cg" in seg, "%s guard not enforced" % m


def test_read_and_navigate_channels_stay_open():
    # 熔断只拦交互：导航（离开该域/过关后重载）与快照/脚本通道必须保持可用
    for m in ("getWebviewSnapshot", "executeInActiveWebview", "browserNavigate"):
        seg = JS.split("async %s(" % m, 1)[1][:400] if m != "browserNavigate" else JS
        if m != "browserNavigate":
            assert "_captchaGuard" not in seg, "%s must not freeze" % m
    assert "async browserNavigate(" in JS


def test_snapshot_arm_and_clear_notes():
    # 命中：拉黑 + 明示熔断；干净：自解除 + 反馈行（agent 可见恢复点）
    assert "_captchaFrozen.add(_ch)" in JS
    assert "captcha_detected=true" in JS and "已熔断" in JS
    assert "_captchaFrozen.delete(_ch)" in JS
    assert "captcha_cleared=true" in JS


def test_no_auto_retry_semantics():
    # 拒绝文案必须劝退自动重试并给出唯一恢复路径（用户过关 + 快照确认）
    i = JS.index("function _captchaGuard")
    body = JS[i:i + 700]
    assert "只会撞同一堵墙" in body and "手动完成验证" in body


def test_harness_green():
    r = subprocess.run(
        ["node", str(ROOT / "tests" / "data" / "captcha_freeze_s297_harness.js"),
         str(ROOT / "static" / "js" / "methods" / "80_webview_agent.js")],
        capture_output=True, text=True, cwd=str(ROOT), timeout=120, shell=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "S297-HARNESS all passed" in r.stdout
