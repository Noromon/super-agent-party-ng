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

# 计划模式（只读）硬拦截集合：敏感工具 + 桌面控制执行类（S221）。
# S221 对齐 opencode：todo_write_tool(_local) 移出——plan 模式允许 todo 做计划可视化，
# 它是任务态呈现而非文件写入；screenshot/wait 只读无副作用不拦截。
# 声明层同集合隐藏（py/tool_assembly._plan_hide_blocked_tools），本集仍为 dispatch 兜底。
COMPUTER_USE_EXEC_TOOLS = frozenset({
    "mouse_move", "mouse_click", "mouse_double_click", "mouse_drag",
    "mouse_hold", "mouse_scroll", "copy_to_input_box",
    "keyboard_press", "keyboard_sequence", "keyboard_hotkey", "keyboard_hold",
})
PLAN_BLOCKED_TOOLS = frozenset(SENSITIVE_TOOLS) | COMPUTER_USE_EXEC_TOOLS | {
    "acpx_agent", "update_workspace_settings",
}
