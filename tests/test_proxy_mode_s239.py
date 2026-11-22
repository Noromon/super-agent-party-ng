# -*- coding: utf-8 -*-
"""S239：代理语义票——proxyBypass 可配置白名单、global_http_client 实时化、
SAP_PROXY_BYPASS 协议线、双侧留痕、死路由清除。单测+AST 提取行为测+静态链路断言。"""
import ast
import contextlib
import importlib.util
import pathlib
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 本仓 'py/' 包与 pytest 生态的 'py' 模块存在名字遮蔽风险：直接 spec 加载
# proxy_util（纯 stdlib 依赖），并用 shim 保证 AST 提取函数里的 from-import 可解析。
_spec = importlib.util.spec_from_file_location("py.proxy_util", ROOT / "py" / "proxy_util.py")
pu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pu)


@contextlib.contextmanager
def _py_pkg_shim():
    saved_pkg = sys.modules.get("py")
    saved_sub = sys.modules.get("py.proxy_util")
    shim = types.ModuleType("py")
    shim.__path__ = [str(ROOT / "py")]
    sys.modules["py"] = shim
    sys.modules["py.proxy_util"] = pu
    try:
        yield
    finally:
        if saved_pkg is None:
            sys.modules.pop("py", None)
        else:
            sys.modules["py"] = saved_pkg
        if saved_sub is None:
            sys.modules.pop("py.proxy_util", None)
        else:
            sys.modules["py.proxy_util"] = saved_sub


def _read(*p):
    return (ROOT.joinpath(*p)).read_text(encoding="utf-8")


SERVER = _read("server.py")
MAIN = _read("main.js")
SYSJS = _read("static", "js", "methods", "60_system_settings.js")
PAGE = _read("static", "templates", "page_system.html")
TEMPLATE = _read("config", "settings_template.json")
DATA = _read("static", "js", "data", "20_brain_settings.js")
POLL = _read("py", "pollinations.py")
UTIL = _read("py", "utility_tools.py")
ZH = _read("static", "js", "locales", "zh-CN.js")
EN = _read("static", "js", "locales", "en-US.js")


def _extract_func(src, name):
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            if seg:
                return seg
    raise AssertionError(f"function {name} not found")


# ---------------- proxy_util 单元 ----------------

def test_bypass_list_parsing():
    s = {"systemSettings": {"proxyBypass": "Example.com, *.corp.local ,10.0.0.0/8;;"}}
    assert pu.bypass_list(s) == ["example.com", "corp.local", "10.0.0.0/8"]
    assert pu.proxy_bypass_rules(s) == "example.com,corp.local,10.0.0.0/8"
    assert pu.bypass_list({}) == []
    assert pu.bypass_list({"systemSettings": {"proxyBypass": None}}) == []


def test_host_in_bypass():
    bl = pu.bypass_list({"systemSettings": {"proxyBypass": "example.com, 10.0.0.0/8"}})
    assert pu.host_in_bypass("example.com", bl)
    assert pu.host_in_bypass("a.b.example.com", bl)
    assert not pu.host_in_bypass("notexample.com", bl)
    assert pu.host_in_bypass("10.20.30.40", bl)
    assert not pu.host_in_bypass("8.8.8.8", bl)
    assert not pu.host_in_bypass(None, bl)
    assert not pu.host_in_bypass("example.com", [])


def test_requests_proxies_bypass_and_normal():
    s = {"systemSettings": {"proxyMode": "manual",
                            "proxy": "socks5h://127.0.0.1:1080",
                            "proxyBypass": "corp.local"}}
    assert pu.requests_proxies(s, "https://x.corp.local/p") is None       # 白名单直连
    assert pu.requests_proxies(s, "https://ok.org/x") == {                # 其余走代理
        "http": "socks5h://127.0.0.1:1080", "https": "socks5h://127.0.0.1:1080"}
    assert pu.requests_proxies(s, "http://127.0.0.1:9/x") is None         # 内建回环直连保持


def test_apply_env_proxy_no_proxy_appends_bypass():
    # Windows 环境键大小写不敏感：monkeypatch 对同键双名(UPPER/lower)存/复会错乱
    # 泄漏 ALL_PROXY=7890 毒化后续 test_proxy_wiring——改手动快照+按平台去重恢复。
    import os
    names = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    if os.name != "nt":
        names += tuple(k.lower() for k in names)
    saved = {}
    for k in names:
        saved.setdefault(k.lower(), os.environ.pop(k, None))
    try:
        s = {"systemSettings": {"proxyMode": "manual",
                                "proxy": "http://127.0.0.1:7890",
                                "proxyBypass": "corp.local,10.0.0.0/8"}}
        px = pu.apply_env_proxy(s)
        assert px == "http://127.0.0.1:7890"
        assert "corp.local" in os.environ["NO_PROXY"]
        assert "127.0.0.1" in os.environ["NO_PROXY"]  # 默认内网段仍在（附加语义）
    finally:
        for lk, v in saved.items():
            if v is None:
                os.environ.pop(lk, None)
            else:
                os.environ[lk] = v


def test_mask_proxy_url():
    assert pu.mask_proxy_url("http://u:p@h:1") == "http://***@h:1"
    assert pu.mask_proxy_url("socks5h://127.0.0.1:1080") == "socks5h://127.0.0.1:1080"
    assert pu.mask_proxy_url(None) is None


# ---------------- server 行为（AST 提取 exec） ----------------

