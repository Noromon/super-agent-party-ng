# -*- coding: utf-8 -*-
"""Files router migration contract (R1, audit 09 item 6).

File management + visual asset endpoints moved from server.py to
py/routers/files.py. All calls hit the sandboxed test instance (SAP_DATA_DIR
isolates uploads), so uploads/guards run for real without touching user data.
"""
import io

import requests

from test_token import tok


def _h(sap):
    return {"X-SAP-Token": tok(sap)}


class TestFilesRouterContract:
    def test_asset_libraries_answer(self, sap):
        for path in ("/get_default_vrm_models", "/get_default_vrma_motions",
                     "/get_default_gauss_scenes", "/get_user_vrma_motions",
                     "/get_user_gauss_scenes"):
            r = requests.get(f"{sap}{path}", timeout=20, headers=_h(sap))
            assert r.status_code == 200, f"{path} -> {r.status_code}"
            if path.startswith("/get_user_"):
                # regression pin for the scan_motion_files(allowed_ext) fix
                assert r.json().get("success") is True, path

    def test_delete_guards_for_missing_files(self, sap):
        for path in ("/delete_vrm_model/nope.vrm", "/delete_vrma_motion/nope.vrma",
                     "/delete_gauss_scene/nope.zip"):
            r = requests.delete(f"{sap}{path}", timeout=15, headers=_h(sap))
            assert r.status_code < 500, f"{path} -> {r.status_code}"
            assert not (r.status_code == 404 and r.json().get("detail") == "Not Found")

    def test_upload_extension_guards(self, sap):
        for path in ("/upload_vrm_model", "/upload_vrma_motion", "/upload_gauss_scene"):
            r = requests.post(f"{sap}{path}",
                              files={"file": ("evil.exe", io.BytesIO(b"MZ"),
                                              "application/octet-stream")},
                              timeout=15, headers=_h(sap))
            assert 400 <= r.status_code < 500, f"{path} -> {r.status_code}"

    def test_file_read_guards(self, sap):
        r = requests.get(f"{sap}/get_file_content",
                         params={"file_url": "../../etc/passwd"},
                         timeout=10, headers=_h(sap))
        assert r.status_code == 403            # path_under guard must fire
        # load_file works for real: a small txt upload lands in the sandbox
        r = requests.post(f"{sap}/load_file",
                          files=[("files", ("t.txt", io.BytesIO(b"hello"),
                                            "text/plain"))],
                          timeout=15, headers=_h(sap))
        assert r.status_code == 200
