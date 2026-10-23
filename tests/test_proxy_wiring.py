# -*- coding: utf-8 -*-
"""S85-D：代理通用化接线——normalize 容错矩阵 / active_proxy / env 注入 /
fake-ip 放行 / 网络错误文案 / 源码接线 pin / socks 依赖可用性。"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s85d_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest  # noqa: E402

import py.proxy_util as pu  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def _settings(mode, proxy=""):
    return {"systemSettings": {"proxyMode": mode, "proxy": proxy}}


# ---------------- normalize_proxy_url：填什么都不炸 ----------------

@pytest.mark.parametrize("raw,expect", [
    ("http://127.0.0.1:7890", "http://127.0.0.1:7890"),
    ("  http://127.0.0.1:7890  ", "http://127.0.0.1:7890"),
    ('"socks5h://127.0.0.1:1080"', "socks5h://127.0.0.1:1080"),
    ("SOCKS5H://127.0.0.1:1080", "socks5h://127.0.0.1:1080"),
    ("127.0.0.1:1080", "http://127.0.0.1:1080"),
    ("clash.lan:7890", "http://clash.lan:7890"),
    ("user:pass@host:1080", None),  # 无协议且非 user@ 形态 → 不猜
])
def test_normalize_matrix(raw, expect):
    assert pu.normalize_proxy_url(raw, warn=False) == expect


@pytest.mark.parametrize("bad", [
    "", "  ", None, "garbage", "ftp://127.0.0.1:21", "socks5://",
    "http://host:notaport", "http://:8080", "socks6://1.2.3.4:1",
])
def test_normalize_never_raises(bad):
    assert pu.normalize_proxy_url(bad, warn=False) is None


def test_normalize_userinfo_preserved():
    assert pu.normalize_proxy_url("socks5://u:p@10.0.0.2:1070", warn=False) \
        == "socks5://u:p@10.0.0.2:1070"


# ---------------- active_proxy 三模式 ----------------

def test_active_proxy_manual_and_none(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    assert pu.active_proxy(_settings("manual", "socks5h://127.0.0.1:1080")) \
        == "socks5h://127.0.0.1:1080"
    assert pu.active_proxy(_settings("manual", "garbage!!!")) is None
    assert pu.active_proxy(_settings("none", "http://127.0.0.1:1")) is None


def test_active_proxy_legacy_no_mode_passthrough(monkeypatch):
    # 旧库无 proxyMode 字段：填了 proxy 即 manual 语义（S85 前的行为，升级不失效）
    s = {"systemSettings": {"proxy": "http://127.0.0.1:7890"}}
    assert pu.active_proxy(s) == "http://127.0.0.1:7890"


def test_active_proxy_system_via_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:33210")
    assert pu.active_proxy(_settings("system")) == "http://127.0.0.1:33210"


def test_active_proxy_system_probe_failure_is_none(monkeypatch):
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    monkeypatch.delenv("HTTPS_PROXY", raising=False)
    monkeypatch.delenv("ALL_PROXY", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "")
    monkeypatch.setattr(pu, "_system_proxy_probe", lambda: None)
    assert pu.active_proxy(_settings("system")) is None


# ---------------- requests_proxies：本机目标直连 ----------------

def test_requests_proxies_local_target_bypass():
    s = _settings("manual", "http://127.0.0.1:7890")
    assert pu.requests_proxies(s, "http://127.0.0.1:8848/search") is None
    assert pu.requests_proxies(s, "http://localhost:11434") is None
    assert pu.requests_proxies(s, "http://192.168.1.5:8080") is None
    assert pu.requests_proxies(s, "https://duckduckgo.com") == {
        "http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}
    assert pu.requests_proxies(_settings("none"), "https://x.com") is None


# ---------------- apply_env_proxy：注入/清除/NO_PROXY 默认 ----------------

def test_apply_env_proxy_manual_and_clear(monkeypatch):
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    px = pu.apply_env_proxy(_settings("manual", "socks5h://127.0.0.1:1080"))
    assert px == "socks5h://127.0.0.1:1080"
    assert os.environ["HTTPS_PROXY"] == px and os.environ["all_proxy"] == px
    assert "127.0.0.1" in os.environ["NO_PROXY"]
    pu.apply_env_proxy(_settings("none"))
    assert "HTTP_PROXY" not in os.environ and "ALL_PROXY" not in os.environ


def test_apply_env_proxy_keeps_user_no_proxy(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "mine")
    pu.apply_env_proxy(_settings("manual", "http://1.2.3.4:1"))
    assert os.environ["NO_PROXY"] == "mine"
    pu.apply_env_proxy(_settings("none"))


# ---------------- fake-ip：198.18.0.0/15 永久视为公网 ----------------

def test_net_guard_fake_ip_allowed():
    from py.net_guard import ip_ok
    assert ip_ok("198.18.1.1") is True
    assert ip_ok("198.19.255.255") is True
    assert ip_ok("10.0.0.8") is False
    assert ip_ok("127.0.0.1") is True
    assert ip_ok("169.254.1.1") is False


def test_url_public_ok_fake_ip(monkeypatch):
    import py.net_guard as ng

    def fake_gai(host, *a, **k):
        return [(2, 1, 6, "", ("198.18.42.7", 0))]
    monkeypatch.setattr(ng.socket, "getaddrinfo", fake_gai)
    assert ng.url_public_ok("https://api.duckduckgo.com/", True) is True


# ---------------- net_error_hint ----------------

class _ConnectError(Exception):
    pass


def test_net_error_hint_positive_negative():
    assert "socks5h" in pu.net_error_hint(_ConnectError("boom"))
    assert pu.net_error_hint(ValueError("bad args")) == ""
    assert "代理" in pu.net_error_hint(OSError("getaddrinfo failed"))


# ---------------- socks 依赖（uv sync 后自动转真测） ----------------

@pytest.mark.parametrize("mod", ["socks", "socksio", "aiohttp_socks"])
def test_socks_deps_available(mod):
    pytest.importorskip(mod, reason="需 uv sync 安装 socks 依赖后生效")


# ---------------- 源码接线 pin（防止后续改动悄悄拆线） ----------------

def test_server_wiring_pins():
    src = _read("server.py")
    assert "proxy_url = normalize_proxy_url(manual_url)" in src
    assert "apply_env_proxy(settings)" in src
    assert "_apply_proxy_env_safe(current)" in src
    assert src.count('"incremental": True') >= 2          # 流式 + DRS 双站点
    assert "current_tool, _frag = _merge_tool_delta(" in src
    assert "已降级为直连" in src                            # httpx 构造失败兜底


def test_fetch_chain_wiring_pins():
    lf = _read("py/load_files.py")
    assert "ProxyConnector.from_url" in lf
    assert "bypass_local_dns = bool(px)" in lf
    assert "proxy_url=px" in lf
    ws = _read("py/web_search.py")
    assert "proxy_url = active_proxy(settings)" in ws
    assert "不支持 SOCKS4" in ws
    lt = _read("py/llm_tool.py")
    assert "_bypass_dns_check" in lt and "_make_session(proxy_url=_dl_proxy)" in lt


def test_frontend_ingest_pins():
    js = _read("static/js/methods/13_resume_stream.js")
    assert "progress.incremental" in js
    assert "65536" in js
    zh = _read("static/js/locales/zh-CN.js")
    assert "socks5h://" in zh
