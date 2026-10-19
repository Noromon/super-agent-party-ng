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


def ip_ok(ip_str, allow_loopback=True):
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
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
