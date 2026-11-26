# -*- coding: utf-8 -*-
"""S327 UI 供给链自证与文案兜底钉。

背景：S324-S326 三轮"文案不显示"排查被"窗口到底加载了哪版前端"拖死。
本钉保证：①tf() 兜底存在且覆盖全部 S324 键；②相关模板已用 tf()；
③SW 缓存已升 v3 且启动即 update；④HTML 出口携带 __UI_BUILD 指纹。
"""
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_VM = _ROOT / "static" / "js" / "vue_methods.js"
_API = _ROOT / "static" / "templates" / "page_api-group.html"
_SYS = _ROOT / "static" / "templates" / "page_system.html"
_SW = _ROOT / "static" / "sw.js"
_INDEX = _ROOT / "static" / "index.html"

_KEYS = [
    "allowAiStartExtension", "allowAiStartExtensionTip", "permManageTitle",
    "permManageTip", "permToolsTitle", "permDirsTitle", "permNoItems",
    "permGrant", "permRevoke", "permToolDesc",
]
_SENS = [
    "shell_tool_local", "edit_file_tool", "edit_file_patch_tool",
    "edit_file_tool_local", "edit_file_patch_tool_local",
    "delete_file_tool_local", "docker_sandbox", "list_processes_tool",
    "get_process_logs_tool", "kill_process_tool", "docker_manage_ports_tool",
    "local_net_tool", "start_extension_node_tool_local",
]


def _tf_block():
    text = _VM.read_text(encoding="utf-8")
    i = text.index("window.__TF_FALLBACK")
    j = text.index("const md =")
    return text[i:j]


class TestTfFallback:
    def test_tf_method_defined(self):
        assert "tf(key) {" in _VM.read_text(encoding="utf-8")

    def test_fallback_covers_all_keys_both_langs(self):
        block = _tf_block()
        zh = block[block.index("'zh-CN'"):block.index("'en-US'")]
        en = block[block.index("'en-US'"):]
        for key in _KEYS:
            assert f"'{key}'" in zh, f"zh fallback missing {key}"
            assert f"'{key}'" in en, f"en fallback missing {key}"
        for tool in _SENS:
            assert f"'{tool}'" in zh and f"'{tool}'" in en, tool


class TestTemplatesUseTf:
    def test_api_group_no_raw_t_for_s324_keys(self):
        html = _API.read_text(encoding="utf-8")
        leftovers = re.findall(r"(?<!f)t\('(allowAi[A-Za-z]+)'", html)
        assert not leftovers, f"allowAi keys still on raw t(): {leftovers}"
        assert "tf('allowAiStartExtension')" in html
        assert "tf('allowAiStartExtensionTip')" in html

    def test_system_perm_all_tf(self):
        html = _SYS.read_text(encoding="utf-8")
        leftovers = re.findall(r"(?<!f)t\('(perm[A-Za-z]+)'", html)
        assert not leftovers, f"perm keys still on raw t(): {leftovers}"
        assert "tf('permManageTitle')" in html


class TestCacheBust:
    def test_sw_cache_v3(self):
        assert "sap-cache-v3" in _SW.read_text(encoding="utf-8")
        assert "sap-cache-v2" not in _SW.read_text(encoding="utf-8")

    def test_registration_update_on_boot(self):
        assert "registration.update()" in _INDEX.read_text(encoding="utf-8")


class TestUiBuildStamp:
    def test_injection_code_present(self):
        srv = (_ROOT / "server.py").read_text(encoding="utf-8")
        assert "_ui_build_stamp" in srv
        assert "window.__UI_BUILD=" in srv

    def test_probe_line_uses_ui_build(self):
        head = (_ROOT / "static" / "js" / "renderer.js").read_text(
            encoding="utf-8")[:500]
        assert "UI build=" in head and "__UI_BUILD" in head

    def test_stamp_format(self):
        import hashlib
        import os
        import time
        base = str(_ROOT / "static")
        h = hashlib.md5()
        latest, n = 0, 0
        for root, dirs, fs in os.walk(base):
            dirs[:] = [d for d in dirs if d not in ("libs",)]
            for f in fs:
                if not f.endswith((".js", ".html", ".css")):
                    continue
                fp = os.path.join(root, f)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                latest = max(latest, st.st_mtime_ns)
                h.update(os.path.relpath(fp, base).replace("\\", "/").encode())
                h.update(str(st.st_mtime_ns).encode())
                n += 1
        stamp = time.strftime("%Y%m%d-%H%M", time.gmtime(latest / 1e9))
        out = f"{stamp}-n{n}-{h.hexdigest()[:8]}"
        assert re.fullmatch(r"\d{8}-\d{4}-n\d{2,}-[0-9a-f]{8}", out), out

    def test_served_index_carries_stamp(self, sap):
        # 子进程实例（项目惯例：进程内 import server 会重跑模块体毒化
        # sys.modules，S300 禁区）
        import requests
        r = requests.get(f"{sap}/", timeout=15)
        assert r.status_code == 200, r.status_code
        assert "window.__UI_BUILD=" in r.text
