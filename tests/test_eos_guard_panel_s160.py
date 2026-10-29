# -*- coding: utf-8 -*-
"""S160 潜龙勿用面板：两段式确认流（scan→apply / plan→restore）、净化总开关、接线钉。

同 topic 卫生规则：本文件不得字面拼出控制形状，全部 chr() 运行时构造。
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ["EOS_MEM0_DB"] = ""  # 测试绝不触碰真实 ~/.mem0
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from fastapi import HTTPException  # noqa: E402

from py import eos_patrol  # noqa: E402
from py import token_guard as tg  # noqa: E402

_S = chr(60) + chr(124)
_E = chr(124) + chr(62)
_ZW = "\u200b"
_NAME = "im" + "_" + "end"
_DIRTY = "x " + _S + _NAME + _E + " y " + chr(60) + _ZW + _NAME + _E + " z " + _NAME + " tail"


def _make_data(tmp):
    con = sqlite3.connect(os.path.join(tmp, "conversations.db"))
    con.execute("CREATE TABLE settings (id INTEGER PRIMARY KEY, data TEXT)")
    con.execute("INSERT INTO settings VALUES (1, ?)", (_DIRTY,))
    con.commit()
    con.close()
    os.makedirs(os.path.join(tmp, "diary"), exist_ok=True)
    import json as _json
    with open(os.path.join(tmp, "diary", "default.json"), "w", encoding="utf-8") as f:
        _json.dump({"entries": [{"title": "t", "content": _DIRTY}]}, f)


class TestSanitizeSwitch:
    def teardown_method(self):
        tg.apply_setting(None)  # 缺省=开

    def test_off_short_circuits(self):
        tg.apply_setting({"sanitize": False})
        assert not tg.is_sanitize_enabled()
        assert tg.neutralize(_DIRTY) == _DIRTY
        assert tg.detect(_DIRTY)[0] >= 1  # 巡检不受开关影响

    def test_on_and_default(self):
        tg.apply_setting({"sanitize": True})
        assert tg.neutralize(_DIRTY) != _DIRTY
        tg.apply_setting(None)
        assert tg.is_sanitize_enabled()


class TestPanelFlow:
    def setup_method(self):
        self._old = os.environ.get("SAP_DATA_DIR")
        self.tmp = tempfile.mkdtemp(prefix="sap_eos_panel_")
        os.environ["SAP_DATA_DIR"] = self.tmp
        _make_data(self.tmp)
        from py.routers import eos_guard
        eos_guard._pending_scan.clear()
        eos_guard._pending_restore.clear()

    def teardown_method(self):
        if self._old is None:
            os.environ.pop("SAP_DATA_DIR", None)
        else:
            os.environ["SAP_DATA_DIR"] = self._old

    def test_scan_apply_restore_flow(self):
        from py.routers import eos_guard as ep

        scan = asyncio.run(ep.eos_guard_scan())
        assert scan["report"]["total"] > 0
        token = scan["confirm_token"]

        try:
            asyncio.run(ep.eos_guard_apply({"confirm_token": "bogus"}))
            raise AssertionError("stale token must be refused")
        except HTTPException as e:
            assert e.status_code == 400

        out = asyncio.run(ep.eos_guard_apply({"confirm_token": token}))
        assert out["result"].get("records", 0) >= 1
        assert eos_patrol.scan(self.tmp)["total"] == 0

        # 一次性 token：复用必须拒绝
        try:
            asyncio.run(ep.eos_guard_apply({"confirm_token": token}))
            raise AssertionError("token must be one-shot")
        except HTTPException as e:
            assert e.status_code == 400

        ts = out["result"]["ts"]
        plan = asyncio.run(ep.eos_guard_restore_plan({"backup_ts": ts}))
        assert plan["plan"]["total_rows"] >= 1
        r = asyncio.run(ep.eos_guard_restore({"confirm_token": plan["confirm_token"]}))
        assert r["result"]["rows_restored"] >= 1
        assert eos_patrol.scan(self.tmp)["total"] > 0  # 灌回后污染回来（后悔药语义）

    def test_restore_unknown_ts(self):
        from py.routers import eos_guard as ep
        try:
            asyncio.run(ep.eos_guard_restore_plan({"backup_ts": "no-such-ts"}))
            raise AssertionError("unknown ts must 404")
        except HTTPException as e:
            assert e.status_code == 404

    def test_drift_requires_reconfirm(self, monkeypatch):
        from py.routers import eos_guard as ep
        scan = asyncio.run(ep.eos_guard_scan())
        token = scan["confirm_token"]
        real_scan = eos_patrol.scan

        def fake_scan(data_dir=None, extras=()):
            rep = real_scan(data_dir, extras)
            rep["stores"]["injected:probe"] = [99, 0]
            rep["total"] += 99
            return rep
        monkeypatch.setattr(eos_patrol, "scan", fake_scan)
        try:
            asyncio.run(ep.eos_guard_apply({"confirm_token": token}))
            raise AssertionError("drifted data must require re-confirm")
        except HTTPException as e:
            assert e.status_code == 409


class TestWiringPins:
    def _src(self, *rel):
        return ROOT.joinpath(*rel).read_text(encoding="utf-8")

    def test_router_and_registration(self):
        r = self._src("py", "routers", "eos_guard.py")
        for needle in ("confirm_token", "compare_digest", "status_code=409", "restore/plan"):
            assert needle in r, needle
        srv = self._src("server.py")
        assert "eos_guard_router" in srv
        assert srv.count("from py.token_guard import apply_setting as _tg_apply_setting") == 1
        gs = self._src("py", "get_setting.py")
        assert "_sync_eos_guard" in gs  # 启动/加载路径的 sanitize 同步

    def test_frontend_wiring(self):
        assert "['eosGuard', 'eosGuardSettings']" in self._src("static", "js", "settings_schema.js")
        idx = self._src("static", "index.html")
        assert "js/data/96_eos_guard.js" in idx and "js/methods/96_eos_guard.js" in idx
        page = self._src("static", "templates", "page_system.html")
        for needle in ("eosGuardScan", "eosGuardApply", "eosGuardRestore", "eosGuardSettings.sanitize"):
            assert needle in page, needle
        assert "eosGuardInit" in self._src("static", "js", "methods", "88_extensions.js")
        for loc in ("zh-CN", "en-US"):
            assert "eosGuardTitle" in self._src("static", "js", "locales", f"{loc}.js")

    def test_help_tooltips_and_grouping(self):
        page = self._src("static", "templates", "page_system.html")
        assert page.count("fa-circle-question") == 6
        assert "el-tooltip" not in page  # S111 popper 链红线：只用纯 CSS 悬浮
        assert page.count('class="eos-help-pop"') == 6
        for needle in ("eosHelpTitle", "eosHelpSanitize", "eosHelpBias",
                       "eosHelpPatrol", "eosHelpReport", "eosHelpBackups",
                       "eosRowKind", "eosReportOnlyCount", "showReportOnly"):
            assert needle in page, needle
        css = self._src("static", "css", "styles.css")
        assert ".eos-help-icon" in css and ".eos-help-pop" in css
        m = self._src("static", "js", "methods", "96_eos_guard.js")
        assert "eosRowKind(k)" in m and "eosReportOnlyCount()" in m
        assert "showReportOnly: false" in self._src("static", "js", "data", "96_eos_guard.js")
        for loc in ("zh-CN.js", "en-US.js"):
            src = self._src("static", "js", "locales", loc)
            for key in ("eosHelpTitle", "eosHelpSanitize", "eosHelpBias",
                        "eosHelpPatrol", "eosHelpReport", "eosHelpBackups",
                        "eosKind_live", "eosKind_snapshot", "eosKind_report",
                        "eosGuardShowReportOnly", "eosGuardHideReportOnly"):
                assert f"'{key}'" in src, (loc, key)

    def test_topic_files_stay_clean(self):
        for rel in [("py", "eos_patrol.py"), ("py", "routers", "eos_guard.py"),
                    ("py", "token_guard.py"), "server.py",
                    ("scripts", "scrub_special_tokens.py"),
                    ("tests", "test_eos_guard_panel_s160.py"),
                    ("static", "js", "data", "96_eos_guard.js"),
                    ("static", "js", "methods", "96_eos_guard.js"),
                    ("static", "js", "methods", "88_extensions.js"),
                    ("static", "templates", "page_system.html"),
                    ("static", "index.html"),
                    ("static", "js", "locales", "zh-CN.js"),
                    ("static", "js", "locales", "en-US.js"),
                    ("static", "css", "styles.css"),
                    ("doc", "quarantine", "eos-contamination.md")]:
            p = ROOT.joinpath(*(rel if isinstance(rel, tuple) else (rel,)))
            if not p.exists() and rel[0] == "doc":
                continue  # 话题笔记目录设计上可整体删除（eos_patrol/token_guard 契约），缺省=通过
            src = p.read_text(encoding="utf-8")
            s, n = tg.detect(src)
            assert s == 0 and n == 0, f"literal shape/name found in {rel}"
