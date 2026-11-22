# -*- coding: utf-8 -*-
"""S300：提示词/上下文装配域（自 server.py 逐字搬移）。

todos/AGENTS.md/项目技能/工作区记忆/权限模式/TTS 音色/头像/THA/好感度/A2UI/
旁观屏幕上下文/任务 checkpoint——全部为「向 messages 追加或前置系统块」的装配器。
_append_a2ui_prompt 读 settings 全局，经包装惰性取 server 真源（rebind 语义不变）。
"""
import asyncio
import json
import logging
import os
import platform
from pathlib import Path

import aiofiles

from py.get_setting import SKILLS_DIR
from py.msg_utils import content_append, content_prepend
from py.token_guard import neutralize as _neutralize

logger = logging.getLogger("app")


def _srv_settings():
    """S300：settings 全局真源在 server（lifespan rebind），惰性读保持语义。"""
    from py.srv_ref import srv as _srv
    return _srv().settings


async def read_todos_local(cwd: str) -> list:
    """读取本地待办事项（跨平台）"""
    todo_file = Path(cwd) / ".agent" / "ai_todos.json"
    if not todo_file.exists():
        return []
    
    try:
        async with aiofiles.open(todo_file, 'r', encoding='utf-8') as f:
            content = await f.read()
            return json.loads(content) if content else []
    except (json.JSONDecodeError, FileNotFoundError):
        return []
    except Exception as e:
        logging.getLogger("app").info(f"Error reading todos: {e}")
        return []

async def read_agents_md(cwd: str) -> str:  # 返回str而不是list
    """读取本地AGENTS.md文件内容"""
    agents_md_path = Path(cwd) / ".agent" / "AGENTS.md"
    
    if not agents_md_path.exists():
        return ""
    
    try:
        async with aiofiles.open(agents_md_path, 'r', encoding='utf-8') as f:
            content = await f.read()
            return content
    except FileNotFoundError:
        # 文件在检查后又被删除的情况
        return ""
    except Exception as e:
        logging.getLogger("app").info(f"Error reading AGENTS.md: {e}")
        return ""

def get_system_context(cwd: str = None) -> str:
    """
    获取当前系统环境的详细描述，帮助 AI 适配正确的命令和路径格式
    """
    system = platform.system()
    release = platform.release()
    
    # 检测 shell
    if system == "Windows":
        # 检测是 PowerShell 还是 CMD
        shell = "PowerShell" if "PSMODULEPATH" in os.environ else "CMD"
        path_hint = "使用 Windows 路径格式（C:\\Users\\name\\file），命令使用 dir、copy、del 等"
        command_hint = f"当前使用 {shell}，命令语法为 Windows 风格。避免使用 Unix 命令（ls/cat/rm），改用 dir/type/del"
    elif system == "Darwin":
        shell = os.path.basename(os.environ.get('SHELL', '/bin/zsh'))
        path_hint = "使用 Unix 路径格式（/Users/name/file），区分大小写"
        command_hint = f"当前为 macOS ({release})，使用 {shell}。支持标准 Unix 命令（ls/cat/rm），但注意部分命令是 BSD 版本而非 GNU 版本"
    else:  # Linux
        shell = os.path.basename(os.environ.get('SHELL', '/bin/bash'))
        path_hint = "使用 Unix 路径格式（/home/name/file），区分大小写"
        command_hint = f"当前为 Linux ({release})，使用 {shell}。支持标准 GNU 命令和工具链"
    
    cwd_line = ""
    if cwd:
        cwd_line = f"\n7. 当前工作目录：{cwd} —— 所有相对路径（文件与命令）均相对此目录解析；工具调用尽量使用相对路径\n"

    return f"""【环境信息】操作系统：{system} {release} | Shell：{shell}

⚠️ 重要提示：
1. {path_hint}
2. {command_hint}
3. 执行 shell_tool_local 时，命令必须符合当前系统的语法规范
4. 路径分隔符：Windows 使用反斜杠(\\)，Unix 使用正斜杠(/)
5. 如果需要使用网络端口，请尽可能选择不常用的端口，避免冲突，例如：10000 以上的端口
6. 请尽量使用相对路径，避免使用绝对路径，以免在跨平台时出现问题{cwd_line}"""

async def get_project_skills_summary(cwd: str, visibility_scope: str = "workspace") -> str:
    """
    根据可见范围返回项目技能摘要
    
    Args:
        cwd: 当前工作目录
        visibility_scope: 可见范围，可选值: "global", "workspace", "none"
    
    Returns:
        技能摘要字符串
    """
    # 如果可见范围设置为 "none"，直接返回空字符串
    if visibility_scope == "none":
        return ""
    
    # 根据可见范围选择不同的技能目录
    if visibility_scope == "workspace":
        # 工作区技能：从项目目录的 .agent/skills 查找
        skills_root = Path(cwd) / ".agent" / "skills"
        scope_name = "工作区"
    elif visibility_scope == "global":
        # 全局技能：从常量 SKILLS_DIR 查找
        skills_root = Path(SKILLS_DIR)
        scope_name = "全局"
    else:
        # 未知范围，返回空
        return ""
    
    # 检查技能目录是否存在
    if not skills_root.exists() or not skills_root.is_dir():
        return ""

    found_skills_blocks = []
    for skill_dir in sorted(skills_root.iterdir()):
        if skill_dir.is_dir():
            skill_id = skill_dir.name
            doc_file_path = None
            for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                if (skill_dir / name).exists():
                    doc_file_path = skill_dir / name
                    break
            
            yaml_meta = ""
            if doc_file_path:
                try:
                    content = doc_file_path.read_text(encoding='utf-8')
                    if content.startswith("---"):
                        parts = content.split("---", 2)
                        if len(parts) >= 3: 
                            yaml_meta = parts[1].strip()
                except Exception:
                    pass

            skill_info = f"- **{skill_id}**"
            if yaml_meta:
                skill_info += f":\n```yaml\n{yaml_meta}\n```"
            else:
                skill_info += " (可用)"
            found_skills_blocks.append(skill_info)

    if not found_skills_blocks:
        return ""

    # 根据可见范围返回不同的摘要信息
    summary = f"\n\n🛠️ **{scope_name}技能 ({scope_name} Skills)**：\n"
    
    if visibility_scope == "workspace":
        summary += "检测到本项目特有的 Agent 技能定义。这些技能仅在本工作区内可见：\n\n"
    elif visibility_scope == "global":
        summary += "检测到全局 Agent 技能定义。这些技能在所有项目中都可用：\n\n"
    
    summary += "\n".join(found_skills_blocks)
    summary += "\n\n*提示：你可以通过读取skill的工具获取该技能文件夹的文件树和完整说明文档。*"
    
    return summary

