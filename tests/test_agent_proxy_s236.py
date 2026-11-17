# -*- coding: utf-8 -*-
"""S236：agent 浏览器/render 工具 per-call 代理选择（默认直连）——静态链路断言。"""
import pathlib

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
    assert "build=S236" in _read("static", "js", "renderer.js")
