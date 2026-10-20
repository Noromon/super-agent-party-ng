# -*- coding: utf-8 -*-
"""Media router migration contract (R1, audit 09 item 6).

The TTS/ASR endpoints moved from server.py to py/routers/media.py; these
checks prove the routes stayed registered on the same paths with the same
validation/guard semantics, without touching external TTS/ASR services.
All calls carry the session token so 401 auth failures can never masquerade
as guard hits.
"""
import io

import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestMediaRouterContract:
    def test_status_endpoints_alive(self, sap):
        r = requests.get(f"{sap}/tts/status", timeout=10, headers=_h(sap))
        assert r.status_code == 200
        body = r.json()
        for key in ("vrm_connections", "overlay_connections", "main_connections"):
            assert key in body

    def test_routes_registered_not_404(self, sap):
        # wrong payloads must reach the handler (validation/guard errors),
        # proving the route exists; a lost route would give 404
        r = requests.post(f"{sap}/asr", timeout=10, headers=_h(sap))
        assert r.status_code == 422                          # no audio file
        r = requests.post(f"{sap}/tts", json={}, timeout=15, headers=_h(sap))
        assert r.status_code != 404                          # no engine/text
        r = requests.post(f"{sap}/tts/tetos/list_voices", json={},
                          timeout=15, headers=_h(sap))
        assert r.status_code != 404

    def test_system_voices_ok(self, sap):
        r = requests.get(f"{sap}/system/voices", timeout=30, headers=_h(sap))
        assert r.status_code == 200

    def test_gsv_upload_rejects_bad_extension(self, sap):
        r = requests.post(f"{sap}/upload_gsv_ref_audio",
                          files={"file": ("evil.exe", io.BytesIO(b"MZ"),
                                          "application/octet-stream")},
                          timeout=15, headers=_h(sap))
        assert r.status_code >= 400          # extension guard must fire
        assert r.status_code < 500

    def test_delete_audio_traversal_guard(self, sap):
        r = requests.delete(f"{sap}/delete_audio/%2e%2e%5c%2e%2e%5cserver.py",
                            timeout=10, headers=_h(sap))
        assert r.status_code >= 400          # traversal guard must fire
        assert r.status_code < 500