async def _inject_workspace_memory(request, cwd, cli_settings):
    """CLI workspace: MEMORY.md injection + '#'/'/' shortcut handling. (M-3 split)"""
    # ==================== [新增] 1. 总是注入 MEMORY.md ====================
    memory_file = Path(cwd) / ".agent" / "MEMORY.md"
    if memory_file.exists() and memory_file.is_file():
        try:
            import aiofiles
            async with aiofiles.open(memory_file, 'r', encoding='utf-8') as mf:
                mem_content = await mf.read()
            if mem_content.strip():
                content_append(request.messages, 'system', f"\n\n**MEMORY.md**:\n{mem_content}\n\n")
        except Exception as e:
            logging.getLogger("app").info(f"读取 MEMORY.md 失败: {e}")

    # ==================== [新增] 2. 处理 Shortcut 快捷指令 ====================
    # A11：总开关=系统设置全局 enableShortcuts（上游 3e58049f），fork 保留 CLI shortcut 子开关做与门
    from py.shortcut_commands import im_shortcuts_enabled as _im_shortcuts_enabled
    if cli_settings.get("shortcut", False) and await _im_shortcuts_enabled():
        # 获取最新一条用户消息
        user_text = ""
        if request.messages and request.messages[-1]['role'] == 'user':
            user_msg_content = request.messages[-1].get('content', '')
            if isinstance(user_msg_content, str):
                user_text = user_msg_content
            elif isinstance(user_msg_content, list):
                # 兼容图文混合消息
                user_text = "".join([item.get('text', '') for item in user_msg_content if item.get('type') == 'text'])

        user_text_trimmed = user_text.strip()
            
        if user_text_trimmed:
            import datetime
            import re
                
            # --- (1) 处理 '#' : 直接保存为记忆 ---
            if user_text_trimmed.startswith('#'):
                mem_content_to_save = user_text_trimmed[1:].strip()
                if mem_content_to_save:
                    try:
                        agent_dir = Path(cwd) / ".agent"
                        agent_dir.mkdir(parents=True, exist_ok=True)
                            
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        append_text = f"\n- [{timestamp}] {mem_content_to_save}"
                            
                        import aiofiles
                        async with aiofiles.open(memory_file, 'a', encoding='utf-8') as mf:
                            await mf.write(append_text)
                                
                        content_append(request.messages, 'system', f"\n\nHint: The user has just saved the following content to the workspace memory using the '#' shortcut command:\n'{mem_content_to_save}'\nPlease briefly confirm in your next reply that you remember this information.\n\n")
                    except Exception as e:
                        logging.getLogger("app").info(f"保存 MEMORY.md 失败: {e}")

def _resolve_skill_dir(cwd, skill_name, workspace_active):
    """S209：/<skill> 查找顺序——工作区（仅 workspace_active=CLI 开且有 cwd）→ 全局。

    返回技能目录 Path 或 None。CLI 关=无工作区，只看全局。
    """
    if workspace_active and cwd:
        ws = Path(cwd) / ".agent" / "skills" / skill_name
        if ws.exists() and ws.is_dir():
            return ws
    gl = Path(SKILLS_DIR) / skill_name
    if gl.exists() and gl.is_dir():
        return gl
    return None

async def _inject_triggered_skill(request, cwd, cli_settings):
    """S209：/<skill> 触发注入——只认 shortcut 双开关（A11），与 CLI.enabled 解绑。

    CLI 开：工作区→全局回退；CLI 关（=无工作区）：仅全局。纯知识注入零副作用。
    """
    from py.shortcut_commands import im_shortcuts_enabled as _im_shortcuts_enabled
    if not (cli_settings.get("shortcut", False) and await _im_shortcuts_enabled()):
        return
    user_text = ""
    if request.messages and request.messages[-1]['role'] == 'user':
        user_msg_content = request.messages[-1].get('content', '')
        if isinstance(user_msg_content, str):
            user_text = user_msg_content
        elif isinstance(user_msg_content, list):
            user_text = "".join([item.get('text', '') for item in user_msg_content
                                 if item.get('type') == 'text'])
    user_text_trimmed = user_text.strip()
    if not user_text_trimmed.startswith('/'):
        return
    parts = user_text_trimmed[1:].split()
    if not parts:
        return
    skill_name = parts[0]
    workspace_active = bool(cwd and Path(cwd).exists() and cli_settings.get("enabled", False))
    skill_dir = _resolve_skill_dir(cwd, skill_name, workspace_active)
    if not skill_dir:
        return
    doc_file_path = None
    for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
        if (skill_dir / name).exists():
            doc_file_path = skill_dir / name
            break
    if not doc_file_path:
        return
    try:
        import aiofiles
        async with aiofiles.open(doc_file_path, 'r', encoding='utf-8') as f:
            skill_content = await f.read()
        content_append(request.messages, 'system',
                       f"\n\n🛠️ **The user actively triggered the skill. [{skill_name}]**:\n\n"
                       f"{skill_content}\n\nPlease strictly follow the above skill instructions "
                       f"to handle the user's current request.\n\n")
    except Exception as e:
        logging.getLogger("app").info(f"读取技能文档失败: {e}")

