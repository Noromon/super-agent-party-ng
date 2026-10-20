# -*- coding: utf-8 -*-
"""M-6 pins: 默认端口/地址单一事实源——server.py 与 node_runner 内魔法数清零，
compose 不再分发明文默认凭据（必填变量语法）。"""
import importlib.util
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_defaults():
    spec = importlib.util.spec_from_file_location(
        "sap_defaults", os.path.join(ROOT, "py", "defaults.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class TestSingleSource:
    def test_constant_values_unchanged(self):
        d = _load_defaults()
        assert d.DEFAULT_SERVER_PORT == 3456
        assert d.FUNASR_WS_URL == "ws://localhost:10095"
        assert d.GSV_TTS_URL == "http://127.0.0.1:9880"
        assert d.NODE_EXT_PORT_RANGE == (3100, 13999)

    def test_server_py_has_no_magic_fallbacks(self):
        src = _read("server.py")
        assert "ws://localhost:10095" not in src
        assert "http://127.0.0.1:9880" not in src
        assert 'default=DEFAULT_SERVER_PORT' in src

    def test_node_runner_delegates_range(self):
        src = _read("py", "node_runner.py")
        assert "(3100, 13999)" not in src
        assert "PORT_RANGE = NODE_EXT_PORT_RANGE" in src


class TestComposeHardening:
    def test_no_plaintext_default_credentials(self):
        text = _read("docker-compose.yml")
        assert "JWT_SECRET=ChangeThis" not in text
        assert "INIT_USER=root" not in text
        assert not re.search(r"INIT_PASS=pass\s*$", text, re.M)

    def test_credentials_are_required_vars(self):
        text = _read("docker-compose.yml")
        for var in ("JWT_SECRET", "INIT_USER", "INIT_PASS"):
            assert f"{var}=${{{var}:?" in text, f"{var} must use required-var syntax"
