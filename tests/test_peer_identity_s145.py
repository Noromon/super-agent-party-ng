# -*- coding: utf-8 -*-
"""S145：IM 对端身份名录钉桩（注入块/seen 登记/渠道接线/前后端全链）。"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _settings(roster=None, inject=True):
    return {"imPeerSettings": {"injectEnabled": inject, "roster": roster or {}}}


class TestIdentityBlock:
    def test_registered_peer_block(self):
        from py.peer_identity import build_peer_identity_block
        st = _settings({"xmpp": {
            "a@b.c": {"alias": "小美", "roleDesc": "姐姐", "approver": True, "notes": "只周末"},
            "d@e.f": {"alias": "老王", "approver": False},
        }})
        blk = build_peer_identity_block("xmpp", "a@b.c", st)
        assert "小美" in blk and "a@b.c" in blk and "姐姐" in blk
        assert "可批准工具调用" in blk and "只周末" in blk
        assert "老王=d@e.f" in blk  # 其他登记对端简表
        assert "未知对端" not in blk

    def test_unknown_peer_and_disable(self):
        from py.peer_identity import build_peer_identity_block
        blk = build_peer_identity_block("xmpp", "z@z.z", _settings({"xmpp": {"a@b.c": {"alias": "小美"}}}))
        assert "未知对端" in blk and "z@z.z" in blk and "小美" in blk
        assert build_peer_identity_block("xmpp", "z@z.z", _settings(inject=False)) == ""
        assert build_peer_identity_block("xmpp", None, _settings()) == ""

    def test_resolve_display(self):
        from py.peer_identity import display_name, resolve_entry
        st = _settings({"xmpp": {"a@b.c": {"alias": "小美"}}})
        assert resolve_entry("xmpp", "a@b.c", st)["alias"] == "小美"
        assert display_name("xmpp", "nope", st) == "nope"
        assert resolve_entry("xmpp", "nope", st) is None


class TestSeenRegistry:
    def test_record_flush_and_shape(self, tmp_path, monkeypatch):
        from py import peer_identity as pi
        f = tmp_path / "peers_seen.json"
        monkeypatch.setattr(pi, "PEERS_SEEN_FILE", str(f))
        monkeypatch.setattr(pi, "_seen", {})
        monkeypatch.setattr(pi, "_last_flush", 0.0)
        pi.record_seen("xmpp", "a@b.c")
        assert "xmpp" in pi.get_seen() and "a@b.c" in pi.get_seen()["xmpp"]
        assert f.exists()  # 首次 record 即越过节流间隔落盘
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["xmpp"]["a@b.c"]["last_seen"] > 0
        pi.record_seen("xmpp", "")  # 空 id 不登记
        assert "" not in data["xmpp"]


class TestWiringS145:
    def test_server_chain(self):
        s = _read("server.py")
        assert "peer_id: Optional[str] = None" in s
        assert "app.include_router(peers_router)" in s
        assert "from py.peer_identity import build_peer_identity_block" in s
        seg = s[s.find("# S145：对端名录——来源行升级"):][:700]
        assert seg and "resolve_entry" in seg and "record_seen" in seg
        assert "当前对端：" in seg and "build_peer_identity_block" in seg

    def test_router_route(self):
        from py.routers.peers import router
        assert any(getattr(r, "path", "") == "/api/peers-seen" for r in router.routes)

    def test_xmpp_passes_peer(self):
        assert '"peer_id": chat_jid' in _read("py", "xmpp_client.py")

    def test_frontend_chain_pins(self):
        assert "['imPeerSettings', 'imPeerSettings']," in _read("static", "js", "settings_schema.js")
        assert '"imPeerSettings"' in _read("config", "settings_template.json")
        assert "imPeerSettings: { injectEnabled: true, roster: {} }," in _read("static", "js", "data", "50_bots_translate.js")
        assert "{ id: 'im_peers', title: 'imPeerRoster'" in _read("static", "js", "data", "50_bots_translate.js")
        assert 'js/methods/47_peer_roster.js' in _read("static", "index.html")
        tpl = _read("static", "templates", "page_deploy-bot.html")
        assert "subMenu === 'im_peers'" in tpl and "imPeerSeenUnlisted()" in tpl
        m = _read("static", "js", "methods", "47_peer_roster.js")
        for fn in ("imPeerRows", "imPeerAdd", "imPeerRemove", "imPeerQuickAdd", "imPeerLoadSeen"):
            assert fn in m, fn

    def test_locales_parity(self):
        for f in ("zh-CN.js", "en-US.js"):
            s = _read("static", "js", "locales", f)
            for k in ("imPeerRoster", "imPeerInject", "imPeerApprover", "imPeerSeenHint", "slackBot"):
                assert f"'{k}'" in s, (f, k)