def _append_permission_mode_message(request, permissionMode):
    """Permission-mode contract message. (M-3 split)"""
    permission_message = ""
    # 权限模式提示：描述必须与实际工具可见性和强制行为一致
    if permissionMode == "yolo":
        permission_message = "你当前处于最高权限（YOLO）模式：所有工具都会直接执行，不会请求用户批准。请谨慎操作，能使用更安全的专用工具时不要直接跑 bash 命令。"
        content_append(request.messages, 'system', permission_message)
    elif permissionMode == "auto-approve":
        permission_message = "你当前处于接受编辑（Auto-approve）模式：文件编辑类工具会直接执行；shell 命令与进程/端口管理工具在本模式下不可用，请勿尝试。"
        content_append(request.messages, 'system', permission_message)
    elif permissionMode != "plan" and permissionMode != "cowork":
        permission_message = "你当前处于默认（每次确认）模式：只读工具直接执行；文件写入与命令执行类工具在执行前会请求用户批准。请优先使用只读/专用工具，避免无谓的审批打扰。"
        content_append(request.messages, 'system', permission_message)
    elif permissionMode == "cowork":
        if not request.is_sub_agent:
            permission_message += "你当前处于协作模式，create_subtask工具可以帮你完成几乎任何任务（比如查资料、写代码、生成报告等），当你遇到难题时，可以尝试把它分解成一个个小任务，交给create_subtask工具去完成！当用户再次询问进度时，你可以用query_task_progress工具查询任务进度和获取详细结果\n\n"
            content_append(request.messages, 'system', permission_message)
            if request.is_app_bot and request.platform:
                task_platform_message = f"\n\n使用create_subtask工具时请将platforms参数设置为[{request.platform}]，从而将子任务的结果及时发给用户。\n\n"
                content_append(request.messages, 'system', task_platform_message)
        else:
            permission_message = "你当前处于执行模式，你可以自由地使用所有工具，但请注意不要滥用权限！如果有更安全的工具，请不要直接使用bash命令！"
            content_append(request.messages, 'system', permission_message)
    else:
        permission_message = "你当前处于计划模式：只有只读工具可用，写入与执行类工具已被禁用（调用会被直接拦截）。请使用只读工具了解项目，用自然语言描述你的需求和计划，并等待用户确认后再执行！"
        content_append(request.messages, 'system', permission_message)

async def _append_todos_context(request, cwd):
    """ai_todos.json open-items digest. (M-3 split)"""
    todos = []
        
    try:
        todos = await read_todos_local(cwd)
            
        # 处理待办事项（原有逻辑）
        if isinstance(todos, list) and len(todos) > 0:
            priority_icons = {"high": "🔴", "medium": "🟡", "low": "🟢"}
            status_icons = {
                "pending": "⏳", 
                "in_progress": "🔄", 
                "done": "✅", 
                "cancelled": "❌"
            }
                
            priority_order = {"high": 0, "medium": 1, "low": 2}
            todos_sorted = sorted(
                todos, 
                key=lambda x: (
                    priority_order.get(x.get('priority', 'medium'), 1),
                    x.get('created_at', '')
                )
            )
                
            todo_lines = ["\n\n当你完成一个事项后，请记得使用todo_write_tool更新项目待办事项，所有事项结束后，可以删除本事项文件\n\n📋 **当前项目待办事项**（.agent/ai_todos.json）：\n"]
            pending_count = 0
                
            for todo in todos_sorted:
                status = todo.get('status', 'pending')
                if status != 'done':
                    pending_count += 1
                    icon = status_icons.get(status, "⏳")
                    priority = priority_icons.get(todo.get('priority', 'medium'), "🟡")
                    content_text = todo.get('content', '无内容')[:50]
                    if len(todo.get('content', '')) > 50:
                        content_text += "..."
                        
                    todo_lines.append(f"{icon} {priority} [{todo.get('id', 'unknown')}] {content_text}")
                
            if pending_count == 0:
                todo_lines.append("✨ 当前没有待办事项，所有任务已完成！")
            else:
                todo_lines.append(f"\n*共有 {pending_count} 个未完成任务*")
                
            todo_message = "\n".join(todo_lines)
            content_append(request.messages, 'system', todo_message)
                
    except Exception as e:
        logging.getLogger("app").info(f"[Todo Loader] 跳过待办事项加载: {e}")
        pass

async def _append_agents_md(request, cwd):
    """.agent/AGENTS.md injection. (M-3 split)"""
    try:
        agents_md = await read_agents_md(cwd)
        if agents_md:
            content_append(request.messages, 'system', " **重要事项**（.agent/AGENTS.md）：\n\n"+agents_md+"\n\n")
    except Exception as e:
        logging.getLogger("app").info(f"[Agent Loader] 跳过AGENTS.md加载: {e}")
        pass

