# -*- coding: utf-8 -*-
"""M4c (X-12): at-rest protection for secrets inside the settings blob.

Windows DPAPI (CryptProtectData, current-user scope + app entropy) wraps any
string field whose name ends in key/token/secret/password with a `dpapi:`
prefix before it reaches SQLite; load_settings unwraps it back to plaintext,
so the ~100 consumers and the web UI keep seeing plain values.

Rule-based on purpose: new config fields inherit protection automatically.
Callers' dicts are never mutated (deep copies in, new dicts out).
Non-Windows or DPAPI failure: values pass through untouched (logged).
"""
import base64
import copy
import ctypes
import ctypes.wintypes as wt
import logging
import re
import sys

PREFIX = "dpapi:"
_APP_ENTROPY = b"super-agent-party-v1"
_SECRET_NAME = re.compile(r"(key|token|secret|pass(word)?)$", re.I)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _crypt32():
    return ctypes.windll.crypt32


def _keep(buf):  # noqa: ARG001 - keeps buffer alive across the native call
    return buf


def protect(text: str):
    """Encrypt str -> base64 ciphertext. Returns None when unavailable."""
    if sys.platform != "win32":
        return None
    try:
        raw_in = text.encode("utf-8")
        data = _keep(ctypes.create_string_buffer(raw_in, len(raw_in)))
        blob_in = _DataBlob(len(raw_in), ctypes.cast(data, ctypes.POINTER(ctypes.c_char)))
        ent = _APP_ENTROPY
        data_e = _keep(ctypes.create_string_buffer(ent, len(ent)))
        blob_e = _DataBlob(len(ent), ctypes.cast(data_e, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DataBlob()
        fn = _crypt32().CryptProtectData
        fn.argtypes = [ctypes.POINTER(_DataBlob), ctypes.c_wchar_p,
                       ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                       ctypes.POINTER(_DataBlob), ctypes.c_uint32,
                       ctypes.POINTER(_DataBlob)]
        fn.restype = wt.BOOL
        if not fn(ctypes.byref(blob_in), "sap", ctypes.byref(blob_e), None, None, 0, ctypes.byref(blob_out)):
            return None
        raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.GlobalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
        return base64.b64encode(raw).decode("ascii")
    except Exception:
        logging.getLogger(__name__).warning("DPAPI protect failed", exc_info=True)
        return None


def unprotect(b64: str):
    """Reverse of protect(). Returns None when unavailable/corrupt."""
    if sys.platform != "win32":
        return None
    try:
        raw = base64.b64decode(b64)
        blob_in = _DataBlob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)), ctypes.POINTER(ctypes.c_char)))
        ent = _APP_ENTROPY
        data_e = _keep(ctypes.create_string_buffer(ent, len(ent)))
        blob_e = _DataBlob(len(ent), ctypes.cast(data_e, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DataBlob()
        fn = _crypt32().CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
                       ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                       ctypes.POINTER(_DataBlob), ctypes.c_uint32,
                       ctypes.POINTER(_DataBlob)]
        fn.restype = wt.BOOL
        if not fn(ctypes.byref(blob_in), None, ctypes.byref(blob_e), None, None, 0, ctypes.byref(blob_out)):
            return None
        plain = ctypes.string_at(blob_out.pbData, blob_out.cbData).decode("utf-8")
        ctypes.windll.kernel32.GlobalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
        return plain
    except Exception:
        logging.getLogger(__name__).warning("DPAPI unprotect failed", exc_info=True)
        return None


def _walk(obj, fn_value):
    if isinstance(obj, dict):
        return {k: fn_value(k, _walk(v, fn_value)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v, fn_value) for v in obj]
    return obj


def encrypt_settings(settings: dict) -> dict:
    """Copy with secret-named string fields wrapped as dpapi:<b64>."""
    def enc(k, v):
        if isinstance(v, str) and v and _SECRET_NAME.search(k) and not v.startswith(PREFIX):
            wrapped = protect(v)
            if wrapped is not None:
                return PREFIX + wrapped
        return v
    try:
        return _walk(copy.deepcopy(settings), enc)
    except Exception:
        logging.getLogger(__name__).warning("encrypt_settings walk failed; saving as-is", exc_info=True)
        return settings


def decrypt_settings(settings: dict) -> dict:
    """Copy with dpapi:-prefixed values unwrapped; failures pass through."""
    def dec(k, v):  # noqa: ARG001 - prefix, not name, is the unwrap criterion
        if isinstance(v, str) and v.startswith(PREFIX):
            plain = unprotect(v[len(PREFIX):])
            if plain is None:
                logging.getLogger(__name__).warning("field %r undecryptable (kept ciphertext)", k)
                return v
            return plain
        return v
    try:
        return _walk(copy.deepcopy(settings), dec)
    except Exception:
        logging.getLogger(__name__).warning("decrypt_settings walk failed", exc_info=True)
        return settings
