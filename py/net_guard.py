# -*- coding: utf-8 -*-
"""SSRF guard (M2 / audit X-8).

User ecosystem lives on loopback (ComfyUI, Strata, node extensions), so
loopback is exempt; private/reserved/link-local/metadata ranges are blocked.
DNS-resolved addresses are checked (not just literal IPs) to cover
domain->private rebinding.
"""
import ipaddress
import socket
from urllib.parse import urlparse

# S85-D4：RFC2544 198.18.0.0/15 是代理软件 fake-ip 池，不是真内网——
# 永久按公网放行（与 load_files.is_private_ip 的既有豁免对齐），
# 否则 fake-ip 环境会把所有公网域名一票误杀。
_FAKE_IP_NET = ipaddress.ip_network("198.18.0.0/15")


def ip_ok(ip_str, allow_loopback=True):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if ip in _FAKE_IP_NET:
        return True
    if ip.is_loopback:
        return bool(allow_loopback)
    if ip.is_private or ip.is_reserved or ip.is_link_local \
            or ip.is_multicast or ip.is_unspecified:
        return False
    return True


def url_public_ok(url, allow_loopback=True):
    try:
        u = urlparse(str(url))
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = u.hostname
    if not host:
        return False
    try:
        ips = {sa[0] for _, _, _, _, sa in socket.getaddrinfo(host, None)}
    except socket.gaierror:
        return True  # unresolvable: nothing to attack
    return bool(ips) and all(ip_ok(ip, allow_loopback) for ip in ips)
