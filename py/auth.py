# -*- coding: utf-8 -*-
"""Local session-token kernel (M2 / audit X-1/X-2/X-10).

The server binds to loopback, but any local browser page (or DNS-rebound
domain) could otherwise drive state-changing endpoints. Defense layers here:
 - Origin guard: browser requests must originate from loopback origins.
 - Session token: generated at startup, persisted for the local Electron host
   and tests; same-origin pages bootstrap via GET /session_token (sets a
   SameSite=Lax cookie so fetch AND WebSocket handshakes carry it with zero
   frontend patching). Non-browser local clients may send X-SAP-Token header.
/v1 and /mcp outbound-facing surfaces stay exempt by design (user keeps them
as external features); dev escape hatch: SAP_DISABLE_TOKEN=1.
"""
import os
import secrets
from urllib.parse import urlparse

HEADER = "X-SAP-Token"
COOKIE = "sap_token"
TOKEN_FILE_NAME = ".session_token"

# Populated at import; file is written by lifespan once USER_DATA_DIR exists.
SESSION_TOKEN = os.environ.get("SAP_SESSION_TOKEN") or secrets.token_urlsafe(24)
# Machine token: stable identity for local non-browser clients (node
# extensions, headless API consumers); persisted, survives restarts.
MACHINE_TOKEN = os.environ.get("SAP_MACHINE_TOKEN") or ""
DISABLED = os.environ.get("SAP_DISABLE_TOKEN", "") == "1"

# M5：外联 API（/v1 OpenAI 兼容面、/mcp）免 token 开关。默认免鉴权以兼容既有
# LAN/脚本用法；settings.externalApiRequireToken=true（或环境变量
# SAP_EXTERNAL_API_REQUIRE_TOKEN=1）后要求 Authorization: Bearer <MACHINE_TOKEN>。
EXTERNAL_TOKEN_FREE = os.environ.get("SAP_EXTERNAL_API_REQUIRE_TOKEN", "") != "1"
_TOKENFREE_PREFIXES = ("/v1", "/mcp")

EXEMPT_PREFIXES = (
    "/v1",          # OpenAI-compatible external API (kept token-free by design)
    "/mcp",         # MCP mount (external clients)
    "/docs", "/redoc", "/openapi.json",
    "/session_token",
    "/health",
    "/favicon.ico",
)


def _token_match(got: str) -> bool:
    if not got:
        return False
    for valid in (SESSION_TOKEN, MACHINE_TOKEN):
        if valid and secrets.compare_digest(got, valid):
            return True
    return False


def token_ok(request) -> bool:
    got = request.headers.get(HEADER) or ""
    if not got:
        authz = request.headers.get("authorization") or ""
        if authz.lower().startswith("bearer "):
            # OpenAI 兼容客户端惯例；token-free 关闭后 /v1 /mcp 走此路
            got = authz[7:].strip()
    if not got:
        got = request.cookies.get(COOKIE, "")
    return _token_match(got)


def origin_ok(request) -> bool:
    """No Origin header (non-browser / same-origin GET nav) passes;
    if present it must be a loopback http(s) origin."""
    origin = request.headers.get("origin")
    if not origin:
        return True
    try:
        u = urlparse(origin)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.hostname or "").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def host_ok(request) -> bool:
    """DNS-rebinding defense: domain-form Host only accepted for loopback
    names; IP-form Host (any, incl. LAN setups the user chose to expose)
    passes since browsers treat it as cross-origin-isolated anyway."""
    host = (request.headers.get("host") or "").strip().lower()
    if not host:
        return False
    if host.startswith("["):
        hostpart = host[1:host.index("]")] if "]" in host else host[1:]
    elif host.count(":") == 1:
        hostpart = host.rsplit(":", 1)[0]
    else:
        hostpart = host
    if hostpart in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        import ipaddress
        ipaddress.ip_address(hostpart)
        return True
    except ValueError:
        return False


def ws_auth_ok(websocket) -> bool:
    """WebSocket handshakes carry the cookie automatically; non-browser local
    clients (node extensions, headless tools) send the X-SAP-Token header or
    use ?sap_token= ."""
    if DISABLED:
        return True
    got = websocket.query_params.get("sap_token") or ""
    if not got:
        got = websocket.headers.get("x-sap-token") or ""
    if not got:
        got = websocket.cookies.get(COOKIE, "")
    return _token_match(got)


def is_exempt(path: str) -> bool:
    if DISABLED:
        return True
    # 静态资源（StaticFiles 挂载面）按“最后一段含扩展名”豁免。
    # 约定：动态 API 路由的最后一段禁止含点号；唯一例外是 /ext 子树内的
    # node 代理（/ext/{id}/node/...），它虽带扩展名也必须走鉴权，单独排除。
    if path == "/":
        return True
    if path.startswith("/ext/") and "/node/" in path:
        return False
    if "." in path.rsplit("/", 1)[-1]:
        return True
    for p in EXEMPT_PREFIXES:
        if path == p or path.startswith(p + "/"):
            if p in _TOKENFREE_PREFIXES and not EXTERNAL_TOKEN_FREE:
                return False
            return True
    return False


def path_under(path, roots) -> bool:
    """Realpath containment (X-6/X-7): candidate must live inside one of roots."""
    import os
    try:
        rp = os.path.realpath(str(path))
    except Exception:
        return False
    for r in roots:
        try:
            rr = os.path.realpath(str(r))
        except Exception:
            continue
        try:
            if os.path.commonpath([rp, rr]) == rr:
                return True
        except ValueError:
            continue
    return False


def write_token_file(data_dir) -> str:
    path = os.path.join(str(data_dir), TOKEN_FILE_NAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(SESSION_TOKEN)
    except OSError:
        pass
    return path


def ensure_machine_token(data_dir) -> str:
    """Load or first-run-generate the persistent local machine token."""
    global MACHINE_TOKEN
    if MACHINE_TOKEN:
        return MACHINE_TOKEN
    path = os.path.join(str(data_dir), ".machine_token")
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                stored = f.read().strip()
            if stored:
                MACHINE_TOKEN = stored
                return MACHINE_TOKEN
    except OSError:
        pass
    MACHINE_TOKEN = secrets.token_urlsafe(32)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(MACHINE_TOKEN)
    except OSError:
        pass
    return MACHINE_TOKEN