def _server_ns():
    import httpx
    ns = {"httpx": httpx, "app_state": types.SimpleNamespace(),
          "logger": types.SimpleNamespace(info=lambda *a, **k: None)}
    exec(_extract_func(SERVER, "_build_proxy_transport"), ns)
    exec(_extract_func(SERVER, "_swap_global_http_proxy"), ns)
    return ns


def test_swap_global_http_proxy_inplace_hotswap():
    import httpx
    with _py_pkg_shim():
        ns = _server_ns()
        client = httpx.AsyncClient(trust_env=False)
        ns["app_state"].global_http_client = client
        old = client._transport
        ns["_swap_global_http_proxy"]("socks5h://127.0.0.1:1080")
        assert client._transport is not old                  # 出口已换
        assert ns["app_state"].global_http_client is client  # 实例引用不变（AsyncOpenAI 持用不断线）
        ns["_swap_global_http_proxy"](None)                  # 直连分支不炸


def test_swap_global_http_proxy_failure_swallowed():
    with _py_pkg_shim():
        ns = _server_ns()
        ns["app_state"].global_http_client = 42  # 无 _transport 可设的怪对象
        ns["_swap_global_http_proxy"]("http://x")  # 绝不 raise（logger 假对象吞 info）
        ns["app_state"].global_http_client = None
        ns["_swap_global_http_proxy"]("http://x")  # 无客户端=静默直通


def test_announce_dual_protocol_lines(capsys):
    logs = []
    ns = {"logger": types.SimpleNamespace(info=lambda *a, **k: logs.append(" ".join(str(x) for x in a)))}
    with _py_pkg_shim():
        exec(_extract_func(SERVER, "_announce_agent_proxy"), ns)
        ns["_announce_agent_proxy"]({"systemSettings": {
            "proxyMode": "manual", "proxy": "http://secret:pw@127.0.0.1:7890",
            "proxyBypass": "corp.local"}})
    out = capsys.readouterr().out
    assert "SAP_PROXY:http://secret:pw@127.0.0.1:7890\n" in out
    assert "SAP_PROXY_BYPASS:corp.local\n" in out
    assert any("SAP_PROXY 下发" in line for line in logs)
    assert "secret" not in "".join(logs) and "pw@" not in "".join(logs)  # 日志脱敏
    with _py_pkg_shim():
        ns["_announce_agent_proxy"]({"systemSettings": {"proxyMode": "none"}})
    out = capsys.readouterr().out
    assert "SAP_PROXY:null" in out and "SAP_PROXY_BYPASS:none" in out


# ---------------- server 静态 ----------------

def test_server_boot_uses_live_active_proxy_and_transport():
    assert "def _build_proxy_transport" in SERVER
    assert "transport=_build_proxy_transport(proxy_url)" in SERVER
    assert "trust_env=trust_env" not in SERVER            # trust_env 通道废除=钉死源头移除
    assert "_swap_global_http_proxy(px)" in SERVER[SERVER.index("def _apply_proxy_env_safe"):]
    assert 'print(f"SAP_PROXY_BYPASS:{bl}"' in SERVER
    assert "[Proxy] SAP_PROXY 下发" in SERVER             # backend.log 留痕


# ---------------- main.js 静态 ----------------

def test_mainjs_bypass_line_and_traces():
    assert "SAP_PROXY_BYPASS:" in MAIN                    # 第二协议线解析
    assert "applyAgentBypassLine" in MAIN
    assert "AGENT_BYPASS_BASE" in MAIN
    assert ",<-" in MAIN and ",<->'" not in MAIN          # T5：合法通配符替换无效 token
    assert "evidenceAppend('[AgentProxy]" in MAIN         # 主进程侧留痕
    assert "://***@" in MAIN                              # evidence 写前脱敏
    assert MAIN.index("const AGENT_DIRECT_PARTITION") < MAIN.index("async function startBackend")
    assert any(ln.startswith("const AGENT_BYPASS_BASE") for ln in MAIN.splitlines())


def test_updateproxy_dead_route_removed():
    assert "fetch('/api/update_proxy'" not in SYSJS
    assert "async updateProxy()" in SYSJS and "autoSaveSettings" in SYSJS


# ---------------- UI/默认值/i18n 静态 ----------------

def test_ui_bypass_input_and_defaults():
    assert 'v-model="systemSettings.proxyBypass"' in PAGE
    assert '@change="updateProxy"' in PAGE                 # 防保存风暴：change 非 input
    assert "proxyBypassHint" in PAGE
    assert '"proxyBypass": ""' in TEMPLATE
    assert "proxyBypass: ''" in DATA


def test_i18n_keys_and_coverage_copy():
    for blob in (ZH, EN):
        assert "proxyBypass" in blob and "proxyBypassPlaceholder" in blob
        assert "proxyBypassHint" in blob
        assert "use_proxy" in blob[blob.index("proxyNotice"):blob.index("proxyNotice") + 700]


def test_python_tools_proxies_wired():
    assert POLL.count("requests_proxies(") == 2           # pollinations 两下载点
    assert "http_client=_kh" in POLL                       # 生图 API 出口同通道
    assert "await client.close()" in POLL                  # 自建 http client 有归还
    assert "requests_proxies(_st, base_url)" in UTIL       # 天气 API


def test_stamp_s239():
    assert "build=S293" in _read("static", "js", "renderer.js")
