# -*- coding: utf-8 -*-
"""S85-D：代理配置统一解析与进程级应用。

代理栏接受 http:// https:// socks4:// socks4a:// socks5:// socks5h://
或裸 host:port（默认按 http 代理处理）。normalize 永不抛异常——
无法识别的形态返回 None 并记一条 warning，保证"代理栏填什么都不炸"。

应用三层：
1. env 注入（apply_env_proxy）：**仅 http/https 型**（S87——socks:// 入 env 会让
   httpx trust_env 默认 True 的裸构造点在构造期炸）；none 模式清空，避免陈旧 env。
2. 显式接线（socks 唯一通道）：primp(DDG) 构造参数；aiohttp ProxyConnector；
   web_search 各 requests 点显式 proxies=requests_proxies(settings, url)。
3. SSRF 防护感知（net_guard/load_files/llm_tool/web_search 调用点）：
   代理链激活时域名跳过本地 DNS 预判定（fake-ip/污染解析会误杀），
   字面 IP 与 198.18.0.0/15 永久放行的判定不变。
"""
import ipaddress
import logging
import os
import re
from urllib.parse import urlparse

SUPPORTED_SCHEMES = ("http", "https", "socks4", "socks4a", "socks5", "socks5h")
_BARE_RE = re.compile(r"^[A-Za-z0-9_\-.]+:\d{1,5}$")

NO_PROXY_DEFAULT = ("localhost,127.0.0.1,::1,10.0.0.0/8,"
                    "172.16.0.0/12,192.168.0.0/16,169.254.0.0/16")

NET_ERR_HINT = ("【网络提示】目标不可达：可能是本地 DNS 被污染（fake-ip/黑洞解析）"
                "或代理未生效。建议在 设置→系统→代理 填写 socks5h://127.0.0.1:<端口>"
                "（远端解析，绕开本地 DNS）或 http://127.0.0.1:<端口>，"
                "也可检查代理软件是否开启对应协议端口。")

_NET_ERR_TOKENS = ("ConnectError", "ConnectTimeout", "ReadTimeout", "TimeoutError",
                   "ProxyError", "SSLError", "ClientConnectorError", "ClientOSError",
                   "ConnectionRefused", "NetworkError")


def normalize_proxy_url(raw, warn=True):
    """任意用户输入 → 规范代理 URL 或 None。永不 raise。"""
    log = logging.getLogger("app")
    if raw is None:
        return None
    url = str(raw).strip().strip('"\'').strip()
    if not url:
        return None
    if "://" not in url:
        if _BARE_RE.match(url):
            url = "http://" + url
        else:
            if warn:
                log.warning(f"[Proxy] 无法识别的代理地址，已忽略: {raw!r}")
            return None
    try:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        _ = parsed.port  # 非法端口在这里抛 ValueError → 走下方 warning+None
    except ValueError:
        if warn:
            log.warning(f"[Proxy] 无法识别的代理地址，已忽略: {raw!r}")
        return None
    if scheme not in SUPPORTED_SCHEMES or not parsed.hostname:
        if warn:
            log.warning(f"[Proxy] 不支持的代理协议/缺主机名，已忽略: {raw!r}"
                        f"（支持 {', '.join(SUPPORTED_SCHEMES)}）")
        return None
    try:
        netloc = parsed.netloc
    except Exception:
        return None
    return f"{scheme}://{netloc}"


def is_literal_ip(host):
    try:
        ipaddress.ip_address(host or "")
        return True
    except ValueError:
        return False


def http_ua(settings, default=""):
    """S88：全局抓取 User-Agent。systemSettings.httpUserAgent 非空 → 覆盖
    抓取/搜索族的 UA（DDG/jina/searxng/markdown.new/网页与图片下载/robots）；
    留空返回 default（各站保持原行为，零变更）。"""
    try:
        ua = str(((settings or {}).get("systemSettings", {}) or {})
                 .get("httpUserAgent") or "").strip()
        return ua or default
    except Exception:
        return default


