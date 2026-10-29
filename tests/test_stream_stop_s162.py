# -*- coding: utf-8 -*-
"""S162: IM /stop 真实停止生成（py/stream_stop.py）。

/stop 从「仅回执」升级为复用 Web 停止键同一端点（POST
/v1/streams/cancel/{stream_id}），服务端围栏与主会话界面停止键一致。
本文件全隔离：aiohttp.ClientSession 与 get_port 均 fake，零真实网络，
零用户数据（不触碰 SAP_DATA_DIR / MEMORY_CACHE_DIR / mem0）。
"""
import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py import stream_stop  # noqa: E402


class _Delta:
    def __init__(self, sid=None, extra=None):
        if sid is not None:
            self.stream_id = sid
        if extra is not None:
            self.model_extra = extra


class TestSniff:
    def test_attr_form(self):
        assert stream_stop.sniff_stream_id(_Delta(sid="s1")) == "s1"

    def test_model_extra_form(self):
        assert stream_stop.sniff_stream_id(_Delta(extra={"stream_id": "s2"})) == "s2"

    def test_dict_form_qq_style(self):
        assert stream_stop.sniff_stream_id({"stream_id": "s3", "content": "x"}) == "s3"

    def test_absent_returns_empty(self):
        assert stream_stop.sniff_stream_id(_Delta()) == ""
        assert stream_stop.sniff_stream_id({"content": "x"}) == ""
        assert stream_stop.sniff_stream_id(None) == ""


class TestLedger:
    def setup_method(self):
        self.led = stream_stop.StreamStopLedger()

    def test_track_and_overwrite_new_stream(self):
        self.led.track("xmpp", "a@b", _Delta(sid="s1"))
        assert self.led.get("xmpp", "a@b") == "s1"
        self.led.track("xmpp", "a@b", _Delta())  # 非首帧：不改动
        assert self.led.get("xmpp", "a@b") == "s1"
        self.led.track("xmpp", "a@b", _Delta(sid="s2"))  # 新流覆盖旧账
        assert self.led.get("xmpp", "a@b") == "s2"

    def test_platform_namespaces_isolated(self):
        self.led.track("xmpp", "u1", _Delta(sid="s1"))
        self.led.track("telegram", "u1", _Delta(sid="s2"))
        assert self.led.pop("xmpp", "u1") == "s1"
        assert self.led.get("telegram", "u1") == "s2"

    def test_empty_peer_ignored(self):
        self.led.track("xmpp", "", _Delta(sid="s1"))
        assert self.led._active == {}

    def test_clear_pops(self):
        self.led.track("xmpp", "u", _Delta(sid="s1"))
        self.led.clear("xmpp", "u")
        assert self.led.get("xmpp", "u") == ""


class _FakeResp:
    def __init__(self, status):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _install_fake_session(monkeypatch, captured, status=200, raise_exc=None):
    class _FakeSession:
        def __init__(self, **kwargs):
            pass

        def post(self, url):
            captured.append(url)
            if raise_exc is not None:
                raise raise_exc
            return _FakeResp(status)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(stream_stop.aiohttp, "ClientSession", _FakeSession)
    monkeypatch.setattr("py.get_setting.get_port", lambda: 59999)


class TestCancel:
    def test_no_ledger_returns_false_without_request(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured)
        led = stream_stop.StreamStopLedger()
        assert asyncio.run(led.cancel("xmpp", "ghost@x")) is False
        assert captured == []

    def test_success_pops_and_returns_true(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured, status=200)
        led = stream_stop.StreamStopLedger()
        led.track("xmpp", "u@x", _Delta(sid="sid-42"))
        assert asyncio.run(led.cancel("xmpp", "u@x")) is True
        assert captured == ["http://127.0.0.1:59999/v1/streams/cancel/sid-42"]
        assert led.get("xmpp", "u@x") == ""

    def test_stale_404_false_but_cleaned(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured, status=404)
        led = stream_stop.StreamStopLedger()
        led.track("xmpp", "u@x", _Delta(sid="stale"))
        assert asyncio.run(led.cancel("xmpp", "u@x")) is False
        assert led.get("xmpp", "u@x") == ""

    def test_exception_false_but_cleaned(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured, raise_exc=OSError("boom"))
        led = stream_stop.StreamStopLedger()
        led.track("telegram", "77", _Delta(sid="s9"))
        assert asyncio.run(led.cancel("telegram", "77")) is False
        assert led.get("telegram", "77") == ""