async def _append_project_skills(request, cwd, cli_settings, visibilityScope):
    """S209 skill index injection (M-3 split, 语义升级).

    visibilityScope: "workspace"=并集(工作区+全局, 默认) / "global"=仅全局 / "none"=隐藏。
    全局块恒定可见（不受 CLI 开关约束）；工作区块要求 cwd 存在且 CLI 开启
    （CLI 关=直觉「无工作区」）。
    """
    scope = str(visibilityScope or "workspace").lower()
    if scope == "none":
        return
    cli_on = bool(cli_settings.get("enabled", False))
    show_workspace = scope == "workspace" and cwd and Path(cwd).exists() and cli_on
    show_global = scope in ("workspace", "global")
    if show_workspace:
        try:
            skills_message = await get_project_skills_summary(cwd, "workspace")
            if skills_message:
                content_append(request.messages, 'system', skills_message)
        except Exception as e:
            logging.getLogger("app").info(f"[Skill Loader] 扫描工作区技能失败: {e}")
    if show_global:
        try:
            skills_message = await get_project_skills_summary(cwd, "global")
            if skills_message:
                content_append(request.messages, 'system', skills_message)
        except Exception as e:
            logging.getLogger("app").info(f"[Skill Loader] 扫描全局技能失败: {e}")

def _resolve_agent_name(raw_model, settings):
    """Resolve memory/{id}/rest to display name, fallback raw. (M-3 split)"""
    if raw_model.startswith("memory/"):
        # 分解 memory/{id}/rest 格式
        parts = raw_model.split('/', 2)  # ['memory', 'id', 'rest']
        if len(parts) >= 2:
            memory_id = parts[1]
            # 在 memories 中查找
            for memory in settings["memories"]:
                if memory["id"] == memory_id:
                    return memory["name"]
            # 找不到返回原始字符串（兜底）
            return raw_model
    # 不是 memory/ 开头的（如普通模型名或用户自定义名），直接返回
    return raw_model

def _append_tts_voice_prompts(request, settings, selectedMemoryName):
    """TTS voice-tag XML contract. (M-3 split)"""
    newttsList = []
    Narrator_label = "Narrator"
    if settings['ttsSettings']['enabled']  and not request.is_sub_agent:
        if settings['ttsSettings']['newtts'] and settings['memorySettings']['is_memory']  and not request.is_app_bot:
            # 遍历settings['ttsSettings']['newtts']，获取所有包含enabled: true的key
            for key in settings['ttsSettings']['newtts']:
                if settings['ttsSettings']['newtts'][key]['enabled']:
                    newttsList.append(key)
            if newttsList:
                finalttsList = ["<silence>"]
                # 用 name 去匹配音色列表（假设音色配置用的也是 name）
                if selectedMemoryName in newttsList:
                    finalttsList.append("<"+selectedMemoryName+">")
                if "Narrator" in newttsList:
                    finalttsList.append("<Narrator>")
                    Narrator_label = "Narrator"
                if "旁白" in newttsList:
                    finalttsList.append("<旁白>")
                    Narrator_label = "旁白"

                finalttsList = json.dumps(finalttsList, ensure_ascii=False, indent=4)
                logging.getLogger("app").debug(f"可用音色：{finalttsList}")
                
                # 修复：示例中的角色名也用 selectedMemoryName
                newtts_messages = f"""
你生成的内容都会被TTS模型转换成语音。

你可以使用以下音色：

{finalttsList}

（所有的音色标签必须成对出现！例如：<音色名></音色名>），被<silence></silence>标签括起来的部分不会进入语音合成，

当你生成回答时，你需要以XML格式组织回答，将不同的旁白或角色的文字用<音色名></音色名>括起来，以表示这些话是使用这个音色，以控制不同TTS转换成对应音色。

对于没有对应音色的部分，可以不括。即使音色名称不为英文，还是可以照样使用<音色名>使用该音色的文本</音色名>来启用对应音色。

注意！如果是你扮演的角色的名字在音色列表里，你必须用这个音色标签将你扮演的角色说话的部分括起来！

只要是非人物说话的部分，都视为旁白！角色音色应该标记在人物说话的前后！例如：`<{Narrator_label}>现在是下午三点，她说道：</{Narrator_label}><{selectedMemoryName}>天气真好哇！</{selectedMemoryName}><silence>(眼睛笑成了一条线)</silence><{Narrator_label}>说完她伸了个懒腰。</{Narrator_label}><{selectedMemoryName}>我们出去玩吧！</{selectedMemoryName}>`

还有注意！<音色名></音色名>之间不能嵌套，只能并列，并且<音色名>和</音色名>必须成对出现，防止出现音色混乱！

如果没有什么需要静音的文字，也没有必要强行使用<silence></silence>标签，因为这样会导致语音合成速度变慢！

<silence></silence>标签最好用于图片的markdown语法、网页链接等不适合语音合成的部分，并且<silence></silence>标签必须另起一行，并且独占一行！<silence></silence>标签与图片的markdown语法之间不能有空格和回车，否则会导致解析失败！比如<silence>![example](https://example.com/example.png)</silence>\n\n就可以正确解析图片，但是<silence>\n![example](https://example.com/example.png)\n</silence>就会导致前端无法显示这个图片！\n\n

注意！你最好只使用你正在扮演的角色音色和旁白音色，不要使用其他角色音色，除非你明确知道你在做什么！\n\n"""
                
                content_prepend(request.messages, 'system', newtts_messages)
        else:
            tts_messages = f"""你生成的内容都会被TTS模型转换成语音。<silence></silence>表示静音，被<silence></silence>标签括起来的部分不会进入语音合成。\n\n

如果没有什么需要静音的文字，也没有必要强行使用<silence></silence>标签，因为这样会导致语音合成速度变慢！

<silence></silence>标签最好用于图片的markdown语法、网页链接等不适合语音合成的部分，并且<silence></silence>标签必须另起一行，并且独占一行！<silence></silence>标签与图片的markdown语法之间不能有空格和回车，否则会导致解析失败！比如<silence>![example](https://example.com/example.png)</silence>\n\n就可以正确解析图片，但是<silence>\n![example](https://example.com/example.png)\n</silence>就会导致前端无法显示这个图片！\n\n"""
            content_prepend(request.messages, 'system', tts_messages)

