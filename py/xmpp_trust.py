# -*- coding: utf-8 -*-
"""M5-XMPP TLS certificate policy: TOFU (Trust On First Use) + host allow-list.

Design (Gajim-style, since slixmpp negotiates STARTTLS itself):
- TLS layer always connects with a non-verifying context (CERT_NONE);
  authenticity is enforced at application level in the `ssl_cert` hook
  inside py/xmpp_client.py:
    * host:port fingerprint matches the stored one  -> pass
    * in the user's ignore_cert_hosts allow-list     -> pass (logged)
    * previously "trusted once" (current bot run)    -> pass
    * otherwise                                      -> hang up + queue for review
- "trust once" lives until the bot stops or SAP restarts (process memory).
- "always trust" persists to xmpp_trust.json, keyed by host:port; a changed
  certificate downgrades to `changed` and demands a fresh review.
"""
import base64
import hashlib
import json
import logging
import os
import ssl
import tempfile
import threading
import time

PEM_MARK = "-----BEGIN"


def pem_to_der(pem: str) -> bytes:
    body = "".join(line.strip() for line in pem.splitlines() if "-----" not in line)
    return base64.b64decode(body)


def fingerprint_pem(pem: str) -> str:
    """'sha256:<hex>' over the DER form."""
    return "sha256:" + hashlib.sha256(pem_to_der(pem)).hexdigest()


def cert_display_info(pem: str) -> dict:
    """Best-effort subject/validity for the review UI (stdlib only)."""
    out = {"subject": "?", "not_before": "", "not_after": ""}
    path = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pem)
            path = f.name
        d = ssl._ssl._test_decode_cert(path)
        out["subject"] = " / ".join(
            f"{k}={v}" for rdn in d.get("subject", ()) for k, v in rdn)
        out["not_before"] = d.get("notBefore", "")
        out["not_after"] = d.get("notAfter", "")
    except Exception:
        pass
    finally:
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    return out


class TrustStore:
    """Persistent host:port -> fingerprint records (TOFU database)."""

    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        self._data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self._data = data
        except Exception:
            self._data = {}

    def _save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.path)

    def check(self, key: str, fp: str) -> str:
        rec = self._data.get(key)
        if not rec:
            return "unknown"
        return "match" if rec.get("fingerprint") == fp else "changed"

    def trust(self, key: str, fp: str, meta: dict | None = None):
        with self._lock:
            self._data[key] = {
                "fingerprint": fp,
                **(meta or {}),
                "added_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            self._save()

    def entries(self) -> dict:
        return dict(self._data)

    def knows_host(self, host: str) -> bool:
        return any(k.split(":")[0] == host for k in self._data)


class OnceTrust:
    """Per-process temporary trust (cleared when the bot stops or SAP exits)."""

    def __init__(self):
        self._granted = set()
        self._lock = threading.Lock()

    def grant(self, key: str):
        with self._lock:
            self._granted.add(key)

    def is_granted(self, key: str) -> bool:
        with self._lock:
            return key in self._granted

    def clear(self):
        with self._lock:
            self._granted.clear()


class PendingReviews:
    """Certificates awaiting user review (in-memory only)."""

    def __init__(self):
        self._items = {}
        self._lock = threading.Lock()

    def add(self, key: str, fp: str, pem: str):
        with self._lock:
            self._items[key] = {
                "key": key,
                "fingerprint": fp,
                "pem": pem,
                "seen_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                **cert_display_info(pem),
            }

    def pop(self, key: str):
        with self._lock:
            return self._items.pop(key, None)

    def list(self):
        with self._lock:
            return [dict(v) for v in self._items.values()]

    def clear(self):
        with self._lock:
            self._items.clear()


# --- process-wide singletons (shared by client, routes, UI) ---
STORE = None      # TrustStore, bound lazily to USER_DATA_DIR
ONCE = OnceTrust()
PENDING = PendingReviews()


def get_store():
    global STORE
    if STORE is None:
        from py.get_setting import USER_DATA_DIR
        STORE = TrustStore(os.path.join(USER_DATA_DIR, "xmpp_trust.json"))
    return STORE


def host_allowed(host: str, ignore_list) -> bool:
    """Whitelist match: entry is 'host' or 'host:port'."""
    for entry in ignore_list or []:
        e = str(entry).strip().lower()
        if not e:
            continue
        e = e.split("//")[-1].split("/")[0]
        if e == host or e.split(":")[0] == host:
            return True
    return False


def decide(key: str, decision: str, pem: str | None = None) -> bool:
    """Route the user's review decision. Returns True when handled."""
    item = PENDING.pop(key)
    if decision == "reject":
        return True
    if decision == "once":
        ONCE.grant(key)
        return True
    if decision == "always":
        fp = (item or {}).get("fingerprint")
        if not fp and pem and pem.startswith(PEM_MARK):
            fp = fingerprint_pem(pem)
        if not fp:
            logging.error("xmpp trust: no fingerprint to store for %s", key)
            return False
        get_store().trust(key, fp, {"subject": (item or {}).get("subject", "")})
        return True
    # unknown decision -> keep the item queued
    if item:
        PENDING.add(key, item.get("fingerprint", ""), item.get("pem", ""))
    return False


def insecure_client_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx
