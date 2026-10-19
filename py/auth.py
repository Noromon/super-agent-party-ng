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
DISABLED = os.environ.get("SAP_DISABLE_TOKEN", "") == "1"

EXEMPT_PREFIXES = (
    "/v1",          # OpenAI-compatible external API (kept token-free by design)
    "/mcp",         # MCP mount (external clients)
    "/docs", "/redoc", "/openapi.json",
    "/session_token",
    "/health",
    "/favicon.ico",
)


def token_ok(request) -> bool:
    got = request.headers.get(HEADER) or ""
    if not got:
        got = request.cookies.get(COOKIE, "")
    return bool(got) and secrets.compare_digest(got, SESSION_TOKEN)


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
    """WebSocket handshakes carry the cookie automatically; also accept
    ?sap_token= for non-browser local clients."""
    if DISABLED:
        return True
    got = websocket.query_params.get("sap_token") or ""
    if not got:
        got = websocket.cookies.get(COOKIE, "")
    return bool(got) and secrets.compare_digest(got, SESSION_TOKEN)


def is_exempt(path: str) -> bool:
    if DISABLED:
        return True
    if path == "/" or "." in path.rsplit("/", 1)[-1]:
        return True  # static assets
    for p in EXEMPT_PREFIXES:
        if path == p or path.startswith(p + "/"):
            return True
    return False


def write_token_file(data_dir) -> str:
    path = os.path.join(str(data_dir), TOKEN_FILE_NAME)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(SESSION_TOKEN)
    except OSError:
        pass
    return path