def _system_proxy_probe():
    """system 模式下探测"真代理"是否存在：env 优先，其次 Windows WinINET。"""
    log = logging.getLogger("app")
    for k in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
        v = os.environ.get(k) or os.environ.get(k.lower())
        n = normalize_proxy_url(v, warn=False)
        if n:
            return n
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            if winreg.QueryValueEx(k, "ProxyEnable")[0] == 1:
                srv = winreg.QueryValueEx(k, "ProxyServer")[0]
                return normalize_proxy_url(
                    srv if "://" in srv else f"http://{srv}", warn=False)
    except Exception as e:
        log.info(f"[Proxy] 系统代理探测失败（按无代理处理）: {e}")
    return None


def active_proxy(settings):
    """当前生效出口代理（已规范化）或 None。永不 raise。"""
    try:
        ss = (settings or {}).get("systemSettings", {}) or {}
        mode = str(ss.get("proxyMode") or "").lower()
        raw_proxy = ss.get("proxy", "")
        if mode == "manual":
            return normalize_proxy_url(raw_proxy)
        if mode == "" and str(raw_proxy or "").strip():
            # 兼容旧库（无 proxyMode 字段）：填了 proxy 即按 manual 透传，
            # 与 S85 之前行为一致，升级用户代理不静默失效。
            return normalize_proxy_url(raw_proxy)
        if mode == "system":
            return _system_proxy_probe()
    except Exception as e:
        logging.getLogger("app").warning(f"[Proxy] active_proxy 异常: {e}")
    return None


def requests_proxies(settings, target_url=None):
    """requests 风格 proxies dict。目标为本机/字面私网 IP 时直连。"""
    px = active_proxy(settings)
    if not px:
        return None
    if target_url:
        try:
            host = urlparse(target_url).hostname
        except Exception:
            host = None
        if host:
            if host == "localhost" or is_literal_ip(host):
                try:
                    ip = ipaddress.ip_address(host)
                except ValueError:
                    ip = None
                if ip is None or ip.is_private or ip.is_loopback \
                        or ip.is_link_local or ip.is_unspecified:
                    return None
    return {"http": px, "https": px}


def apply_env_proxy(settings):
    """按代理模式写/清进程 env（manual=注入，system=探测到则注入，none=清除）。

    S87：SOCKS 型绝不入 env——httpx trust_env 默认 True 的裸构造点（全仓 20+ 处
    AsyncOpenAI 回连本地 LLM）会在**构造期**建 SOCKS transport：缺 socksio 直接
    ImportError，装上也会让本地回连被迫绕代理软件。socks 只走显式通道
    （DDG/primp、aiohttp ProxyConnector、requests 显式 proxies 接线点）。
    """
    px = active_proxy(settings)
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
              "http_proxy", "https_proxy", "all_proxy"):
        os.environ.pop(k, None)
    if px and px.split("://", 1)[0] in ("http", "https"):
        for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                  "http_proxy", "https_proxy", "all_proxy"):
            os.environ[k] = px
        os.environ.setdefault("NO_PROXY", NO_PROXY_DEFAULT)
        os.environ.setdefault("no_proxy", NO_PROXY_DEFAULT)
    elif px:
        logging.getLogger("app").info(
            f"[Proxy] {px.split('://', 1)[0]}:// 型代理不注入 env"
            "（防 httpx 构造期炸/本地回连绕行），仅显式接线点生效")
    return px


def net_error_hint(exc):
    """网络类异常附加提示文案；非网络类返回空串。"""
    try:
        name = type(exc).__name__
        msg = str(exc)
    except Exception:
        return ""
    if any(t in name for t in _NET_ERR_TOKENS) \
            or "getaddrinfo failed" in msg or "Connection refused" in msg \
            or "error sending request for url" in msg \
            or "Cannot connect to host" in msg:
        return "\n" + NET_ERR_HINT
    return ""
