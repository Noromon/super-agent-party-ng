"""S89：流内错误帧可见化——helper 单测 + server/xmpp 接线 pin。"""
import os
import pathlib
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("SAP_DATA_DIR", tempfile.mkdtemp(prefix="sap_s89_"))
_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.im_empty_guard import EMPTY_REPLY_MSG, empty_reply_msg, error_from_delta

ROOT = _ROOT


def test_error_from_delta_dict():
    assert error_from_delta({"tool_content": {"type": "error", "content": "boom"}}) == "boom"
    assert error_from_delta({"tool_content": {"type": "tool", "content": "x"}}) == ""
    assert error_from_delta({"tool_content": None}) == ""
    assert error_from_delta(None) == ""
    assert error_from_delta("plain-string-delta") == ""


def test_error_from_delta_obj_and_truncate():
    tc = SimpleNamespace(type="error", content="x" * 400, title=None)
    out = error_from_delta(SimpleNamespace(tool_content=tc))
    assert out.startswith("xxx")
    assert len(out) == 300


def test_error_from_delta_error_without_content_uses_title():
    assert error_from_delta({"tool_content": {"type": "error", "title": "❎ Error"}}) == "❎ Error"


def test_empty_reply_msg():
    assert empty_reply_msg("") == EMPTY_REPLY_MSG
    m = empty_reply_msg("Connection error")
    assert "Connection error" in m and "内部错误" in m


def _src(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_server_stream_error_logging_pin():
    sv = _src("server.py")
    assert "[StreamError]" in sv
    assert "exc_info=True" in sv
    assert 'logger.error(f"{request.messages}")' not in sv


def test_xmpp_wiring_pins():
    xm = _src("py/xmpp_client.py")
    assert "err_text = error_from_delta(delta)" in xm
    assert "empty_reply_msg(err_text)" in xm
    assert "_empty_reply_flags" in xm
    assert "EMPTY_REPLY_MSG" not in xm
