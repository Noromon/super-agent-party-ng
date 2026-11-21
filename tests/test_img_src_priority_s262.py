# build=S266
# S262：take_snapshot 图片 URL 解析——已渲染 src 优先，懒属性仅回退。
# 动因：S258 把 _src/data-actualsrc 排在 src 之前是回归——贴吧帖内页 JS 渲染后
# src=真长图、_src 仍是旧缩略，agent 刷图贴只能拿到"贴"占位/缩略（取证落盘图仅 4.2KB）。
# 昨晚（S258 前）src 优先时帖内长图闭环是通的。
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "static/js/methods/80_webview_agent.js").read_text(encoding="utf-8")


def test_rendered_src_checked_before_lazy_attrs():
    seg = JS[JS.index("S262: 帖内页"):JS.index("S259: blob:/data:")]
    # http(s) src 先行采纳
    assert "const cur = String(el.currentSrc || el.src || '');" in seg
    assert "if (/^https?:/i.test(cur)) iurl = cur;" in seg
    # 懒属性链降级为"仅当 src 未命中 http 时"回退
    assert "if (!iurl) {" in seg
    assert seg.index("iurl = cur;") < seg.index("'_src', 'data-src', 'data-actualsrc'")
    # 回退链本体保留（列表页 src=data: 占位场景仍靠它）
    assert "new URL(String(v), location.href)" in seg


def test_no_eager_lazy_wins_left():
    # 全文件不允许残留旧顺序：lz 循环直接 break 后无条件覆盖 src 的写法
    assert "if (!iurl) iurl = String(el.currentSrc || el.src || '');" not in JS


def test_harness_still_syntax_clean():
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")
    r = subprocess.run(
        [node, str(ROOT / "tests/data/guest_check_harness.js"),
         str(ROOT / "static/js/methods/80_webview_agent.js")],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    assert "failed=0" in r.stdout, r.stdout + r.stderr
