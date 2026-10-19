# -*- coding: utf-8 -*-
"""M2 pins: file-path containment on uploads endpoints (X-6/X-7)."""
import requests

from test_token import tok


def H(sap):
    return {"X-SAP-Token": tok(sap)}


class TestPathFences:
    def test_legit_upload_then_read(self, sap):
        up = requests.post(f"{sap}/load_file",
                           files=[("files", ("t.txt", b"hello fence"))],
                           headers=H(sap), timeout=30)
        assert up.status_code == 200
        link = up.json()["fileLinks"][0]["path"]
        uniq = link.rsplit("/", 1)[-1]
        rd = requests.get(f"{sap}/get_file_content", params={"file_url": uniq},
                          headers=H(sap), timeout=30)
        assert rd.status_code == 200
        assert "hello fence" in rd.json().get("content", "")

    def test_absolute_path_read_rejected(self, sap):
        r = requests.get(f"{sap}/get_file_content",
                         params={"file_url": r"C:\Windows\win.ini"},
                         headers=H(sap), timeout=30)
        assert r.status_code == 403

    def test_traversal_read_rejected(self, sap):
        r = requests.get(f"{sap}/get_file_content",
                         params={"file_url": "../../../Windows/win.ini"},
                         headers=H(sap), timeout=30)
        assert r.status_code == 403

    def test_delete_file_traversal_rejected(self, sap):
        victim = sap.data_dir / "super_agent_party.db"
        assert victim.exists()
        r = requests.delete(f"{sap}/delete_file",
                            json={"fileName": "../super_agent_party.db"},
                            headers=H(sap), timeout=30)
        assert r.status_code == 403
        assert victim.exists(), "victim must survive rejected delete"

    def test_delete_files_traversal_reported(self, sap):
        victim = sap.data_dir / "super_agent_party.db"
        r = requests.delete(f"{sap}/delete_files",
                            json={"fileNames": ["../../" + str(sap.data_dir) + "/super_agent_party.db"]},
                            headers=H(sap), timeout=30)
        assert r.status_code == 200
        assert r.json().get("errors"), "escaped name must land in errors"
        assert victim.exists()

    def test_delete_workflow_traversal_rejected(self, sap):
        r = requests.delete(f"{sap}/delete_workflow/..%5c..%5cevil",
                            headers=H(sap), timeout=30)
        assert r.status_code == 403

    def test_load_file_json_arbitrary_path_rejected(self, sap):
        r = requests.post(f"{sap}/load_file",
                          json={"files": [{"path": r"C:\Windows\win.ini", "name": "x.txt"}]},
                          headers={**H(sap), "Content-Type": "application/json"},
                          timeout=30)
        assert r.status_code == 403
