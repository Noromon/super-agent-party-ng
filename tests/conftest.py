# -*- coding: utf-8 -*-
"""Shared fixtures: scripted mock LLM + isolated SAP instance (SAP_DATA_DIR)."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# S72 hardening: pin the isolated data dir at collection time, before any
# test module imports py.get_setting — an accidental `pytest` run without
# the SAP_DATA_DIR env var must never write into the production data dir.
os.environ.setdefault("SAP_DATA_DIR",
                      tempfile.mkdtemp(prefix="sap_test_conftest_"))

import pytest
import requests

from mock_llm import MockLLM

REPO = Path(__file__).resolve().parents[1]
TEMPLATE = REPO / "config" / "settings_template.json"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(scope="session")
def mock_llm():
    m = MockLLM()
    yield m
    m.stop()


def _seed_db(data_dir: Path, mock: MockLLM, project_dir: Path):
    settings = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    settings.update({
        "base_url": mock.base_url,
        "api_key": "mock-key",
        "selectedProvider": "mock-provider",
        "modelProviders": [{"id": "mock-provider", "vendor": "OpenAI", "name": "mock"}],
        "model": "",
        "agents": {},
    })
    settings["fast"]["enabled"] = False
    settings["reasoner"]["enabled"] = False
    settings["memorySettings"]["selectedMemory"] = None
    settings["memorySettings"]["is_memory"] = False
    settings["llmGuardSettings"]["enabled"] = False
    settings["CLISettings"].update({"enabled": True, "engine": "local",
                                    "cc_path": str(project_dir)})
    settings["localEnvSettings"].update({"enabled": True, "permissionMode": "default"})
    settings["contextManagement"].update({"contextWindow": 32000})
    con = sqlite3.connect(data_dir / "super_agent_party.db")
    con.execute("CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY, data TEXT NOT NULL)")
    con.execute("INSERT OR REPLACE INTO settings (id, data) VALUES (1, ?)",
                (json.dumps(settings, ensure_ascii=False),))
    con.commit()
    con.close()


class SapUrl(str):
    """Instance base URL with attached data dir (str-compatible for f-strings)."""
    data_dir = None


@pytest.fixture(scope="session")
def sap(tmp_path_factory, mock_llm):
    root = tmp_path_factory.mktemp("sap-data")
    data_dir = root / "data"
    project_dir = root / "project"
    data_dir.mkdir()
    project_dir.mkdir()
    _seed_db(data_dir, mock_llm, project_dir)

    port = free_port()
    env = {**os.environ,
           "SAP_DATA_DIR": str(data_dir),
           "PYTHONUNBUFFERED": "1",
           "PYTHONIOENCODING": "utf-8",
           "HTTP_PROXY": "", "HTTPS_PROXY": "", "ALL_PROXY": "",
           "http_proxy": "", "https_proxy": "", "all_proxy": ""}
    out = open(root / "server.out", "wb")
    err = open(root / "server.err", "wb")
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(port)],
        cwd=str(REPO), env=env, stdout=out, stderr=err)
    base = SapUrl(f"http://127.0.0.1:{port}")
    base.data_dir = data_dir
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            if requests.get(f"{base}/health", timeout=2).status_code == 200:
                break
        except Exception:
            if proc.poll() is not None:
                raise RuntimeError(f"server died at startup; see {root}/server.err")
            time.sleep(1)
    else:
        proc.kill()
        raise RuntimeError(f"server not healthy in 90s; see {root}/server.err")

    yield base

    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                       capture_output=True)
    else:
        proc.terminate()
    proc.wait(timeout=30)
    out.close()
    err.close()
