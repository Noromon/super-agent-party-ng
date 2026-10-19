# -*- coding: utf-8 -*-
"""M5 TOFU pins: fingerprinting, trust store lifecycle, once-trust,
allow-list matching, decision routing, ssl_cert enforcement (fail-closed),
per-request aiohttp ssl selection.
"""
import base64
import hashlib
import ssl

import pytest

from test_xmpp_channel import make_client  # same package-mode bootstrapping
from py import xmpp_trust
from py.xmpp_trust import (OnceTrust, PendingReviews, TrustStore,
                           fingerprint_pem, host_allowed)

DER = bytes(range(64))
PEM = ("-----BEGIN CERTIFICATE-----\n"
       + base64.b64encode(DER).decode()
       + "\n-----END CERTIFICATE-----\n")
FP = "sha256:" + hashlib.sha256(DER).hexdigest()
DER2 = bytes(range(64, 128))
PEM2 = ("-----BEGIN CERTIFICATE-----\n"
        + base64.b64encode(DER2).decode()
        + "\n-----END CERTIFICATE-----\n")
FP2 = "sha256:" + hashlib.sha256(DER2).hexdigest()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Every test gets a throwaway store and clean singletons."""
    monkeypatch.setattr(xmpp_trust, "STORE", TrustStore(tmp_path / "xmpp_trust.json"))
    xmpp_trust.ONCE.clear()
    xmpp_trust.PENDING.clear()
    yield
    xmpp_trust.ONCE.clear()
    xmpp_trust.PENDING.clear()


class FakeXmpp:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


def make_tls_client():
    c = make_client()
    c._tls_key = "xmpp.local:5222"
    c.ignore_cert_hosts = []
    fx = FakeXmpp()
    c.xmpp = fx
    return c, fx


class TestFingerprint:
    def test_sha256_over_der(self):
        assert fingerprint_pem(PEM) == FP
        assert FP != FP2

    def test_display_info_survives_fake_pem(self):
        info = xmpp_trust.cert_display_info(PEM)
        assert "subject" in info  # garbage pem -> best-effort, never raises


class TestTrustStore:
    def test_lifecycle_unknown_match_changed(self, tmp_path):
        st = TrustStore(tmp_path / "t.json")
        assert st.check("h:5222", FP) == "unknown"
        st.trust("h:5222", FP, {"subject": "CN=x"})
        assert st.check("h:5222", FP) == "match"
        assert st.check("h:5222", FP2) == "changed"   # cert rotated -> re-review
        st2 = TrustStore(tmp_path / "t.json")          # persistence
        assert st2.check("h:5222", FP) == "match"
        assert st2.knows_host("h") is True
        assert st2.knows_host("other") is False


class TestOnceAndAllowList:
    def test_once_lifecycle(self):
        o = OnceTrust()
        assert not o.is_granted("k")
        o.grant("k")
        assert o.is_granted("k")
        o.clear()
        assert not o.is_granted("k")

    def test_host_allowed_forms(self):
        assert host_allowed("xmpp.local", ["xmpp.local"])
        assert host_allowed("xmpp.local", ["xmpp.local:5223"])
        assert host_allowed("xmpp.local", ["wss://xmpp.local/ws"])
        assert not host_allowed("evil.local", ["xmpp.local"])
        assert not host_allowed("xmpp.local", [])


class TestDecisionRouting:
    def test_once(self):
        xmpp_trust.PENDING.add("k:1", FP, PEM)
        assert xmpp_trust.decide("k:1", "once") is True
        assert xmpp_trust.ONCE.is_granted("k:1")
        assert xmpp_trust.PENDING.list() == []

    def test_always_persists(self):
        xmpp_trust.PENDING.add("k:2", FP, PEM)
        assert xmpp_trust.decide("k:2", "always") is True
        assert xmpp_trust.get_store().check("k:2", FP) == "match"

    def test_reject_clears_without_grant(self):
        xmpp_trust.PENDING.add("k:3", FP, PEM)
        assert xmpp_trust.decide("k:3", "reject") is True
        assert not xmpp_trust.ONCE.is_granted("k:3")
        assert xmpp_trust.PENDING.list() == []

    def test_unknown_decision_requeues(self):
        xmpp_trust.PENDING.add("k:4", FP, PEM)
        assert xmpp_trust.decide("k:4", "maybe") is False
        assert len(xmpp_trust.PENDING.list()) == 1


class TestSslCertEnforcement:
    def test_unknown_cert_disconnects_and_queues(self):
        c, fx = make_tls_client()
        c._on_ssl_cert(PEM)
        assert fx.disconnected is True
        assert [p["key"] for p in xmpp_trust.PENDING.list()] == ["xmpp.local:5222"]

    def test_trusted_fingerprint_passes(self):
        c, fx = make_tls_client()
        xmpp_trust.get_store().trust("xmpp.local:5222", FP)
        c._on_ssl_cert(PEM)
        assert fx.disconnected is False

    def test_changed_fingerprint_requeued(self):
        c, fx = make_tls_client()
        xmpp_trust.get_store().trust("xmpp.local:5222", FP)
        c._on_ssl_cert(PEM2)
        assert fx.disconnected is True
        assert xmpp_trust.PENDING.list()[0]["fingerprint"] == FP2

    def test_once_grant_covers_reconnect(self):
        c, fx = make_tls_client()
        xmpp_trust.ONCE.grant("xmpp.local:5222")
        c._on_ssl_cert(PEM)   # unknown cert but granted for this bot run
        assert fx.disconnected is False

    def test_allow_list_bypasses(self):
        c, fx = make_tls_client()
        c.ignore_cert_hosts = ["xmpp.local"]
        c._on_ssl_cert(PEM)
        assert fx.disconnected is False
        assert xmpp_trust.PENDING.list() == []

    def test_garbage_pem_fails_closed(self):
        c, fx = make_tls_client()
        c._on_ssl_cert("not a pem at all")
        assert fx.disconnected is True


class TestAioSslSelection:
    def test_whitelisted_and_known_hosts_skip_verification(self):
        c, _ = make_tls_client()
        assert c._aio_ssl("https://other.local/upload") is True
        c.ignore_cert_hosts = ["files.local"]
        ctx = c._aio_ssl("https://files.local:8443/upload")
        assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_NONE
        xmpp_trust.get_store().trust("xmpp.local:5222", FP)
        assert isinstance(c._aio_ssl("https://xmpp.local/upload"), ssl.SSLContext)

    def test_insecure_context_shape(self):
        ctx = xmpp_trust.insecure_client_context()
        assert ctx.verify_mode == ssl.CERT_NONE and ctx.check_hostname is False