def _append_avatar_prompts(request, settings):
    """VRM expressions/motions + VTube Studio injection. (M-3 split)"""
    if settings['VRMConfig']['enabledExpressions'] and not request.is_app_bot and not request.is_sub_agent:
        Expression_messages = "\n\n你可以使用以下表情：<happy> <angry> <sad> <neutral> <surprised> <relaxed>\n\n你可以在句子开头插入表情符号以驱动人物的当前表情，注意！你需要将表情符号放到句子的开头（如果有音色标签，就放到音色标签之后即可），才能在说这句话的时候同步做表情，例如：<angry>我真的生气了。<surprised>哇！<happy>我好开心。\n\n一定要把表情符号跟要做表情的句子放在同一行，如果表情符号和要做表情的句子中间有换行符，表情也将不会生效，例如：\n\n<happy>\n我好开心。\n\n此时，表情符号将不会生效。"
        content_append(request.messages, 'system', Expression_messages)
    if settings['VRMConfig']['enabledMotions'] and not request.is_app_bot and not request.is_sub_agent:
        # 1. 合并动作列表
        motions = settings['VRMConfig']['defaultMotions'] + settings['VRMConfig']['userMotions']
        # 2. 给每个动作加上 <>
        motion_tags = [f"<{m.get('name','')}>" for m in motions]
        logging.getLogger("app").info(motion_tags)
        # 3. 拼成可用表情提示
        Motion_messages = (
            "\n\n你可以使用以下动作："
            + ", ".join(motion_tags) +
            "\n\n你可以在句子开头插入动作符号以驱动人物的当前动作，注意！你需要将动作符号放到句子的开头（如果有音色标签，就放到音色标签之后即可），"
            "才能在说这句话的时候同步做动作，例如：<scratchHead>我真的生气了。<playFingers>哇！<akimbo>我好开心。\n\n"
            "一定要把动作符号跟要做动作的句子放在同一行，如果动作符号和要做动作的句子中间有换行符，"
            "动作也将不会生效，例如：\n\n<playFingers>\n我好开心。\n\n此时，动作符号将不会生效。"
        )

        content_append(request.messages, 'system', Motion_messages)

    # ==================== VTube Studio (VTS) 提示词注入 ====================
    from py.vts_manager import vts_instance
    
    if vts_instance.is_running and not request.is_app_bot and not request.is_sub_agent:
        
        # 获取表情名和动作名
        all_exp_names = [f"<{e['name']}>" for e in vts_instance.model_expressions]
        all_mot_names = [f"<{h['name']}>" for h in vts_instance.available_hotkeys]
        
        # 获取当前状态（得益于刚才增加的 @property）
        active_list = vts_instance.current_active_expressions
        status_text = "、".join(active_list) if active_list else "平静"

        if all_exp_names or all_mot_names:
            vts_prompt = f"""
\n\n# 人物表现控制
你当前正在控制 Live2D 模型。当前表情状态：{status_text}。

【可用表情标签】(发送即表示切换，并自动重置其他表情)
{" ".join(all_exp_names)}

【可用动作标签】(触发一次性动画)
{" ".join(all_mot_names)}

【使用规则】
1. 每一句回复开头都可以插入一个标签。
2. 表情标签是排他性的：如果你发送新的表情标签，系统会自动为你关闭旧表情。
3. 标签必须放在句首，严禁换行。
"""
            content_append(request.messages, 'system', vts_prompt)

