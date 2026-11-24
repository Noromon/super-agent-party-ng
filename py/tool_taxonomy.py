# -*- coding: utf-8 -*-
"""S204 工具类别学（单一事实源）：工具名 → 能力类别。

能力索引/指引块按类别门控渲染：只有本轮声明集与类别相交时，该类别才在提示词
宇宙中「存在」。名字未匹配任何显式条目时走关键词规则，仍不中则归 other（有索引
无指引）。动态族（MCP/HA/浏览器扩展等运行时注册）依赖关键词与前后缀规则覆盖。
"""
from __future__ import annotations

from typing import Dict, List

OTHER = "other"

# 类别 -> (prompt 展示名, 显式成员)。显式成员须与注册表同步；测试钉注册表全覆盖。
_CATEGORIES: Dict[str, tuple] = {
    "file_read": ("file reading", {
        "read_file_tool", "read_file_tool_local", "read_file_range_tool",
        "read_file_range_tool_local", "list_files_tool", "list_files_tool_local",
        "glob_files_tool", "glob_files_tool_local", "search_files_tool",
        "search_files_tool_local", "tail_file_tool", "tail_file_tool_local",
        "get_file_content", "read_skill_tool", "read_skill_tool_local",
    }),
    "file_edit": ("file editing", {
        "edit_file_patch_tool", "edit_file_patch_tool_local", "edit_file_patch_wsl",
    }),
    "file_write": ("file writing", {
        "edit_file_tool", "edit_file_tool_local", "edit_file_wsl", "delete_file_tool_local",
    }),
    "shell_exec": ("shell & process", {
        "shell_tool_local", "shell_tool_wsl", "docker_sandbox", "list_processes_tool",
        "get_process_logs_tool", "kill_process_tool", "docker_manage_ports_tool",
        "local_net_tool",
    }),
    "web_search": ("web search & fetch", {
        "DDGsearch", "searxng", "bochaai_search", "Tavily_search", "Google_search",
        "Brave_search", "Exa_search", "Serper_search", "jina_crawler",
        "Crawl4Ai_search", "firecrawl_search", "simple_fetch", "markdown_new",
        "search_arxiv_papers",
    }),
    "browse": ("browser control", {
        "list_pages", "new_page", "close_page", "select_page", "navigate_page",
        "take_snapshot", "click", "fill", "evaluate_script", "take_screenshot",
        "hover", "press_key", "wait_for", "fill_form", "drag", "handle_dialog",
        "get_image_content",
    }),
    "info_query": ("live-world info", {
        "time", "get_weather", "get_weather_by_city", "get_location_coordinates",
        "get_wikipedia_summary_and_sections", "get_wikipedia_section_content",
    }),
    "knowledge_diary": ("knowledge & diary recall", {
        "query_diary", "list_diary_books", "query_knowledge_base",
    }),
    "todo_plan": ("todo & planning", {
        "todo_write_tool", "todo_write_tool_local",
    }),
    "ask_user": ("asking the user", {
        "ask_user_question_tool",
    }),
    "orchestration": ("subtasks & agents", {
        "create_subtask", "query_task_progress", "acpx_agent", "run_sub_agent",
    }),
    "media_analysis": ("media analysis", {
        "secondhand_describe_image", "secondhand_describe_images",
        "secondhand_review_image", "view_images",
    }),
    "settings_admin": ("workspace settings", {
        "update_workspace_settings",
    }),
}

# 关键词规则（大小写不敏感，命中子串即归类；顺序即优先级）。覆盖动态注册族。
_RULES: List[tuple] = [
    ("ask_user", ("ask_user",)),
    ("todo_plan", ("todo_write",)),
    ("orchestration", ("subtask", "sub_agent", "acpx", "task_progress")),
    ("file_edit", ("edit_file_patch", "patch_file", "apply_diff")),
    ("file_write", ("edit_file", "write_file", "save_file")),
    ("file_read", ("read_file", "list_files", "glob_files", "search_files",
                   "tail_file", "read_skill", "get_file_content")),
    ("shell_exec", ("shell", "docker", "process", "kill_process")),
    ("browse", ("browser", "_page", "take_snapshot", "screenshot", "cdp")),
    ("web_search", ("search", "crawl", "fetch", "crawler")),
    ("media_analysis", ("secondhand", "analyze_image", "review_image", "vision")),
    ("media_gen", ("text2img", "img2img", "generate_image", "paint", "tts",
                   "music", "comfy")),
    ("knowledge_diary", ("diary", "knowledge_base", "memory", "knowbase")),
    ("info_query", ("weather", "wikipedia", "arxiv", "location")),
    ("settings_admin", ("workspace_settings", "secret")),
]

_CATEGORY_LABELS = {k: v[0] for k, v in _CATEGORIES.items()}
# 渲染顺序（稳定，可测）：核心工作流在前，杂项在后。
CATEGORY_ORDER = [
    "file_read", "file_edit", "file_write", "shell_exec", "web_search", "browse",
    "info_query", "knowledge_diary", "todo_plan", "ask_user", "orchestration",
    "media_analysis", "media_gen", "settings_admin", "external", OTHER,
]


def classify(name: str) -> str:
    """工具名 -> 类别 id。未匹配归 other。"""
    if not name:
        return OTHER
    if "__" in name or name.lower().startswith(("mcp_", "chrome_mcp", "ha_")):
        return "external"
    low = name.lower()
    for cat, members in _CATEGORIES.items():
        if name in members[1]:
            return cat
    for cat, keys in _RULES:
        if any(k in low for k in keys):
            return cat
    return OTHER


def label(category: str) -> str:
    return _CATEGORY_LABELS.get(category, "external & misc" if category in ("external", OTHER) else category)


def group(declared: List[str]) -> Dict[str, List[str]]:
    """声明集 -> {类别: [去重后的名字...]}，按 CATEGORY_ORDER 稳定排序。"""
    buckets: Dict[str, List[str]] = {}
    for n in declared or []:
        if not n:
            continue
        buckets.setdefault(classify(n), [])
        if n not in buckets[classify(n)]:
            buckets[classify(n)].append(n)
    return {c: buckets[c] for c in CATEGORY_ORDER if c in buckets}
