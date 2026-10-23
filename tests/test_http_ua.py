"""S88：全局 HTTP User-Agent 配置——helper 矩阵 + DDG 引擎注入 + 接线 pin。"""
import os
import pathlib
import sys
import tempfile

os.environ.setdefault("SAP_DATA_DIR", tempfile.mkdtemp(prefix="sap_s88_"))
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import pytest

from py.proxy_util import http_ua

ROOT = _ROOT


def test_ua_empty_keeps_default():
    assert http_ua({}, "D") == "D"
    assert http_ua(None, "D") == "D"
    assert http_ua({"systemSettings": {}}, "D") == "D"
    assert http_ua({"systemSettings": {"httpUserAgent": "   "}}, "D") == "D"
    assert http_ua({"systemSettings": {"httpUserAgent": None}}, "D") == "D"


def test_ua_override_and_strip():
    s = {"systemSettings": {"httpUserAgent": "  MyUA/1.0  "}}
    assert http_ua(s, "D") == "MyUA/1.0"


def test_ua_garbage_settings_never_raises():
    assert http_ua({"systemSettings": "not-a-dict"}, "D") == "D"
    assert http_ua("junk", "") == ""


def test_ddg_ua_injection_real_lib():
    pytest.importorskip("ddgs")
    from ddgs.engines import ENGINES
    from py.web_search import _apply_ddg_ua

    engines = dict(ENGINES.get("text", {}))
    assert engines, "ddgs 无 text 引擎，注入前提不成立"
    before = {k: dict(v.headers_update or {}) for k, v in engines.items()}
    try:
        assert _apply_ddg_ua({}) is False
        for k, v in engines.items():
            assert (v.headers_update or {}) == before[k]
        assert _apply_ddg_ua({"systemSettings": {"httpUserAgent": "ProbeUA/9"}}) is True
        for v in engines.values():
            assert v.headers_update.get("User-Agent") == "ProbeUA/9"
    finally:
        for k, v in engines.items():
            v.headers_update = before[k]


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_wiring_pins():
    ws = _src("py/web_search.py")
    assert ws.count("http_ua(") >= 5
    assert "_apply_ddg_ua(settings)" in ws

    lf = _src("py/load_files.py")
    assert "http_ua(_s, USER_AGENT)" in lf
    assert "http_ua(await load_settings(), USER_AGENT)" in lf
    assert "can_fetch(_ua, url)" in lf

    lt = _src("py/llm_tool.py")
    assert "_img_ua = _http_ua(_st, USER_AGENT)" in lt
    assert "{'User-Agent': _img_ua}" in lt

    tpl = _src("static/templates/page_system.html")
    assert 'v-model="systemSettings.httpUserAgent"' in tpl
    assert "uaPlaceholder" in tpl
    assert "@change=\"autoSaveSettings\"" in tpl

    for loc in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        s = _src(loc)
        assert "'httpUserAgent'" in s
        assert "'uaPlaceholder'" in s
        assert "'uaNotice'" in s