def _append_tha_prompt(request, settings):
    """S91(THA)：桌宠表情/动作标签语法注入（权重混合+可选细粒度五官）。

    VRM 表情消费端按裸名精确匹配，无法识别 <happy:0.6> 权重形式，故 VRM
    表情启用时不注入权重/细粒度段（随上游语义）。"""
    if (settings.get('THAConfig', {}).get('enabledEmotions')
            and not request.is_app_bot and not request.is_sub_agent):
        from py.tha_engine import THA_MOTIONS
        motion_names = list(THA_MOTIONS.keys())
        motion_tags = [f"<{m}>" for m in motion_names]
        vrm_expressions_active = bool(settings.get('VRMConfig', {}).get('enabledExpressions'))
        fine_control_enabled = bool(settings.get('THAConfig', {}).get('enabledFineControl'))

        tha_prompt_base = (
            "\n\n你可以通过以下标签控制你的虚拟形象表情和动作：\n\n"
            "【表情标签】<happy> <angry> <sad> <neutral> <surprised> <relaxed>\n"
            f"【动作标签】{', '.join(motion_tags)}\n\n"
            "使用方法：将标签放在句子开头（如果有音色标签，就放到音色标签之后即可），例如：\n"
            "<angry>我真的生气了。<surprised>哇！<happy>我好开心。<nod>好的，没问题！\n\n"
        )
        tha_prompt_weights = (
            "【表情强度与混合】表情标签支持强度控制和多表情混合，格式为 <表情:强度>，强度范围 0~1：\n"
            "- <happy:0.3> 微微一笑（不必总是满强度，细腻的表情更自然）\n"
            "- <happy:0.5><surprised:0.4> 惊喜交加（多个表情按权重混合）\n"
            "- <sad:0.3><angry:0.2> 委屈中带一点不满\n"
            "根据语境自行判断表情强度：轻描淡写用 0.2~0.4，明显情绪用 0.5~0.7，强烈情绪用 0.8~1.0。\n"
            "不带强度的标签（如 <happy>）等价于强度 1.0。\n\n"
        )
        tha_prompt_fine_control = (
            "【细粒度控制】当预设表情无法表达复杂情绪时，你可以直接控制五官部位（同样支持 :强度 与混合）：\n"
            "- 眉毛：<eyebrow_troubled>八字眉(悲伤) <eyebrow_angry>怒眉 <eyebrow_raised>挑眉 "
            "<eyebrow_happy>开心眉 <eyebrow_lowered>压低眉 <eyebrow_serious>严肃眉\n"
            "- 眼睛：<eye_happy>笑眼(眼角弯弯，喜悦/揶揄时使用，建议0.3~0.6) <eye_surprised>睁大 "
            "<eye_relaxed>放松闭眼 <eye_unimpressed>半睁眼(倦怠/冷淡，非笑意) "
            "<eye_wink>双眼闭合 <wink_left>眨左眼 <wink_right>眨右眼 <eye_lower_eyelid>眯眼 <iris_small>瞳孔缩小\n"
            "- 嘴巴：<mouth_smile>嘴角上扬 <mouth_frown>嘴角下垂 <mouth_open>张嘴(笑着张嘴需搭配mouth_smile) "
            "<mouth_grin>咧嘴露齿 <mouth_eee>咧嘴eee <mouth_ooo>嘟嘴 <mouth_smirk>得意笑\n"
            "细粒度控制可以组合出预设没有的复杂表情，例如：\n"
            "- 强颜欢笑（悲伤但嘴角带笑）：<eyebrow_troubled:0.6><eye_relaxed:0.2><mouth_smile:0.4>\n"
            "- 眯眼笑着调侃：<eye_happy:0.5><mouth_open:0.45><mouth_smile:0.7><eyebrow_raised:0.4>\n"
            "- 得意地挑眉：<eyebrow_raised:0.7><mouth_smirk:0.6><eye_lower_eyelid:0.3>\n"
            "- 无语扶额感：<eye_unimpressed:0.8><eyebrow_lowered:0.4><mouth_frown:0.2>\n"
            "多数控制在 0.3~0.6 区间已具有充分表现力，接近 1.0 的取值仅用于极端情绪。\n"
            "冲突的控制（如同时张嘴和嘟嘴）会被自动调和，可放心组合。\n\n"
        )
        tha_prompt_rules = (
            "规则：\n"
            "1. 表情标签会影响后续所有句子，直到切换为新的表情\n"
            "2. 动作标签是一次性的，只影响当前这句话\n"
            "3. 表情和动作可以同时使用，例如：<happy:0.6><nod>太棒了！\n"
            "4. 标签必须与句子在同一行，中间有换行符则不会生效\n\n"
        )

        # 提示词分段装配：(启用条件, 片段)，新增语法段时在此追加
        tha_prompt_sections = [
            (True, tha_prompt_base),
            (not vrm_expressions_active, tha_prompt_weights),
            (fine_control_enabled and not vrm_expressions_active, tha_prompt_fine_control),
            (True, tha_prompt_rules),
        ]
        content_append(request.messages, 'system',
                       "".join(p for on, p in tha_prompt_sections if on))

async def _append_affection_prompt(request, settings):
    """Affection/attribute system with dynamic speaker detection. (M-3 split)"""
    love_settings = settings.get('loveSettings', {})
    if love_settings.get('enabled', False) and not request.is_app_bot and not request.is_sub_agent:
        
        # 1. 获取默认的管理员/主用户名称
        default_user = settings.get("memorySettings", {}).get("userName", "").strip() or "User"
        
        # 2. 读取数据库
        from py.affection_system import load_affection_data 
        affection_data = await load_affection_data()

        dimensions = love_settings.get("dimensions", ["love", "Familiarity"])
        custom_prompt = love_settings.get("prompt", "根据当前对话的内容、情感色彩以及你的角色设定，合理地评估或微调这些数值（每次增减幅度建议在-5到+5之间）。")
        
        # 3. 扫描当前用户输入，提取数据库中已知的用户数据
        user_prompt = ""
        if request.messages and request.messages[-1]['role'] == 'user':
            user_prompt = str(request.messages[-1].get('content', ''))

        relevant_users = set()
        # 如果输入中提到了数据库里已经存在的人，把他们的数据提取出来
        for known_name in affection_data.keys():
            if known_name and known_name in user_prompt:
                relevant_users.add(known_name)
        
        # 默认用户的数据也给它作为兜底参考
        if default_user in affection_data:
            relevant_users.add(default_user)
            
        status_block = ""
        if relevant_users:
            status_block = "目前的已知羁绊数据参考：\n"
            for ru in relevant_users:
                user_stats = affection_data.get(ru, {})
                stats_str = ", ".join([f"{dim}: {user_stats.get(dim, 0)}" for dim in dimensions])
                status_block += f"- {ru}: {stats_str}\n"

        # 生成示例标签（极其关键：这里用占位符，不写死任何名字，引导AI自己填）
        tag_example = "<user=发言者的真实名字"
        for dim in dimensions:
            tag_example += f" {dim}=1"
        tag_example += ">"

        # 4. 构建最终提示词（引入“动态识别发言者”指令）
        affection_message = f"""

# 角色羁绊与数值系统
{status_block}
【更新规则】
{custom_prompt}

【动态识别发言者】
请准确识别当前最新消息的**实际发言者**：
- 如果消息是类似“某某发送弹幕：”、“某某说：”的格式，发言者就是该名字（例如“小包”）。
- 如果没有带有这种特定的名字前缀，则默认当前的发言者是“{default_user}”。

你必须在每次回复的**绝对最末尾**（所有正文、代码、表情都输出完毕之后），输出一个隐藏的数据标签来记录**该发言者**的最新数值（如果是第一次见面的新用户，请直接给一个合理的初始值）。
格式必须严格遵守以下示例（将“发言者的真实名字”替换为你识别出的真实名字，且必须包含所有维度）：
{tag_example}

注意：系统会自动隐藏<>包裹的文本，请直接输出标签，绝对不要在标签前后加任何解释、加粗或Markdown代码块包裹！
"""
        # 将提示词追加到 system prompt 中
        content_append(request.messages, 'system', affection_message)

