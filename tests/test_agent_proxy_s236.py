# -*- coding: utf-8 -*-
"""S236：agent 浏览器/render 工具 per-call 代理选择（默认直连）——静态链路断言。"""
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


MAIN = _read("main.js")
SERVER = _read("server.py")
CDP = _read("py", "cdp_tool.py")
WV = _read("static", "js", "methods", "80_webview_agent.js")
TABS = _read("static", "js", "methods", "98_browser_tabs.js")
PAGE = _read("static", "templates", "page_ai-browser.html")


def test_mainjs_partitions_and_protocol_line():
    assert "const AGENT_DIRECT_PARTITION = 'persist:agent-direct'" in MAIN
    assert "const AGENT_PROXY_PARTITION = 'persist:agent-proxy'" in MAIN
    assert "_sapLineBuf" in MAIN and "SAP_PROXY:" in MAIN  # 行缓冲协议解析
    assert "mode: 'direct'" in MAIN                        # agent-direct 启动钉直连
    assert "mode: 'fixed_servers'" in MAIN                 # 下发代理→fixed_servers
    assert "proxyBypassRules" in MAIN                      # 本地地址绕代理
    # S237：声明必须在模块顶层且先于 startBackend（块作用域内声明=启动 ReferenceError）
    assert MAIN.index("const AGENT_DIRECT_PARTITION") < MAIN.index("async function startBackend")
    assert any(ln.startswith("const AGENT_DIRECT_PARTITION") for ln in MAIN.splitlines())  # 零缩进=顶层
    # 用户分区不受影响
    assert "persist:party-browser-session" in PAGE


def test_server_announce():
    assert 'print(f"SAP_PROXY:{px}" if px else "SAP_PROXY:null", flush=True)' in SERVER
    assert SERVER.count("_announce_agent_proxy(settings)") >= 2  # boot + save_settings
    assert "_announce_agent_proxy(settings)" in SERVER[SERVER.index("def _apply_proxy_env_safe"):]


def test_cdp_precheck_and_params():
    assert "async def _proxy_egress_precheck(use_proxy):" in CDP
    assert "from py.proxy_util import active_proxy" in CDP
    assert 'partition = "persist:agent-proxy" if use_proxy else "persist:agent-direct"' in CDP
    assert CDP.count('"use_proxy"') == 2  # new_page + web_render schema
    assert '"useProxy": bool(use_proxy)' in CDP
    assert "openUrlInBackground', [url, partition]" in CDP
    assert "openUrlInNewTab', [url, partition]" in CDP
    # 描述写明用意（默认直连 + VPN 场景 + 重建换出口）
    assert CDP.count("不受系统全局代理") >= 2  # 描述/文档均写明默认直连的用意
    assert "close_page + new_page(use_proxy)" in CDP
    assert "keeps the current egress" in CDP
    # 过时提示已更新
    assert "内置浏览器不走 SAP 应用内代理" not in CDP


def test_js_partition_plumbing():
    assert "opts.useProxy ? 'persist:agent-proxy' : 'persist:agent-direct'" in WV
    assert "openUrlInBackground(url, partition)" in WV
    assert "openUrlInNewTab(url, partition)" in TABS
    assert "partition: partition || 'persist:party-browser-session'" in TABS
    assert ':partition="tab.partition || \'persist:party-browser-session\'"' in PAGE


def test_stamp_s236():
    assert "build=S246" in _read("static", "js", "renderer.js")


_AST_SCRIPT = (
    "const acorn=require('acorn');"
    "const src=require('fs').readFileSync(process.argv[1],'utf8');"
    "const ast=acorn.parse(src,{ecmaVersion:'latest',sourceType:'script',allowReturnOutsideFunction:true});"
    "const want=['AGENT_DIRECT_PARTITION','AGENT_PROXY_PARTITION','_sapLineBuf','applyAgentProxyLine'];"
    "for(const n of want){"
    "const ok=ast.body.some(t=>(t.type==='VariableDeclaration'&&t.declarations.some(d=>d.id&&d.id.name===n))"
    "||(t.type==='FunctionDeclaration'&&t.id&&t.id.name===n));"
    "if(!ok){console.error('NOT-TOPLEVEL:'+n);process.exit(1);}}"
    "console.log('TOPLEVEL-OK');"
)


def test_mainjs_agent_proxy_symbols_really_top_level():
    """S237：S236 曾因声明落在 startBackend 的 executor 块作用域内、函数体开头
    引用不到而启动即 ReferenceError——node --check 只验语法。此处用 AST 真验
    四个符号位于模块顶层（Program.body），把该崩溃形态钉死。"""
    if not shutil.which("node"):
        import pytest
        pytest.skip("node unavailable")
    r = subprocess.run(["node", "-e", _AST_SCRIPT, str(ROOT / "main.js")],
                       capture_output=True, text=True, timeout=60, cwd=str(ROOT))
    assert "TOPLEVEL-OK" in (r.stdout or ""), (r.stdout or "") + (r.stderr or "")
