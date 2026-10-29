# -*- coding: utf-8 -*-
"""S160: special-token neutralizer for persistence boundaries (eos-contamination firewall).

Context (see doc/quarantine/eos-contamination.md; if that directory is deleted, treat this
note as deleted with it): local chat models carry prior knowledge of their own turn-end
vocabulary entry. Whenever the *textual shape* of a control token (or the guard's escaped
near-spelling) is persisted in model output and later re-injected into prompts, the sampling
probability of that entry drifts upward - a self-reinforcing loop that ends in system-level
unavailability. Engineering break: keep the shape invisible in context (this module), keep the
token suppressed at sampling (apply_eos_guard), and stop generating new contaminated memories
(request-level quarantine handled upstream).

Self-denial rule: every pattern here is built at runtime from character codes. Nothing in this
file - and in no file touched for this topic - may ever spell the shape literally, because
source files are themselves read back into agent context.
"""
import logging

import re

_LT = chr(60)
_PB = chr(124)
_GT = chr(62)
# format characters a guard may splice into an escaped control tag
_ZW = "\u200b\u200c\u200d\ufeff"

_OPEN = _LT + _PB

# full control-tag shape, tolerant of up to 3 spliced format chars (the guard's escape convention)
_SHAPE = re.compile(
    re.escape(_LT) + "[" + _ZW + "]{0,3}" + re.escape(_PB)
    + "[^" + _LT + _GT + _PB + "\r\n]{1,48}?" + re.escape(_PB + _GT)
)

# bare token-name spellings kept verbatim inside escaped tags; word-boundary guarded so
# ordinary identifiers (e.g. an identifier ending in the same syllable) are not touched
_BARE_NAMES = (
    "im" + "_" + "end",
    "im" + "_" + "start",
    "im" + "_" + "sep",
    "end" + "oftext",
)
_BARE = re.compile(
    r"(?<![0-9A-Za-z_])(" + "|".join(re.escape(n) for n in _BARE_NAMES) + r")(?![0-9A-Za-z_])"
)

PLACEHOLDER = "\u3014\u5df2\u8131\u654f\u3015"  # opaque CJK bracket marker, zero token association

_STATS = {"total": 0, "by_store": {}}

# GUI master switch (潜龙勿用 panel): sanitization can be silenced for forensics without
# restarting the server. Sampling-side apply_eos_guard has its own independent config gate.
_SANITIZE_ENABLED = True


def set_sanitize_enabled(on):
    global _SANITIZE_ENABLED
    _SANITIZE_ENABLED = bool(on)


def is_sanitize_enabled():
    return _SANITIZE_ENABLED


def apply_setting(cfg):
    """Sync the sanitization switch from settings.eosGuard after load/hot-update (missing = on)."""
    if not isinstance(cfg, dict):
        set_sanitize_enabled(True)
    else:
        set_sanitize_enabled(bool(cfg.get("sanitize", True)))


def get_stats():
    return {"total": _STATS["total"], "by_store": dict(_STATS["by_store"])}


def reset_stats():
    _STATS["total"] = 0
    _STATS["by_store"].clear()


def _note_hits(store, n):
    _STATS["total"] += n
    key = store or "-"
    _STATS["by_store"][key] = _STATS["by_store"].get(key, 0) + n
    logging.getLogger("app").info(f"[eos-guard] neutralized store={key} hits={n}")


def detect(text):
    """Count control-tag shapes / bare names in text (read-only, no stats side effect)."""
    if not isinstance(text, str) or not text:
        return 0, 0
    if _PB not in text and not any(n in text for n in _BARE_NAMES):
        return 0, 0
    return len(_SHAPE.findall(text)), len(_BARE.findall(text))


def neutralize(text, store=""):
    """Replace control-tag shapes and bare token names with an opaque placeholder."""
    if not _SANITIZE_ENABLED:
        return text
    if not isinstance(text, str) or not text:
        return text
    if _PB not in text and not any(n in text for n in _BARE_NAMES):
        return text
    cleaned, n = _SHAPE.subn(PLACEHOLDER, text)
    cleaned, n2 = _BARE.subn(PLACEHOLDER, cleaned)
    if n or n2:
        _note_hits(store, n + n2)
    return cleaned


def neutralize_deep(obj, store=""):
    """Recursively neutralize strings inside message/dict/list blobs (returns new containers)."""
    if isinstance(obj, str):
        return neutralize(obj, store)
    if isinstance(obj, list):
        return [neutralize_deep(x, store) for x in obj]
    if isinstance(obj, tuple):
        return tuple(neutralize_deep(x, store) for x in obj)
    if isinstance(obj, dict):
        return {k: neutralize_deep(v, store) for k, v in obj.items()}
    return obj


# ---------------- L0a: sampling-side soft suppression (local engines only) ----------------

_LOOPBACK_HINTS = ("127.0.0.1", "localhost", "0.0.0.0", "[::1]", "::1")


def apply_eos_guard(params, settings, base_url=""):
    """Soft-suppress turn-end vocabulary entries via logit_bias on loopback reasoner calls.

    In-place on the outbound kwargs dict. No-ops unless eosGuard.enabled, the target is a
    loopback base_url (local engine that honors logit_bias), and the caller did not already
    set logit_bias (user config always wins). A finite negative bias keeps natural stopping
    possible while making context-drift alone insufficient to push the token into sampling.
    """
    cfg = (settings or {}).get("eosGuard") or {}
    if not cfg.get("enabled", False) or not isinstance(params, dict) or "logit_bias" in params:
        return params
    try:
        bias = float(cfg.get("softBias", -30))
    except (TypeError, ValueError):
        bias = -30.0
    if not (-100.0 <= bias < 0):
        return params
    raw_ids = cfg.get("eosTokenIds") or []
    ids = []
    for item in raw_ids:
        try:
            value = int(item)
        except (TypeError, ValueError):
            continue
        if value >= 0 and value not in ids:
            ids.append(value)
    if not ids:
        return params
    host = (base_url or "").lower()
    if not any(h in host for h in _LOOPBACK_HINTS):
        return params
    params["logit_bias"] = {str(i): bias for i in ids}
    logging.getLogger("app").info(
        f"[eos-guard] soft logit_bias={bias} ids={ids} attached to reasoner call")
    return params