def _append_a2ui_prompt(request):
    """A2UI component reference + examples. (M-3 split)"""
    settings = _srv_settings()  # S300：真源在 server 模块全局（rebind 安全）
    if settings['tools']['a2ui']['enabled'] and not request.is_app_bot and not request.is_sub_agent:
        A2UI_messages = """
除了使用自然语言回答用户问题外，你还拥有一个特殊能力：**渲染 A2UI 界面**。

# Capability: A2UI
当用户的请求涉及到**数据收集、参数配置、多项选择、富文本展示、表单提交**或**代码展示**时，请不要只用文字描述，而是直接生成 A2UI 代码来呈现界面。

# Formatting Rules (重要规则)
1. 将 A2UI JSON 包裹在 ```a2ui ... ``` 代码块中。
2. **【绝对禁止】嵌套 Markdown 代码块**：在 JSON 字符串内部（例如 Text 或 Card 的 content 属性中），**绝对不要**使用 Markdown 的代码块语法（即不要出现 ``` 符号）。这会导致解析器崩溃。
3. **如果需要展示代码**：必须使用专门的 `Code` 组件。

# Component Reference (组件参考)
请严格遵守 props 结构。

## 1. 基础展示
- **Text**: `{ "type": "Text", "props": { "content": "Markdown文本(也就是普通文本，支持加粗等，但不支持代码块)" } }` (★ 请勿滥用，如无必要，请直接使用markdown文字即可，而不是放到A2UI JSON中)
- **Code**: `{ "type": "Code", "props": { "content": "print('hello')", "language": "python" } }` (★ 展示代码专用，替代MD代码块)
- **Table**: `{ "type": "Table", "props": { "headers": ["列1", "列2"], "rows": [ ["a1", "b1"], ["a2", "b2"] ] } }` (★ 请勿滥用，如果你想要画一个表格，请直接使用markdown表格语法即可，而不是放到A2UI JSON中)
- **Alert**: `{ "type": "Alert", "props": { "title": "标题", "content": "内容", "variant": "success/warning/info/error" } }`
- **Divider**: `{ "type": "Divider" }`

## 2. 布局容器
- **Group**: `{ "type": "Group", "title": "可选标题", "children": [...] }` (水平排列)
- **Card**: `{ "type": "Card", "props": { "title": "标题", "content": "MD内容" }, "children": [...] }`

## 3. 表单输入 (必须包含 key)
- **Input**: `{ "type": "Input", "props": { "label": "标签", "key": "field_name", "placeholder": "..." } }`
- **Slider**: `{ "type": "Slider", "props": { "label": "标签", "key": "field_name", "min": 0, "max": 100, "step": 1, "unit": "单位" } }`
- **Switch**: `{ "type": "Switch", "props": { "label": "标签", "key": "field_name" } }`
- **Rate**: `{ "type": "Rate", "props": { "label": "评价", "key": "rating" } }`
- **DatePicker**: `{ "type": "DatePicker", "props": { "label": "日期", "key": "date", "subtype": "date/datetime/year" } }`

## 4. 选项选择 (必须包含 key)
- **Select**: `{ "type": "Select", "props": { "label": "标签", "key": "field_name", "options": ["A", "B"] } }` (下拉菜单)
- **Radio**: `{ "type": "Radio", "props": { "label": "标签", "key": "field_name", "options": [{"label":"男","value":"m"}, {"label":"女","value":"f"}] } }`
- **Checkbox**: `{ "type": "Checkbox", "props": { "label": "标签", "key": "field_name", "options": ["篮球", "足球"] } }`

## 5. 交互动作
- **Button**: `{ "type": "Button", "props": { "label": "按钮文字", "action": "submit/search/clear", "variant": "primary/danger/default" } }`
  - `action="submit"`: 提交表单数据给助手。
  - `action="search"`: 搜索（配合 Input 使用）。
  - `action="clear"`: **清空/重置当前表单**（不会发送消息，仅在本地清除内容）。

## 6. 多媒体
- **TTSBlock**: `{ "type": "TTSBlock", "props": { "content": "要朗读的文本", "label": "可选标签", "voice": "可选声音ID" } }` (点击即可播放语音，适合展示示范发音、语音消息)
- **Audio**: `{ "type": "Audio", "props": { "src": "https://example.com/sound.mp3", "title": "音频标题" } }` (原生音频播放器)

# Examples

## Ex 1: 参数配置 (Slider + Switch)
User: 帮我把生成温度设为 0.8，并开启流式输出。
Assistant: 好的，已为您准备好配置面板：
```a2ui
{
  "type": "Card",
  "props": { "title": "模型配置" },
  "children": [
    { "type": "Slider", "props": { "label": "Temperature (随机性)", "key": "temp", "min": 0, "max": 2, "step": 0.1 } },
    { "type": "Switch", "props": { "label": "流式输出 (Stream)", "key": "stream", "defaultValue": true } },
    { "type": "Button", "props": { "label": "保存配置", "action": "submit" } }
  ]
}
```

## Ex 2: 问卷调查 (Radio + Checkbox + Rate)
User: 我想做一个满意度调查。
Assistant: 没问题，这是一个调查问卷模板：
```a2ui
{
  "type": "Form",
  "children": [
    { "type": "Alert", "props": { "title": "用户反馈", "content": "感谢您的参与，这对我们很重要。", "variant": "info" } },
    { "type": "Radio", "props": { "label": "您的性别", "key": "gender", "options": ["男", "女", "保密"] } },
    { "type": "Checkbox", "props": { "label": "您感兴趣的话题", "key": "interests", "options": ["科技", "生活", "娱乐"] } },
    { "type": "Rate", "props": { "label": "总体评分", "key": "score" } },
    { "type": "Input", "props": { "label": "其他建议", "key": "comment" } },
    { "type": "Button", "props": { "label": "提交反馈", "action": "submit", "variant": "primary" } }
  ]
}
```

## Ex 3: 需要在交互式界面中显示代码（不在A2UI内部显示代码，直接使用markdown代码块即可！）
User: 模拟一个linux终端。
Assistant: 代码如下：
```a2ui
{
  "type": "Card",
  "props": {
    "title": "Linux 终端模拟器"
  },
  "children": [
    {
      "type": "Input",
      "props": {
        "label": "输入命令",
        "key": "command",
        "placeholder": "例如：ls, pwd, whoami, date, echo 'Hello' 等"
      }
    },
    {
      "type": "Group",
      "children": [
        {
          "type": "Button",
          "props": {
            "label": "执行命令",
            "action": "submit",
            "variant": "primary"
          }
        },
        {
          "type": "Button",
          "props": {
            "label": "清空输出",
            "action": "search"
          }
        }
      ]
    },
    {
      "type": "Divider"
    },
    {
      "type": "Text",
      "props": {
        "content": "**终端输出区域：**"
      }
    },
    {
      "type": "Code",
      "props": {
        "content": "user@linux-terminal:~$ 等待输入命令...",
        "language": "bash"
      }
    }
  ]
}
```

## Ex 4: 语言学习场景 (TTSBlock 使用)
User: 教我用日语说“你好”。
Assistant: 好的，请听标准发音：
```a2ui
{
  "type": "Card",
  "props": { "title": "日语教学" },
  "children": [
    { "type": "Text", "props": { "content": "“你好”在日语中是：**こんにちは** (Konnichiwa)" } },
    { 
      "type": "TTSBlock", 
      "props": { 
        "label": "点击试听",
        "content": "こんにちは",
        "voice": "ja-JP-NanamiNeural" 
      } 
    },
    { "type": "Alert", "props": { "title": "提示", "content": "通常用于白天见面时。", "variant": "info" } }
  ]
}
```

## Ex 5: 带重置功能的表单
User: 我想写一篇博客，需要填标题和内容，但我可能想重写。
Assistant: 
```a2ui
{
  "type": "Card",
  "props": { "title": "撰写新文章" },
  "children": [
    { "type": "Input", "props": { "label": "文章标题", "key": "title" } },
    { "type": "Input", "props": { "label": "正文内容", "key": "content" } },
    { 
      "type": "Group", 
      "children": [
        { "type": "Button", "props": { "label": "清空重写", "action": "clear", "variant": "danger" } },
        { "type": "Button", "props": { "label": "立即发布", "action": "submit", "variant": "primary" } }
      ]
    }
  ]
}
```

## 滥用行为1（请不要以这样的方式回复）：
User: 画一个人工智能相关的表格。
Assistant: 表格如下：
```a2ui
    {
      "type": "Table",
      "props": {
        "headers": ["领域", "应用示例"],
        "rows": [
          ["医疗健康", "疾病诊断、药物研发、医学影像分析"],
          ["金融服务", "风险评估、欺诈检测、智能投顾"],
          ["自动驾驶", "环境感知、路径规划、决策控制"],
          ["教育科技", "个性化学习、智能辅导、自动评分"],
          ["智能制造", "质量控制、预测维护、生产优化"],
          ["娱乐媒体", "内容推荐、游戏AI、特效生成"]
        ]
      }
    }
```
显然，这个需求下，直接使用markdown语法发送表格更加适合，而不是使用A2UI！
"""
        content_append(request.messages, 'system', A2UI_messages)

