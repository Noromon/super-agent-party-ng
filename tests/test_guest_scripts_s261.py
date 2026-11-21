# build=S273
# S261：拼接 guest 脚本语法防线——arm 脚本 try 缺 catch 令内置 network_watch 自 S253
# 起从未生效（线上 'GUEST_VIEW_MANAGER_CALL: Missing catch or finally after try'），
# findExpr 同族缺 catch 令 scroll_and_find 命中检测静默失效（被循环 catch 吞掉，
# agent 误判"标题碎片化"）。本测试用 node harness stub 驱动方法，对真实拼接产物逐个
# new Function 验语法——这类 bug 从此 CI 拦截，不再烧到线上。
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests" / "data" / "guest_check_harness.js"
AGENT_JS = ROOT / "static" / "js" / "methods" / "80_webview_agent.js"
NODE = shutil.which("node")


def test_all_assembled_guest_scripts_parse():
    if not NODE:
        import pytest
        pytest.skip("node 不可用")
    r = subprocess.run([NODE, str(HARNESS), str(AGENT_JS)],
                       capture_output=True, text=True, timeout=60)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0 and "failed=0" in out, out[:800]
    # 覆盖量下限：networkWatch 全 mode + scrollAndFind + snapshot 都须被捕获驱动
    captured = int(out.split("captured=")[1].split()[0])
    assert captured >= 20, f"捕获脚本过少({captured})，harness 驱动路径可能失效"


def test_arm_and_find_have_real_catches_now():
    js = AGENT_JS.read_text(encoding="utf-8")
    i = js.index("if(BODY&&r&&r.clone){try{")
    assert "}catch(_e){}" in js[i:i + 200]
    j = js.index("if(!c.offsetParent)continue;var t=nf(")
    assert "}catch(e){}" in js[j:j + 260]


def test_scroll_not_found_surfaces_exec_err():
    js = AGENT_JS.read_text(encoding="utf-8")
    i = js.index("exec_err: execErr || undefined")
    seg = js[i:i + 400]
    assert "命中检测可能未生效，非目标不存在" in seg  # 语法/执行错不再伪装成"没找到"
