# -*- coding: utf-8 -*-
"""S182：区内 yolo（区内 fs 全免含新建）+ 区外哨兵审批双推协议 + 日志分线 + 后台节流误报防护。"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

SENT = '{"__sap_approval_v1__":1,'


def _ps():
    import py.path_scope as ps
    return ps


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _settings(cwd, mode="default"):
    return {"CLISettings": {"cc_path": str(cwd), "engine": "local", "enabled": True},
            "localEnvSettings": {"permissionMode": mode}}


@pytest.fixture
def ws(tmp_path):
    ps = _ps()
    w = tmp_path / "ws"
    w.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    (out / "secret.txt").write_text("outside", encoding="utf-8")
    ps.clear_grants()
    yield w, out
    ps.clear_grants()


class TestIntraZoneYoloS182:
    def test_new_file_inside_workspace_gate_free(self, ws):
        ps = _ps()
        w, _ = ws
        # 区内新建（路径尚不存在）：免门、无 [参数错误]、无哨兵——区内外壳由工具层处理
        assert ps.evaluate("edit_file_tool_local", {"path": "lab/core.py"}, _settings(w)) is None
        assert ps.evaluate("edit_file_patch_tool_local",
                           {"path": "lab/deep/new/mod.py"}, _settings(w)) is None
        assert ps.evaluate("list_files_tool_local", {"path": "lab"}, _settings(w)) is None

    def test_outside_missing_still_clear_error(self, ws):
        ps = _ps()
        w, out = ws
        d = ps.evaluate("edit_file_tool_local",
                        {"path": str(out / "nope" / "x.py")}, _settings(w))
        assert d is not None and d.error and "本地文件/目录不存在" in d.error
        assert d.payload is None

    def test_read_family_boundary_unchanged(self, ws):
        # T1 重排只免 fs 家族；读取族（图像/文件直读）区内仍需审批（S153 决策保持）
        ps = _ps()
        w, _ = ws
        d = ps.evaluate("secondhand_describe_image", {"image_url": str(w / "p.png")}, _settings(w))
        assert d is not None and d.error and "不存在" in d.error
        (w / "p.png").write_bytes(b"\x89PNG\r\n\x1a\nx")
        d = ps.evaluate("secondhand_describe_image", {"image_url": str(w / "p.png")}, _settings(w))
        assert d.payload.startswith(SENT)


class TestOutsideSentinelPipelineS182:
    def test_pathscope_sentinel_recognized_by_approval_hook(self, ws):
        # T3：区外真哨兵与 _approval_payload 同协议 → 流内 _is_approval_result
        # 命中即断轮，进入 approval_store 双推（会话渠道 + 通知中心）
        from py.tool_dispatch import _is_approval_result
        ps = _ps()
        w, out = ws
        d = ps.evaluate("read_file_tool_local",
                        {"path": str(out / "secret.txt")}, _settings(w))
        assert d.payload.startswith(SENT)
        obj = _is_approval_result(d.payload)
        assert obj is not None and obj.get("scope") == "local-path"
        assert obj.get("tool_name") == "read_file_tool_local"

    def test_double_push_wiring_present(self):
        s = _read("server.py") + _read("py", "complete_engine.py")  # S303：complete 引擎域迁出，合并面守恒（体逐字未动）
        store = _read("py", "approval_store.py")
        assert "if _is_approval_result(results) is not None:" in s
        assert "pending_abort = True" in s
        assert "_NOTIFY.get(platform)" in store
        assert 'notification_center.emit("approval"' in store


class TestLogLineSplitS182:
    def test_server_log_lines(self):
        # S301：dispatch 路径门随工具域迁 py/tool_hooks.py，日志分线钉随迁（段逐字未动）
        s = _read("py", "tool_hooks.py")
        a = s.find("# S182(T4) 日志分线")
        seg = s[a:s.find("if _ps.grants:", a)]
        assert a > 0 and "if _ps.payload is not None:" in seg
        assert "审批哨兵已回注模型" in seg and "非审批、无批复等待" in seg
        # 误导性静态文案已死（S172 版与更早版本都不许复活）
        assert "进入批复等待（Web 审批卡" not in s
        assert "等待用户路径授权" not in s


class TestStarveFalsePositiveGuardS182:
    def test_renderer_heartbeat_visibility_aware(self):
        js = _read("static", "js", "renderer.js")
        a = js.find("S182(P1): 后台节流误报修复")
        seg = js[a:js.find("capture-channels electron=", a)]
        assert a > 0 and seg
        assert "document.hidden" in seg
        assert "[TimerThrottle]" in seg
        assert "visibilitychange" in seg
        assert "600000" in seg  # P2：抓取冷却 10 分钟

    def test_main_profile_rolling_prune(self):
        mj = _read("main.js")
        a = mj.find("S182(P2)")
        seg = mj[a:mj.find("冻结 CPU 采样已开始", a)]
        assert a > 0 and seg
        assert "Math.max(0, names.length - 20)" in seg