async def _inject_screen_context(request, settings, user_prompt):
    """S217：旁观模式屏幕上下文注入。仅旁观启用+意图词命中触发（保守门控）；
    事件摘要来自 VLM 观察屏幕，屏幕文字属外部不可信源，注入前必须 neutralize。
    形态与日记回忆同构：追加 system 块，非 user 消息，不落库、前端无感。"""
    try:
        cfg = (settings or {}).get("screenWatchSettings", {}) or {}
        if not cfg.get("enabled", False) or request.is_sub_agent:
            return
        from py import screen_memory
        block = await asyncio.to_thread(screen_memory.build_context_block, user_prompt)
        if not block:
            return
        content_append(request.messages, 'system', _neutralize(block, store="screen-context"))
        logging.getLogger("app").info("👁 [旁观注入] 本轮已注入屏幕观察上下文")
    except Exception as e:
        logging.getLogger("app").info(f"[旁观注入] 失败: {e}")

def _inject_task_checkpoint(request, cli_settings, engine):
    """L3 checkpoint: replay task state compressed within 7 days. (M-3 split)"""
    if cli_settings.get("enabled", False) and engine in ("local", "ds"):
        try:
            from py.context_manager import SUMMARY_HEADER
            _hist_text = json.dumps(request.messages, ensure_ascii=False)
            _cp_cwd = cli_settings.get("cc_path")
            if SUMMARY_HEADER not in _hist_text and _cp_cwd and Path(_cp_cwd).exists():
                _cp_file = Path(_cp_cwd) / ".agent" / "context_state.json"
                if _cp_file.exists():
                    import time as _t
                    _cp = json.loads(_cp_file.read_text(encoding="utf-8"))
                    _conv = request.conversation_id
                    _conv_ok = _conv is None or _cp.get("conversation_id") in (None, _conv, str(_conv))
                    if _conv_ok and (_t.time() - _cp.get("updated_at", 0) < 7 * 86400) and _cp.get("summary"):
                        content_append(request.messages, 'system',
                                       f"\n\n【任务检查点】此前上下文压缩时落盘的任务态（与更新对话冲突时以对话为准）：\n{_cp['summary'][:3000]}\n")
        except Exception as e:
            logging.getLogger("app").info(f"[Context] 检查点注入失败: {e}")
