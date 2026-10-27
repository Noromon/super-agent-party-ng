# -*- coding: utf-8 -*-
"""S132 / R3: A13 WSL 沙箱引擎移植（上游 ad36b6cd + c427eee9）+ findAvailablePort 死码清理。

fork 适配记档：工具集=permission 版（对齐 local/ds，上游 mode 版不随迁）；
edit_file_string→edit_file_patch；send_process_input/goal 无 fork 对应不随迁；
chat.html 套件无 CLI pill 不加；WSL 卡片落 page_toolkit（上游 index 拆分产物）。
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

from py.cli_tool import LOCAL_TOOLS_REGISTRY, WSL_TOOLS_REGISTRY  # noqa: E402
from py.cli_tool import get_wsl_tools_for_permission  # noqa: E402


def _read(rel):
    return (_ROOT / rel).read_text(encoding="utf-8")


class TestWslToolsPermission:
    def test_plan_readonly(self):
        tools = get_wsl_tools_for_permission("plan")
        assert len(tools) == 7
        assert WSL_TOOLS_REGISTRY["bash_wsl"] not in tools

    def test_auto_approve_no_exec(self):
        tools = get_wsl_tools_for_permission("auto-approve")
        assert len(tools) == 10
        assert WSL_TOOLS_REGISTRY["bash_wsl"] not in tools

    def test_default_full_has_bash(self):
        tools = get_wsl_tools_for_permission("default")
        assert len(tools) == 15
        assert WSL_TOOLS_REGISTRY["bash_wsl"] in tools

    def test_registry_reuses_local_objects(self):
        assert WSL_TOOLS_REGISTRY["read_file_wsl"] is LOCAL_TOOLS_REGISTRY["read_file_local"]
        assert WSL_TOOLS_REGISTRY["edit_file_patch_wsl"] is LOCAL_TOOLS_REGISTRY["edit_file_patch_local"]
        assert WSL_TOOLS_REGISTRY["bash_wsl"]["function"]["name"] == "shell_tool_wsl"


class TestCliToolWsl:
    def setup_method(self):
        self.src = _read("py/cli_tool.py")

    def test_helpers_defined(self):
        for name in ("def _check_wsl_available", "def _windows_to_wsl_path",
                     "async def _ensure_bubblewrap_in_wsl", "async def shell_tool_wsl"):
            assert name in self.src, name

    def test_read_stream_utf16le(self):
        assert "utf-16-le" in self.src
        assert "\\x00" in self.src

    def test_windows_path_conversion(self):
        assert '/mnt/{drive}' in self.src


class TestServerWiring:
    def setup_method(self):
        self.src = _read("server.py")

    def test_hooks_registered_both_domains(self):
        assert self.src.count('"shell_tool_wsl": shell_tool_wsl,') >= 2

    def test_generator_specialcase_both_domains(self):
        assert self.src.count('("shell_tool_local", "docker_sandbox", "shell_tool_wsl")') >= 2

    def test_env_settings_wsl_branches(self):
        # plan 硬拦 + 审批门 + tools_change + cli_permission_mode_for(S153 起委托
        # py/path_scope.permission_mode_for) + stream = 5 处（跨文件合计）
        total = self.src.count('settings.get("wslSettings", {})')
        total += _read("py/path_scope.py").count('get("wslSettings", {})')
        assert total >= 5

    def test_toolkit_registered(self):
        assert '"get_wsl_tools_for_permission": get_wsl_tools_for_permission,' in self.src
        assert "get_wsl_tools_for_permission" in self.src.split("def _assemble_toolkit")[1][:2000]

    def test_engine_lists_include_wsl(self):
        assert self.src.count('engine in ["ds", "local", "wsl"]') == 2

    def test_wsl_system_context(self):
        assert 'elif engine == "wsl":' in self.src
        assert "Linux (WSL2) | Shell：bash" in self.src


class TestModeChangeAndAssembly:
    def test_mode_change_wsl_support(self):
        src = _read("py/mode_change.py")
        assert "wsl_permission_mode" in src
        assert 'valid_engines.append("wsl")' in src
        assert "wsl (WSL Sandbox - Windows only)" in src
        assert '"wsl": "WSL Sandbox"' in src

    def test_tool_assembly_wsl_branch(self):
        src = _read("py/tool_assembly.py")
        assert 'elif settings[\'CLISettings\'][\'engine\'] == \'wsl\':' in src
        assert 'tk["get_wsl_tools_for_permission"](_cli_mode)' in src


class TestFrontendPins:
    def test_dropdowns_windows_only(self):
        dash = _read("static/templates/page_dashboard.html")
        kit = _read("static/templates/page_toolkit.html")
        assert 'v-if="isWindows" :label="t(\'wslSandbox\')' in dash
        assert 'v-if="isWindows" :label="t(\'wslSandbox\')' in kit

    def test_toolkit_wsl_card(self):
        kit = _read("static/templates/page_toolkit.html")
        assert "v-show=\"CLISettings.engine === 'wsl'\"" in kit
        assert "wslSandboxNotice" in kit

    def test_pill_wsl_templates(self):
        for rel in ("static/templates/page_home.html", "static/templates/page_chat_main.html"):
            src = _read(rel)
            assert "v-else-if=\"CLISettings.engine === 'wsl'\"" in src, rel
            assert "wslSettings.permissionMode='plan'" in src, rel

    def test_state_schema_template(self):
        assert "['wslSettings', 'wslSettings']," in _read("static/js/settings_schema.js")
        assert "wslSettings: {" in _read("static/js/data/60_cards_options.js")
        assert '"wslSettings"' in _read("config/settings_template.json")

    def test_renderer_fallback(self):
        src = _read("static/js/renderer.js")
        assert "this.CLISettings.engine === 'wsl'" in src
        assert "this.CLISettings.engine = 'local'" in src

    def test_i18n_keys(self):
        for rel in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
            src = _read(rel)
            for key in ("'wslSandbox'", "'wslSandboxPermission'", "'wslSandboxNotice'"):
                assert key in src, (rel, key)


class TestDeadCodeGone:
    def test_find_available_port_removed(self):
        assert "findAvailablePort" not in _read("main.js")
