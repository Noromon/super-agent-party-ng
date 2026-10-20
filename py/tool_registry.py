# -*- coding: utf-8 -*-
"""E-1：工具元数据单一事实源（首片=权限清单；终态=ToolSpec(handler, schema,
permission, mode_mask) 注册表，dispatch/提示词/权限三处由本模块生成）。

新增敏感/受限工具时只改本文件；server.dispatch_tool 与一切权限判定从此导入。
"""

# 需要执行前权限检查（审批/permissionMode）的敏感工具
SENSITIVE_TOOLS = [
    "docker_sandbox",
    "edit_file_tool",
    "edit_file_patch_tool",
    "shell_tool_local",
    "edit_file_tool_local",
    "edit_file_patch_tool_local",
    "list_processes_tool",
    "get_process_logs_tool",
    "kill_process_tool",
    "docker_manage_ports_tool",
    "local_net_tool",
]

# 计划模式（只读）硬拦截集合：敏感工具 + 显式追加的写/执行类工具
PLAN_BLOCKED_TOOLS = frozenset(SENSITIVE_TOOLS) | {
    "todo_write_tool", "todo_write_tool_local", "acpx_agent", "update_workspace_settings",
}
