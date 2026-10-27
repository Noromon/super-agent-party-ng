
import logging
import json
import os
import threading
from pathlib import Path

# T-10：.party/config.json 的读-改-写并发保护（"始终允许"并发点击
# 互覆盖丢白名单）。进程级单锁——写入频率极低，无需按 cwd 细分。
_PROJECT_CONFIG_LOCK = threading.Lock()

def _get_project_config_path(cwd: str) -> Path:
    """获取 .party/config.json 的路径"""
    return Path(cwd) / ".party" / "config.json"

def is_tool_allowed_by_project_config(cwd: str, tool_name: str) -> bool:
    """
    检查项目级配置文件中是否已允许该工具
    """
    if not cwd:
        return False
    
    config_path = _get_project_config_path(cwd)
    if not config_path.exists():
        return False
        
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            allowed_tools = data.get("allowed_tools", [])
            return tool_name in allowed_tools
    except Exception as e:
        logging.getLogger("app").info(f"[Config Error] Failed to read .party config: {e}")
        return False

def add_tool_to_project_config(cwd: str, tool_name: str):
    """
    将工具添加到项目级允许列表中 (创建 .party/config.json)
    """
    if not cwd:
        return
        
    config_path = _get_project_config_path(cwd)
    party_dir = config_path.parent
    
    # 1. 确保文件夹存在
    if not party_dir.exists():
        party_dir.mkdir(parents=True, exist_ok=True)
        # 在 Windows 上隐藏文件夹 (可选)
        try:
            import ctypes
            FILE_ATTRIBUTE_HIDDEN = 0x02
            ctypes.windll.kernel32.SetFileAttributesW(str(party_dir), FILE_ATTRIBUTE_HIDDEN)
        except:
            pass

    # 2/3) 读-改-写同一临界区 + 原子替换（T-10）
    with _PROJECT_CONFIG_LOCK:
        data = {"allowed_tools": []}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass

        if tool_name not in data.get("allowed_tools", []):
            if "allowed_tools" not in data:
                data["allowed_tools"] = []
            data["allowed_tools"].append(tool_name)

        tmp_path = str(config_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, config_path)


# ==================== S153: 目录级白名单（allowed_dirs） ====================
# 与 allowed_tools 相互独立：工具"总是允许"永远绕不过路径门（opencode
# external_directory 语义）。匹配=前缀+分隔符边界（path_within，normcase）。

def is_dir_allowed_by_project_config(cwd: str, target_dir: str) -> bool:
    if not cwd or not target_dir:
        return False
    from py.path_scope import path_within
    config_path = _get_project_config_path(cwd)
    if not config_path.exists():
        return False
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            allowed_dirs = data.get("allowed_dirs", []) or []
        return any(path_within(target_dir, d) for d in allowed_dirs)
    except Exception as e:
        logging.getLogger("app").info(f"[Config Error] Failed to read .party config: {e}")
        return False


def add_dirs_to_project_config(cwd: str, dirs):
    """把目录（str 或 list[str]）永久加入项目 allowed_dirs（读-改-写同一临界区+原子替换，T-10 同款）。"""
    if not cwd or not dirs:
        return
    if isinstance(dirs, str):
        dirs = [dirs]
    from py.path_scope import path_norm
    config_path = _get_project_config_path(cwd)
    party_dir = config_path.parent
    if not party_dir.exists():
        party_dir.mkdir(parents=True, exist_ok=True)
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(party_dir), 0x02)
        except Exception:
            pass

    with _PROJECT_CONFIG_LOCK:
        data = {"allowed_tools": []}
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                pass
        allowed = data.setdefault("allowed_dirs", [])
        for d in dirs:
            dn = path_norm(d)
            if dn and dn not in allowed:
                allowed.append(dn)
        tmp_path = str(config_path) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        os.replace(tmp_path, config_path)