class TestHandleImStop:
    def _patch(self, monkeypatch, pending, led):
        from py import approval_im
        calls = []

        async def fake_cancel_pending(platform, peer):
            calls.append((platform, peer))
            if isinstance(pending, Exception):
                raise pending
            return pending

        monkeypatch.setattr(approval_im, "cancel_pending", fake_cancel_pending)
        monkeypatch.setattr(stream_stop, "registry", led)
        return calls

    def test_both_actions_zh(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured)
        led = stream_stop.StreamStopLedger()
        led.track("xmpp", "u@x", _Delta(sid="s1"))
        self._patch(monkeypatch, 2, led)
        msg = asyncio.run(stream_stop.handle_im_stop("xmpp", "u@x"))
        assert msg.startswith("已停止当前输出")
        assert "已停止正在进行的生成" in msg
        assert "已作废 2 个待审批" in msg
        assert captured and captured[0].endswith("/v1/streams/cancel/s1")

    def test_noop_keeps_legacy_text(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured)
        self._patch(monkeypatch, 0, stream_stop.StreamStopLedger())
        from py import shortcut_commands
        msg = asyncio.run(stream_stop.handle_im_stop("xmpp", "ghost@x"))
        assert msg == shortcut_commands.STOP_MSG_ZH

    def test_en_variant(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured)
        led = stream_stop.StreamStopLedger()
        led.track("slack", "C1", _Delta(sid="s1"))
        self._patch(monkeypatch, 1, led)
        from py import shortcut_commands
        msg = asyncio.run(stream_stop.handle_im_stop("slack", "C1", "en"))
        assert msg.startswith(shortcut_commands.STOP_MSG_EN)
        assert "Stopped ongoing generation." in msg
        assert "Discarded 1 pending approval(s)." in msg

    def test_pending_exception_swallowed(self, monkeypatch):
        captured = []
        _install_fake_session(monkeypatch, captured)
        self._patch(monkeypatch, RuntimeError("db down"), stream_stop.StreamStopLedger())
        from py import shortcut_commands
        msg = asyncio.run(stream_stop.handle_im_stop("xmpp", "ghost@x"))
        assert msg == shortcut_commands.STOP_MSG_ZH


PLATFORMS = {
    "xmpp_client.py": '"xmpp"',
    "telegram_client.py": '"telegram"',
    "feishu_bot_manager.py": '"feishu"',
    "wechat_bot_manager.py": '"wechat"',
    "dingtalk_bot_manager.py": '"dingtalk"',
    "qq_bot_manager.py": '"qq"',
    "wecom_bot_manager.py": '"wecom"',
    "discord_bot_manager.py": '"discord"',
    "slack_bot_manager.py": '"slack"',
}


class TestWiring:
    """9 平台接线静态钉桩：track（流循环记账）+ clear（流终清账）+
    handle_im_stop（/stop 真实处置），杜绝回退为仅回执。"""

    def test_all_platforms_wired(self):
        for fname, plat in PLATFORMS.items():
            src = (_ROOT / "py" / fname).read_text(encoding="utf-8")
            assert f"stream_stop.registry.track({plat}" in src, fname
            assert "stream_stop.registry.clear(" in src, fname
            assert f"stream_stop.handle_im_stop({plat}" in src, fname

    def test_stop_branch_no_longer_ack_only(self):
        # 任何平台的 stop 分支不得再把 STOP_MSG 直接作为回执发出
        for fname in PLATFORMS:
            src = (_ROOT / "py" / fname).read_text(encoding="utf-8")
            assert "STOP_MSG_ZH)" not in src and "STOP_MSG_EN)" not in src, fname
