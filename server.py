# -- coding: utf-8 --
# ==========================================
# 第一步：在加载任何沉重库之前，先搞定端口
# ==========================================
import signal
import sys
import os
import argparse
import socket
import errno
from py.cli_tool import read_file_tool_local
from py.context_builder import sanitize_tool_chains
from py import auth as sap_auth
from py.defaults import DEFAULT_SERVER_PORT, GSV_TTS_URL
from py.tool_registry import PLAN_BLOCKED_TOOLS, SENSITIVE_TOOLS

from py.tool_assembly import build_llm_tools


def _assemble_toolkit():
    """Toolkit snapshot for build_llm_tools; rebuilt per request so that
    module-level client rebindings (lifespan, MCP reload) are picked up."""
    from py.llm_tool import get_llm_tool
    from py.agent_tool import get_agent_tool
    from py.a2a_tool import get_a2a_tool
    from py.cli_tool import get_tools_for_permission, get_local_tools_for_permission
    from py.load_files import file_tool, image_tool, analyze_image_tool, review_image_tool, analyze_images_tool
    from py.pollinations import pollinations_image_tool, openai_image_tool, openai_chat_image_tool
    from py.code_interpreter import e2b_code_tool, local_run_code_tool
    from py.utility_tools import (time_tool, weather_tool, location_tool, timer_weather_tool,
                                  wikipedia_summary_tool, wikipedia_section_tool, arxiv_tool)
    from py.autoBehavior import auto_behavior_tool
    from py.cdp_tool import all_cdp_tools
    from py.random_topic import random_topics_tools
    from py.computer_use_tool import computer_use_tools, mouse_use_tools, keyboard_use_tools, desktopVision_use_tools
    from py.mode_change import mode_change_tool
    from py.acpx_tools import acp_agent_tool
    return {
        "mcp_client_list": app_state.mcp_client_list,
        "mcp_status": app_state.mcp_status,
        "node_ext_mcp_tools": node_ext_mcp_tools,
        "HA_client": app_state.HA_client,
        "ChromeMCP_client": app_state.ChromeMCP_client,
        "sql_client": app_state.sql_client,
        "get_llm_tool": get_llm_tool,
        "get_agent_tool": get_agent_tool,
        "get_a2a_tool": get_a2a_tool,
        "cli_permission_mode_for": cli_permission_mode_for,
        "get_tools_for_permission": get_tools_for_permission,
        "get_local_tools_for_permission": get_local_tools_for_permission,
        "all_cdp_tools": all_cdp_tools,
        "acp_agent_tool": acp_agent_tool,
        "mode_change_tool": mode_change_tool,
        "diary_query_tool": diary_query_tool,
        "diary_books_tool": diary_books_tool,
        "computer_use_tools": computer_use_tools,
        "mouse_use_tools": mouse_use_tools,
        "keyboard_use_tools": keyboard_use_tools,
        "desktopVision_use_tools": desktopVision_use_tools,
        "time_tool": time_tool,
        "weather_tool": weather_tool,
        "location_tool": location_tool,
        "timer_weather_tool": timer_weather_tool,
        "wikipedia_summary_tool": wikipedia_summary_tool,
        "wikipedia_section_tool": wikipedia_section_tool,
        "random_topics_tools": random_topics_tools,
        "arxiv_tool": arxiv_tool,
        "pollinations_image_tool": pollinations_image_tool,
        "openai_image_tool": openai_image_tool,
        "openai_chat_image_tool": openai_chat_image_tool,
        "file_tool": file_tool,
        "image_tool": image_tool,
        "analyze_image_tool": analyze_image_tool,
        "review_image_tool": review_image_tool,
        "analyze_images_tool": analyze_images_tool,
        "auto_behavior_tool": auto_behavior_tool,
        "e2b_code_tool": e2b_code_tool,
        "local_run_code_tool": local_run_code_tool,
    }

from py.tool_loop import (NONE_TEXT, TOOL_EXC_TMPL,
                        arg_error_text, append_missing_results)
from py.task_tools import query_task_progress
from py.ws_manager import ws_manager
from py import llm_gate
import shortuuid
os.environ["MEM0_TELEMETRY"] = "False"
parser = argparse.ArgumentParser(description="Run the ASGI application server.")
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT)
args, _ = parser.parse_known_args()

HOST = args.host
PREFERED_PORT = args.port

def is_addr_in_use_error(e):
    """跨平台判断是否为地址被占用错误"""
    if hasattr(e, 'errno'):
        if e.errno == errno.EADDRINUSE:
            return True
        # Windows 有时用 WSAEADDRINUSE (10048)
        if sys.platform == 'win32' and e.errno == 10048:
            return True
    # Windows winerror 属性
    if hasattr(e, 'winerror') and e.winerror == 10048:
        return True
    # macOS/Linux 错误消息
    if 'address already in use' in str(e).lower():
        return True
    return False

def is_permission_error(e):
    """跨平台判断是否为权限/拒绝访问错误"""
    if isinstance(e, PermissionError):
        return True
    if hasattr(e, 'errno'):
        if e.errno in (errno.EACCES, errno.EPERM):
            return True
        # Windows ERROR_ACCESS_DENIED (5)
        if sys.platform == 'win32' and e.errno == 13:
            return True
    if hasattr(e, 'winerror') and e.winerror in (5, 10013):
        return True
    err_str = str(e).lower()
    if any(x in err_str for x in ['permission', 'denied', 'access', 'not permitted']):
        return True
    return False

def force_bind_or_fallback(host, preferred_port):
    """
    跨平台端口绑定：
    1. 尝试强制绑定指定端口（处理TIME_WAIT）
    2. 如果被真正占用/无权限/系统保留，自动降级到随机端口
    3. 绝不抛出异常导致退出
    """
    # 尝试绑定首选端口
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 关键：允许快速复用 TIME_WAIT 状态的端口
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, preferred_port))
        sock.close()
        return preferred_port
        
    except (socket.error, OSError, PermissionError) as e:
        # 判断错误类型
        if is_addr_in_use_error(e):
            reason = "in use"
        elif is_permission_error(e):
            reason = "permission denied/system reserved"
        else:
            reason = f"error ({e})"
        
        print(f"Port {preferred_port} unavailable ({reason}), auto-assigning...", 
              file=sys.stderr, flush=True)
        
        # 关闭失败的 socket
        try:
            if sock:
                sock.close()
        except:
            pass
        
        # 降级：让系统分配端口
        return auto_assign_port(host)
        
    except Exception as e:
        # 捕获所有其他异常
        print(f"Unexpected error binding port {preferred_port}: {e}, auto-assigning...", 
              file=sys.stderr, flush=True)
        try:
            if sock:
                sock.close()
        except:
            pass
        return auto_assign_port(host)

def auto_assign_port(host):
    """自动分配可用端口，带多重降级"""
    # 尝试 127.0.0.1
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        port = sock.getsockname()[1]
        sock.close()
        print(f"Auto-assigned port: {port}", file=sys.stderr, flush=True)
        return port
    except Exception as e:
        print(f"Failed to bind {host}: {e}", file=sys.stderr, flush=True)
        try:
            sock.close()
        except:
            pass
    
    # 降级 1: 尝试 0.0.0.0 (所有接口)
    if host != "0.0.0.0":
        try:
            print("Trying 0.0.0.0...", file=sys.stderr, flush=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", 0))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Auto-assigned port on 0.0.0.0: {port}", file=sys.stderr, flush=True)
            return port
        except Exception as e:
            print(f"Failed to bind 0.0.0.0: {e}", file=sys.stderr, flush=True)
            try:
                sock.close()
            except:
                pass
    
    # 降级 2: 尝试 localhost
    if host != "localhost":
        try:
            print("Trying localhost...", file=sys.stderr, flush=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("localhost", 0))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Auto-assigned port on localhost: {port}", file=sys.stderr, flush=True)
            return port
        except Exception as e:
            print(f"Failed to bind localhost: {e}", file=sys.stderr, flush=True)
            try:
                sock.close()
            except:
                pass
    
    # 最后手段：硬编码高位端口（极端情况）
    fallback_ports = [45678, 45679, 45680, 0]
    for fp in fallback_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host if host != "0.0.0.0" else "127.0.0.1", fp))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Fallback to hardcoded port: {port}", file=sys.stderr, flush=True)
            return port
        except:
            try:
                sock.close()
            except:
                pass
            continue
    
    # 理论上不会到这里，如果真的到了，返回一个肯定能用的
    return 0

# 执行端口查找
FINAL_PORT = force_bind_or_fallback(HOST, PREFERED_PORT)
PORT = FINAL_PORT
os.environ['DYNAMIC_PORT'] = str(FINAL_PORT)

# 同时调用 change_port 保持同步
from py.get_setting import change_port
change_port(FINAL_PORT)

# 核心：立刻打印！
print(f"REAL_PORT_FOUND:{PORT}", flush=True)

# ==========================================
# 第二步：屏蔽掉后面库可能产生的骚扰警告
# ==========================================
import warnings
warnings.filterwarnings("ignore") # 忽略普通警告
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' # 如果有 tensorflow 等库，减少其日志输出

import hashlib
import importlib
import mimetypes
import pathlib
import sys
import traceback
import platform
import requests

from py.agent import add_tool_to_project_config, is_tool_allowed_by_project_config
sys.stdout.reconfigure(encoding='utf-8')
import base64
from datetime import datetime
import glob
import io
import os
from pathlib import Path
import pickle
import socket
import sys
import tempfile
import httpx
import ipaddress
from urllib.parse import urlparse, urlunparse, urljoin
from urllib.robotparser import RobotFileParser
from py.load_files import check_robots_txt, get_file_content, is_private_ip, sanitize_url
from py.proxy_util import net_error_hint

# 修复 sherpa-onnx 在 macOS arm64 上的 onnxruntime dylib 路径问题
import site
try:
    _sp = site.getsitepackages()[0]
    _sherpa_lib = os.path.join(_sp, "sherpa_onnx", "lib")
    _onnx_capi = os.path.join(_sp, "onnxruntime", "capi")
    import glob as _glob
    _dylibs = _glob.glob(os.path.join(_onnx_capi, "libonnxruntime*.dylib"))
    if _dylibs:
        _dylib = _dylibs[0]
        _target = os.path.join(_sherpa_lib, os.path.basename(_dylib))
        if not os.path.exists(_target):
            os.makedirs(_sherpa_lib, exist_ok=True)
            os.symlink(os.path.abspath(_dylib), _target)
except Exception:
    pass

def fix_macos_environment():
    """
    专门修复 macOS 下找不到 node (nvm) 和 uv (python framework) 的问题
    """
    if sys.platform != 'darwin':
        return

    user_home = Path.home()
    paths_to_add = []

    # ---------------------------------------------------------
    # 1. 自动发现 NVM 安装的 Node.js
    # 路径通常是: ~/.nvm/versions/node/vX.X.X/bin
    # ---------------------------------------------------------
    nvm_path = user_home / ".nvm" / "versions" / "node"
    if nvm_path.exists():
        # 获取所有版本文件夹 (如 v20.19.5, v18.0.0)
        # 使用 glob 匹配所有 v 开头的文件夹
        node_versions = sorted(nvm_path.glob("v*"), key=lambda p: p.name, reverse=True)
        
        # 将所有版本的 bin 目录都加入，或者只加最新的
        for version_dir in node_versions:
            bin_path = version_dir / "bin"
            if bin_path.exists():
                paths_to_add.append(str(bin_path))
                # 如果只想用最新的 node，这里可以 break
                # break 

    # ---------------------------------------------------------
    # 2. 自动发现 Python Framework 中的 uv
    # 路径通常是: /Library/Frameworks/Python.framework/Versions/X.X/bin
    # ---------------------------------------------------------
    py_framework_path = Path("/Library/Frameworks/Python.framework/Versions")
    if py_framework_path.exists():
        # 查找所有版本，如 3.13, 3.12
        py_versions = py_framework_path.glob("*")
        for ver in py_versions:
            bin_path = ver / "bin"
            if bin_path.exists():
                paths_to_add.append(str(bin_path))

    # ---------------------------------------------------------
    # 3. 补充 macOS 常见的其他路径 (Homebrew, Cargo, Local)
    # uv 也经常被安装在 .local/bin 或 .cargo/bin 下
    # ---------------------------------------------------------
    common_extras = [
        "/opt/homebrew/bin",           # Apple Silicon Mac Homebrew
        "/usr/local/bin",              # Intel Mac Homebrew
        str(user_home / ".local" / "bin"), # 用户级安装通常在这里
        str(user_home / ".cargo" / "bin"), # Rust 工具链 (uv 可能在这里)
    ]
    paths_to_add.extend(common_extras)

    # ---------------------------------------------------------
    # 4. 将发现的路径注入到当前进程的环境变量中
    # ---------------------------------------------------------
    current_path = os.environ.get("PATH", "")
    new_path_str = current_path
    
    # 将新路径加到最前面 (优先级最高)
    for p in paths_to_add:
        if p and os.path.isdir(p):
            # 避免重复添加
            if p not in new_path_str:
                new_path_str = p + os.pathsep + new_path_str
    
    # 更新环境变量
    os.environ['PATH'] = new_path_str
    
    # (可选) 打印调试信息
    # print(f"Fixed macOS PATH. Added: {paths_to_add}")

# --- 在程序最开始的地方调用这个函数 ---
fix_macos_environment()

def _fix_onnx_dll():
    if sys.platform == 'darwin':
        return
    # 1. 找到 uv 虚拟环境里的 onnxruntime
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or spec.origin is None:
        return          # 没装 onnxruntime，随它去
    # DLL 就在 site-packages/onnxruntime/capi 里
    dll_dir = pathlib.Path(spec.origin).with_name("capi")
    if not dll_dir.is_dir():
        return

    # 2. 置顶搜索路径
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
    if hasattr(os, "add_dll_directory"):      # Python 3.8+
        os.add_dll_directory(str(dll_dir))

    # 3. 如果已经有人 import 过 onnxruntime，清掉缓存
    for mod in list(sys.modules):
        if mod.startswith("onnxruntime"):
            del sys.modules[mod]

_fix_onnx_dll()

# 在程序最开始设置
if hasattr(sys, '_MEIPASS'):
    # 打包后的程序
    os.environ['PYTHONPATH'] = sys._MEIPASS
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
import asyncio
import contextvars
import copy
from functools import partial

# 用于在工具调用时传递当前对话上下文（特别是 review_image 工具需要）
current_request_messages = contextvars.ContextVar('current_request_messages', default=None)
import json
import random
import re
import shutil
from fastapi import BackgroundTasks, Body, FastAPI, File, Form, HTTPException, UploadFile, WebSocket, Request, WebSocketDisconnect
from fastapi_mcp import FastApiMCP
import logging
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI
from pydantic import BaseModel
from fastapi import status
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse,Response
import uuid
import time
from typing import Any, AsyncIterator, List, Dict,Optional, Tuple, Union
import shortuuid
from py.mcp_clients import McpClient
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
import aiofiles
import argparse
from py.dify_openai import DifyOpenAIAsync
from py.ClaudeAsOpenAI import AsyncClaudeAsOpenAI
from py.GeminiAsOpenAI import AsyncGeminiAsOpenAI
from py.ResponsesAsOpenAI import AsyncResponsesAsOpenAI
from py.diary_query_tool import diary_query_tool, diary_books_tool, handle_query_diary, handle_list_diary_books
from py.diary_chat_integration import append_to_chat_buffer, update_buffer_identity, get_chat_buffer
from py.diary_system import get_recent_diary_entries, DEFAULT_BOOK_ID as DIARY_DEFAULT_BOOK

from py.get_setting import EXT_DIR, IS_DOCKER, SKILLS_DIR, _copy_default_skills, convert_to_opus_simple, deep_update, load_covs, load_settings, save_covs,save_settings,clean_temp_files_task,base_path,configure_host_port,UPLOAD_FILES_DIR,AGENT_DIR,MEMORY_CACHE_DIR,KB_DIR,DEFAULT_VRM_DIR,USER_DATA_DIR,LOG_DIR,TOOL_TEMP_DIR,COVS_PATH
from py.llm_tool import get_image_base64,get_image_media_type
from py.tool_dispatch import (_APPROVAL_PREFIX, _approval_payload,
                              _is_approval_result)
from py.tool_dispatch import (dispatch_external_tool as _dispatch_external_tool,
                              dispatch_task_center_tool as _dispatch_task_center_tool,
                              dispatch_unknown_tool as _dispatch_unknown_tool)
from py.file_utils import (ALLOWED_EXTENSIONS, ALLOWED_IMAGE_EXTENSIONS,
                           ALLOWED_VIDEO_EXTENSIONS, ALLOWED_AUDIO_EXTENSIONS,
                           ALLOWED_VRM_EXTENSIONS, ALLOWED_VRMA_EXTENSIONS,
                           ALLOWED_GAUSS, animation_dir, GAUSS_DIR,
                           make_file_url, scan_motion_files, get_internal_ip)

logger = None      
os.environ["no_proxy"] = "localhost,127.0.0.1"
local_timezone = None
settings = None
client = None
fast_client = None 
reasoner_client = None
node_ext_mcp_clients: Dict[str, McpClient] = {}
node_ext_mcp_tools: Dict[str, List[Dict]] = {}  # 存储每个扩展的工具列表
locales = {}
sleep_guard = None
scheduler_task = None
diary_engine_task = None
_TOOL_HOOKS = {}
# 1. 先清空系统可能给错的条目
for ext in ("js", "mjs", "css", "html", "htm", "json", "xml", "map", "svg"):
    mimetypes.add_type("", f".{ext}")          # 先删掉
# 2. 再写死我们想要的
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("text/html", ".html")
mimetypes.add_type("text/html", ".htm")
mimetypes.add_type("application/json", ".json")
mimetypes.add_type("application/xml", ".xml")
mimetypes.add_type("application/json", ".map")
mimetypes.add_type("image/svg+xml", ".svg")

import platform
import ctypes
from PIL import Image, ImageDraw, ImageFont
import io
if platform.system() == "Windows":
    try:
        # 设置 DPI 感知，确保截屏尺寸和 size() 返回的一致
        ctypes.windll.shcore.SetProcessDpiAwareness(1) 
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

def draw_grid_on_image(image: Image.Image, grid_spacing: int = 10) -> Image.Image:
    """
    在图片上绘制网格和千分比坐标标签
    grid_spacing: 每隔多少百分比画一根线，默认 10 (即 10x10 的网格)
    """
    draw = ImageDraw.Draw(image)
    width, height = image.size
    
    # 颜色设置 (半透明红色或亮绿色，视情况而定)
    line_color = (255, 0, 0, 128)  # 红色线
    text_color = (255, 0, 0, 255)
    
    # 绘制垂直线 (百分比 0-100，但标签显示为千分比 0-1000‰)
    for x_pc in range(0, 101, grid_spacing):
        x = int(width * (x_pc / 100.0))
        # 确保不超出边界
        x = min(x, width - 1)
        draw.line([(x, 0), (x, height)], fill=line_color, width=1)
        x_permille = x_pc
        draw.text((x + 2, 5), f"{x_permille}%", fill=text_color)

    # 绘制水平线
    for y_pc in range(0, 101, grid_spacing):
        y = int(height * (y_pc / 100.0))
        y = min(y, height - 1)
        draw.line([(0, y), (width, y)], fill=line_color, width=1)
        y_permille = y_pc
        draw.text((5, y + 2), f"{y_permille}%", fill=text_color)
        
    return image

def draw_action_feedback(image: Image.Image, action_str: str) -> Image.Image:
    """
    解析返回结果字符串，并在图像上绘制动作反馈轨迹。
    （已针对红色网格优化，全面移除红色，使用高对比度的青/蓝/绿/黄色）
    """
    # 强制将原始图像转换为 RGBA，以便使用半透明色彩
    image = image.convert("RGBA")
    
    # 创建一个与原图同尺寸的透明涂层
    overlay = Image.new("RGBA", image.size, (255, 255, 255, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = image.size
    
    def to_px(tx, ty):
        return int(float(tx) * w / 1000), int(float(ty) * h / 1000)

    # 1. 匹配 MOVE(x,y) -> 画个白色小圆点带黑边
    move_match = re.search(r"\[LAST_ACTION: MOVE\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if move_match:
        x, y = move_match.groups()
        px, py = to_px(x, y)
        r = 6
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(255, 255, 255, 200), outline=(0, 0, 0, 255), width=1)

    # 2. 匹配 CLICK(x,y) -> 画个青色(Cyan)半透明十字靶心 (对比红色网格极佳)
    click_match = re.search(r"\[LAST_ACTION: CLICK\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if click_match:
        x, y = click_match.groups()
        px, py = to_px(x, y)
        r = 12
        # 青色底圈
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 255, 255, 150), outline=(255, 255, 255, 255), width=2)
        # 白色十字
        draw.line([px-r-5, py, px+r+5, py], fill=(255, 255, 255, 255), width=2)
        draw.line([px, py-r-5, px, py+r+5], fill=(255, 255, 255, 255), width=2)

    # 3. 匹配 DOUBLE_CLICK(x,y) -> 画个蓝色(Blue)双圈靶心
    dclick_match = re.search(r"\[LAST_ACTION: DOUBLE_CLICK\((\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if dclick_match:
        x, y = dclick_match.groups()
        px, py = to_px(x, y)
        r = 14
        # 蓝色底圈
        draw.ellipse([px-r, py-r, px+r, py+r], fill=(0, 100, 255, 150), outline=(255, 255, 255, 255), width=2)
        # 内层白圈
        draw.ellipse([px-(r-4), py-(r-4), px+(r-4), py+(r-4)], outline=(255, 255, 255, 255), width=1)

    # 4. 匹配 DRAG(x1,y1,x2,y2) -> 绿色轨迹线，绿色起点，黄色终点
    drag_match = re.search(r"\[LAST_ACTION: DRAG\((\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*),(\d+\.?\d*)\)\]", action_str)
    if drag_match:
        x1, y1, x2, y2 = drag_match.groups()
        p1 = to_px(x1, y1)
        p2 = to_px(x2, y2)
        
        # 绿色带透明度的连接线
        draw.line([p1, p2], fill=(0, 255, 0, 200), width=4)
        
        # 绿色起点圆
        draw.ellipse([p1[0]-6, p1[1]-6, p1[0]+6, p1[1]+6], fill=(0, 255, 0, 255), outline=(255,255,255,255), width=1)
        
        # 黄色终点靶心 (黄色在网格上也很显眼)
        r_end = 8
        draw.ellipse([p2[0]-r_end, p2[1]-r_end, p2[0]+r_end, p2[1]+r_end], fill=(255, 215, 0, 180), outline=(255,255,255,255), width=2)

    # 合并图层，转回 RGB (防 JPG 格式不支持 Alpha 通道)
    combined = Image.alpha_composite(image, overlay)
    return combined.convert("RGB")

def scale_to_fit(width: int, height: int, max_w: int = 1920, max_h: int = 1080) -> tuple[int, int]:
    """计算等比例缩放后的尺寸"""
    # 计算宽和高的缩放比例
    scale_w = max_w / width
    scale_h = max_h / height
    
    # 取较小的那个缩放比例，确保长宽都不超过限制
    scale = min(scale_w, scale_h, 1.0) # 如果原图比 1920x1080 小，则不放大(1.0)
    
    new_width = int(width * scale)
    new_height = int(height * scale)
    return new_width, new_height

def _get_target_message(message, role):
    """
    根据角色获取目标消息
    
    参数:
        message (list): 消息列表引用
        role (str): 要操作的角色，可选值: 'user', 'assistant', 'system'
    
    返回:
        dict: 目标消息字典
    """
    # 验证输入参数
    if not isinstance(message, list):
        raise TypeError("message必须是列表类型")
    
    if role not in ['user', 'assistant', 'system']:
        raise ValueError("role必须是'user'或'assistant'或'system'")
    
    target_message = None
    
    # 根据role决定要操作的对象
    if role == 'user':
        # 查找最后一个role为'user'的消息
        for msg in reversed(message):
            if isinstance(msg, dict) and msg['role'] == 'user':
                target_message = msg
                break
    elif role == 'assistant':
        # 检查最后一个消息
        if message and message[-1]['role'] == 'assistant':
            target_message = message[-1]
        else:
            # 如果最后一个消息不是assistant，创建一个新的
            new_assistant_msg = {'role': 'assistant', 'content': '','reasoning_content': ''}
            message.append(new_assistant_msg)
            target_message = new_assistant_msg
    elif role == 'system':
        # 查找第一个role为'system'的消息
        if message and message[0]['role'] == 'system':
            target_message = message[0]
        else:
            # 如果没有找到system消息，创建一个新的
            target_message = {'role': 'system', 'content': ''}
            message.insert(0, target_message)
    
    return target_message

def content_append(message, role, content):
    """
    将content添加到指定role消息的末尾
    """
    target_message = _get_target_message(message, role)
    if target_message:
        current_content = target_message.get('content', '')
        target_message['content'] = current_content + content

def content_prepend(message, role, content):
    """
    将content添加到指定role消息的前面
    """
    target_message = _get_target_message(message, role)
    if target_message:
        current_content = target_message.get('content', '')
        target_message['content'] = content + current_content

def content_replace(message, role, content):
    """
    用content替换指定role消息的内容
    """
    target_message = _get_target_message(message, role)
    if target_message:
        target_message['content'] = content

def content_new(message, role, content):
    """
    用content替换指定role消息的内容
    """
    message.append({'role': role, 'content': content})

configure_host_port(args.host, args.port)

def get_client_class(config, provider_id):
    if not config or 'modelProviders' not in config:
        return AsyncOpenAI
    vendor = 'OpenAI'
    for provider in config['modelProviders']:
        if provider['id'] == provider_id:
            vendor = provider['vendor']
            break
    # 假设你已经导入了 DifyOpenAIAsync 和 AsyncOpenAI
    if vendor == 'Dify':
        return DifyOpenAIAsync 
    elif vendor == 'customAnthropic':
        return AsyncClaudeAsOpenAI
    elif vendor == 'Gemini':
        return AsyncGeminiAsOpenAI
    elif vendor == 'OpenAIResponses':
        return AsyncResponsesAsOpenAI
    else: 
        return AsyncOpenAI

from py.node_runner import node_mgr
async def _t10_shutdown(temp_sweep_task):
    """T-10（D4）：统一关停钩子——bot 渠道 → MCP 长连接 → 周期清扫任务。"""
    try:
        await asyncio.wait_for(asyncio.to_thread(BotContainer.stop_all), timeout=90)
    except Exception as e:
        logging.getLogger("app").warning(f"T-10: 机器人批量停止异常: {e}")
    for _mcp in [app_state.HA_client, app_state.ChromeMCP_client, app_state.sql_client] \
            + list(app_state.mcp_client_list.values()):
        if _mcp is None:
            continue
        try:
            await asyncio.wait_for(_mcp.close(), timeout=5)
        except Exception as e:
            logging.getLogger("app").warning(f"T-10: MCP 连接关闭异常: {e}")
    app_state.mcp_client_list.clear()
    app_state.HA_client = app_state.ChromeMCP_client = app_state.sql_client = None
    temp_sweep_task.cancel()


async def _temp_sweep_loop():
    """T-10：tool_temp/桌面截图等临时目录的周期清扫（原仅启动一次）。"""
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            await clean_temp_files_task()
        except Exception as e:
            logging.getLogger("app").warning(f"T-10 周期临时目录清扫失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sap_auth.write_token_file(USER_DATA_DIR)
    sap_auth.ensure_machine_token(USER_DATA_DIR)
    # --- [核心防御] 立即清理系统环境变量中的 SOCKS 代理，防止 httpx 崩溃 ---
    for env_key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        val = os.environ.get(env_key, "")
        if val.lower().startswith('socks'):
            # 彻底移除会导致崩溃的 socks 环境变量
            os.environ.pop(env_key, None)

    # 基础初始化
    await _copy_default_skills()
    
    # 1. 准备所有独立的初始化任务
    from py.get_setting import init_db, init_covs_db, load_settings, save_settings
    from tzlocal import get_localzone
    
    asyncio.create_task(clean_temp_files_task())
    temp_sweep_task = asyncio.create_task(_temp_sweep_loop())  # T-10
    
    # 并行执行耗时操作
    init_db_task = init_db()
    init_covs_task = init_covs_db()
    load_locales_task = asyncio.to_thread(lambda: json.load(open(base_path + "/config/locales.json", "r", encoding="utf-8")))
    settings_task = load_settings() 
    timezone_task = asyncio.to_thread(get_localzone)
    
    results = await asyncio.gather(
        init_db_task, 
        init_covs_task, 
        load_locales_task, 
        settings_task, 
        timezone_task
    )
    
    # 2. 解包结果
    global settings, client, reasoner_client, fast_client, local_timezone, logger, locales, scheduler_task, sleep_guard, diary_engine_task
    _, _, locales, settings, local_timezone = results
    
    # --- [M4-lite: 启动数据快照（滚动5份、1h 节流、失败不阻塞启动）] ---
    async def _startup_snapshot():
        try:
            from py.data_backup import snapshot_data_dir
            # 开关持久化域=systemSettings 子对象（前端开关所在层），兼容顶层旧写法
            _s = settings or {}
            include = bool(((_s.get("systemSettings") or {}).get("backupIncludeUploads")
                            or _s.get("backupIncludeUploads") or False))
            res = await asyncio.to_thread(snapshot_data_dir, USER_DATA_DIR, 5, include)
            if res.get("ok"):
                logging.getLogger("app").info(f"[Backup] 启动快照完成: {os.path.basename(res.get('snap', ''))} ({res.get('files')} 文件 / {res.get('bytes')} B)")
            elif res.get("skipped"):
                logging.getLogger("app").info("[Backup] 启动快照节流跳过（距上次 <1h）")
            else:
                logging.getLogger("app").info(f"[Backup] 启动快照失败: {res.get('reason')}")
        except Exception as e:
            logging.getLogger("app").info(f"[Backup] 启动快照异常: {e}")
    asyncio.create_task(_startup_snapshot())
    
    # --- [M4-B2': 启动对账探针（只读，mismatch 仅告警留证据，不影响启动）] ---
    async def _startup_reconcile():
        try:
            from py import covs_reconcile
            blob_map, rows_map, traces = await asyncio.to_thread(covs_reconcile.load_maps, COVS_PATH)
            r = covs_reconcile.reconcile(blob_map, rows_map, traces)
            if not r["consistent"]:
                logging.getLogger("app").info(f"[Reconcile] 会话 blob/行级影子不一致: blob-only={len(r['blob_only'])} "
                      f"rows-only={len(r['rows_only'])} content-mismatch={len(r['content_mismatch'])}"
                      f"；建议运行 python py/covs_reconcile.py --out report.md")
            else:
                logging.getLogger("app").info(f"[Reconcile] 会话一致性对账通过（{r['blob_conversations']} 会话）")
        except Exception as e:
            logging.getLogger("app").info(f"[Reconcile] 对账探针跳过: {e}")
    asyncio.create_task(_startup_reconcile())
    
    from py.sleep_guard import SleepGuard
    sleep_guard = SleepGuard(verbose=True)
    try:
        await asyncio.to_thread(sleep_guard.start)
        if sleep_guard.is_running():
            logging.getLogger("app").info("🛡️ 防休眠保护已启动，系统将不会自动休眠")
        else:
            logging.getLogger("app").info("⚠️ 防休眠启动失败，系统可能会在空闲时休眠")
    except Exception as e:
        logging.getLogger("app").info(f"防休眠启动异常: {e}")


    from py.scheduler import AgentScheduler
    # 传入全局 settings 对象的引用
    # 因为 python 字典是引用传递，后续 UI 修改了 settings，这里拿到的也是最新的
    scheduler = AgentScheduler(settings)
    scheduler_task = asyncio.create_task(scheduler.start_loop())

    # --- [日记系统引擎初始化] ---
    # 引擎循环常驻，未启用时空转；保存设置时通过 update_config 热更新。
    try:
        from py.diary_engine import global_diary_engine
        global_diary_engine.update_config((settings or {}).get("diarySettings"))
        diary_engine_task = asyncio.create_task(global_diary_engine.start())
    except Exception as e:
        logging.getLogger("app").error(f"日记引擎启动异常: {e}")
        diary_engine_task = None

    # --- [日志系统初始化] ---
    from py.log_setup import setup_logger
    logger = setup_logger(LOG_DIR)
    logger.info("===== 日志系统初始化成功 =====\n[Version] " + _version_fingerprint())

    # --- [代理与 HTTP 客户端初始化] ---
    proxy_url = None
    trust_env = False
    
    if settings:
        sys_set = settings.get("systemSettings", {})
        mode = sys_set.get("proxyMode")
        manual_url = sys_set.get("proxy", "").strip()
        isChinaProxy = sys_set.get("isChinaProxy", False)

        # S85-D：normalize 容错——代理栏任何形态（http/socks5h/裸host:port/垃圾）
        # 都只会得到 None+warning，永不炸启动；env 兜底让全部 SDK 同步生效
        from py.proxy_util import apply_env_proxy, normalize_proxy_url
        if mode == "manual":
            proxy_url = normalize_proxy_url(manual_url)
        elif mode == "system":
            trust_env = True
        apply_env_proxy(settings)
        if isChinaProxy:
            # 2. 注入 Node.js / NPM 镜像源 (重点)
            # 设置这个环境变量后，所有的 npm install (包括你的 node_runner) 都会默认使用这个源
            os.environ["npm_config_registry"] = "https://registry.npmmirror.com/"
            
            # 3. 注入 UV / Pip 镜像源 (重点)
            # 这样后续如果调用 uv 或 pip，也会自动使用国内镜像
            os.environ["UV_INDEX_URL"] = "https://mirrors.aliyun.com/pypi/simple/"

    # 初始化全局带连接池的 HTTP 客户端
    timeout_config = httpx.Timeout(None, connect=10.0)
    try:
        app_state.global_http_client = httpx.AsyncClient(
            timeout=timeout_config, proxy=proxy_url, trust_env=trust_env)
    except Exception as _px_e:  # S85-D：socks 依赖缺失等 → 降级直连，绝不阻断启动
        logger.error(f"HTTP 客户端带代理初始化失败（{_px_e}），已降级为直连")
        app_state.global_http_client = httpx.AsyncClient(
            timeout=timeout_config, trust_env=False)

    # --- [模型 Client 初始化] ---
    # 辅助函数：统一注入 app_state.global_http_client
    def create_model_client(provider_key, config_node=None):
        if not settings: return AsyncOpenAI(http_client=app_state.global_http_client)
        
        target_cfg = config_node if config_node else settings
        p_name = target_cfg.get('selectedProvider', settings.get('selectedProvider'))
        c_cls = get_client_class(settings, p_name)
        
        return c_cls(
            api_key=target_cfg.get('api_key') or settings.get('api_key', ''),
            base_url=target_cfg.get('base_url') or settings.get('base_url') or "https://api.openai.com/v1",
            http_client=app_state.global_http_client  # 强制使用我们定义的带代理控制的客户端
        )

    if settings:
        client = create_model_client('main')
        reasoner_client = create_model_client('reasoner', settings.get('reasoner', {}))
        
        fast_cfg = settings.get('fast', {})
        if fast_cfg.get('enabled'):
            fast_client = create_model_client('fast', fast_cfg)
        else:
            fast_client = None
    else:
        client = AsyncOpenAI(http_client=app_state.global_http_client)
        reasoner_client = AsyncOpenAI(http_client=app_state.global_http_client)
        fast_client = AsyncOpenAI(http_client=app_state.global_http_client)

    # --- [其他初始化：ASR / MCP] ---
    try:
        from py.sherpa_asr import _get_recognizer
        asyncio.get_running_loop().run_in_executor(None, _get_recognizer)
    except Exception as e:
        logger.error(f"尝试启动sherpa失败: {e}")

    try:
        from py.moss_tts import _get_moss_runtime
        # 将重型的本地 TTS 加载也扔到后台线程池，如果没有下载模型它只会静默返回 None
        asyncio.get_running_loop().run_in_executor(None, _get_moss_runtime)
    except Exception as e:
        logger.error(f"尝试预热 MOSS TTS 失败: {e}")

    # MCP 初始化逻辑 (保持你原有的逻辑，但内部会复用 app_state.global_http_client)
    mcp_init_tasks = []

    async def init_mcp_with_timeout(server_name: str, server_config: dict, timeout=6.0, max_wait_failure=5.0):
        if server_config.get("disabled"):
            return server_name, None, "disabled"
        
        mcp_client = app_state.mcp_client_list.get(server_name) or McpClient()
        app_state.mcp_client_list[server_name] = mcp_client
        failure_event = asyncio.Event()
        first_error = None

        async def on_failure(msg: str):
            nonlocal first_error
            if first_error: return
            first_error = msg
            logger.error(f"MCP {server_name} failure: {msg}")
            settings.setdefault("mcpServers", {}).setdefault(server_name, {})["disabled"] = True
            mcp_client.disabled = True
            await mcp_client.close()
            failure_event.set()

        init_task = asyncio.create_task(mcp_client.initialize(server_name, server_config, on_failure_callback=on_failure))
        try:
            await asyncio.wait_for(init_task, timeout=timeout)
            try:
                await asyncio.wait_for(failure_event.wait(), timeout=max_wait_failure)
            except asyncio.TimeoutError:
                pass
            return server_name, (None if first_error else mcp_client), first_error
        except Exception as exc:
            return server_name, None, str(exc)
        finally:
            if not init_task.done(): init_task.cancel()

    async def check_results():
        for task in asyncio.as_completed(mcp_init_tasks):
            name, m_client, err = await task
            if err:
                settings['mcpServers'][name]['processingStatus'] = 'server_error'
            elif m_client:
                app_state.mcp_client_list[name] = m_client
        await save_settings(settings)
        await ws_manager.broadcast_settings_update(settings)

    if settings and settings.get('mcpServers'):
        mcp_init_tasks = [asyncio.create_task(init_mcp_with_timeout(k, v)) for k, v in settings['mcpServers'].items()]
        if mcp_init_tasks: asyncio.create_task(check_results())
    else:
        asyncio.create_task(ws_manager.broadcast_settings_update(settings or {}))

    # --- [心跳维持机制] ---
    async def heartbeat_loop():
        try:
            while True:
                await asyncio.sleep(10)  # 心跳间隔10秒，必须在uvicorn ws_ping_interval(20s)内完成，防止1006断开
                await ws_manager.send_heartbeat()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}")

    heartbeat_task = asyncio.create_task(heartbeat_loop())
    logger.info("WebSocket heartbeat task started")

    # --- [IM bot 自动连接] ---
    async def autostart_im_bots():
        import importlib
        getter_map = {key: getter for key, _m, _c, getter in BOT_AUTOSTART_TABLE}
        for cfg_key, mod_name, cls_name in _bot_autostart_plan(settings):
            async def _boot(cfg_key=cfg_key, mod_name=mod_name, cls_name=cls_name):
                try:
                    raw = dict((settings or {}).get(cfg_key) or {})
                    cfg_cls = getattr(importlib.import_module(mod_name), cls_name)
                    await asyncio.to_thread(getattr(BotContainer, getter_map[cfg_key])().start_bot,
                                            cfg_cls(**raw))
                    logger.info(f"IM 自动连接成功: {cfg_key}")
                except Exception as e:
                    logger.warning(f"IM 自动连接失败 {cfg_key}: {e}")
            asyncio.create_task(_boot())

    asyncio.create_task(autostart_im_bots())

    # --- [T-4 流缓存 TTL 清扫] ---
    stream_ttl_task = asyncio.create_task(_stream_ttl_loop())

    # --- [启动完成] ---
    yield

    # --- [关闭逻辑] ---
    logging.getLogger("app").info("System shutting down, cleaning up...")
    try:
        stream_ttl_task.cancel()
    except Exception:
        pass

    try:
        await asyncio.to_thread(sleep_guard.stop)
        logging.getLogger("app").info("🛡️ 防休眠保护已停止，系统将恢复正常休眠策略")
    except Exception as e:
        logging.getLogger("app").info(f"防休眠停止异常: {e}")

    if scheduler_task:
        scheduler_task.cancel()
    try:
        if diary_engine_task:
            from py.diary_engine import global_diary_engine
            global_diary_engine.stop()
            diary_engine_task.cancel()
    except Exception as e:
        logging.getLogger("app").info(f"日记引擎停止异常: {e}")
    ext_ids = list(node_mgr.exts.keys())
    for ext_id in ext_ids:
        try: await node_mgr.stop(ext_id)
        except: pass
        
    await _t10_shutdown(temp_sweep_task)
    if app_state.global_http_client:
        await app_state.global_http_client.aclose()
    logging.getLogger("app").info("All processes terminated.")


app = FastAPI(lifespan=lifespan)

# M2 (X-5): 全站通配 CORS 已拆除。仅 /v1 与 /mcp（用户保留的对外接口）响应跨源，
# 内部 API 一律同源 + session token；OPTIONS 预检只对这两个前缀应答。
_EXTERNAL_PREFIXES = ("/v1", "/mcp")

from py import app_state
from py.voice import router as voice_router
from py.bot_container import (BOT_AUTOSTART_TABLE, BotContainer,
                                  _bot_autostart_plan, sync_all_bots_behavior)
from py.stream_relay import (
    _active_streams, _active_streams_lock, _current_stream_entry, _stream_cancelled,
    _stream_producer_wrapper, _stream_consumer_generator,
    _stream_ttl_loop, _cleanup_stream,
)
from py.routers import (media, bots, memories, system, files,
                        bot_conversations, tasks, agents, workflows,
                        status)
app.include_router(media.router)
app.include_router(bots.router)
app.include_router(memories.router)
app.include_router(system.router)
app.include_router(files.router)
app.include_router(bot_conversations.router)
app.include_router(tasks.router)
app.include_router(agents.router)
app.include_router(workflows.router)
app.include_router(status.router)
app.include_router(voice_router)  # 批 1c：/ws/asr /ws/tts /ws/vrm /ws/subtitles
from py.diary_api import router as diary_router  # A5：/api/diary/*（book CRUD + 查询）
app.include_router(diary_router)

@app.middleware("http")
async def external_api_cors(request: Request, call_next):
    path = request.url.path
    if path.startswith(_EXTERNAL_PREFIXES):
        if request.method == "OPTIONS":
            return Response(
                status_code=200,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                    "Access-Control-Allow-Headers": "Authorization, Content, Content-Type, Accept",
                    "Access-Control-Max-Age": "86400",
                }
            )
        response = await call_next(request)
        response.headers["Access-Control-Allow-Origin"] = "*"
        # C-14: 暴露流 id 响应头，跨源客户端在 meta 帧前即可 resume/cancel
        response.headers["Access-Control-Expose-Headers"] = "X-Stream-Id"
        return response
    return await call_next(request)

@app.middleware("http")
async def auth_guard(request: Request, call_next):
    # M2: loopback session-token kernel (X-1/X-2/X-10)
    if not sap_auth.is_exempt(request.url.path):
        if not sap_auth.host_ok(request):
            return JSONResponse(status_code=403,
                                content={"error": {"message": "forbidden host"}})
        if not sap_auth.origin_ok(request):
            return JSONResponse(status_code=403,
                                content={"error": {"message": "forbidden origin"}})
        if not sap_auth.token_ok(request):
            return JSONResponse(status_code=401,
                                content={"error": {"message": "missing or invalid session token"}})
    return await call_next(request)

@app.get("/session_token")
async def session_token(request: Request):
    # Same-origin bootstrap: browser pages fetch this once; the Lax cookie then
    # rides along on all fetch AND WebSocket handshakes automatically.
    if not sap_auth.origin_ok(request):
        return JSONResponse(status_code=403,
                            content={"error": {"message": "forbidden origin"}})
    if sap_auth.DISABLED:
        return JSONResponse(content={"token": "", "disabled": True})
    resp = JSONResponse(content={"token": sap_auth.SESSION_TOKEN})
    resp.set_cookie(sap_auth.COOKIE, sap_auth.SESSION_TOKEN,
                    httponly=False, samesite="lax", secure=False)
    return resp

async def t(text: str) -> str:
    global locales
    settings = await load_settings()
    target_language = settings["currentLanguage"]
    return locales[target_language].get(text, text)


# 全局存储异步工具状态
async_tools = {}
async_tools_lock = asyncio.Lock()

async def execute_tool(tool_id: str, tool_name: str, args: dict, settings: dict,user_prompt: str):
    try:
        results = await dispatch_tool(tool_name, args, settings)
        if isinstance(results, AsyncIterator):
            buffer = []
            async for chunk in results:
                buffer.append(chunk)
            results = "".join(buffer)
                
        if tool_name in ["query_knowledge_base"] and type(results) == list:
            from py.know_base import rerank_knowledge_base
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt,results)
            results = json.dumps(results, ensure_ascii=False, indent=4)
        async with async_tools_lock:
            async_tools[tool_id] = {
                "status": "completed",
                "result": results,
                "name": tool_name,
                "parameters": args,
            }
    except Exception as e:
        async with async_tools_lock:
            async_tools[tool_id] = {
                "status": "error",
                "result": str(e),
                "name": tool_name,
                "parameters": args,
            }

async def get_image_content(image_url: str) -> str:
    import hashlib
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url= f"data:{media_type};base64,{base64_image}"
    image_hash = hashlib.md5(image_url.encode()).hexdigest()
    content = ""
    if settings['vision']['enabled']:
        # 如果uploaded_files/{item['image_url']['hash']}.txt存在，则读取文件内容，否则调用vision api
        if os.path.exists(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt")):
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "r", encoding='utf-8') as f:
                content += f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(f.read())+"\n\n"
        else:
            images_content = [{"type": "text", "text": "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"},{"type": "image_url", "image_url": {"url": url}}]
            client = AsyncOpenAI(api_key=settings['vision']['api_key'],base_url=settings['vision']['base_url'])
            
            extra = {}

            if settings['vision']['temperature'] !=1:
                extra['temperature'] = settings['vision']['temperature']
            
            response = await client.chat.completions.create(
                model=settings['vision']['model'],
                messages = [{"role": "user", "content": images_content}],
                **extra
            )
            content = f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(response.choices[0].message.content)+"\n\n"
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "w", encoding='utf-8') as f:
                f.write(str(response.choices[0].message.content))
    else:           
        # 如果uploaded_files/{item['image_url']['hash']}.txt存在，则读取文件内容，否则调用vision api
        if os.path.exists(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt")):
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "r", encoding='utf-8') as f:
                content += f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(f.read())+"\n\n"
        else:
            images_content = [{"type": "text", "text": "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"},{"type": "image_url", "image_url": {"url": url}}]
            client = AsyncOpenAI(api_key=settings['api_key'],base_url=settings['base_url'])
            
            extra = {}

            if settings['temperature'] !=1:
                extra['temperature'] = settings['temperature']
            
            response = await client.chat.completions.create(
                model=settings['model'],
                messages = [{"role": "user", "content": images_content}],
                **extra
            )
            content = f"\n\n图片(URL:{image_url} 哈希值：{image_hash})信息如下：\n\n"+str(response.choices[0].message.content)+"\n\n"
            with open(os.path.join(UPLOAD_FILES_DIR, f"{image_hash}.txt"), "w", encoding='utf-8') as f:
                f.write(str(response.choices[0].message.content))
    return content

async def analyze_image(image_url: str, prompt: str) -> str:
    """针对特定提示词分析图像，不使用通用描述缓存"""
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url = f"data:{media_type};base64,{base64_image}"
    
    if settings['vision']['enabled']:
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if settings['vision']['temperature'] != 1:
            extra['temperature'] = settings['vision']['temperature']
        
        response = await client.chat.completions.create(
            model=settings['vision']['model'],
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]}],
            **extra
        )
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if settings['temperature'] != 1:
            extra['temperature'] = settings['temperature']
        response = await client.chat.completions.create(
            model=settings['model'],
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": url}}]}],
            **extra
        )
        return response.choices[0].message.content

async def analyze_images(image_urls: list, prompt: str) -> str:
    """一次性将多张图片交给VLM联合分析或比较，每张图前附序号标记便于模型指代"""
    settings = await load_settings()
    if not image_urls:
        return "错误：image_urls 不能为空"
    content = [{"type": "text", "text": prompt}]
    for index, image_url in enumerate(image_urls, start=1):
        base64_image = await get_image_base64(image_url)
        media_type = await get_image_media_type(image_url, base64_image)
        content.append({"type": "text", "text": f"【第{index}张图】"})
        content.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{base64_image}"}})

    if settings['vision']['enabled']:
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if settings['vision']['temperature'] != 1:
            extra['temperature'] = settings['vision']['temperature']
        response = await client.chat.completions.create(
            model=settings['vision']['model'],
            messages=[{"role": "user", "content": content}],
            **extra
        )
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if settings['temperature'] != 1:
            extra['temperature'] = settings['temperature']
        response = await client.chat.completions.create(
            model=settings['model'],
            messages=[{"role": "user", "content": content}],
            **extra
        )
        return response.choices[0].message.content

async def review_image(image_url: str, prompt: str) -> str:
    """基于对话上下文审查图像，使VLM像读连环画一样理解图像在对话中的位置和意义
    
    截断行为由 vision.contextTruncation 配置控制：
    - False（默认）：完整传递对话历史，不做任何截断。适用于本地部署等不在意token数的场景。
    - True：启用截断以节省token。会剥离思考内容，限制历史条数，截断过长消息。
    """
    settings = await load_settings()
    base64_image = await get_image_base64(image_url)
    media_type = await get_image_media_type(image_url, base64_image)
    url = f"data:{media_type};base64,{base64_image}"
    
    # 读取截断配置，默认不截断（完整传递上下文，审查质量最高）
    vision_cfg = settings.get('vision', {})
    context_truncation = vision_cfg.get('contextTruncation', False)
    
    # 从 contextvars 获取当前对话历史
    raw_messages = current_request_messages.get() or []
    
    # 构建上下文消息：只保留文本，去除图片以节省token
    context_messages = [
        {"role": "system", "content": "你是一个图像审查助手。你需要基于对话上下文来审查图像是否符合要求。以下是之前的对话历史，请结合上下文理解当前图像的意义："}
    ]
    
    if context_truncation:
        # ===== 截断模式：节省token，适合云端API =====
        # 限制历史长度
        recent_messages = raw_messages[-20:] if len(raw_messages) > 20 else raw_messages
        for msg in recent_messages:
            content = msg.get('content', '')
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue
            # 如果content是list（图文混合），只提取文本部分
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                content = '\n'.join(text_parts)
            if content and isinstance(content, str) and content.strip():
                # 剥离思考内容（深度思考模式下，思考过程可能很长但审查图像通常不需要看AI的内心独白）
                # 匹配 <think>...</think> 或 ༞...༎ 或 <thought>...</thought> 等常见思考标签
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL)
                content = re.sub(r'༎.*?༎', '', content, flags=re.DOTALL)
                content = re.sub(r'<thought>.*?</thought>', '', content, flags=re.DOTALL)
                content = content.strip()
                # 截断过长的单条消息
                if len(content) > 500:
                    content = content[:500] + "...(已截断)"
                if content:
                    context_messages.append({"role": role, "content": content})
    else:
        # ===== 完整模式（默认）：不截断，完整传递上下文 =====
        # 适用于本地部署等不在意token数的场景，审查质量最高
        for msg in raw_messages:
            content = msg.get('content', '')
            role = msg.get('role', '')
            if role not in ('user', 'assistant'):
                continue
            # 如果content是list（图文混合），只提取文本部分（图片已单独传给VLM，无需重复）
            if isinstance(content, list):
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get('type') == 'text':
                        text_parts.append(item.get('text', ''))
                content = '\n'.join(text_parts)
            if content and isinstance(content, str) and content.strip():
                context_messages.append({"role": role, "content": content})
    
    # 添加实际的审查请求（带图片）
    context_messages.append({
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": url}}
        ]
    })
    
    # 调用VLM
    if settings['vision']['enabled']:
        client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
        extra = {}
        if settings['vision']['temperature'] != 1:
            extra['temperature'] = settings['vision']['temperature']
        response = await client.chat.completions.create(
            model=settings['vision']['model'],
            messages=context_messages,
            **extra
        )
        return response.choices[0].message.content
    else:
        client = AsyncOpenAI(api_key=settings['api_key'], base_url=settings['base_url'])
        extra = {}
        if settings['temperature'] != 1:
            extra['temperature'] = settings['temperature']
        response = await client.chat.completions.create(
            model=settings['model'],
            messages=context_messages,
            **extra
        )
        return response.choices[0].message.content

# 存储等待中的MCP调用结果
mcp_call_results: Dict[str, asyncio.Future] = {}

async def call_node_extension_tool(ext_id: str, tool_name: str, tool_params: dict) -> str:
    """通过WebSocket调用Node扩展的工具"""
    import uuid
    
    call_id = str(uuid.uuid4())
    future = asyncio.Future()
    mcp_call_results[call_id] = future
    
    # 广播给所有连接，找到对应的扩展
    await ws_manager.broadcast({
        "type": "call_mcp_tool",
        "data": {
            "ext_id": ext_id,
            "tool_name": tool_name,
            "tool_params": tool_params,
            "call_id": call_id
        }
    })
    
    try:
        # 等待结果，超时30秒
        result = await asyncio.wait_for(future, timeout=30.0)
        return str(result)
    except asyncio.TimeoutError:
        return f"调用扩展 {ext_id} 的工具 {tool_name} 超时"
    finally:
        if call_id in mcp_call_results:
            del mcp_call_results[call_id]


def _build_tool_hooks():
    """Tool-name -> callable table (audit 09 M-3: built once on first use).

    Imports stay function-local so aliases (e.g. py.utility_tools.time) do
    not leak into module scope; only the resulting dict is published to the
    module-level _TOOL_HOOKS that dispatch_tool and audit tooling read.
    """
    global _TOOL_HOOKS
    from py.web_search import (
        DDGsearch, 
        searxng,
        Tavily_search,
        Bing_search,
        Google_search,
        Brave_search,
        Exa_search,
        Serper_search,
        bochaai_search,
        youcom_search,
        jina_crawler,
        Crawl4Ai_search,
        firecrawl_search,
        simple_fetch,
        markdown_new,
        make_engine_with_fallback as _fb, browser_search,
    )
    from py.know_base import query_knowledge_base
    from py.agent_tool import agent_tool_call
    from py.a2a_tool import a2a_tool_call
    from py.llm_tool import custom_llm_tool
    from py.pollinations import pollinations_image,openai_image,openai_chat_image
    from py.load_files import get_file_content
    from py.code_interpreter import e2b_code,local_run_code
    from py.custom_http import fetch_custom_http
    from py.comfyui_tool import comfyui_tool_call
    from py.utility_tools import (
        time,
        get_weather,
        get_location_coordinates,
        get_weather_by_city,
        get_wikipedia_summary_and_sections,
        get_wikipedia_section_content,
        search_arxiv_papers
    )
    from py.autoBehavior import auto_behavior

    # Docker CLI 工具（原有）
    from py.cli_tool import (
        docker_sandbox,
        list_files_tool,
        read_file_tool,
        read_file_range_tool, 
        tail_file_tool,     
        search_files_tool,
        edit_file_tool,
        edit_file_patch_tool, 
        glob_files_tool,       
        todo_write_tool, 
        list_processes_tool,
        get_process_logs_tool,
        kill_process_tool,
        docker_manage_ports_tool,
        read_skill_tool,
    )

    # 新增：本地环境 CLI 工具（假设保存在 py/local_cli_tool.py）
    from py.cli_tool import (
        shell_tool_local,           # 本地 bash 执行（对应 docker_sandbox）
        list_files_tool_local,     # 本地文件列表
        read_file_tool_local,      # 本地文件读取
        read_file_range_tool_local, # <--- 新增导入
        tail_file_tool_local,       # <--- 新增导入
        search_files_tool_local,   # 本地文件搜索
        edit_file_tool_local,      # 本地文件写入
        edit_file_patch_tool_local,# 本地精确替换
        glob_files_tool_local,     # 本地 glob 查找
        todo_write_tool_local,     # 本地任务管理
        local_net_tool,            # 本地网络工具
        read_skill_tool_local,
    )

    from py.cdp_tool import (
        list_pages,
        navigate_page,
        new_page,
        close_page,
        select_page,
        take_snapshot,
        wait_for,
        click,
        fill,
        hover,
        press_key,
        evaluate_script,
        take_screenshot,
        fill_form,
        drag,
        handle_dialog
    )
    from py.random_topic import get_random_topics,get_categories

    from py.task_tools import (
        create_subtask,
        query_task_progress,
        cancel_subtask,
        finish_task
    )
    
    from py.computer_use_tool import (
        mouse_move,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        mouse_scroll,
        mouse_hold,
        copy_to_input_box,
        keyboard_press,
        keyboard_sequence,
        keyboard_hotkey,
        keyboard_hold,
        wait,
        screenshot
    )

    from py.mode_change import update_workspace_settings
    from py.acpx_tools import acpx_agent

    # ==================== 2. 定义工具映射表 ====================
    _TOOL_HOOKS = {
        "DDGsearch": _fb("duckduckgo", DDGsearch), "browser_lookup": browser_search, "searxng": _fb("searxng", searxng),
        "Tavily_search": _fb("tavily", Tavily_search),
        "query_knowledge_base": query_knowledge_base,
        "jina_crawler": jina_crawler,
        "Crawl4Ai_search": Crawl4Ai_search,
        "firecrawl_search": firecrawl_search,
        "simple_fetch":simple_fetch,
        "markdown_new":markdown_new,
        "agent_tool_call": agent_tool_call,
        "a2a_tool_call": a2a_tool_call,
        "custom_llm_tool": custom_llm_tool,
        "pollinations_image":pollinations_image,
        "get_file_content":get_file_content,
        "get_image_content": get_image_content,
        "analyze_image": analyze_image,
        "review_image": review_image,
        "analyze_images": analyze_images,
        "e2b_code": e2b_code,
        "local_run_code": local_run_code,
        "openai_image": openai_image,
        "openai_chat_image":openai_chat_image,
        "query_diary": handle_query_diary,
        "list_diary_books": handle_list_diary_books,
        "Bing_search": _fb("bing", Bing_search),
        "Google_search": _fb("google", Google_search),
        "Brave_search": _fb("brave", Brave_search),
        "Exa_search": _fb("exa", Exa_search),
        "Serper_search": _fb("serper", Serper_search),
        "bochaai_search": _fb("bochaai", bochaai_search),
        "youcom_search": _fb("youcom", youcom_search),
        "comfyui_tool_call": comfyui_tool_call,
        "time": time,
        "get_weather": get_weather,
        "get_location_coordinates": get_location_coordinates,
        "get_weather_by_city":get_weather_by_city,
        "get_wikipedia_summary_and_sections": get_wikipedia_summary_and_sections,
        "get_wikipedia_section_content": get_wikipedia_section_content,
        "search_arxiv_papers": search_arxiv_papers,
        "auto_behavior": auto_behavior,
        "list_pages": list_pages,
        "new_page": new_page,
        "close_page": close_page,
        "select_page": select_page,
        "navigate_page": navigate_page,
        "take_snapshot": take_snapshot,
        "click": click,
        "fill": fill,
        "evaluate_script": evaluate_script,
        "take_screenshot": take_screenshot,
        "hover": hover,
        "press_key": press_key,
        "wait_for": wait_for,
        "fill_form":fill_form,
        "drag": drag,
        "handle_dialog": handle_dialog,
        "get_random_topics":get_random_topics,
        "get_categories":get_categories,
        
        # Docker Sandbox 相关工具（原有）
        "docker_sandbox": docker_sandbox,
        "list_files_tool": list_files_tool,
        "read_file_tool": read_file_tool,
        "read_file_range_tool": read_file_range_tool, # <--- 映射新工具
        "tail_file_tool": tail_file_tool,             # <--- 映射新工具
        "search_files_tool": search_files_tool,
        "edit_file_tool": edit_file_tool,
        "edit_file_patch_tool": edit_file_patch_tool,
        "glob_files_tool": glob_files_tool,
        "todo_write_tool": todo_write_tool,
        "list_processes_tool": list_processes_tool,
        "get_process_logs_tool": get_process_logs_tool,
        "kill_process_tool": kill_process_tool,
        "docker_manage_ports_tool": docker_manage_ports_tool,
        "read_skill_tool": read_skill_tool,
        
        # 本地环境工具（新增）- 与 Docker 版本功能相同但操作本地文件系统
        "shell_tool_local": shell_tool_local,                     # 本地 bash 执行
        "list_files_tool_local": list_files_tool_local,         # 本地文件列表
        "read_file_tool_local": read_file_tool_local,           # 本地文件读取
        "read_file_range_tool_local": read_file_range_tool_local, # <--- 映射新工具
        "tail_file_tool_local": tail_file_tool_local,             # <--- 映射新工具
        "search_files_tool_local": search_files_tool_local,     # 本地文件搜索
        "edit_file_tool_local": edit_file_tool_local,           # 本地文件写入
        "edit_file_patch_tool_local": edit_file_patch_tool_local,  # 本地精确替换
        "glob_files_tool_local": glob_files_tool_local,         # 本地 glob 查找
        "todo_write_tool_local": todo_write_tool_local,         # 本地任务管理
        "local_net_tool": local_net_tool,                       # 本地网络工具
        "read_skill_tool_local": read_skill_tool_local,         # 本地技能读取

        # 任务中心工具（新增）
        "create_subtask": create_subtask,
        "query_task_progress": query_task_progress,
        "cancel_subtask": cancel_subtask,
        "finish_task":finish_task,

        # 鼠标键盘控制
        "mouse_move":mouse_move,
        "mouse_click":mouse_click,
        "mouse_double_click":mouse_double_click,
        "mouse_drag":mouse_drag,
        "mouse_scroll":mouse_scroll,
        "mouse_hold":mouse_hold,
        "copy_to_input_box":copy_to_input_box,
        "keyboard_press":keyboard_press,
        "keyboard_sequence":keyboard_sequence,
        "keyboard_hotkey":keyboard_hotkey,
        "keyboard_hold":keyboard_hold,
        "wait":wait,
        "screenshot":screenshot,

        "update_workspace_settings":update_workspace_settings,
        "acpx_agent":acpx_agent,
    }



def _plan_mode_block(tool_name, settings):
    """Plan-mode read-only hard block (rule 0). Returns message or None."""
    if tool_name in PLAN_BLOCKED_TOOLS:
        from py.cli_tool import normalize_permission_mode
        _engine0 = settings.get("CLISettings", {}).get("engine", "")
        if _engine0 == "local":
            _env0 = settings.get("localEnvSettings", {})
        elif _engine0 == "ds":
            _env0 = settings.get("dsSettings", {})
        else:
            _env0 = settings.get("acpSettings", {})
        if normalize_permission_mode(_env0.get("permissionMode", "default")) == "plan":
            logging.getLogger("app").info(f"[Permission] plan mode blocked '{tool_name}'")
            return "[Blocked] 你当前处于计划模式（只读），该工具不可用。请使用只读工具完成分析，用自然语言输出执行计划，并等待用户确认后再执行。"

    return None


def _sensitive_approval(tool_name, tool_params, settings):
    """Human-in-the-loop approval gate for SENSITIVE_TOOLS."""
    if tool_name in SENSITIVE_TOOLS:
        
        # 获取相关配置
        cli_settings = settings.get("CLISettings", {})
        cwd = cli_settings.get("cc_path")
        # 修复：local 环境应该从 localEnvSettings 读取权限模式
        engine = cli_settings.get("engine", "")
        
        if engine == "local":
            env_settings = settings.get("localEnvSettings", {})
        elif engine == "ds":
            env_settings = settings.get("dsSettings", {})
        else:
            env_settings = settings.get("acpSettings", {})
        
        permission_mode = cli_permission_mode_for(settings)
        
        is_allowed = False

        # --- 规则 A: 全局 YOLO 模式 (Bypass Permissions) ---
        if permission_mode == "yolo" or permission_mode == "cowork":
            is_allowed = True
            
        # --- 规则 B: 自动批准模式 (Accept Edits) ---
        # 允许文件编辑类工具（包括全量写入、精确替换、任务管理）
        # 但依然拦截终端命令（docker/bash）
        elif permission_mode == "auto-approve":
            if tool_name in ["edit_file_tool", "edit_file_patch_tool", "todo_write_tool", "edit_file_tool_local", "edit_file_patch_tool_local", "todo_write_tool_local"]:
                is_allowed = True
            # docker/bash 等危险命令在此模式下依然默认拦截，除非在项目白名单中
        
        # --- 规则 C: 默认模式 (Default) ---
        # 默认全部拦截
        
        # --- 规则 D: 项目级白名单覆盖 (Project Config Override) ---
        # 如果以上规则未通过，检查 .agent/config.json
        # 如果用户之前点击过 "Allow Always"，这里会返回 True
        if not is_allowed and cwd:
            if is_tool_allowed_by_project_config(cwd, tool_name):
                is_allowed = True
                logging.getLogger("app").info(f"[Permission] Tool '{tool_name}' allowed by project config.")

        # --- 最终判定 ---
        if not is_allowed:
            # 返回前端特定的 JSON 结构，触发审批 UI
            logging.getLogger("app").info(f"[Permission] Blocked '{tool_name}', requesting approval.")
            return _approval_payload(tool_name, tool_params, permission_mode, cwd)

    return None


async def dispatch_tool(tool_name: str, tool_params: dict, settings: dict) -> str | List | AsyncIterator[str] | None :
    global _TOOL_HOOKS, node_ext_mcp_clients, node_ext_mcp_tools
    print("dispatch_tool",tool_name,tool_params)
    
    # ==================== 1. 工具映射表（首次使用时构建一次，M-3 拆分） ====================
    if not _TOOL_HOOKS:
        _build_tool_hooks()
    
    # ==================== 3. 权限拦截逻辑 (Human-in-the-loop) ====================
    # 敏感/受限工具清单单一来源=py/tool_registry.py（E-1，顶部已导入）
    # 规则 0: 计划模式只读硬拦截（对全部写入/执行类工具生效，不经审批弹窗）
    blocked = _plan_mode_block(tool_name, settings)
    if blocked is not None:
        return blocked

    # 只有当调用的工具属于敏感工具列表时才进行拦截检查
    approval = _sensitive_approval(tool_name, tool_params, settings)
    if approval is not None:
        return approval

    # ==================== 4. 常规工具处理逻辑 (原有代码) ====================

    tool_name, handled = await _dispatch_external_tool(tool_name, tool_params, settings)
    if handled is not None:
        return handled
                
    # ==================== 5. 任务中心工具特殊处理 ====================
    if tool_name in ["create_subtask", "query_task_progress", "cancel_subtask","finish_task"]:
        return await _dispatch_task_center_tool(tool_name, tool_params, settings)

    if tool_name not in _TOOL_HOOKS:
        return await _dispatch_unknown_tool(tool_name, tool_params,
                                            set(_TOOL_HOOKS), node_ext_mcp_tools,
                                            call_node_extension_tool, settings)
        
    tool_call = _TOOL_HOOKS[tool_name]
    try:
        if tool_name in ("shell_tool_local", "docker_sandbox"):
            # 异步生成器：调用即返回 AsyncIterator，无需 await
            return tool_call(**tool_params)
        if tool_name == "acpx_agent":
            # 常规异步函数：必须 await 才能获得实际结果
            return await tool_call(**tool_params)

        ret_out = await tool_call(**tool_params)
        if tool_name == "auto_behavior":
            settings = ret_out
            await ws_manager.broadcast_settings_update(settings)
            ret_out = "任务设置成功！"
        return ret_out
    except Exception as e:
        logger.error(f"Error calling tool {tool_name}: {e}")
        return f"Error calling tool {tool_name}: {e}{net_error_hint(e)}"

def process_extra_params(extra_params_list):
    extra_body = {}
    for item in extra_params_list:
        name = item.get('name', '').strip()
        if not name:
            continue
            
        value = item.get('value')
        p_type = item.get('type')

        try:
            if p_type == 'json':  # 合并后的判断
                if isinstance(value, str):
                    extra_body[name] = json.loads(value) if value.strip() else {}
                else:
                    extra_body[name] = value
            elif p_type == 'integer':
                extra_body[name] = int(value)
            elif p_type == 'float':
                extra_body[name] = float(value)
            elif p_type == 'boolean':
                extra_body[name] = bool(value)
            else:
                extra_body[name] = str(value)
        except (json.JSONDecodeError, ValueError) as e:
            logging.getLogger("app").info(f"Error parsing param {name}: {e}")
            extra_body[name] = value 

    return extra_body

class ChatRequest(BaseModel):
    messages: List[Dict]
    model: str = None
    tools: dict = None
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: float = 1
    fileLinks: List[str] = None
    enable_thinking: bool = False
    enable_deep_research: bool = False
    enable_web_search: bool = False
    asyncToolsID: List[str] = None
    reasoning_effort: str = None
    is_app_bot: bool = False
    platform: str = None
    is_sub_agent: bool = False
    enable_tools : List[str] = None
    disable_tools: List[str] = None
    conversation_id: Optional[Union[str, int, float]] = None
    group_id: Optional[Union[str, int, float]] = None
    user_message_id: Optional[Union[str, int, float]] = None

GROUP_MEMORY_TYPES = {"fact", "decision", "preference", "todo", "constraint", "glossary"}
GROUP_MEMORY_DONE_HINTS = ("完成", "已完成", "done", "resolved", "fixed", "closed")

def _extract_text_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                texts.append(item.get("text", ""))
        return "\n".join(filter(None, texts))
    return ""

def _memory_tokens(text: str) -> set[str]:
    if not text:
        return set()
    tokens = re.findall(r'[\u4e00-\u9fff]{1,6}|[a-zA-Z0-9_]{2,}', text.lower())
    return set(tokens)

def _normalize_memory_text(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').strip().lower())

def _normalize_entity_id(value: Optional[Union[str, int, float]]) -> str:
    if value is None:
        return ""
    return str(value).strip()

def _merge_group_memories(*memory_lists: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for memory_list in memory_lists:
        for item in memory_list or []:
            if not isinstance(item, dict):
                continue
            memory_type = str(item.get("memory_type", "")).strip().lower()
            summary = str(item.get("summary", "")).strip()
            content = str(item.get("content", "")).strip()
            if memory_type not in GROUP_MEMORY_TYPES or not summary or not content:
                continue
            dedupe_key = (
                memory_type,
                _normalize_memory_text(summary),
                _normalize_memory_text(content),
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            merged.append({
                "memory_type": memory_type,
                "summary": summary,
                "content": content,
                "importance": max(0.0, min(1.0, float(item.get("importance", 0.5) or 0.5))),
            })
    return merged

async def _load_group_map() -> dict:
    covs = await load_covs()
    groups = covs.get("conversationGroups", []) or []
    group_map = {"default": {"id": "default", "name": "Ungrouped", "memoryConfig": {}}}
    for group in groups:
        if group and group.get("id"):
            group_map[group["id"]] = group
    return group_map

async def _fetch_group_memories(group_id: str, query_text: str, top_k: int = 6) -> list[dict]:
    if not group_id:
        return []
    query_tokens = _memory_tokens(query_text)
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM group_memory
            WHERE group_id = ? AND status = 'active'
            ORDER BY updated_at DESC
            """,
            (group_id,),
        ) as cursor:
            rows = [dict(row) for row in await cursor.fetchall()]

    def score_memory(item: dict) -> float:
        text = f"{item.get('summary', '')}\n{item.get('content', '')}"
        overlap = len(query_tokens & _memory_tokens(text))
        importance = float(item.get("importance") or 0)
        recency = float(item.get("updated_at") or 0) / 1_000_000_000_000
        return overlap * 5 + importance * 2 + recency

    ranked = sorted(rows, key=score_memory, reverse=True)
    selected = ranked[:top_k]
    if selected:
        now_ts = int(time.time() * 1000)
        import aiosqlite
        async with aiosqlite.connect(COVS_PATH) as db:
            await db.executemany(
                "UPDATE group_memory SET last_used_at = ? WHERE id = ?",
                [(now_ts, item["id"]) for item in selected],
            )
            await db.commit()
    return selected

def _build_group_memory_prompt(group: dict, memories: list[dict]) -> str:
    if not memories:
        return ""
    header = [
        f"当前对话分组: {group.get('name') or group.get('id')}",
        "以下是仅限当前分组可用的长期记忆，请只在相关时使用，不要臆测或扩展未确认的信息。",
        "如果记忆中包含具体值，请优先直接复述具体值，不要用“见记忆条目”或占位说明代替：",
    ]
    lines = []
    for idx, memory in enumerate(memories, 1):
        summary = str(memory.get('summary') or '').strip()
        content = str(memory.get('content') or '').strip()
        memory_type = memory.get('memory_type', 'fact')
        if summary and content and summary != content:
            lines.append(f"{idx}. [{memory_type}] 摘要: {summary}")
            lines.append(f"   具体内容: {content}")
        else:
            lines.append(f"{idx}. [{memory_type}] {content or summary}")
    return "\n".join(header + lines)

def _trim_request_messages(messages: List[Dict], recent_count: int = 12) -> List[Dict]:
    system_messages = [copy.deepcopy(m) for m in messages if m.get("role") == "system"]
    dialog_messages = [copy.deepcopy(m) for m in messages if m.get("role") != "system"]
    return system_messages + dialog_messages[-recent_count:]

async def _apply_group_memory_context(request: ChatRequest) -> dict:
    request.conversation_id = _normalize_entity_id(request.conversation_id) or None
    request.user_message_id = _normalize_entity_id(request.user_message_id) or None
    request.group_id = _normalize_entity_id(request.group_id) or "default"
    group_id = request.group_id or "default"
    if not group_id or group_id == "default":
        request.messages = _trim_request_messages(request.messages)
        return {"enabled": False, "group_id": group_id}

    group_map = await _load_group_map()
    group = group_map.get(group_id)
    memory_enabled = bool(group and (group.get("memoryConfig") or {}).get("enabled"))

    request.messages = _trim_request_messages(request.messages)
    if not memory_enabled:
        return {"enabled": False, "group_id": group_id, "group": group}

    last_user_text = ""
    for msg in reversed(request.messages):
        if msg.get("role") == "user":
            last_user_text = _extract_text_content(msg.get("content"))
            break

    memories = await _fetch_group_memories(group_id, last_user_text, top_k=6)
    memory_prompt = _build_group_memory_prompt(group or {"id": group_id, "name": group_id}, memories)
    if memory_prompt:
        content_append(request.messages,'system',memory_prompt)
    return {"enabled": memory_enabled, "group_id": group_id, "group": group, "memories": memories}

async def _extract_group_memories(client, settings: dict, payload: dict) -> list[dict]:
    user_message = (payload.get("user_message") or "").strip()
    assistant_message = (payload.get("assistant_message") or "").strip()
    if not user_message or not assistant_message:
        return []

    extraction_prompt = (
        "你是一个结构化记忆提取器。只提取后续同组对话可复用的长期信息，"
        "不要总结整段聊天，不要保留闲聊、猜测、情绪宣泄、不确定信息和重复信息。"
        "只允许 memory_type 为 fact、decision、preference、todo、constraint、glossary。"
        "返回 JSON 数组，每项字段必须包含 memory_type、content、summary、importance。"
        "importance 取 0 到 1。若没有可提取记忆，返回 []。"
    )

    example_input = f"用户消息:\n{user_message}\n\n助手回复:\n{assistant_message}"

    def fallback_memories() -> list[dict]:
        combined = f"{user_message}\n{assistant_message}"
        results = []
        if any(keyword in combined.lower() for keyword in ["决定", "采用", "使用", "choose", "decide", "use "]):
            results.append({
                "memory_type": "decision",
                "summary": assistant_message[:120] or user_message[:120],
                "content": assistant_message or user_message,
                "importance": 0.82,
            })
        if any(keyword in combined.lower() for keyword in ["偏好", "喜欢", "prefer", "preferred"]):
            results.append({
                "memory_type": "preference",
                "summary": user_message[:120],
                "content": user_message,
                "importance": 0.72,
            })
        if any(keyword in combined.lower() for keyword in ["限制", "必须", "不能", "constraint", "must", "cannot", "can't"]):
            results.append({
                "memory_type": "constraint",
                "summary": (user_message or assistant_message)[:120],
                "content": user_message or assistant_message,
                "importance": 0.78,
            })
        if any(keyword in combined.lower() for keyword in ["todo", "待办", "后续", "需要", "next"]):
            results.append({
                "memory_type": "todo",
                "summary": user_message[:120],
                "content": user_message,
                "importance": 0.68,
            })
        return _merge_group_memories(results)

    try:
        extra_params = settings.get('extra_params') or []
        extra_body = process_extra_params(extra_params)
        response = await client.chat.completions.create(
            model=settings['model'],
            messages=[
                {"role": "system", "content": extraction_prompt},
                {"role": "user", "content": example_input},
            ],
            temperature=0.1,
            stream=False,
            extra_body=extra_body,
        )
        content = response.choices[0].message.content or "[]"
        if "```json" in content:
            match = re.search(r'```json(.*?)```', content, re.DOTALL)
            content = match.group(1) if match else content.replace("```json", "").replace("```", "")
        data = json.loads(content)
    except Exception as e:
        logger.warning(f"Group memory extraction failed: {e}")
        return fallback_memories()

    if not isinstance(data, list):
        return []

    cleaned = []
    for item in data:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("memory_type", "")).strip().lower()
        summary = str(item.get("summary", "")).strip()
        content = str(item.get("content", "")).strip()
        importance = float(item.get("importance", 0.5) or 0.5)
        if memory_type not in GROUP_MEMORY_TYPES or not summary or not content:
            continue
        cleaned.append({
            "memory_type": memory_type,
            "summary": summary,
            "content": content,
            "importance": max(0.0, min(1.0, importance)),
        })
    return _merge_group_memories(cleaned) or fallback_memories()

async def _upsert_group_memories(group_id: str, source_chat_id: str, source_message_id: str, memories: list[dict]) -> None:
    if not group_id or not source_chat_id or not memories:
        return
    now_ts = int(time.time() * 1000)
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        db.row_factory = aiosqlite.Row
        for memory in memories:
            normalized_summary = _normalize_memory_text(memory["summary"])
            normalized_content = _normalize_memory_text(memory["content"])
            async with db.execute(
                """
                SELECT * FROM group_memory
                WHERE group_id = ? AND memory_type = ? AND status = 'active'
                """,
                (group_id, memory["memory_type"]),
            ) as cursor:
                existing_rows = [dict(row) for row in await cursor.fetchall()]

            duplicate = None
            superseded_ids = []
            for row in existing_rows:
                row_summary = _normalize_memory_text(row.get("summary"))
                row_content = _normalize_memory_text(row.get("content"))
                if row_summary == normalized_summary or row_content == normalized_content:
                    duplicate = row
                    break
                if (
                    memory["memory_type"] in {"decision", "preference", "constraint", "todo"}
                    and (normalized_summary in row_summary or row_summary in normalized_summary)
                ):
                    superseded_ids.append(row["id"])

            if memory["memory_type"] == "todo" and any(hint in normalized_content for hint in GROUP_MEMORY_DONE_HINTS):
                superseded_ids.extend([row["id"] for row in existing_rows if row["memory_type"] == "todo"])
                continue

            if duplicate:
                await db.execute(
                    """
                    UPDATE group_memory
                    SET importance = MAX(importance, ?), updated_at = ?, last_used_at = ?
                    WHERE id = ?
                    """,
                    (memory["importance"], now_ts, now_ts, duplicate["id"]),
                )
                continue

            if superseded_ids:
                await db.executemany(
                    "UPDATE group_memory SET status = 'superseded', updated_at = ? WHERE id = ?",
                    [(now_ts, item_id) for item_id in superseded_ids],
                )

            await db.execute(
                """
                INSERT INTO group_memory (
                    id, group_id, source_chat_id, source_message_id, memory_type, content, summary,
                    importance, status, version, created_at, updated_at, last_used_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    group_id,
                    source_chat_id,
                    source_message_id,
                    memory["memory_type"],
                    memory["content"],
                    memory["summary"],
                    memory["importance"],
                    now_ts,
                    now_ts,
                    now_ts,
                    json.dumps({"normalized_summary": normalized_summary}, ensure_ascii=False),
                ),
            )
        await db.commit()

async def _invalidate_group_memories_by_chat(source_chat_id: str) -> None:
    if not source_chat_id:
        return
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory WHERE source_chat_id = ?",
            (source_chat_id,),
        )
        await db.commit()

async def _invalidate_group_memories_by_group(group_id: str) -> None:
    if not group_id:
        return
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory WHERE group_id = ?",
            (group_id,),
        )
        await db.commit()

async def _invalidate_all_group_memories() -> None:
    import aiosqlite
    async with aiosqlite.connect(COVS_PATH) as db:
        await db.execute(
            "DELETE FROM group_memory",
        )
        await db.commit()

async def message_without_images(messages: List[Dict]) -> List[Dict]:
    if messages:
        for message in messages:
            if 'content' in message:
                if isinstance(message['content'], list):
                    for item in message['content']:
                        # 剥离包含图像和视频的内容，只保留文本传递（用于快速生成请求或剥离富媒体阶段）
                        if isinstance(item, dict) and item.get('type') == 'text':
                            message['content'] = item['text']
                            break
    return messages

def _append_note(content, note: str):
    """Append a text note to str-or-list message content.
    Caution: list += str would splat the string character-by-character."""
    if isinstance(content, list):
        return content + [{"type": "text", "text": note}]
    return content + note


async def images_in_messages(messages: List[Dict], fastapi_base_url: str) -> List[Dict]:
    media_items = []
    index = 0
    for message in messages:
        extracted_media =[]
        if 'content' in message:
            if isinstance(message['content'], list):
                for item in message['content']:
                    # 动态捕获图片或视频
                    if isinstance(item, dict) and item.get('type') in ['image_url', 'video_url']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        
                        if item[media_key]["url"].startswith("http"):
                            media_url = item[media_key]["url"]
                            if fastapi_base_url in media_url:
                                media_url = media_url.replace(fastapi_base_url, f"http://127.0.0.1:{PORT}/")
                            
                            # 假设你的 get_image_base64 同样可以将视频流转为 Base64
                            base64_data = await get_image_base64(media_url)
                            # 假设 get_image_media_type 也能正常返回 video/mp4, video/webm 等
                            mime_type = await get_image_media_type(media_url, base64_data)
                            
                            item[media_key]["url"] = f"data:{mime_type};base64,{base64_data}"
                            item[media_key]["hash"] = hashlib.md5(item[media_key]["url"].encode()).hexdigest()
                        else:
                            item[media_key]["hash"] = hashlib.md5(item[media_key]["url"].encode()).hexdigest()

                        extracted_media.append(item)
        if extracted_media:
            # 保持原来的字典结构向下兼容，images 实际上装载了 media
            media_items.append({'index': index, 'images': extracted_media})
        index += 1
    return media_items

async def images_add_in_messages(request_messages: List[Dict], images: List[Dict], settings: dict) -> List[Dict]:
    messages = copy.deepcopy(request_messages)
    
    if settings['vision']['enabled']:
        for image in images:
            index = image['index']
            if index < len(messages):
                if 'content' in messages[index]:
                    for item in image['images']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        file_hash = item[media_key]['hash']
                        media_name = "视频" if media_key == "video_url" else "图片"
                        
                        # 统一缓存处理，如果是视频就是视频文本解析记录
                        cache_file = os.path.join(UPLOAD_FILES_DIR, f"{file_hash}.txt")
                        if os.path.exists(cache_file):
                            with open(cache_file, "r", encoding='utf-8') as f:
                                messages[index]['content'] = _append_note(
                                    messages[index]['content'],
                                    f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{f.read()}\n\n")
                        else:
                            # 根据输入类型调整提示词
                            prompt_text = "请仔细描述这段视频中的内容，包含视频中发生的事件、场景变化、人物动作以及关键细节等信息。" if media_key == "video_url" else "请仔细描述图片中的内容，包含图片中可能存在的文字、数字、颜色、形状、大小、位置、人物、物体、场景等信息。"
                            
                            media_content =[
                                {"type": "text", "text": prompt_text},
                                {"type": media_key, media_key: {"url": item[media_key]['url']}}
                            ]
                            
                            # 直接交给视觉模型（视觉模型需原生支持视频）
                            client = AsyncOpenAI(api_key=settings['vision']['api_key'], base_url=settings['vision']['base_url'])
                            
                            extra = {}

                            if settings['vision']['temperature'] !=1:
                                extra['temperature'] = settings['vision']['temperature']

                            response = await client.chat.completions.create(
                                model=settings['vision']['model'],
                                messages=[{"role": "user", "content": media_content}],
                                **extra
                            )
                            result_text = str(response.choices[0].message.content)
                            messages[index]['content'] = _append_note(
                                messages[index]['content'],
                                f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{result_text}\n\n")
                            
                            with open(cache_file, "w", encoding='utf-8') as f:
                                f.write(result_text)
    else:           
        for image in images:
            index = image['index']
            if index < len(messages):
                if 'content' in messages[index]:
                    for item in image['images']:
                        media_key = item['type']  # 'image_url' 或 'video_url'
                        file_hash = item[media_key]['hash']
                        media_name = "视频" if media_key == "video_url" else "图片"
                        
                        cache_file = os.path.join(UPLOAD_FILES_DIR, f"{file_hash}.txt")
                        if os.path.exists(cache_file):
                            with open(cache_file, "r", encoding='utf-8') as f:
                                messages[index]['content'] = _append_note(
                                    messages[index]['content'],
                                    f"\n\nsystem: 用户发送的{media_name}(哈希值：{file_hash})信息如下：\n\n{f.read()}\n\n")
                        else:
                            if isinstance(messages[index]['content'], str):
                                messages[index]['content'] =[{"type": "text", "text": messages[index]['content']}]
                            
                            # 未开启视觉模型，直接以原生的 `video_url` 或 `image_url` 拼入请求，让当前大模型自行读取理解
                            messages[index]['content'].append({"type": media_key, media_key: {"url": item[media_key]['url']}})
                            
    return messages

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

            # --- (2) 处理 '/' : 注入特定技能 ---
            elif user_text_trimmed.startswith('/'):
                parts = user_text_trimmed[1:].split()
                if parts:
                    skill_name = parts[0]
                    skill_dir = Path(cwd) / ".agent" / "skills" / skill_name
                    if skill_dir.exists() and skill_dir.is_dir():
                        doc_file_path = None
                        # 尝试匹配常见的技能说明文档命名
                        for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                            if (skill_dir / name).exists():
                                doc_file_path = skill_dir / name
                                break
                            
                        if doc_file_path:
                            try:
                                import aiofiles
                                async with aiofiles.open(doc_file_path, 'r', encoding='utf-8') as f:
                                    skill_content = await f.read()
                                content_append(request.messages, 'system', f"\n\n🛠️ **The user actively triggered the workspace skill. [{skill_name}]**:\n\n{skill_content}\n\nPlease strictly follow the above skill instructions to handle the user's current request.\n\n")
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


async def _append_project_skills(request, cwd, visibilityScope):
    """project skills summary injection. (M-3 split)"""
    try:
        # 无论是在 docker 还是 local，逻辑路径通常是一致的（通过挂载）
        # 如果是 Docker 环境且 backend 无法直接访问 cwd，则需通过 docker exec ls 扫描，
        # 但通常项目路径是共享的。
        skills_message = await get_project_skills_summary(cwd, visibilityScope)
        if skills_message:
            content_append(request.messages, 'system', skills_message)
    except Exception as e:
        logging.getLogger("app").info(f"[Skill Loader] 扫描技能失败: {e}")


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
                print("可用音色：",finalttsList)
                
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

async def tools_change_messages(request: ChatRequest, settings: dict):
    
    if request.messages and request.messages[0]['role'] == 'system' and request.messages[0]['content'] != '':
        basic_message = " "
        request.messages[0]['content'] += basic_message

    cli_settings = settings.get("CLISettings", {})
    cwd = cli_settings.get("cc_path")
    visibilityScope = cli_settings.get("visibilityScope", "workspace")
    # 修复：local 环境应该从 localEnvSettings 读取权限模式
    engine = cli_settings.get("engine", "")
    
    if engine == "local":
        env_settings = settings.get("localEnvSettings", {})
    elif engine == "ds":
        env_settings = settings.get("dsSettings", {})
    else:
        env_settings = settings.get("acpSettings", {})
    
    permissionMode = cli_permission_mode_for(settings)
    
    if cwd and Path(cwd).exists() and cli_settings.get("enabled", False):
        
        await _inject_workspace_memory(request, cwd, cli_settings)

    if request.is_app_bot and request.platform:
        platform_message = f"\n\n用户正在使用 {request.platform} 软件与你交流\n\n"
        content_append(request.messages, 'system', platform_message)

    if cwd and Path(cwd).exists() and cli_settings.get("enabled", False):
        _append_permission_mode_message(request, permissionMode)

    if permissionMode == "cowork" and not request.is_sub_agent:
        if cwd and Path(cwd).exists() and cli_settings.get("enabled", False) and engine in ["ds", "local"]:
            sub_task_context = await query_task_progress(cwd)
            content_append(request.messages, 'system', sub_task_context)
    elif cwd and Path(cwd).exists() and cli_settings.get("enabled", False) and engine in ["ds", "local"]:
        
        if engine == "local":
            # 在本地环境下，首先注入系统环境信息
            system_context = get_system_context(cwd=cwd)
            content_append(request.messages, 'system', system_context)
        elif engine == "ds":
            # 在 Docker 环境下，注入系统环境信息
            system_context = """【环境信息】操作系统：Linux | Shell：bash

⚠️ 重要提示：
1. 当前为 Docker 环境，请使用 Linux 命令和工具链
2. 执行 docker_sandbox 时，命令必须符合 Linux 的语法规范
3. 路径分隔符：Unix 使用正斜杠(/)
4. 请尽量使用相对路径，避免使用绝对路径，以免在跨平台时出现问题

### ✅ **已安装的主要开发工具**

#### **编程语言和运行时**
1. **Python**
   - Python
   - pip
   - uv

2. **Node.js**
   - Node.js
   - npm
   - npx

3. **Go**
   - Go

4. **Perl**
   - Perl

#### **版本控制和协作工具**
1. **Git**
   - git
   - GitHub CLI (gh)

#### **包管理和构建工具**
1. **Python 包管理**
   - pip / pip3
   - uv

2. **Node.js 包管理**
   - npm / npx

3. **系统包管理**
   - apt-get / dpkg

#### **文本处理和命令行工具**
1. **文本处理**
   - jq
   - awk / sed / grep
   - cat / less / more / head / tail

2. **文件操作**
   - tar / unzip
   - rsync
   - 所有基本 Unix 命令（ls, cp, mv, rm, mkdir, chmod 等）

3. **系统工具**
   - bash shell
   - make
   - which / whereis

#### **网络工具**
1. **HTTP 客户端**
   - curl

2. **安全工具**
   - openssl
   - gpg

#### **系统监控**
1. **进程和资源监控**
   - top / ps
   - free / df / du
   
"""
            content_append(request.messages, 'system', system_context)

        await _append_todos_context(request, cwd)

        await _append_agents_md(request, cwd)

        await _append_project_skills(request, cwd, visibilityScope)

    if request.messages[-1]['role'] == 'system' and settings['tools']['autoBehavior']['enabled'] and not request.is_app_bot and not request.is_sub_agent:
        language_message = f"\n\n当你看到被插入到对话之间的系统消息，这是自主行为系统向你发送的消息，例如用户主动或者要求你设置了一些定时任务或者延时任务，当你看到自主行为系统向你发送的消息时，说明这些任务到了需要被执行的节点，例如：用户要你三点或五分钟后提醒开会的事情，然后当你看到一个被插入的“提醒用户开会”的系统消息，你需要立刻提醒用户开会，以此类推\n\n"
        content_append(request.messages, 'system', language_message)

    # 先统一获取当前选中的 memory 对象（后面多处会用到）
    cur_memory = None
    if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"]:
        memoryId = settings["memorySettings"]["selectedMemory"]
        for memory in settings["memories"]:
            if memory["id"] == memoryId:
                cur_memory = memory
                break
    
    # 获取角色名称（用于显示），如果找不到就用 id 兜底
    selectedMemoryName = cur_memory["name"] if cur_memory else settings["memorySettings"]["selectedMemory"]


    if settings["isGroupMode"] and not request.is_app_bot and not request.is_sub_agent:
        selectedGroupAgents = settings['selectedGroupAgents']
        if selectedGroupAgents:
            userName = "user"
            if settings["memorySettings"]["userName"]:
                userName = settings["memorySettings"]["userName"]
            selectedGroupAgents.append(userName)
            
            # 修复：把每个 agent 的 id 转成 name
            agent_names = [_resolve_agent_name(agent, settings) for agent in selectedGroupAgents]
            
            group_message = f"\n\n你当前处于群聊模式，群聊中的角色有：{agent_names}\n\n你在扮演{selectedMemoryName}"
            content_append(request.messages, 'system', group_message)

    _append_tts_voice_prompts(request, settings, selectedMemoryName)
    if settings['vision']['desktopVision'] and not request.is_app_bot  and not request.is_sub_agent:
        desktop_message = "\n\n用户与你对话时，如果发了图片给你，有可能是给你发当前的桌面截图。\n\n"
        content_append(request.messages, 'system', desktop_message)
    if settings['tools']['time']['enabled'] and settings['tools']['time']['triggerMode'] == 'beforeThinking':
        time_message = f"\n\n最后一条消息发送时间：{local_timezone}  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}\n\n"
        content_prepend(request.messages, 'system', time_message)
    if settings['tools']['inference']['enabled']:
        inference_message = "回答用户前请先思考推理，再回答问题，你的思考推理的过程必须放在<think>与</think>之间。\n\n"
        content_prepend(request.messages, 'user', f"{inference_message}\n\n用户：")
    if settings['tools']['formula']['enabled']:
        latex_message = "\n\n当你想使用latex公式时，你必须是用 ['$', '$'] 作为行内公式定界符，以及 ['$$', '$$'] 作为行间公式定界符。\n\n"
        content_append(request.messages, 'system', latex_message)
    if settings['tools']['language']['enabled']:
        language_message = f"请使用{settings['tools']['language']['language']}语言说话！，不要使用其他语言，语气风格为{settings['tools']['language']['tone']}\n\n"
        content_append(request.messages, 'system', language_message)
    if settings["stickerPacks"]:
        for stickerPack in settings["stickerPacks"]:
            if stickerPack["enabled"]:
                sticker_message = f"\n\n图片库名称：{stickerPack['name']}，包含的图片：{json.dumps(stickerPack['stickers'])}\n\n"
                content_append(request.messages, 'system', sticker_message)
        content_append(request.messages, 'system', "\n\n当你需要使用图片时，请将图片的URL放在markdown的图片标签中，例如：\n\n<silence>![图片名](图片URL)</silence>\n\n，图片markdown必须另起并且独占一行！<silence>和</silence>是控制TTS的静音标签，表示这个图片部分不会进入语音合成\n\n你必须在回复中正确使用 <silence> 标签来包裹图片的 Markdown 语法\n\n<silence>和</silence>与图片的 Markdown 语法之间不能有空格和回车，会导致解析失败！\n\n")
    if settings['text2imgSettings']['enabled']:
        text2img_messages = "\n\n当你使用画图工具后，必须将图片的URL放在markdown的图片标签中，例如：\n\n<silence>![图片名](图片URL)</silence>\n\n，图片markdown必须另起并且独占一行！请主动发给用户，工具返回的结果，用户看不到！<silence>和</silence>是控制TTS的静音标签，表示这个图片部分不会进入语音合成\n\n你必须在回复中正确使用 <silence> 标签来包裹图片的 Markdown 语法\n\n注意！！！<silence>和</silence>与图片的 Markdown 语法之间不能有空格和回车，会导致解析失败！\n\n"
        content_append(request.messages, 'system', text2img_messages)
    _append_avatar_prompts(request, settings)
    await _append_affection_prompt(request, settings)
    # ==================== 好感度系统注入结束 ====================

    _append_a2ui_prompt(request)

    # ===== L3 任务检查点：注入此前压缩落盘的任务态（7 天内、当前或未知会话、且历史中尚无摘要时） =====
    _inject_task_checkpoint(request, cli_settings, engine)

    # ===== 分层 system prompt：Agent 核心契约置最前，权限模式契约置最后 =====
    _cli_cfg = settings.get("CLISettings", {})
    if (_cli_cfg.get("enabled", False) and _cli_cfg.get("engine") in ("local", "ds")
            and _cli_cfg.get("agentCorePrompt", {}).get("enabled", True)):
        from py.agent_prompt import build_agent_core_prompt, build_mode_footer
        _core_mode = cli_permission_mode_for(settings)
        content_prepend(request.messages, 'system', build_agent_core_prompt(
            _core_mode,
            engine=_cli_cfg.get("engine", "local"),
            is_cowork_main=(_core_mode == "cowork" and not request.is_sub_agent),
        ))
        content_append(request.messages, 'system', build_mode_footer(_core_mode))

    logging.getLogger("app").info(f"系统提示：{request.messages[0]['content']}")
    return request

def get_drs_stage(DRS_STAGE):
    if DRS_STAGE == 1:
        drs_msg = "当前阶段为明确用户需求阶段，你需要分析用户的需求，并给出明确的需求描述。如果用户的需求描述不明确，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。"
    elif DRS_STAGE == 2:
        drs_msg = "当前阶段为工具调用阶段，利用你的知识库、互联网搜索、数据库查询、各类MCP等你所有的工具（如果有，这些工具不一定会提供），执行计划中未完成的步骤。每次完成计划中的一个步骤。在工具调用阶段中，你不要完成最终任务，而是尽可能的调用相关的工具，为最后的回答阶段做准备。"
    elif DRS_STAGE == 3:
        drs_msg = "当前阶段为生成结果阶段，根据当前收集到的所有信息，完成任务，给出任务执行结果。如果用户要求你生成一个超过2000字的回答，你可以尝试将该任务拆分成多个部分，每次只完成其中一个部分。"
    else:
        drs_msg = "当前阶段为生成结果阶段，根据当前收集到的所有信息，完成任务，给出任务执行结果。如果用户要求你生成一个超过2000字的回答，你可以尝试将该任务拆分成多个部分，每次只完成其中一个部分。"
    return drs_msg  

def get_drs_stage_name(DRS_STAGE):
    if DRS_STAGE == 1:
        drs_stage_name = "明确用户需求阶段"
    elif DRS_STAGE == 2:
        drs_stage_name = "工具调用阶段"
    elif DRS_STAGE == 3:
        drs_stage_name = "生成结果阶段"
    else:
        drs_stage_name = "生成结果阶段"
    return drs_stage_name

def get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content):
    drs_stage_name = get_drs_stage_name(DRS_STAGE)
    if DRS_STAGE == 1:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 当前阶段，请输出json字符串：

### 如果需要用户明确需求，请输出json字符串（如果你已经在上一轮对话中向用户提出过明确需求，请不要重复使用"need_more_info"，这会导致用户无法快速获取结果）：
{{
    "status": "need_more_info",
    "unfinished_task": ""
}}

### 如果不需要进一步明确需求，进入并进入工具调用阶段，请输出json字符串：
{{
    "status": "need_work",
    "unfinished_task": ""
}}
"""
    elif DRS_STAGE == 2:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 注意！工具调用阶段，是为最后的回答阶段做准备。不需要生成最终的回答，如果已经没有未完成的需要调用工具的步骤，请进入生成结果阶段。

## 当前阶段，请输出json字符串：

### 如果还有计划中的需要调用工具的步骤没有完成，请输出json字符串：
{{
    "status": "need_more_work",
    "unfinished_task": "这里填入未完成的步骤"
}}

### 如果所有计划的需要调用工具的步骤都已完成，进入生成结果阶段，请输出json字符串：
{{
    "status": "answer",
    "unfinished_task": ""
}}
"""    
    else:
        search_prompt = f"""
# 当前状态：

## 初始任务：
{user_prompt}

## 当前结果：
{full_content}

## 当前阶段：
{drs_stage_name}

# 深度研究一共有三个阶段：1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段

## 当前阶段，请输出json字符串：

如果初始任务已完成，请输出json字符串：
{{
    "status": "done",
    "unfinished_task": ""
}}

如果初始任务未完成，请输出json字符串：
{{
    "status": "not_done",
    "unfinished_task": "这里填入未完成的任务"
}}
"""    
    return search_prompt

# =========================================================================
# 第二阶段：强制合法性清洗 (Sanitizer) - 无论是否压缩都必须执行
# 目标：彻底杜绝 Messages with role 'tool' must be a response... 报错
# =========================================================================
def get_role(m): return m.get("role") if isinstance(m, dict) else m.role
def get_tcs(m): 
    if get_role(m) != "assistant": return None
    return m.get("tool_calls") if isinstance(m, dict) else getattr(m, "tool_calls", None)

_ARG_SHELL_KEYS = ("arguments", "params", "input", "tool_arguments")


def _unwrap_arg_shell(data, depth=3):
    """S85-A：单键壳解包。llama 系本地模型常输出 {"arguments": {...}} 双层包裹
    （内层还可能是字符串化 JSON），直接 **dict 会得到 unexpected keyword 'arguments'。"""
    while depth > 0 and isinstance(data, dict) and len(data) == 1:
        key = next(iter(data)).lower()
        if key not in _ARG_SHELL_KEYS:
            break
        val = data[next(iter(data))]
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except Exception:
                break
        if not isinstance(val, dict):
            break
        data, depth = val, depth - 1
    return data


def _merge_tool_delta(tool_calls, tool):
    """S85-A(C-20 扩展)：流式 tool_call delta 槽位合并。返回 (槽对象, 本帧参数片段)。
    槽位定位优先级：协议 tool.index → 既有槽中 id 匹配 → 末槽（无 index 旧模型）。
    修复顺序多 call 无 index 时后一 call 的参数拼进前一 buffer（'}{' 拼接串）。"""
    _slot = getattr(tool, "index", None)
    if _slot is None:
        _slot = None
        tc_id = getattr(tool, "id", None)
        if tc_id:
            for i, ex in enumerate(tool_calls):
                if getattr(ex, "id", None) == tc_id:
                    _slot = i
                    break
            if _slot is None:
                _slot = len(tool_calls)  # 带 id 但无匹配 = 无 index provider 的新调用
            elif (getattr(tool, "function", None)
                  and getattr(tool.function, "name", None)
                  and tool_calls[_slot].function
                  and getattr(tool_calls[_slot].function, "arguments", "")):
                # id 跨轮复用：带 name 且旧槽已有参数 → 新一轮调用，开新槽
                _slot = len(tool_calls)
        if _slot is None:
            _slot = max(len(tool_calls) - 1, 0)  # 无 index 无 id 旧模型：回退末槽
    while len(tool_calls) <= _slot:
        _fill = copy.deepcopy(tool)
        if _fill.function is not None:
            _fill.function.arguments = ""
        tool_calls.append(_fill)
    current = tool_calls[_slot]
    if getattr(tool, "id", None) and not current.id:
        current.id = tool.id
    frag = ""
    if tool.function:
        if tool.function.name and not current.function.name:
            current.function.name = tool.function.name
        if tool.function.arguments:
            current.function.arguments = (current.function.arguments or "") + tool.function.arguments
            frag = tool.function.arguments
    return current, frag


def parse_tool_arguments(raw):
    """解析工具调用参数。返回 (args_dict, error_msg)。
    先直接 JSON 解析（含单键壳解包）；失败则回退 '}{ 拼接拆分，取首个非空片段
    再解壳；仍失败返回错误供模型自愈，不炸流。"""
    raw = (raw or "").strip()
    if not raw:
        return {}, None
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return _unwrap_arg_shell(data), None
        if isinstance(data, list):
            return _unwrap_arg_shell(data[0] if data and isinstance(data[0], dict) else {}), None
        return {}, None
    except Exception:
        pass
    try:
        data_list = json.loads('[' + raw.replace('}{', '},{') + ']')
        if isinstance(data_list, list):
            for item in data_list:
                if isinstance(item, dict) and item:
                    return _unwrap_arg_shell(item), None
            return {}, None
        return {}, None
    except Exception as e:
        return None, (
            f"Invalid JSON arguments: {e}. "
            "Arguments must be ONE JSON object like {\"path\": \"src/main.py\"} — "
            "double-quoted keys/strings, no trailing commas, no markdown fences, no comments. "
            f"Raw (truncated): {raw[:200]!r}"
        )

def truncate_tool_result(text, limit: int = 32000):
    """截断超长工具结果（头 2/3 + 尾 1/3），仅用于回填 message 历史，UI 展示不受影响。"""
    if not isinstance(text, str):
        text = str(text)
    if len(text) <= limit:
        return text
    head = int(limit * 2 / 3)
    tail = limit - head
    omitted = len(text) - limit
    return (text[:head]
            + f"\n\n...[结果过长，已截断中间 {omitted} 个字符。如需完整内容请缩小查询范围或写文件后读取]...\n\n"
            + text[-tail:])

def cli_permission_mode_for(settings: dict) -> str:
    """读取当前 CLI 引擎对应的权限模式（值域已归一化）"""
    from py.cli_tool import normalize_permission_mode
    cli = settings.get("CLISettings", {})
    engine = cli.get("engine", "")
    if engine == "local":
        env = settings.get("localEnvSettings", {})
    elif engine == "ds":
        env = settings.get("dsSettings", {})
    else:
        env = settings.get("acpSettings", {})
    return normalize_permission_mode(env.get("permissionMode", "default"))

RESUME_NUDGE_TEXT = (
    "【系统提示】上面的工具结果已收到。工具的“成功”仅代表这一处操作完成，"
    "不代表用户的原始任务已全部完成。如果任务仍有未完成的步骤（继续修改、读回验证、运行测试等），"
    "请立即继续调用工具执行；只有在确认全部完成并验证后，才向用户做最终总结。"
)

def append_resume_nudge(messages):
    """恢复续跑 nudge：当请求历史以 tool 结果结尾（审批通过后手动执行工具再恢复的典型场景）时，
    追加一条“继续推进”指令，防止模型把成功的工具结果当成最终报告直接收尾。"""
    if messages and get_role(messages[-1]) == "tool":
        messages.append({"role": "user", "content": RESUME_NUDGE_TEXT})
    return messages

# =========================================================================
# 第三阶段：思考模式字段填充 (Thinking Mode Sanitizer)
# 目标：防止 "reasoning_content must be passed back" 错误
# 策略：为所有 assistant 消息添加 reasoning_content: ""
# =========================================================================

def ensure_thinking_fields(messages):
    """
    为所有 assistant 消息强制添加 reasoning_content: ""（空字符串）
    """
    if not messages:
        return messages
    
    for msg in messages:
        role = get_role(msg)
        
        if role == "assistant":
            # 处理字典格式
            if isinstance(msg, dict):
                # 强制设置为空字符串
                msg["reasoning_content"] = ""
            
            # 处理对象格式
            else:
                setattr(msg, "reasoning_content", "")
    
    return messages
def _cm_context_enabled(settings: dict) -> bool:
    from py.context_manager import get_context_settings
    try:
        return bool(get_context_settings(settings)["enabled"])
    except Exception:
        return False


def _write_context_state(settings: dict, request, res: dict):
    """L3: 把压缩产生的结构化摘要落盘为任务检查点（按会话）"""
    try:
        cwd = settings.get("CLISettings", {}).get("cc_path")
        if not cwd or not Path(cwd).exists():
            return
        state_dir = Path(cwd) / ".agent"
        state_dir.mkdir(parents=True, exist_ok=True)
        import time as _time
        data = {
            "conversation_id": request.conversation_id,
            "updated_at": int(_time.time()),
            "task_mode": res.get("task_mode"),
            "summary": (res.get("summary") or "")[:6000],
        }
        (state_dir / "context_state.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logging.getLogger("app").info("[Context] 任务检查点已写入 .agent/context_state.json")
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 检查点写入失败: {e}")


async def _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools=None):
    """上下文管线：L1 工具结果修剪 -> L2 自动摘要（仅 agent 模式）。
    执行了 L2 时返回 context_compact 事件 dict（供前端落账），否则 None。"""
    try:
        from py.context_manager import (get_context_settings, estimate_tokens, prune_tool_results,
                                        compact_messages, detect_task_mode)
        cm = get_context_settings(settings)
        if not cm["enabled"]:
            return None
        budget = int(cm["context_window"] * cm["compact_ratio"])
        est = estimate_tokens(request.messages, tools)
        if est <= budget:
            return None
        request.messages, pruned_n = prune_tool_results(request.messages, cm["keep_recent_tools"])
        est2 = estimate_tokens(request.messages, tools)
        logging.getLogger("app").info(f"[Context] L1 修剪旧工具结果 {pruned_n} 条: est {est} -> {est2} (budget {budget})")
        if est2 <= budget:
            return None
        mode = detect_task_mode(request.messages)
        if not (mode == "agent" and cm["auto_agent_compact"]):
            logging.getLogger("app").info(f"[Context] 超预算但模式={mode}，仅修剪不摘要")
            return None
        r_cli = reasoner_client if settings.get("reasoner", {}).get("enabled") else None
        r_model = settings["reasoner"]["model"] if r_cli else None
        res = await compact_messages(client, model, request.messages, task_mode="agent",
                                     keep_recent_dialog=cm["keep_recent_dialog"],
                                     extra_params=extra_params,
                                     reasoner_client=r_cli, reasoner_model=r_model)
        if not res:
            return None
        request.messages = res["messages"]
        _write_context_state(settings, request, res)
        logging.getLogger("app").info(f"[Context] L2 自动摘要完成，压缩 {res['compacted_count']} 条消息")
        return {"type": "context_compact", "reason": "auto", "summary": res["summary"],
                "task_mode": res["task_mode"], "compacted_count": res["compacted_count"]}
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 上下文管线异常（跳过）: {e}")
        return None


TOOL_RESULT_CHAR_CAP = 15000


def _cap_tool_result(result):
    """工具输出源头截断（对齐 opencode）：单条结果超长截断并提示分页续读。"""
    if not isinstance(result, str) or len(result) <= TOOL_RESULT_CHAR_CAP:
        return result
    head = result[:TOOL_RESULT_CHAR_CAP]
    logging.getLogger("app").info(f"[Context] 工具输出截断: {len(result)} -> {TOOL_RESULT_CHAR_CAP} 字符")
    return (f"{head}\n\n==== [输出已截断：共 {len(result)} 字符，仅显示前 {TOOL_RESULT_CHAR_CAP} 字符。"
            "如需后续内容，请使用工具的 offset/分页参数分段续读] ====")


def _apply_ctx_guardrail(extra, messages, settings):
    """防 Strata 400：max_tokens 不得超过 window - prompt估算 - 512。"""
    try:
        from py.context_manager import get_context_settings, estimate_tokens
        window = get_context_settings(settings)["context_window"]
        est = estimate_tokens(messages)
        mt = extra.get('max_completion_tokens') or extra.get('max_tokens')
        if mt:
            guard = window - est - 512
            if mt > guard:
                key = 'max_completion_tokens' if 'max_completion_tokens' in extra else 'max_tokens'
                extra = dict(extra)
                extra[key] = max(512, guard)
                logging.getLogger("app").info(f"[Context] 护栏: max_tokens {mt} -> {extra[key]} (估算 prompt {est}, window {window})")
    except Exception as e:
        logging.getLogger("app").info(f"[Context] 护栏检查异常（跳过）: {e}")
    return extra


def _breakdown_tokens(messages, tools=None):
    """上下文分段估算：system/历史user/历史assistant/工具结果/tools schema/本轮user。"""
    from py.context_manager import estimate_text_tokens
    seg = {"system": 0, "history_user": 0, "history_assistant": 0,
           "tool_results": 0, "tools_schema": 0, "current_user": 0}
    try:
        import json as _json
        role_of = lambda m: (m.get('role') if isinstance(m, dict) else getattr(m, 'role', None))
        last_user = max((i for i, m in enumerate(messages) if role_of(m) == 'user'), default=-1)
        for i, m in enumerate(messages):
            role = role_of(m)
            if role is None:
                continue
            c = m.get('content') if isinstance(m, dict) else getattr(m, 'content', None)
            t = estimate_text_tokens(c if isinstance(c, str) else _json.dumps(c or "", ensure_ascii=False))
            for tc in (m.get('tool_calls') or [] if isinstance(m, dict) else []):
                fn = tc.get('function') or {}
                t += estimate_text_tokens(str(fn.get('name', '')) + str(fn.get('arguments', '')))
            if role == 'system':
                seg["system"] += t
            elif role == 'user':
                seg["current_user" if i == last_user else "history_user"] += t
            elif role == 'tool':
                seg["tool_results"] += t
            elif role == 'assistant':
                seg["history_assistant"] += t
        if tools:
            seg["tools_schema"] = estimate_text_tokens(_json.dumps(tools, ensure_ascii=False)) // 2
    except Exception:
        pass
    return seg



async def _stream_desktop_capture(request, settings, vision_cfg, vision_control_enabled, user_prompt, fastapi_base_url):
    """Desktop-vision wake/vision-control capture pipeline + injection. (M-3 split)"""
    should_capture = False
    if vision_control_enabled and settings.get('visionControlSettings', {}).get('desktopVision', False):
        should_capture = True
    elif vision_cfg.get('desktopVision'):
        # 检查唤醒词
        if vision_cfg.get('enableWakeWord'):
            wake_words = [w.strip() for w in vision_cfg.get('wakeWord', "").split('\n') if w.strip()]
            if any(word in user_prompt for word in wake_words):
                should_capture = True
        else:
            # 未开启唤醒词则默认每次捕获（或根据需求调整）
            should_capture = True
        
    if should_capture:
        try:
            import pyautogui
            # 引入我们刚才写的设置区域的方法
            from py.computer_use_tool import set_screen_region
                
            # 获取配置
            v_settings = settings.get('visionControlSettings', {})
            is_full_screen = v_settings.get('isFullScreen', True)
            screen_size = v_settings.get('ScreenSize', [0, 0, 1280, 720])
            is_grid_enabled = vision_control_enabled and v_settings.get('isEnableGrid', False)

            logging.getLogger("app").info(f"正在执行桌面截图 (全屏: {is_full_screen}, 网格: {is_grid_enabled})...")
                
            # 1. 根据全屏配置决定截取范围，并同步给鼠标工具
            if not is_full_screen and len(screen_size) == 4:
                x, y, w, h = map(int, screen_size)
                # 截取指定区域
                screenshot = await asyncio.to_thread(pyautogui.screenshot, region=(x, y, w, h))
                logical_width, logical_height = w, h
                # 通知计算机工具，接下来的鼠标操作要基于这个区域
                set_screen_region((x, y, w, h))
            else:
                # 全屏截图
                logical_width, logical_height = pyautogui.size()
                screenshot = await asyncio.to_thread(pyautogui.screenshot)
                # 恢复全屏鼠标映射
                set_screen_region(None)
                
            # 2. 统一缩放到逻辑坐标系 (解决 Windows DPI 缩放偏移)
            if screenshot.width != logical_width or screenshot.height != logical_height:
                screenshot = await asyncio.to_thread(
                    screenshot.resize, (logical_width, logical_height), Image.Resampling.LANCZOS
                )
                
            # 3. 缩放到传输尺寸 (1280x720 左右，平衡清晰度与 Token 消耗)
            target_w, target_h = scale_to_fit(logical_width, logical_height, 1280, 720)
                
            if screenshot.width > target_w or screenshot.height > target_h:
                logging.getLogger("app").info(f"检测到高分辨率屏幕，正在从 {screenshot.size} 缩放到 {(target_w, target_h)}")
                screenshot = await asyncio.to_thread(
                    screenshot.resize, (target_w, target_h), Image.Resampling.LANCZOS
                )

            # 4. 根据设置决定是否绘制网格
            if is_grid_enabled:
                # 在副本上绘制网格
                display_image = await asyncio.to_thread(draw_grid_on_image, screenshot.copy(), grid_spacing=10)
                if not is_full_screen:
                    grid_hint = "\n\n【system info】Current partial screen region screenshot with coordinate grid (0-1000) is injected. Use coordinates for precise clicking."
                else:
                    grid_hint = "\n\n【system info】Current desktop screenshot with coordinate grid (0-1000) is injected. Use coordinates for precise clicking."
            else:
                display_image = screenshot
                grid_hint = "\n\n【system info】Current desktop screenshot is injected."

            # 5. 保存图片
            file_prefix = "desktop_grid" if is_grid_enabled else "desktop_plain"
            desktop_img_name = f"{file_prefix}_{uuid.uuid4().hex}.png"
            desktop_img_path = os.path.join(UPLOAD_FILES_DIR, desktop_img_name)
                
            await asyncio.to_thread(display_image.save, desktop_img_path, optimize=True)
            desktop_url = f"{fastapi_base_url}uploaded_files/{desktop_img_name}"
                
            # 6. 注入到当前消息
            current_user_msg = request.messages[-1]
            if isinstance(current_user_msg['content'], str):
                original_text = current_user_msg['content']
                current_user_msg['content'] = [
                    {"type": "text", "text": original_text + grid_hint},
                    {"type": "image_url", "image_url": {"url": desktop_url}}
                ]
            elif isinstance(current_user_msg['content'], list):
                current_user_msg['content'].append(
                    {"type": "image_url", "image_url": {"url": desktop_url}}
                )
                
            # 7. 清理历史截图 (如果开启了 onlyNewScreen)
            if settings.get('visionControlSettings', {}).get('onlyNewScreen', False):
                for msg in request.messages[:-1]: # 不处理最后一条刚刚添加的消息
                    if isinstance(msg.get('content'), list):
                        # 过滤掉 image_url，只保留 text
                        new_content = [item for item in msg['content'] if item.get('type') != 'image_url']
                        # 如果 list 里只剩文本，简化为字符串提高处理效率
                        if len(new_content) == 1 and new_content[0].get('type') == 'text':
                            msg['content'] = new_content[0]['text']
                        else:
                            msg['content'] = new_content
                logging.getLogger("app").info("已清理历史上下文中的旧截图。")

            logging.getLogger("app").info(f"桌面截图已注入: {desktop_url}")

        except Exception as e:
            logging.getLogger("app").info(f"后端桌面截图失败: {e}")


def _stream_context_compress(request, settings):
    """L1 context window compression (stream channel; dead-neutral inits kept)."""
    max_rounds = 0 if _cm_context_enabled(settings) else settings.get("max_rounds", 0)
    chat_messages = request.messages # 这里的 chat_messages 包含 system
    usage_info = None
    _ctx_peak = 0
        
    if max_rounds > 0:
            
        # 区分系统消息和对话消息
        sys_msgs = [m for m in chat_messages if get_role(m) == "system"]
        dialog_msgs = [m for m in chat_messages if get_role(m) != "system"]
            
        # 设定压缩阈值：当非系统消息超过 max_rounds * 2 + 1 时开始压缩
        if len(dialog_msgs) > (max_rounds * 2 + 1):
            keep_indices = set()
                
            # 1. 总是保留第一条消息 (Anchor User Prompt)
            if len(dialog_msgs) > 0: keep_indices.add(0)
                
            # 2. 保留所有 User 消息 (User 优先策略)
            for i, m in enumerate(dialog_msgs):
                if get_role(m) == "user": keep_indices.add(i)
                
            # 3. 保留每个 Turn 的最后一个 Assistant 消息 (最终答案)
            for i in range(len(dialog_msgs)):
                if get_role(dialog_msgs[i]) == "assistant":
                    is_last = True
                    for j in range(i + 1, len(dialog_msgs)):
                        if get_role(dialog_msgs[j]) == "assistant":
                            is_last = False; break
                        if get_role(dialog_msgs[j]) == "user": break
                    if is_last: keep_indices.add(i)
                
            # 4. 保留最近的活跃窗口 (最近 N 条消息，确保当前工具链不被切断)
            tail_start = max(0, len(dialog_msgs) - (max_rounds * 2))
            for i in range(tail_start, len(dialog_msgs)):
                keep_indices.add(i)
                
            # 构造初步压缩后的列表
            compressed_dialog = [dialog_msgs[i] for i in sorted(list(keep_indices))]
            chat_messages = sys_msgs + compressed_dialog
            logging.getLogger("app").info(f"[Context] Compressed to {len(chat_messages)} msgs.")

    request.messages = sanitize_tool_chains(chat_messages)
    request.messages = ensure_thinking_fields(request.messages)


async def _stream_character_context(request, settings, user_prompt, cur_memory, memoryId, m0):
    """Character-book lore + persona fields + mem0 recall (stream wording)."""
    if settings["memorySettings"]["userName"]:
        logging.getLogger("app").info("添加用户名：\n\n" + settings["memorySettings"]["userName"] + "\n\n用户名结束\n\n")
        content_append(request.messages, 'system', "与你交流的默认用户名为：\n\n" + settings["memorySettings"]["userName"] + "\n\n注意！除非用户消息中提到了是其他用户发送，否则视为默认用户发送的消息\n\n")
    lore_content = ""
    assistant_reply = ""
    # 找出request.messages中上次的assistant回复
    for i in range(len(request.messages)-1, -1, -1):
        if request.messages[i]['role'] == 'assistant':
            assistant_reply = request.messages[i]['content']
            break
    if cur_memory["characterBook"]:
        for lore in cur_memory["characterBook"]:
            # lore['keysRaw'] 按照换行符分割，并去除空字符串
            lore_keys = lore["keysRaw"].split("\n")
            lore_keys = [key for key in lore_keys if key != ""]
            logging.getLogger("app").info(lore_keys)
            # 如果lore_keys不为空，并且lore_keys的任意一个元素在user_prompt或者assistant_reply中，则添加lore['content']到lore_content中
            if lore_keys != [] and any(key in user_prompt or key in assistant_reply for key in lore_keys):
                lore_content += lore['content'] + "\n\n"
    if lore_content:
        if settings["memorySettings"]["userName"]:
            # 替换lore_content中的{{user}}为settings["memorySettings"]["userName"]
            lore_content = lore_content.replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换lore_content中的{{char}}为cur_memory["name"]
        lore_content = lore_content.replace("{{char}}", cur_memory["name"])
        logging.getLogger("app").info("添加世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
        content_append(request.messages, 'system', "世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
    if cur_memory["description"]:
        if settings["memorySettings"]["userName"]:
            # 替换cur_memory["description"]中的{{user}}为settings["memorySettings"]["userName"]
            cur_memory["description"] = cur_memory["description"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["description"]中的{{char}}为cur_memory["name"]
        cur_memory["description"] = cur_memory["description"].replace("{{char}}", cur_memory["name"])
        logging.getLogger("app").info("添加角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
        content_append(request.messages, 'system', "角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
    if cur_memory["personality"]:
        if settings["memorySettings"]["userName"]:
            # 替换cur_memory["personality"]中的{{user}}为settings["memorySettings"]["userName"]
            cur_memory["personality"] = cur_memory["personality"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["personality"]中的{{char}}为cur_memory["name"]
        cur_memory["personality"] = cur_memory["personality"].replace("{{char}}", cur_memory["name"])
        logging.getLogger("app").info("添加性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n")
        content_append(request.messages, 'system', "性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n") 
    if cur_memory['mesExample']:
        if settings["memorySettings"]["userName"]:
            # 替换cur_memory["mesExample"]中的{{user}}为settings["memorySettings"]["userName"]
            cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["mesExample"]中的{{char}}为cur_memory["name"]
        cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{char}}", cur_memory["name"])
        logging.getLogger("app").info("添加对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
        content_append(request.messages, 'system', "对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
    if cur_memory["systemPrompt"]:
        if settings["memorySettings"]["userName"]:
            # 替换cur_memory["systemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
            cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
        cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{char}}", cur_memory["name"])
        content_append(request.messages, 'system', "\n\n" + cur_memory["systemPrompt"] + "\n\n")
    if settings["memorySettings"]["genericSystemPrompt"]:
        if settings["memorySettings"]["userName"]:
            # 替换settings["memorySettings"]["genericSystemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
            settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
        # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
        settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{char}}", cur_memory["name"])
        content_append(request.messages, 'system', "\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n")
    if m0 and not request.is_sub_agent:
        memoryLimit = settings["memorySettings"]["memoryLimit"]
        try:
            # 【核心修改】：使用 asyncio.to_thread 将同步的 search 方法放入线程池运行
            # 这样主线程（Event Loop）会被释放，可以去处理 /minilm/embeddings 请求，从而避免死锁
            relevant_memories = await asyncio.to_thread(
                m0.search, 
                query=user_prompt, 
                user_id=memoryId, 
                limit=memoryLimit
            )
            relevant_memories = json.dumps(relevant_memories, ensure_ascii=False)
        except Exception as e:
            print("m0.search error:",e)
            relevant_memories = ""
        logging.getLogger("app").info("添加相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")
        content_append(request.messages, 'system', "之前的相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")                   


async def _stream_async_tools(request, async_tools_id):
    """Async-tool result harvesting + SSE tool_result chunks. (M-3 split)

    Delegation pattern: the caller re-yields every chunk so SSE ordering and
    backpressure stay identical to the original inline code.
    """
    if async_tools_id:
        responses_to_send = []
        responses_to_wait = []
        async with async_tools_lock:
            # 收集已完成的结果并删除条目
            for tid in list(async_tools.keys()):  # 转成list避免字典修改异常
                if tid in async_tools_id:
                    if async_tools[tid]["status"] in ("completed", "error"):
                        responses_to_send.append({
                            "tool_id": tid,
                            **async_tools.pop(tid)  # 移除已处理的条目
                        })
                    elif async_tools[tid]["status"] == "pending":
                        responses_to_wait.append({
                            "tool_id": tid,
                            "name":async_tools[tid]["name"],
                            "parameters": async_tools[tid]["parameters"]
                        })
        for response in responses_to_send:
            tid = response["tool_id"]
            if response["status"] == "completed":
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": response["name"], "content": str(response["result"]), "type": "tool_result"},
                            "async_tool_id": tid,
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
                request.messages.insert(-1, 
                    {
                        "tool_calls": [
                            {
                                "id": "agentParty",
                                "function": {
                                    "arguments": json.dumps(response["parameters"]),
                                    "name": response["name"],
                                },
                                "type": "function",
                            }
                        ],
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "",
                    }
                )
                request.messages.insert(-1, 
                    {
                        "role": "tool",
                        "tool_call_id": "agentParty",
                        "name": response["name"],
                        "content": f"之前调用的异步工具（{tid}）的结果：\n\n{_cap_tool_result(str(response['result']))}\n\n====结果结束====\n\n你必须根据工具结果回复未回复的问题或需求。请不要重复调用该工具！"
                    }
                )
            if response["status"] == "error":
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": f"{tid}{await t('tool_result')}", "content": f"Error: {str(response['result'])}"},
                            "async_tool_id": tid
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
                request.messages.append({
                    "role": "system",
                    "content": f"之前调用的异步工具（{tid}）发生错误：\n\n{response['result']}\n\n====错误结束====\n\n"
                }) 
        for response in responses_to_wait:
            # 在request.messages倒数第一个元素之前的位置插入一个新元素
            request.messages.insert(-1, 
                {
                    "tool_calls": [
                        {
                            "id": "agentParty",
                            "function": {
                                "arguments": json.dumps(response["parameters"]),
                                "name": response["name"],
                            },
                            "type": "function",
                        }
                    ],
                    "role": "assistant",
                    "content": "",
                    "reasoning_content": "",
                }
            )
            results = f"{response["name"]}工具已成功启动，获取结果需要花费很久的时间。请不要再次调用该工具，因为工具结果将生成后自动发送，再次调用也不能更快的获取到结果。请直接告诉用户，你会在获得结果后回答他的问题。"
            request.messages.insert(-1, 
                {
                    "role": "tool",
                    "tool_call_id": "agentParty",
                    "name": response["name"],
                    "content": str(results),
                }
            )


async def _stream_kb_before(request, settings, user_prompt, kb_list):
    """before_thinking knowledge-base query with call/result SSE notices."""
    from py.know_base import query_knowledge_base, rerank_knowledge_base
    if settings["KBSettings"]["when"] == "before_thinking" or settings["KBSettings"]["when"] == "both":
        if kb_list:
            chunk_dict = {
                "id": "webSearch",
                "choices": [
                    {
                        "finish_reason": None,
                        "index": 0,
                        "delta": {
                            "role":"assistant",
                            "content": "",
                            "tool_content": {"title": "query_knowledge_base", "content": "", "type": "call"},
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            all_kb_content = []
            # 用query_knowledge_base函数查询kb_list中所有的知识库
            for kb in kb_list:
                kb_content = await query_knowledge_base(kb["kb_id"],user_prompt)
                all_kb_content.extend(kb_content)
                if settings["KBSettings"]["is_rerank"]:
                    all_kb_content = await rerank_knowledge_base(user_prompt,all_kb_content)
            if all_kb_content:
                all_kb_content = json.dumps(all_kb_content, ensure_ascii=False, indent=4)
                kb_message = f"\n\n可参考的知识库内容：{all_kb_content}"
                content_append(request.messages, 'user',  f"{kb_message}\n\n用户：{user_prompt}")
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": "query_knowledge_base", "content": str(all_kb_content), "type": "tool_result"},
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"


async def _stream_web_search_pre(request, settings, user_prompt, tools, enable_web_search):
    """Web search before-thinking injection + after-thinking announcements."""
    from py.web_search import (
        DDGsearch, searxng, Tavily_search, Bing_search, Google_search,
        Brave_search, Exa_search, Serper_search, bochaai_search, youcom_search,
        duckduckgo_tool, searxng_tool, tavily_tool, bing_tool, google_tool,
        brave_tool, exa_tool, serper_tool, bochaai_tool, youcom_tool, jina_crawler_tool,
        simple_fetch_tool, Crawl4Ai_tool, firecrawl_tool, markdown_new_tool,
        websearch_with_fallback, browser_search_tool,
    )
    if settings['webSearch']['enabled'] or enable_web_search:
        if settings['webSearch']['when'] == 'before_thinking' or settings['webSearch']['when'] == 'both':
            chunk_dict = {
                "id": "webSearch",
                "choices": [
                    {
                        "finish_reason": None,
                        "index": 0,
                        "delta": {
                            "role":"assistant",
                            "content": "",
                            "tool_content": {"title": "web_search", "content": "", "type": "call"},
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            # S90：统一入口——配置引擎失败自动走内置浏览器兜底
            results = await websearch_with_fallback(
                settings['webSearch']['engine'], user_prompt)
            if results:
                content_append(request.messages, 'user',  f"\n\n联网搜索结果：{results}\n\n请根据联网搜索结果组织你的回答，并确保你的回答是准确的。")
                tool_chunk = {
                    "choices": [{
                        "delta": {
                            "tool_content": {"title": "web_search", "content": str(results), "type": "tool_result"},
                        }
                    }]
                }
                yield f"data: {json.dumps(tool_chunk)}\n\n"
        if settings['webSearch']['when'] == 'after_thinking' or settings['webSearch']['when'] == 'both':
            if settings['webSearch']['engine'] == 'duckduckgo':
                tools.append(duckduckgo_tool)
            elif settings['webSearch']['engine'] == 'searxng':
                tools.append(searxng_tool)
            elif settings['webSearch']['engine'] == 'tavily':
                tools.append(tavily_tool)
            elif settings['webSearch']['engine'] == 'bing':
                tools.append(bing_tool)
            elif settings['webSearch']['engine'] == 'google':
                tools.append(google_tool)
            elif settings['webSearch']['engine'] == 'brave':
                tools.append(brave_tool)
            elif settings['webSearch']['engine'] == 'exa':
                tools.append(exa_tool)
            elif settings['webSearch']['engine'] == 'serper':
                tools.append(serper_tool)
            elif settings['webSearch']['engine'] == 'bochaai':
                tools.append(bochaai_tool)
            elif settings['webSearch']['engine'] == 'youcom':
                tools.append(youcom_tool)
            elif settings['webSearch']['engine'] == 'browser':
                tools.append(browser_search_tool)

            if settings['webSearch']['crawler'] == 'jina':
                tools.append(jina_crawler_tool)
            elif settings['webSearch']['crawler'] == 'crawl4ai':
                tools.append(Crawl4Ai_tool)
            elif settings['webSearch']['crawler'] == 'firecrawl':
                tools.append(firecrawl_tool)
            elif settings['webSearch']['crawler'] == 'simpleRequest':
                tools.append(simple_fetch_tool)
            elif settings['webSearch']['crawler'] == 'mdnew':
                tools.append(markdown_new_tool)


def _stream_filter_tools(request, tools):
    """enable/disable whitelist-blacklist filter + subagent safety policy.

    S73: 显式空列表（[] 而非 None）= 有效指令：enable_tools=[] -> 0 工具。
    旧语义把 [] 当“未指定”导致日记总结的无工具意图被静默忽略（全量工具）。
    """
    _has_enable = request.enable_tools is not None
    _has_disable = request.disable_tools is not None
    if request.is_sub_agent or _has_enable or _has_disable:
        original_tool_count = len(tools)
                    
        # 1. Enable Tools 过滤（白名单模式）
        if _has_enable:
            # 只保留白名单中的工具（空名单 -> 无工具）
            filtered_tools = []
            enable_set = set(request.enable_tools)
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name in enable_set:
                    filtered_tools.append(tool)
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[Tool Filter] Enable mode: {original_tool_count} -> {len(tools)} tools (enabled: {request.enable_tools})")
                    
        # 2. Disable Tools 过滤（黑名单模式）
        elif _has_disable and len(request.disable_tools) > 0:
            # 移除黑名单中的工具
            disable_set = set(request.disable_tools)
            filtered_tools = []
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name not in disable_set:
                    filtered_tools.append(tool)
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[Tool Filter] Disable mode: {original_tool_count} -> {len(tools)} tools (disabled: {request.disable_tools})")
                    
        # 3. 子智能体默认策略（如果没有指定 enable/disable）
        elif request.is_sub_agent:
            # 子智能体默认只保留安全的工具，移除高风险操作
            SUBAGENT_BLOCKED_TOOLS = [
                            
                # 阻止子智能体管理进程/端口
                "list_processes_tool",
                "get_process_logs_tool",
                "kill_process_tool",
                "docker_manage_ports_tool",
                "local_net_tool",
                            
                # 阻止子智能体创建子任务（防止递归）
                "create_subtask",
                            
                # 阻止高风险的浏览器操作
                "new_page",
                "close_page",
                "evaluate_script",
                            
                # 阻止子智能体使用 Agent 调用（防止复杂的嵌套）
                "agent_tool_call",
                "todo_write_tool",
            ]
                        
            filtered_tools = []
            blocked_count = 0
                        
            for tool in tools:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name not in SUBAGENT_BLOCKED_TOOLS:
                    filtered_tools.append(tool)
                else:
                    blocked_count += 1
                        
            tools = filtered_tools
            logging.getLogger("app").info(f"[SubAgent Safety] Blocked {blocked_count} dangerous tools: {original_tool_count} -> {len(tools)} tools")
    return tools

async def _stream_deepsearch_pre(_st, client, model, extra_params, request):
    """Deep-research step planning streamed to the client as tool_progress.

    Mutable results cross the generator boundary via _st (yield delegation
    cannot carry a return value). (M-3 split)
    """
    deepsearch_messages = copy.deepcopy(request.messages)
    content_append(deepsearch_messages, 'user',  "\n\n将用户提出的问题或给出的当前任务拆分成多个步骤，每一个步骤用一句简短的话概括即可，无需回答或执行这些内容，直接返回总结即可，但不能省略问题或任务的细节。如果用户输入的只是闲聊或者不包含任务和问题，直接把用户输入重复输出一遍即可。如果是非常简单的问题，也可以只给出一个步骤即可。一般情况下都是需要拆分成多个步骤的。")
                    
    # 1. 开启 stream=True 进行流式请求
    response = await client.chat.completions.create(
        model=model,
        messages=deepsearch_messages,
        stream=True,  # 新增
        extra_body = extra_params, # 其他参数
    )
                    
    user_prompt = ""
    # 生成一个唯一的 ID，用于让前端锁定同一个 UI 块进行内容更新
    deepsearch_id = f"ds_{uuid.uuid4().hex[:8]}"
                    
    # 2. 遍历流式响应并实时推给前端
    async for chunk in response:
        if not chunk.choices:
            continue
                        
        # 兼容不同版本的 openai 响应对象
        chunk_dict = chunk.model_dump() if hasattr(chunk, 'model_dump') else chunk
        delta = chunk_dict["choices"][0].get("delta", {})
        content = delta.get("content", "")
                        
        if content:
            user_prompt += content
                            
            # 3. 借用前端原有的 tool_progress 渲染机制
            # 前端会自动创建类似 "调用deep_research工具" 的动态刷新框
            progress_chunk = {
                "choices": [{
                    "delta": {
                        "tool_progress": {
                            "name": "deep_research",
                            "arguments": user_prompt, # 传入不断累加的内容
                            "tool_call_id": deepsearch_id
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(progress_chunk)}\n\n"
                    
    content_append(request.messages, 'user',  f"\n\n如果用户没有提出问题或者任务，直接闲聊即可，如果用户提出了问题或者任务，任务描述不清晰或者你需要进一步了解用户的真实需求，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。")

    _st["user_prompt"] = user_prompt


async def _stream_reasoner_prep(_st, request, reasoner_client, settings, images, reasoner_extra, open_tag, close_tag, tools, DRS_STAGE, user_prompt, enable_deep_research):
    """First reasoner pass (streamed reasoning deltas) + vendor resolution."""
    reasoner_messages = copy.deepcopy(request.messages)
    if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
        content_append(reasoner_messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
        drs_msg = get_drs_stage(DRS_STAGE)
        if drs_msg:
            content_append(reasoner_messages, 'user',  f"\n\n{drs_msg}\n\n")
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)
    if vendor == 'Ollama':
        if settings['reasoner']['temperature'] !=1:
            reasoner_extra['temperature'] = settings['reasoner']['temperature']

        # 流式调用推理模型
        reasoner_stream = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            **reasoner_extra
        )
        full_reasoning = ""
        buffer = ""  # 跨chunk的内容缓冲区
        in_reasoning = False  # 是否在标签内
                        
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue
            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                current_content = delta.get("content", "")
                buffer += current_content  # 累积到缓冲区
                                
                # 实时处理缓冲区内容
                while True:
                    reasoning_content = delta.get("reasoning_content", "")
                    if reasoning_content:
                        full_reasoning += reasoning_content
                    else:
                        reasoning_content = delta.get("reasoning", "")
                        if reasoning_content:
                            delta['reasoning_content'] = reasoning_content
                            full_reasoning += reasoning_content
                    if reasoning_content:
                        yield f"data: {json.dumps(chunk_dict)}\n\n"
                        break
                    if not in_reasoning:
                        # 寻找开放标签
                        start_pos = buffer.find(open_tag)
                        if start_pos != -1:
                            # 开放标签前的内容（非思考内容）
                            non_reasoning = buffer[:start_pos]
                            buffer = buffer[start_pos+len(open_tag):]
                            in_reasoning = True
                        else:
                            break  # 无开放标签，保留后续处理
                    else:
                        # 寻找闭合标签
                        end_pos = buffer.find(close_tag)
                        if end_pos != -1:
                            # 提取思考内容并构造响应
                            reasoning_part = buffer[:end_pos]
                            chunk_dict["choices"][0]["delta"] = {
                                "reasoning_content": reasoning_part,
                                "content": ""  # 清除非思考内容
                            }
                            yield f"data: {json.dumps(chunk_dict)}\n\n"
                            full_reasoning += reasoning_part
                            buffer = buffer[end_pos+len(close_tag):]
                            in_reasoning = False
                        else:
                            # 发送未闭合的中间内容
                            if buffer:
                                chunk_dict["choices"][0]["delta"] = {
                                    "reasoning_content": buffer,
                                    "content": ""
                                }
                                yield f"data: {json.dumps(chunk_dict)}\n\n"
                                full_reasoning += buffer
                                buffer = ""
                            break  # 等待更多内容
    else:
        if settings['reasoner']['temperature'] !=1:
            reasoner_extra['temperature'] = settings['reasoner']['temperature']
        # 流式调用推理模型
        reasoner_stream = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            stop=settings['reasoner']['stop_words'],
            **reasoner_extra
        )
        full_reasoning = ""
        # 处理推理模型的流式响应
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue

            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                reasoning_content = delta.get("reasoning_content", "")
                if reasoning_content:
                    full_reasoning += reasoning_content
                else:
                    reasoning_content = delta.get("reasoning", "")
                    if reasoning_content:
                        delta['reasoning_content'] = reasoning_content
                        full_reasoning += reasoning_content
                # 移除content字段，确保yield的内容中不包含content
                if 'content' in delta:
                    del delta['content']
            yield f"data: {json.dumps(chunk_dict)}\n\n"

    # 在推理结束后添加完整推理内容到消息
    content_append(request.messages, 'assistant', f"<think>\n{full_reasoning}\n</think>")  # 可参考的推理过程

    _st["vendor"] = vendor


async def _stream_first_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, is_tool_call, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count):
    """First LLM stream: tool_call slot merging + think-tag splitting + SSE."""
    async for chunk in response:
        if not chunk.choices:
            if getattr(chunk, "usage", None):
                usage_info = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else dict(chunk.usage)
                _ctx_peak = max(_ctx_peak, usage_info.get("prompt_tokens") or 0)
            continue
        _chunk_count += 1
        if _chunk_count % 5 == 0:
            await asyncio.sleep(0)  # 定期让出控制权，让事件循环处理WebSocket ping
        choice = chunk.choices[0]
        if choice.delta is None:  # B1(1775d8d3): 末包 delta:null 兼容（少数兼容服务）
            continue
        if choice.delta.tool_calls:  # function_calling
            is_tool_call = True
            # C-20+S85-A: 槽位合并统一走 _merge_tool_delta
            # （index → id 匹配 → 末槽），progress 帧只下发本帧增量。
            for tool in choice.delta.tool_calls:
                current_tool, _frag = _merge_tool_delta(tool_calls, tool)
                _slot = tool_calls.index(current_tool)
                if current_tool.function and current_tool.function.name:
                    progress_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_progress": {  # 新增字段，区别于最终的 tool_content
                                    "name": current_tool.function.name,
                                    "arguments": _frag,
                                    "incremental": True,
                                    "index": _slot,
                                    "id": current_tool.id or f"call_{_slot}"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(progress_chunk)}\n\n"
        else:
            if hasattr(choice.delta, "audio") and choice.delta.audio and is_tool_call == False:
                # 只把 Base64 音频数据留在 delta 里，别动它
                yield f"data: {chunk.model_dump_json()}\n\n"
                continue
            elif hasattr(choice.delta, "audio") and choice.delta.audio and is_tool_call == True:
                continue
            # 创建原始chunk的拷贝
            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0]["delta"]
                        
            # 初始化必要字段
            delta.setdefault("content", "")
            delta.setdefault("reasoning_content", "")
                        
            # 优先处理 reasoning_content
            if delta["reasoning_content"]:
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                continue
            if delta.get("reasoning", ""):
                delta["reasoning_content"] = delta["reasoning"]
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                continue

            # 处理内容
            current_content = delta["content"]
            buffer = current_content
                        
            while buffer:
                if not in_reasoning:
                    # 寻找开始标签
                    start_pos = buffer.find(open_tag)
                    if start_pos != -1:
                        # 处理开始标签前的内容
                        content_buffer.append(buffer[:start_pos])
                        buffer = buffer[start_pos+len(open_tag):]
                        in_reasoning = True
                    else:
                        content_buffer.append(buffer)
                        buffer = ""
                else:
                    # 寻找结束标签
                    end_pos = buffer.find(close_tag)
                    if end_pos != -1:
                        # 处理思考内容
                        reasoning_buffer.append(buffer[:end_pos])
                        buffer = buffer[end_pos+len(close_tag):]
                        in_reasoning = False
                    else:
                        reasoning_buffer.append(buffer)
                        buffer = ""
                        
            # 构造新的delta内容
            new_content = "".join(content_buffer)
            new_reasoning = "".join(reasoning_buffer)
                        
            # 更新chunk内容
            delta["content"] = new_content.strip("\x00")  # 保留未完成内容
            delta["reasoning_content"] = new_reasoning.strip("\x00") or None
                        
            # 重置缓冲区但保留未完成部分
            if in_reasoning:
                content_buffer = [new_content.split(open_tag)[-1]] 
            else:
                content_buffer = []
            reasoning_buffer = []
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            full_content += delta.get("content") or "" 

    _st["usage_info"] = usage_info
    _st["_ctx_peak"] = _ctx_peak
    _st["is_tool_call"] = is_tool_call
    _st["full_content"] = full_content
    _st["in_reasoning"] = in_reasoning
    _st["content_buffer"] = content_buffer
    _st["reasoning_buffer"] = reasoning_buffer
    _st["_chunk_count"] = _chunk_count


async def _stream_drs_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
    """Post-first-pass deep-research status machine with per-status SSE notices."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content)
    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
            "role": "system",
            "content": source_prompt,
            },
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        extra_body = extra_params, # 其他参数
    )
    response_content = response.choices[0].message.content
    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    try:
        response_content = json.loads(response_content)
    except json.JSONDecodeError:
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❌{await t('task_error')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
    if response_content["status"] == "done":
        search_chunk = {
            "choices": [{
                "delta": {
                   "tool_content": {"title": f"✅{await t('task_done')}", "content": ""},
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❎{await t('task_not_done')}", "content": ""},
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "need_more_info":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❓{await t('task_need_more_info')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await t('enter_search_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
                "reasoning_content": "",
            }
        )
    elif response_content["status"] == "need_more_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await t('need_more_work')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "answer":
        DRS_STAGE = 3
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"⭐{await t('enter_answer_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
                "reasoning_content": "",
            }
        )

    _st["drs"] = DRS_STAGE
    _st["snot"] = search_not_done
    _st["stask"] = search_task



def _stream_round_compress(request, settings, _st):
    """L1 context compression after a tool round (W1 copy). (M-3 split)"""
    max_rounds = 0 if _cm_context_enabled(settings) else settings.get("max_rounds", 0)
    chat_messages = request.messages # 这里的 chat_messages 包含 system
    _st.setdefault("_ctx_peak", 0)
    if max_rounds > 0:
                            
        # 区分系统消息和对话消息
        sys_msgs = [m for m in chat_messages if get_role(m) == "system"]
        dialog_msgs = [m for m in chat_messages if get_role(m) != "system"]
                            
        # 设定压缩阈值：当非系统消息超过 max_rounds * 2 + 1 时开始压缩
        if len(dialog_msgs) > (max_rounds * 2 + 1):
            keep_indices = set()
                                
            # 1. 总是保留第一条消息 (Anchor User Prompt)
            if len(dialog_msgs) > 0: keep_indices.add(0)
                                
            # 2. 保留所有 User 消息 (User 优先策略)
            for i, m in enumerate(dialog_msgs):
                if get_role(m) == "user": keep_indices.add(i)
                                
            # 3. 保留每个 Turn 的最后一个 Assistant 消息 (最终答案)
            for i in range(len(dialog_msgs)):
                if get_role(dialog_msgs[i]) == "assistant":
                    is_last = True
                    for j in range(i + 1, len(dialog_msgs)):
                        if get_role(dialog_msgs[j]) == "assistant":
                            is_last = False; break
                        if get_role(dialog_msgs[j]) == "user": break
                    if is_last: keep_indices.add(i)
                                
            # 4. 保留最近的活跃窗口 (最近 N 条消息，确保当前工具链不被切断)
            tail_start = max(0, len(dialog_msgs) - (max_rounds * 2))
            for i in range(tail_start, len(dialog_msgs)):
                keep_indices.add(i)
                                
            # 构造初步压缩后的列表
            compressed_dialog = [dialog_msgs[i] for i in sorted(list(keep_indices))]
            chat_messages = sys_msgs + compressed_dialog
            logging.getLogger("app").info(f"[Context] Compressed to {len(chat_messages)} msgs.")


    request.messages = sanitize_tool_chains(chat_messages)
    request.messages = ensure_thinking_fields(request.messages)

async def _stream_tool_round(_st, request, settings, user_prompt, full_content, tool_calls, reasoner_messages):
    """While-loop tool round: ack, dispatch, SSE results, abort/cancel signals.

    w1_cancel = user cancelled mid-round (generator must terminate);
    w1_abort  = approval gate hit (while must break). (M-3 split)
    """
    from py.know_base import rerank_knowledge_base
    # 将本轮全部 tool_calls 连同伴随的叙述文本一次性 append 为 assistant 消息
    assistant_tool_calls = []
    for _tc in tool_calls:
        _fn = _tc.function
        assistant_tool_calls.append({
            "id": _tc.id or f"call_{uuid.uuid4().hex[:12]}",
            "function": {
                "arguments": _fn.arguments or "",
                "name": _fn.name,
            },
            "type": getattr(_tc, "type", None) or "function",
        })
    request.messages.append({
        "role": "assistant",
        "content": full_content or "",
        "tool_calls": assistant_tool_calls,
        "reasoning_content": "",
    })
    pending_abort = False
    acked_ids = set()
    reasoner_tool_events = []
    for _ti, _tc in enumerate(tool_calls):
        tool_call_id = assistant_tool_calls[_ti]["id"]
        response_content = _tc.function
        logging.getLogger("app").info(response_content)
        args_dict, arg_err = parse_tool_arguments(response_content.arguments)
        if arg_err is not None:
            err_text = arg_error_text(arg_err)
            acked_ids.add(tool_call_id)
            reasoner_tool_events.append((f"{response_content.name}({response_content.arguments})", err_text))
            err_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": err_text,
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(err_chunk)}\n\n"
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": err_text,
            })
            continue

        # 显式发送 "call" 事件，锁定 UI 状态并同步 ID（参数接收完毕，确认调用，绑定 ID）
        call_confirm_chunk = {
            "choices": [{
                "delta": {
                    "tool_call_id": tool_call_id,
                    "tool_content": {
                        "title": response_content.name,
                        "content": json.dumps(args_dict, ensure_ascii=False),
                        "type": "call"
                    }
                }
            }]
        }
        yield f"data: {json.dumps(call_confirm_chunk)}\n\n"

        if settings['tools']['asyncTools']['enabled']:
            # ... 异步工具逻辑保持不变 ...
            tool_id = uuid.uuid4()
            async_tool_id = f"{response_content.name}_{tool_id}"
            chunk_dict = {
                "id": "agentParty",
                "choices": [
                    {
                        "finish_reason": None,
                        "index": 0,
                        "delta": {
                            "role":"assistant",
                            "content": "",
                            "async_tool_id": async_tool_id
                        }
                    }
                ]
            }
            yield f"data: {json.dumps(chunk_dict)}\n\n"
            asyncio.create_task(
                execute_tool(
                    async_tool_id,
                    response_content.name,
                    args_dict,
                    settings,
                    user_prompt
                )
            )
            async with async_tools_lock:
                async_tools[async_tool_id] = {
                    "status": "pending",
                    "result": None,
                    "name":response_content.name,
                    "parameters":args_dict
                }
            results = f"{response_content.name}tool has been successfully launched. It will take some time to run, and the results will be provided in the next round of conversation."
        else:
            if _stream_cancelled():
                logging.getLogger("app").info(f"[Cancel] 流已被用户取消，跳过工具 {response_content.name} 并终止本轮")
                _st["w1_cancel"] = True
                yield "data: [DONE]\n\n"
                return
            try:
                await asyncio.sleep(0)  # 让出控制权，确保心跳/ping能及时发送
                results = await dispatch_tool(response_content.name, args_dict, settings)
                await asyncio.sleep(0)  # 工具调用完成后再次让出，防止事件循环饥饿
            except Exception as e:
                results = TOOL_EXC_TMPL.format(type=type(e).__name__, exc=e)

        if results is None:
            none_text = NONE_TEXT
            none_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": none_text,
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(none_chunk)}\n\n"
            acked_ids.add(tool_call_id)
            reasoner_tool_events.append((f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})", none_text))
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": none_text,
            })
            pending_abort = True
            break

        if response_content.name in ["query_knowledge_base"] and type(results) == list:
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt, results)
            results = json.dumps(results, ensure_ascii=False, indent=4)

        # 发送结果，带上匹配的 tool_call_id
        if not isinstance(results, AsyncIterator):
            results = _cap_tool_result(results)
            result_chunk = {
                "choices": [{
                    "delta": {
                        "tool_call_id": tool_call_id,
                        "tool_content": {
                            "title": response_content.name,
                            "content": str(results),
                            "type": "tool_result"
                        }
                    }
                }]
            }
            yield f"data: {json.dumps(result_chunk)}\n\n"
            if str(response_content.name).startswith("todo_write_tool"):
                try:
                    from py.cli_tool import read_todo_snapshot
                    _td = await read_todo_snapshot()
                    _td_done = sum(1 for _t in _td if isinstance(_t, dict) and _t.get("status") == "done")
                    _td_evt = {"type": "todo_stats",
                               "items": [{k: _t.get(k) for k in ("id", "content", "status", "priority")} for _t in _td if isinstance(_t, dict)],
                               "done": _td_done, "total": len(_td)}
                    yield f"data: {json.dumps(_td_evt, ensure_ascii=False)}\n\n"
                except Exception as _te:
                    logging.getLogger("app").info(f"[Todo] todo_stats 事件推送异常（跳过）: {_te}")
        else:
            # 流式工具结果处理 (AsyncIterator)
            buffer = []
            first = True
            async for chunk in results:
                buffer.append(chunk)
                if first:
                    # 第一帧带 title
                    stream_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_call_id": tool_call_id,
                                "tool_content": {
                                    "title": response_content.name,
                                    "content": chunk,
                                    "type": "tool_result_stream"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(stream_chunk)}\n\n"
                    first = False
                else:
                    # 后续帧
                    stream_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_call_id": tool_call_id,
                                "tool_content": {
                                    "title": "tool_result_stream",
                                    "content": chunk,
                                    "type": "tool_result_stream"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(stream_chunk)}\n\n"
            results = "".join(buffer)

        tool_result_text = str("".join(results))
        _st["results"] = results
        acked_ids.add(tool_call_id)
        reasoner_tool_events.append((f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})", tool_result_text))
        request.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": truncate_tool_result(tool_result_text),
            }
        )

        # 如果工具返回审批请求：停止执行本轮后续调用并跳出循环，等待前端手动调用恢复
        # T-9: 结构化哨兵判定（非子串嗅探），命中即断
        if _is_approval_result(results) is not None:
            pending_abort = True
            break

    # 为未执行的调用补上说明性 tool 结果，保证 tool_calls 与 tool 消息成对闭合
    append_missing_results(request.messages, assistant_tool_calls, acked_ids)


    # =========================================================================
    # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
    # =========================================================================
    _stream_round_compress(request, settings, _st)

    # 将本轮工具事件喂给推理模型上下文
    for _r_call, _r_result in reasoner_tool_events:
        reasoner_messages.append(
            {
                "role": "assistant",
                "content": _r_call,
                "reasoning_content": "",
            }
        )
        reasoner_messages.append(
            {
                "role": "user",
                "content": f"工具结果：" + truncate_tool_result(str(_r_result), 8000),
                "reasoning_content": "",
            }
        )

    _st["w1_abort"] = pending_abort


async def _stream_reasoner_update(_st, request, reasoner_client, settings, reasoner_messages, images, reasoner_extra, open_tag, close_tag, tools, vendor):
    """While-loop reasoner refresh (streamed) + vendor resolution."""
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)
    if vendor == 'Ollama':
        if settings['reasoner']['temperature'] !=1:
            reasoner_extra['temperature'] = settings['reasoner']['temperature']
        # 流式调用推理模型
        reasoner_stream = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            **reasoner_extra
        )
        full_reasoning = ""
        buffer = ""  # 跨chunk的内容缓冲区
        in_reasoning = False  # 是否在标签内
                            
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue
            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                current_content = delta.get("content", "")
                buffer += current_content  # 累积到缓冲区
                                    
                # 实时处理缓冲区内容
                while True:
                    reasoning_content = delta.get("reasoning_content", "")
                    if reasoning_content:
                        full_reasoning += reasoning_content
                    else:
                        reasoning_content = delta.get("reasoning", "")
                        if reasoning_content:
                            delta['reasoning_content'] = reasoning_content
                            full_reasoning += reasoning_content
                    if reasoning_content:
                        yield f"data: {json.dumps(chunk_dict)}\n\n"
                        break
                    if not in_reasoning:
                        # 寻找开放标签
                        start_pos = buffer.find(open_tag)
                        if start_pos != -1:
                            # 开放标签前的内容（非思考内容）
                            non_reasoning = buffer[:start_pos]
                            buffer = buffer[start_pos+len(open_tag):]
                            in_reasoning = True
                        else:
                            break  # 无开放标签，保留后续处理
                    else:
                        # 寻找闭合标签
                        end_pos = buffer.find(close_tag)
                        if end_pos != -1:
                            # 提取思考内容并构造响应
                            reasoning_part = buffer[:end_pos]
                            chunk_dict["choices"][0]["delta"] = {
                                "reasoning_content": reasoning_part,
                                "content": ""  # 清除非思考内容
                            }
                            yield f"data: {json.dumps(chunk_dict)}\n\n"
                            full_reasoning += reasoning_part
                            buffer = buffer[end_pos+len(close_tag):]
                            in_reasoning = False
                        else:
                            # 发送未闭合的中间内容
                            if buffer:
                                chunk_dict["choices"][0]["delta"] = {
                                    "reasoning_content": buffer,
                                    "content": ""
                                }
                                yield f"data: {json.dumps(chunk_dict)}\n\n"
                                full_reasoning += buffer
                                buffer = ""
                            break  # 等待更多内容
    else:
        if settings['reasoner']['temperature'] !=1:
            reasoner_extra['temperature'] = settings['reasoner']['temperature']

        # 流式调用推理模型
        reasoner_stream = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=True,
            stop=settings['reasoner']['stop_words'],
            **reasoner_extra
        )
        full_reasoning = ""
        # 处理推理模型的流式响应
        async for chunk in reasoner_stream:
            if not chunk.choices:
                continue

            chunk_dict = chunk.model_dump()
            delta = chunk_dict["choices"][0].get("delta", {})
            if delta:
                reasoning_content = delta.get("reasoning_content", "")
                if reasoning_content:
                    full_reasoning += reasoning_content
                else:
                    reasoning_content = delta.get("reasoning", "")
                    if reasoning_content:
                        delta['reasoning_content'] = reasoning_content
                        full_reasoning += reasoning_content
                # 移除content字段，确保yield的内容中不包含content
                if 'content' in delta:
                    del delta['content']
            yield f"data: {json.dumps(chunk_dict)}\n\n"

    # 在推理结束后添加完整推理内容到消息
    content_append(request.messages, 'user', f"\n\n可参考的推理过程：{full_reasoning}") # 可参考的推理过程

    _st["vendor"] = vendor


async def _stream_regrab(request, settings, results, images, fastapi_base_url):
    """Post-tool desktop re-grab with action feedback + grid."""
    try:
        import pyautogui
        # 必须从你的工具类中引入设置区域的方法
        from py.computer_use_tool import set_screen_region
                            
        v_settings = settings.get('visionControlSettings', {})
        is_grid_enabled = v_settings.get('isEnableGrid', False)
        is_full_screen = v_settings.get('isFullScreen', True)
        # ScreenSize 格式为 [x, y, width, height]
        screen_size = v_settings.get('ScreenSize', [0, 0, 1920, 1080])
        time.sleep(0.5) # 等待一下，确保截图工具已经准备好
        logging.getLogger("app").info(f"正在执行桌面截图 (全屏: {is_full_screen}, 网格: {is_grid_enabled})...")
                            
        # --- 1. 区域判定与捕获 ---
        if not is_full_screen and len(screen_size) == 4:
            # 局部截图模式
            rx, ry, rw, rh = map(int, screen_size)
            # 关键：告诉鼠标工具，接下来的 0-1000 坐标要映射到这个局部矩形
            set_screen_region((rx, ry, rw, rh))
                                
            # 逻辑尺寸即为选区尺寸
            logical_width, logical_height = rw, rh
            # 捕获指定区域
            screenshot = await asyncio.to_thread(pyautogui.screenshot, region=(rx, ry, rw, rh))
        else:
            # 全屏截图模式
            set_screen_region(None) # 恢复全屏映射
            logical_width, logical_height = pyautogui.size()
            screenshot = await asyncio.to_thread(pyautogui.screenshot)
                            
        # --- 2. 强制 Resize 到逻辑坐标系 (解决 Windows 缩放偏移) ---
        if screenshot.width != logical_width or screenshot.height != logical_height:
            screenshot = await asyncio.to_thread(
                screenshot.resize, (logical_width, logical_height), Image.Resampling.LANCZOS
            )
                            
        # 限制传输图片大小，平衡 Token 消耗
        target_w, target_h = scale_to_fit(logical_width, logical_height, 1280, 720)
        if screenshot.width > target_w or screenshot.height > target_h:
            screenshot = await asyncio.to_thread(
                screenshot.resize, (target_w, target_h), Image.Resampling.LANCZOS
            )

        # --- 3. 绘制视觉反馈 (红点/线) ---
        action_feedback_hint = ""
        if results and "[LAST_ACTION:" in str(results):
            screenshot = await asyncio.to_thread(draw_action_feedback, screenshot, str(results))
            action_feedback_hint = (
                " Notice: The colored markers show your PREVIOUS actions relative to this view. "
                "Cyan = Click. Blue = Double Click. Green-Yellow = Drag."
            )

        # --- 4. 绘制网格辅助 ---
        if is_grid_enabled:
            display_image = await asyncio.to_thread(draw_grid_on_image, screenshot.copy(), grid_spacing=10)
            region_text = "partial region" if not is_full_screen else "full desktop"
            grid_hint = f"\n\n【system info】Screenshot of {region_text} with coordinate grid (0-1000) injected. Use coordinates for precise clicking within this view.\n{action_feedback_hint}"
        else:
            display_image = screenshot
            grid_hint = f"\n\n【system info】Current screenshot injected.\n{action_feedback_hint}"
                            
        # --- 5. 保存并注入消息 ---
        desktop_img_name = f"desktop_view_{uuid.uuid4().hex}.png"
        desktop_img_path = os.path.join(UPLOAD_FILES_DIR, desktop_img_name)
        await asyncio.to_thread(display_image.save, desktop_img_path, optimize=True)
                            
        desktop_url = f"{fastapi_base_url}uploaded_files/{desktop_img_name}"
                            
        current_user_msg = {
            "role": "user",
            "content": [
                {"type": "text", "text": '[Getting screenshot]' + grid_hint},
                {"type": "image_url", "image_url": {"url": desktop_url}}
            ]
        }
        request.messages.append(current_user_msg)
                            
        # --- 6. 清理旧截图 ---
        if v_settings.get('onlyNewScreen', False):
            for msg in request.messages[:-1]:
                if isinstance(msg.get('content'), list):
                    msg['content'] = [item for item in msg['content'] if item.get('type') != 'image_url']
                    if len(msg['content']) == 1 and msg['content'][0].get('type') == 'text':
                        msg['content'] = msg['content'][0]['text']
                    elif len(msg['content']) == 0:
                        msg['content'] = ""

    except Exception as e:
        logging.getLogger("app").info(f"后端桌面截图失败: {e}")
                            
    images = await images_in_messages(request.messages, fastapi_base_url)
    request.messages = await message_without_images(request.messages)

    return images


async def _stream_loop_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count2):
    """While-loop LLM re-request chunk stream (slot merge + think tags)."""
    async for chunk in response:
        if not chunk.choices:
            if getattr(chunk, "usage", None):
                usage_info = chunk.usage.model_dump() if hasattr(chunk.usage, "model_dump") else dict(chunk.usage)
                _ctx_peak = max(_ctx_peak, usage_info.get("prompt_tokens") or 0)
            continue
        _chunk_count2 += 1
        if _chunk_count2 % 5 == 0:
            await asyncio.sleep(0)  # 定期让出控制权，防止事件循环饥饿导致1006断开
        if chunk.choices:
            choice = chunk.choices[0]
            if choice.delta is None:  # B1(1775d8d3): 末包 delta:null 兼容
                continue
            if hasattr(choice.delta, "audio") and choice.delta.audio:
                # 只把 Base64 音频数据留在 delta 里，别动它
                yield f"data: {chunk.model_dump_json()}\n\n"
                continue
            if choice.delta.tool_calls:  # function_calling
                current_tool, _frag = None, ""
                for tool in choice.delta.tool_calls:
                    current_tool, _frag = _merge_tool_delta(tool_calls, tool)
                _idx = tool_calls.index(current_tool)
                if current_tool.function and current_tool.function.name:
                    progress_chunk = {
                        "choices": [{
                            "delta": {
                                "tool_progress": {  # 新增字段，区别于最终的 tool_content
                                    "name": current_tool.function.name,
                                    # S85-A：本帧只下发增量片段（incremental=true），
                                    # 旧实现每帧下发全量累积串 → 前端拼接 O(n²) 膨胀
                                    "arguments": _frag,
                                    "incremental": True,
                                    "index": _idx,
                                    "id": current_tool.id or f"call_{_idx}"
                                }
                            }
                        }]
                    }
                    yield f"data: {json.dumps(progress_chunk)}\n\n"
            else:
                # 创建原始chunk的拷贝
                chunk_dict = chunk.model_dump()
                delta = chunk_dict["choices"][0]["delta"]
                                
                # 初始化必要字段
                delta.setdefault("content", "")
                delta.setdefault("reasoning_content", "")

                # 优先处理 reasoning_content
                if delta["reasoning_content"]:
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                    continue
                if delta.get("reasoning", ""):
                    delta["reasoning_content"] = delta["reasoning"]
                    yield f"data: {json.dumps(chunk_dict)}\n\n"
                    continue
                # 处理内容
                current_content = delta["content"]
                buffer = current_content
                                
                while buffer:
                    if not in_reasoning:
                        # 寻找开始标签
                        start_pos = buffer.find(open_tag)
                        if start_pos != -1:
                            # 处理开始标签前的内容
                            content_buffer.append(buffer[:start_pos])
                            buffer = buffer[start_pos+len(open_tag):]
                            in_reasoning = True
                        else:
                            content_buffer.append(buffer)
                            buffer = ""
                    else:
                        # 寻找结束标签
                        end_pos = buffer.find(close_tag)
                        if end_pos != -1:
                            # 处理思考内容
                            reasoning_buffer.append(buffer[:end_pos])
                            buffer = buffer[end_pos+len(close_tag):]
                            in_reasoning = False
                        else:
                            reasoning_buffer.append(buffer)
                            buffer = ""
                                
                # 构造新的delta内容
                new_content = "".join(content_buffer)
                new_reasoning = "".join(reasoning_buffer)
                                
                # 更新chunk内容
                delta["content"] = new_content.strip("\x00")  # 保留未完成内容
                delta["reasoning_content"] = new_reasoning.strip("\x00") or None
                                
                # 重置缓冲区但保留未完成部分
                if in_reasoning:
                    content_buffer = [new_content.split(open_tag)[-1]] 
                else:
                    content_buffer = []
                reasoning_buffer = []
                                
                yield f"data: {json.dumps(chunk_dict)}\n\n"
                full_content += delta.get("content") or "" 

    _st["usage_info"] = usage_info
    _st["_ctx_peak"] = _ctx_peak
    _st["full_content"] = full_content
    _st["in_reasoning"] = in_reasoning
    _st["content_buffer"] = content_buffer
    _st["reasoning_buffer"] = reasoning_buffer
    _st["_chunk_count2"] = _chunk_count2


async def _stream_drs_loop_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
    """While-loop deep-research status machine (stream SSE notices)."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,full_content)
    response = await client.chat.completions.create(
        model=model,
        messages=[                        
            {
            "role": "system",
            "content": source_prompt,
            },
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        extra_body = extra_params, # 其他参数
    )
    response_content = response.choices[0].message.content
    if response_content is None:
        response_content = ""
    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    try:
        response_content = json.loads(response_content)
    except json.JSONDecodeError:
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❌{await t('task_error')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
    if response_content["status"] == "done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"✅{await t('task_done')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❎{await t('task_not_done')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "need_more_info":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"❓{await t('task_need_more_info')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await t('enter_search_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )
    elif response_content["status"] == "need_more_work":
        DRS_STAGE = 2
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"🔍{await t('need_more_work')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "answer":
        DRS_STAGE = 3
        search_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {"title": f"⭐{await t('enter_answer_stage')}", "content": ""}
                }
            }]
        }
        yield f"data: {json.dumps(search_chunk)}\n\n"
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": full_content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )

    _st["drs"] = DRS_STAGE
    _st["snot"] = search_not_done
    _st["stask"] = search_task


async def _stream_usage_event(request, settings, usage_info, _ctx_peak, tools):
    """context_usage SSE event generation + log line. (M-3 split)"""
    try:
        from py.context_manager import get_context_settings as _gcs, estimate_tokens as _esttok
        _cm_u = _gcs(settings)
        _usage_evt = {
            "type": "context_usage",
            "prompt_tokens": (usage_info or {}).get("prompt_tokens"),
            "completion_tokens": (usage_info or {}).get("completion_tokens"),
            "peak_prompt_tokens": _ctx_peak or None,
            "window": _cm_u["context_window"],
            "budget": int(_cm_u["context_window"] * _cm_u["compact_ratio"]),
            "est_total": _esttok(request.messages, tools),
            "breakdown": _breakdown_tokens(request.messages, tools),
        }
        yield f"data: {json.dumps(_usage_evt, ensure_ascii=False)}\n\n"
        logging.getLogger("app").info(f"[Context] usage: prompt={_usage_evt['prompt_tokens']} peak={_usage_evt['peak_prompt_tokens']} est_total={_usage_evt['est_total']} window={_usage_evt['window']}")
    except Exception as _ue:
        logging.getLogger("app").info(f"[Context] usage 事件生成异常（跳过）: {_ue}")


async def _stream_finalize_jobs(request, settings, full_content, user_prompt, m0, memoryId, cur_memory):
    """turn-log shadow append + affection extraction + mem0 submit job."""
    try:
        from py.turn_log import shadow_append as _shadow_append
        await _shadow_append(request.conversation_id, request.messages, log=print)
    except Exception as _tle:
        logging.getLogger("app").info(f"[TurnLog] stream shadow skip: {_tle}")
    if settings.get('loveSettings', {}).get('enabled', False) and not request.is_sub_agent:
        try:
            from py.affection_system import extract_and_update_affection
            # full_content 是当前轮次 AI 的完整回复文本
            await extract_and_update_affection(full_content)
        except Exception as e:
            logging.getLogger("app").info(f"解析好感度标签出错: {e}")
    # ========== 对话缓冲：记录助手回复用于闲时自动总结 ==========
    try:
        diary_settings_inner = (settings.get("diarySettings", {}) or {})
        if diary_settings_inner.get("enabled", False) and diary_settings_inner.get("chatSummary", {}).get("enabled", True):
            ms = (settings or {}).get("memorySettings", {}) or {}
            buffer_key = ms.get("selectedMemory") or DIARY_DEFAULT_BOOK
            if full_content:
                append_to_chat_buffer(buffer_key, "assistant", full_content)
    except Exception as e:
        logging.getLogger("app").info(f"[DiaryBuffer] 记录助手回复失败: {e}")
    if m0 and not request.is_sub_agent:
        logging.getLogger("app").info("记忆更新任务开始提交")
        messages = f"用户说：{user_prompt}\n\n---\n\n你说：{full_content}"
        infer = cur_memory.get('infer', False) or False
        _m0_job = m0
        _mid = memoryId
        _job_msgs = messages

        def _mem_job():
            metadata = {
                "timetamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _m0_job.add(_job_msgs, user_id=_mid, metadata=metadata, infer=infer)

        llm_gate.submit_memory_job(
            _mid, _mem_job, name="mem0-add",
            debounce=float((settings.get('llmGuardSettings') or {}).get('debounceSeconds', 20) or 0)
                     if (settings.get('llmGuardSettings') or {}).get('enabled', True) else 0.0,
            wait_idle=(settings.get('llmGuardSettings') or {}).get('enabled', True))
        logging.getLogger("app").info("记忆更新任务已提交到后台线程")

def _append_loopcap_hint(request, tag):
    """S78(B2-2/T-8 单点): 工具迭代上限后的收尾提示——强制模型基于已有
    工作向用户总结（流式与非流式共用）。"""
    logging.getLogger("app").info(f"[LoopCap] {tag}工具调用迭代上限已达，强制模型收尾")
    request.messages.append({
        "role": "user",
        "content": "[系统提示] 你已达到本轮工具调用迭代上限，工具已不可用。请基于已完成的工作向用户总结当前进展与剩余步骤。",
    })


def _drs_round_cap(loop_count, max_iters, search_not_done, tool_calls, tag):
    """S78(B2-2 16f079d4 fork 侧补强): 纯深度研究轮（无 tool_calls）也须有
    出口。返回 False=轮数超限且非可收尾工具轮，调用方应结束循环。"""
    if loop_count <= max_iters:
        return True
    if tool_calls and not search_not_done:
        return True  # 纯工具轮交给迭代上限收尾提示路径
    logging.getLogger("app").info(f"[LoopCap] {tag}迭代上限({max_iters})已达，强制结束循环")
    return False


async def stream_generator(client, reasoner_client, request, settings, fastapi_base_url,
                     enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                     user_prompt, DRS_STAGE, tools, images,
                     chat_vendor, reasoner_vendor, model, extra_params,
                     open_tag, close_tag, source_prompt, m0, memoryId, cur_memory):
    from py.know_base import kb_tool
    from py.task_tools import (
        create_subtask_tool,
        query_tasks_tool,
        cancel_subtask_tool,
        finish_task_tool,
    )
    from py.mode_change import mode_change_tool
    # ---------- 统一 SSE 封装 ----------
    def make_sse(tool_data: dict) -> str:
        chunk = {
            "choices": [{
                "delta": {
                    "tool_content": tool_data, # 这里直接传字典
                }
            }]
        }
        return f"data: {json.dumps(chunk)}\n\n"
    try:
        llm_gate.enter()
        _st = {}
        usage_info = None
        _ctx_peak = 0
        extra = {}
        reasoner_extra = {}
        if chat_vendor == 'OpenAI':
            extra['max_completion_tokens'] = request.max_tokens or settings['max_tokens']
        else:
            extra['max_tokens'] = request.max_tokens or settings['max_tokens']
        if settings.get('enableOmniTTS',False) and not request.is_sub_agent:
            extra['modalities'] = ["text", "audio"]
            extra['audio'] ={"voice": settings.get('omniVoice',"Cherry"), "format": "wav"}
        if reasoner_vendor == 'OpenAI':
            reasoner_extra['max_completion_tokens'] = settings['reasoner']['max_tokens']
        else:
            reasoner_extra['max_tokens'] = settings['reasoner']['max_tokens']
        if request.reasoning_effort or settings['reasoning_effort']:
            extra['reasoning_effort'] = request.reasoning_effort or settings['reasoning_effort']
        if settings['reasoner']['reasoning_effort'] is not None:
            reasoner_extra['reasoning_effort'] = settings['reasoner']['reasoning_effort']
        # 处理传入的异步工具ID查询
        async for _c in _stream_async_tools(request, async_tools_id):
            yield _c
        kb_list = []
        if settings["knowledgeBases"]:
            for kb in settings["knowledgeBases"]:
                if kb["enabled"] and kb["processingStatus"] == "completed":
                    kb_list.append({"kb_id":kb["id"],"name": kb["name"],"introduction":kb["introduction"]})
        async for _c in _stream_kb_before(request, settings, user_prompt, kb_list):
            yield _c
        if settings["KBSettings"]["when"] == "after_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                kb_list_message = f"\n\n可调用的知识库列表：{json.dumps(kb_list, ensure_ascii=False)}"
                content_append(request.messages, 'system', kb_list_message)
        else:
            kb_list = []
        async for _c in _stream_web_search_pre(request, settings, user_prompt, tools, enable_web_search):
            yield _c
        if kb_list:
            tools.append(kb_tool)

        # ==================== 获取权限模式 ====================
        cli_settings = settings.get("CLISettings", {})
        engine = cli_settings.get("engine", "")
                
        # 根据环境类型获取权限模式
        if engine == "local":
            env_settings = settings.get("localEnvSettings", {})
        elif engine == "ds":
            env_settings = settings.get("dsSettings", {})
        else:
            env_settings = settings.get("acpSettings", {})
                
        permission_mode = cli_permission_mode_for(settings)
        if permission_mode == "cowork" and settings['CLISettings']['enabled'] and not request.is_sub_agent:
            tools = []
            tools.append(create_subtask_tool)
            tools.append(query_tasks_tool)
            tools.append(cancel_subtask_tool)
            if  settings['CLISettings']['mode_change']:
                tools.append(mode_change_tool)

        if request.is_sub_agent:
            tools.append(finish_task_tool)
        # 如果是子智能体调用，或者指定了工具过滤规则
        tools = _stream_filter_tools(request, tools)
            

        logging.getLogger("app").info(tools)

        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            async for _c in _stream_deepsearch_pre(_st, client, model, extra_params, request):
                yield _c
            user_prompt = _st["user_prompt"]
        # 如果启用推理模型
        if settings['reasoner']['enabled'] or enable_thinking:
            async for _c in _stream_reasoner_prep(_st, request, reasoner_client, settings, images, reasoner_extra, open_tag, close_tag, tools, DRS_STAGE, user_prompt, enable_deep_research):
                yield _c
            vendor = _st["vendor"]
        # 状态跟踪变量
        in_reasoning = False
        reasoning_buffer = []
        content_buffer = []
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            content_append(request.messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
            drs_msg = get_drs_stage(DRS_STAGE)
            if drs_msg:
                content_append(request.messages, 'user',  f"\n\n{drs_msg}\n\n")
        # ===== 上下文管理管线：L1 修剪 -> L2 自动摘要（agent 模式），结果下发前端落账 =====
        _compact_event_payload = await _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools)
        if _compact_event_payload:
            yield f"data: {json.dumps(_compact_event_payload, ensure_ascii=False)}\n\n"
        msg = await images_add_in_messages(request.messages, images,settings)
        if request.top_p != 1 or settings['top_p'] != 1:
            extra['top_p'] = request.top_p or settings['top_p']

        if settings['temperature'] !=1:
            extra['temperature'] = settings['temperature']

        if tools:
            extra['tools'] = tools

        if _stream_cancelled():
            logging.getLogger("app").info("[Cancel] 流已被用户取消，发起 LLM 调用前终止")
            yield "data: [DONE]\n\n"
            return

        response = await client.chat.completions.create(
            model=model,
            messages=msg,  # 添加图片信息到消息
            stream=True,
            stream_options={"include_usage": True},
            extra_body = extra_params, # 其他参数
            **_apply_ctx_guardrail(extra, msg, settings)
        )

        tool_calls = []
        full_content = ""
        search_not_done = False
        search_task = ""
        is_tool_call = False
        _chunk_count = 0  # 流式让出计数器，防止事件循环饥饿
        async for _c in _stream_first_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, is_tool_call, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count):
            yield _c
        usage_info = _st["usage_info"]
        _ctx_peak = _st["_ctx_peak"]
        is_tool_call = _st["is_tool_call"]
        full_content = _st["full_content"]
        in_reasoning = _st["in_reasoning"]
        content_buffer = _st["content_buffer"]
        reasoning_buffer = _st["reasoning_buffer"]
        _chunk_count = _st["_chunk_count"]
        # 最终flush未完成内容
        if content_buffer or reasoning_buffer:
            final_chunk = {
                "choices": [{
                    "delta": {
                        "content": "".join(content_buffer),
                        "reasoning_content": "".join(reasoning_buffer)
                    }
                }]
            }
            yield f"data: {json.dumps(final_chunk)}\n\n"
            full_content += final_chunk["choices"][0]["delta"].get("content", "")
        if not tool_calls:
            # 将响应添加到消息列表
            content_append(request.messages, 'assistant', full_content)
        # 工具和深度搜索
        if tool_calls:
            print("tool_calls",tool_calls)
            pass
        elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            async for _c in _stream_drs_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
                yield _c
            DRS_STAGE = _st["drs"]
            search_not_done = _st["snot"]
            search_task = _st["stask"]

        reasoner_messages = copy.deepcopy(request.messages)
        _tool_loop_count = 0
        _max_tool_iterations = int(settings.get("max_tool_iterations", 100) or 100)
        force_no_tools = False
        while tool_calls or search_not_done:
            _tool_loop_count += 1
            if not _drs_round_cap(_tool_loop_count, _max_tool_iterations, search_not_done, tool_calls, "流式"):
                search_not_done, tool_calls = False, []
                break
            if tool_calls and _tool_loop_count > _max_tool_iterations:
                _append_loopcap_hint(request, "流式")
                tool_calls = []
                force_no_tools = True
            if tool_calls:
                async for _c in _stream_tool_round(_st, request, settings, user_prompt, full_content, tool_calls, reasoner_messages):
                    yield _c
                # RA-11：旧内联压缩段首「逐轮擦除 usage_info」随 helper 化失活，回植旧位（tool round 内顺序执行处）
                usage_info = None
                if _st.pop("w1_cancel", False):
                    return
                if _st.pop("w1_abort", False):
                    break
                results = _st.get("results")
            # 如果启用推理模型
            if settings['reasoner']['enabled'] or enable_thinking:
                async for _c in _stream_reasoner_update(_st, request, reasoner_client, settings, reasoner_messages, images, reasoner_extra, open_tag, close_tag, tools, vendor):
                    yield _c
                vendor = _st["vendor"]
                    
            vision_control_enabled = settings.get('visionControlSettings', {}).get('enabled', False)
            if vision_control_enabled and (results =='[Getting screenshot]' or settings.get('visionControlSettings', {}).get('desktopVision', False)):
                images = await _stream_regrab(request, settings, results, images, fastapi_base_url)
            msg = await images_add_in_messages(request.messages, images, settings)
            if request.top_p != 1 or settings['top_p'] != 1:
                extra['top_p'] = request.top_p or settings['top_p']

            if settings['temperature'] !=1:
                extra['temperature'] = settings['temperature']

            full_content = ""
            if tools and not force_no_tools:
                extra['tools'] = tools
            if _stream_cancelled():
                logging.getLogger("app").info("[Cancel] 流已被用户取消，工具后续轮次终止")
                yield "data: [DONE]\n\n"
                return
            response = await client.chat.completions.create(
                model=model,
                messages=msg,  # 添加图片信息到消息
                stream=True,
                stream_options={"include_usage": True},
                extra_body = extra_params, # 其他参数
                **_apply_ctx_guardrail(extra, msg, settings)
            )
            tool_calls = []
            _chunk_count2 = 0  # 流式让出计数器（工具调用循环内）
            async for _c in _stream_loop_pass(_st, response, open_tag, close_tag, tool_calls, usage_info, _ctx_peak, full_content, in_reasoning, content_buffer, reasoning_buffer, _chunk_count2):
                yield _c
            usage_info = _st["usage_info"]
            _ctx_peak = _st["_ctx_peak"]
            full_content = _st["full_content"]
            in_reasoning = _st["in_reasoning"]
            content_buffer = _st["content_buffer"]
            reasoning_buffer = _st["reasoning_buffer"]
            _chunk_count2 = _st["_chunk_count2"]
            # 最终flush未完成内容
            if content_buffer or reasoning_buffer:
                final_chunk = {
                    "choices": [{
                        "delta": {
                            "content": "".join(content_buffer),
                            "reasoning_content": "".join(reasoning_buffer)
                        }
                    }]
                }
                yield f"data: {json.dumps(final_chunk)}\n\n"
                full_content += final_chunk["choices"][0]["delta"].get("content", "")
            if not tool_calls and full_content:
                # 将响应添加到消息列表（S68：空生成不写历史，防 assistant 空串污染上下文）
                content_append(request.messages, 'assistant', full_content)
            # 工具和深度搜索
            if tool_calls:
                pass
            elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
                async for _c in _stream_drs_loop_round(client, model, extra_params, request, source_prompt, user_prompt, full_content, DRS_STAGE, search_not_done, search_task, _st):
                    yield _c
                DRS_STAGE = _st["drs"]
                search_not_done = _st["snot"]
                search_task = _st["stask"]
        async for _c in _stream_usage_event(request, settings, usage_info, _ctx_peak, tools):
            yield _c
        logger.info(f"all msg: {request.messages}")
        yield "data: [DONE]\n\n"
        await _stream_finalize_jobs(request, settings, full_content, user_prompt, m0, memoryId, cur_memory)

        return
    except Exception as e:
        logger.error(f"[StreamError] {type(e).__name__}: {e} | msgs={len(request.messages)}", exc_info=True)
        # 捕获异常并返回结构化错误信息
        error_chunk = {
            "choices": [{
                "delta": {
                    "tool_content": {
                        "title": "❎ Error", # 统一标题
                        "content": str(e),   # 错误详情
                        "type": "error"      # 标记类型，方便前端切换样式
                    }
                }
            }]
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"  # 确保最终结束
        return
    finally:
        llm_gate.leave()


async def generate_stream_response(client, reasoner_client, request: ChatRequest, settings: dict, 
                                   fastapi_base_url, enable_thinking, enable_deep_research, 
                                   enable_web_search, async_tools_id):
    try:
        # (global decl cleared: migrated to py/app_state.py)
        
        # 设置对话上下文，供 review_image 等工具使用
        current_request_messages.set(request.messages)
        
        DRS_STAGE = 1
        if len(request.messages) > 2:
            DRS_STAGE = 2
            
        vision_cfg = settings.get('vision', {})
        vision_control_enabled = settings.get('visionControlSettings', {}).get('enabled', False)
        user_prompt = request.messages[-1].get('content') or ""
        
        # 1. 只要开启了计算机控制 或者 符合桌面视觉唤醒词条件，就进行初始截图
        await _stream_desktop_capture(request, settings, vision_cfg, vision_control_enabled, user_prompt, fastapi_base_url)

        # =========================================================================
        # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
        # =========================================================================
        _stream_context_compress(request, settings)
        # =========================================================================
        images = await images_in_messages(request.messages,fastapi_base_url)
        request.messages = await message_without_images(request.messages)
        from py.load_files import get_files_content,file_tool,image_tool,analyze_image_tool,review_image_tool,analyze_images_tool
        from py.web_search import (
            DDGsearch, 
            searxng, 
            Tavily_search,
            Bing_search,
            Google_search,
            Brave_search,
            Exa_search,
            Serper_search,
            bochaai_search,
            youcom_search,
            duckduckgo_tool, 
            searxng_tool, 
            tavily_tool, 
            bing_tool,
            google_tool,
            brave_tool,
            exa_tool,
            serper_tool,
            bochaai_tool,
            youcom_tool,
            jina_crawler_tool, 
            simple_fetch_tool,
            Crawl4Ai_tool,
            firecrawl_tool,
            markdown_new_tool,
        )
        from py.know_base import kb_tool,query_knowledge_base,rerank_knowledge_base
        from py.agent_tool import get_agent_tool
        from py.a2a_tool import get_a2a_tool
        from py.llm_tool import get_llm_tool
        from py.pollinations import pollinations_image_tool,openai_image_tool,openai_chat_image_tool
        from py.code_interpreter import e2b_code_tool,local_run_code_tool
        from py.utility_tools import (
            time_tool, 
            weather_tool,
            location_tool,
            timer_weather_tool,
            wikipedia_summary_tool,
            wikipedia_section_tool,
            arxiv_tool 
        ) 
        from py.autoBehavior import auto_behavior_tool
        from py.cli_tool import get_tools_for_mode,get_local_tools_for_mode,get_tools_for_permission,get_local_tools_for_permission
        from py.cdp_tool import all_cdp_tools
        from py.random_topic import random_topics_tools
        from py.computer_use_tool import computer_use_tools,mouse_use_tools,keyboard_use_tools,desktopVision_use_tools

        from py.task_tools import (
            create_subtask_tool,
            query_tasks_tool,
            cancel_subtask_tool,
            finish_task_tool,
        )

        from py.mode_change import mode_change_tool
        from py.acpx_tools import acp_agent_tool

        m0 = None
        memoryId = None
        cur_memory = None
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != ""  and not request.is_sub_agent:
            memoryId = settings["memorySettings"]["selectedMemory"]
            cur_memory = None
            for memory in settings["memories"]:
                if memory["id"] == memoryId:
                    cur_memory = memory
                    break
            if cur_memory and cur_memory["providerId"]:
                logging.getLogger("app").info("长期记忆启用")
                m0 = llm_gate.get_mem0_instance(memoryId, cur_memory, settings)
                logging.getLogger("app").info("长期记忆配置加载完成")
        open_tag = "<think>"
        close_tag = "</think>"

        tools = await build_llm_tools(request, settings, _assemble_toolkit())
        
        source_prompt = ""
        if request.fileLinks:
            print("fileLinks",request.fileLinks)
            # 异步获取文件内容
            files_content = await get_files_content(request.fileLinks)
            fileLinks_message = f"\n\n相关文件内容：{files_content}"
            
            # 修复字符串拼接错误
            content_append(request.messages, 'system', fileLinks_message)
            source_prompt += fileLinks_message
        user_prompt = request.messages[-1].get('content') or ""
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != ""  and not request.is_sub_agent:
            await _stream_character_context(request, settings, user_prompt, cur_memory, memoryId, m0)
        # ========== 日记集成：将近期日记注入对话上下文 ==========
        diary_cfg = (settings.get("diarySettings", {}) or {}).get("chatIntegration", {}) or {}
        if diary_cfg.get("enabled", False) and not request.is_sub_agent:
            try:
                ms = (settings or {}).get("memorySettings", {}) or {}
                diary_book_id = DIARY_DEFAULT_BOOK
                if ms.get("is_memory") and ms.get("selectedMemory"):
                    diary_book_id = ms.get("selectedMemory")
                max_entries = max(1, int(diary_cfg.get("maxEntries", 5) or 5))
                recent = await get_recent_diary_entries(diary_book_id, max_entries)
                if recent:
                    diary_lines = []
                    for e in recent:
                        diary_title = e.get("title", "") or e.get("content", "")[:24]
                        diary_lines.append(f"- [{e.get('time', '')[:16]}] ({e.get('type', '')}) {diary_title}: {e.get('content', '')[:200]}")
                    diary_text = "\n".join(diary_lines)
                    content_append(request.messages, 'system',
                        "\n\n[角色日记 - 近期回忆]\n以下是该角色最近的日记记录，可供你参考其心境和经历：\n" + diary_text + "\n")
                    logging.getLogger("app").info(f"📔 [日记集成] 已注入 {len(recent)} 条日记到对话上下文")
            except Exception as e:
                logging.getLogger("app").info(f"[日记集成] 提取日记失败: {e}")
        request = await tools_change_messages(request, settings)
        # ========== 对话缓冲：记录用户消息用于闲时自动总结 ==========
        try:
            diary_settings = (settings.get("diarySettings", {}) or {})
            if diary_settings.get("enabled", False) and diary_settings.get("chatSummary", {}).get("enabled", True):
                ms = (settings or {}).get("memorySettings", {}) or {}
                buffer_key = ms.get("selectedMemory") or DIARY_DEFAULT_BOOK
                update_buffer_identity(buffer_key, book_id=buffer_key,
                                       character_name=(ms.get("userName") or ""))
                last_msg = request.messages[-1] if request.messages else None
                if last_msg and last_msg.get("role") == "user":
                    append_to_chat_buffer(buffer_key, "user", _extract_text_content(last_msg.get("content", "")))
        except Exception as e:
            logging.getLogger("app").info(f"[DiaryBuffer] 记录对话缓冲失败: {e}")
        # 如果系统消息为空字符串或者仅包含空白符，则将系统消息改成"you are a helpful assistant."
        if request.messages[0]['role'] == 'system' and not request.messages[0]['content'].strip():
            request.messages[0]['content'] = "you are a helpful assistant."
        append_resume_nudge(request.messages)
        chat_vendor = 'OpenAI'
        reasoner_vendor = 'OpenAI'
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['selectedProvider']:
                chat_vendor = modelProvider['vendor']
                break
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['reasoner']['selectedProvider']:
                reasoner_vendor = modelProvider['vendor']
                break
        if chat_vendor == 'Dify':
            try:
                if len(request.messages) >= 3:
                    if request.messages[2]['role'] == 'user':
                        if request.messages[1]['role'] == 'assistant':
                            request.messages[2]['content'] = "你上一次的发言：\n" +request.messages[0]['content'] + "\n你上一次的发言结束\n\n用户：" + request.messages[2]['content']
                        if request.messages[0]['role'] == 'system':
                            request.messages[2]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n" + request.messages[2]['content']
                elif len(request.messages) >= 2:
                    if request.messages[1]['role'] == 'user':
                        if request.messages[0]['role'] == 'system':
                            request.messages[1]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n用户：" + request.messages[1]['content']
            except Exception as e:
                print("Dify error:",e)
        model = settings['model']
        extra_params = settings['extra_params']
        # 移除extra_params这个list中"name"不包含非空白符的键值对
        if extra_params:
            for extra_param in extra_params:
                if not extra_param['name'].strip():
                    extra_params.remove(extra_param)
            # 列表转换为字典
            extra_params = process_extra_params(extra_params)
        else:
            extra_params = {}
        
        # 检查是否启用断点续传
        enable_stream_resume = settings.get('enableStreamResume', True)
        
        if enable_stream_resume:
            # 生产者/消费者解耦模式：客户端断开后生成器继续运行
            stream_id = str(uuid.uuid4())
            _active_streams[stream_id] = {
                "buffer": [],
                "done": False,
                "error": None,
                "cancelled": False,
                "created_at": time.time(),
                "consumer_count": 1,
                "task": None,
            }
            # 启动生产者后台任务
            # 关键：必须将 task 引用保存到字典中，否则会被 Python GC 回收，
            # 导致 stream_generator 中的 httpx 流式请求中途被中断！
            _active_streams[stream_id]["task"] = asyncio.create_task(
                _stream_producer_wrapper(
                    stream_id,
                    stream_generator(
                        client, reasoner_client, request, settings, fastapi_base_url,
                        enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                        user_prompt, DRS_STAGE, tools, images,
                        chat_vendor, reasoner_vendor, model, extra_params,
                        open_tag, close_tag, source_prompt, m0, memoryId, cur_memory)
                )
            )

            
            async def _first_frame_consumer():
                """消费者：先发 stream_id 元数据帧，再转发实际内容"""
                meta_chunk = {"choices": [{"delta": {"stream_id": stream_id}}]}
                yield f"data: {json.dumps(meta_chunk)}\n\n"
                async for chunk in _stream_consumer_generator(stream_id, 0):
                    yield chunk
            
            return StreamingResponse(
                _first_frame_consumer(),
                media_type="text/event-stream",
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Stream-Id": stream_id,
                }
            )
        else:
            return StreamingResponse(
                stream_generator(
                    client, reasoner_client, request, settings, fastapi_base_url,
                enable_thinking, enable_deep_research, enable_web_search, async_tools_id,
                user_prompt, DRS_STAGE, tools, images,
                chat_vendor, reasoner_vendor, model, extra_params,
                open_tag, close_tag, source_prompt, m0, memoryId, cur_memory),
                media_type="text/event-stream",
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                }
            )
    except Exception as e:
        logger.error(f"Error occurred: {e}")

        # 如果e.status_code存在，则使用它作为HTTP状态码，否则使用500
        return JSONResponse(
            status_code=getattr(e, "status_code", 500),
            content={"error": str(e)},
        )

async def generate_complete_response(*args, **kwargs):
    """T-8/T-5: complete 路径统一闸门+取消围栏入口层（与 stream 共用
    _active_streams/cancel 端点/llm_gate 基建）。实现体在 _generate_complete_impl。"""
    complete_stream_id = str(uuid.uuid4())
    entry = {
        "buffer": [], "done": False, "error": None, "cancelled": False,
        "created_at": time.time(), "consumer_count": 0, "task": None,
        "kind": "complete",
    }
    async with _active_streams_lock:
        _active_streams[complete_stream_id] = entry
    _current_stream_entry.set(entry)
    llm_gate.enter()
    try:
        return await _generate_complete_impl(*args, **kwargs)
    finally:
        llm_gate.leave()
        async with _active_streams_lock:
            entry["done"] = True
            if entry.get("consumer_count", 0) <= 0:
                _active_streams.pop(complete_stream_id, None)
            else:
                asyncio.create_task(_cleanup_stream(complete_stream_id, delay=5.0))



def _apply_context_compression(request, DRS_STAGE):
    """L1 context window compression (complete channel). (M-3 split)"""
    if len(request.messages) > 2:
        DRS_STAGE = 2

        # =========================================================================
        # 第一阶段：上下文压缩 (仅在达到阈值时触发，决定“保留哪些消息”)
        # =========================================================================
        max_rounds = 0 if _cm_context_enabled(settings) else settings.get("max_rounds", 0)
        chat_messages = request.messages # 这里的 chat_messages 包含 system
        
        if max_rounds > 0:
            
            # 区分系统消息和对话消息
            sys_msgs = [m for m in chat_messages if get_role(m) == "system"]
            dialog_msgs = [m for m in chat_messages if get_role(m) != "system"]
            
            # 设定压缩阈值：当非系统消息超过 max_rounds * 2 + 1 时开始压缩
            if len(dialog_msgs) > (max_rounds * 2 + 1):
                keep_indices = set()
                
                # 1. 总是保留第一条消息 (Anchor User Prompt)
                if len(dialog_msgs) > 0: keep_indices.add(0)
                
                # 2. 保留所有 User 消息 (User 优先策略)
                for i, m in enumerate(dialog_msgs):
                    if get_role(m) == "user": keep_indices.add(i)
                
                # 3. 保留每个 Turn 的最后一个 Assistant 消息 (最终答案)
                for i in range(len(dialog_msgs)):
                    if get_role(dialog_msgs[i]) == "assistant":
                        is_last = True
                        for j in range(i + 1, len(dialog_msgs)):
                            if get_role(dialog_msgs[j]) == "assistant":
                                is_last = False; break
                            if get_role(dialog_msgs[j]) == "user": break
                        if is_last: keep_indices.add(i)
                
                # 4. 保留最近的活跃窗口 (最近 N 条消息，确保当前工具链不被切断)
                tail_start = max(0, len(dialog_msgs) - (max_rounds * 2))
                for i in range(tail_start, len(dialog_msgs)):
                    keep_indices.add(i)
                
                # 构造初步压缩后的列表
                compressed_dialog = [dialog_msgs[i] for i in sorted(list(keep_indices))]
                chat_messages = sys_msgs + compressed_dialog
                logging.getLogger("app").info(f"[Context] Compressed to {len(chat_messages)} msgs.")

        request.messages = sanitize_tool_chains(chat_messages)
        request.messages = ensure_thinking_fields(request.messages)
    return DRS_STAGE


def _diary_recall_sample(payload, memory_limit):
    """S83：日记（自主触发，query 变化有限）长期记忆召回抽样。

    m0.search 为确定性语义 top-k，固定/近固定提示词永远召回同一批条目；
    这里从扩大召回的候选集中随机抽 memory_limit 条制造多样性。
    仅日记平台调用；候选不足或结构异常时原样返回。
    """
    try:
        results = payload.get("results")
        if not isinstance(results, list) or memory_limit <= 0 or len(results) <= memory_limit:
            return payload
        return {**payload, "results": random.sample(results, memory_limit)}
    except Exception:
        return payload


def _version_fingerprint():
    """S84：运行树+代码版本指纹。多份同名 fork 拷贝共存时用于日志判别。"""
    import subprocess
    root = os.path.dirname(os.path.abspath(__file__))
    head = "-"
    try:
        head = subprocess.run(
            ["git", "-C", root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            creationflags=(0x08000000 if os.name == "nt" else 0),  # CREATE_NO_WINDOW
        ).stdout.strip() or "-"
    except Exception:
        pass
    try:
        mtime = time.strftime("%Y-%m-%d %H:%M", time.localtime(
            os.path.getmtime(os.path.join(root, "server.py"))))
    except Exception:
        mtime = "?"
    dirty = ""
    try:
        out = subprocess.run(
            ["git", "-C", root, "status", "--porcelain", "--", "server.py", "py/"],
            capture_output=True, text=True, timeout=5,
            creationflags=(0x08000000 if os.name == "nt" else 0),
        ).stdout.strip()
        dirty = " dirty" if out else ""
    except Exception:
        pass
    return f"tree={root} HEAD={head}{dirty} server.py-mtime={mtime}"


async def _complete_character_context(request, settings, user_prompt, cur_memory, memoryId, m0):
    """Character-book lore + persona fields + mem0 relevant-memory recall."""
    if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
        if settings["memorySettings"]["userName"] and settings["memorySettings"]["userName"] != "user":
            logging.getLogger("app").info("添加用户名：\n\n" + settings["memorySettings"]["userName"] + "\n\n用户名结束\n\n")
            content_append(request.messages, 'system', "当前与你交流的人的名字为：\n\n" + settings["memorySettings"]["userName"] + "\n\n")
        lore_content = ""
        assistant_reply = ""
        # 找出request.messages中上次的assistant回复
        for i in range(len(request.messages)-1, -1, -1):
            if request.messages[i]['role'] == 'assistant':
                assistant_reply = request.messages[i]['content']
                break
        if cur_memory["characterBook"]:
            for lore in cur_memory["characterBook"]:
                # lore['keysRaw'] 按照换行符分割，并去除空字符串
                lore_keys = lore["keysRaw"].split("\n")
                lore_keys = [key for key in lore_keys if key != ""]
                logging.getLogger("app").info(lore_keys)
                # 如果lore_keys不为空，并且lore_keys的任意一个元素在user_prompt或者assistant_reply中，则添加lore['content']到lore_content中
                if lore_keys != [] and any(key in user_prompt or key in assistant_reply for key in lore_keys):
                    lore_content += lore['content'] + "\n\n"
        if lore_content:
            if settings["memorySettings"]["userName"]:
                # 替换lore_content中的{{user}}为settings["memorySettings"]["userName"]
                lore_content = lore_content.replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换lore_content中的{{char}}为cur_memory["name"]
            lore_content = lore_content.replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
            content_append(request.messages, 'system', "世界观设定：\n\n" + lore_content + "\n\n世界观设定结束\n\n")
        if cur_memory["description"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["description"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["description"] = cur_memory["description"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["description"]中的{{char}}为cur_memory["name"]
            cur_memory["description"] = cur_memory["description"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
            content_append(request.messages, 'system', "角色设定：\n\n" + cur_memory["description"] + "\n\n角色设定结束\n\n")
        if cur_memory["personality"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["personality"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["personality"] = cur_memory["personality"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["personality"]中的{{char}}为cur_memory["name"]
            cur_memory["personality"] = cur_memory["personality"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n")
            content_append(request.messages, 'system', "性格设定：\n\n" + cur_memory["personality"] + "\n\n性格设定结束\n\n") 
        if cur_memory['mesExample']:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["mesExample"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["mesExample"]中的{{char}}为cur_memory["name"]
            cur_memory["mesExample"] = cur_memory["mesExample"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
            content_append(request.messages, 'system', "对话示例：\n\n" + cur_memory['mesExample'] + "\n\n对话示例结束\n\n")
        if cur_memory["systemPrompt"]:
            if settings["memorySettings"]["userName"]:
                # 替换cur_memory["systemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
                cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
            cur_memory["systemPrompt"] = cur_memory["systemPrompt"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加系统提示：\n\n" + cur_memory["systemPrompt"] + "\n\n系统提示结束\n\n")
            content_append(request.messages, 'system', "系统提示：\n\n" + cur_memory["systemPrompt"] + "\n\n系统提示结束\n\n")
        if settings["memorySettings"]["genericSystemPrompt"]:
            if settings["memorySettings"]["userName"]:
                # 替换settings["memorySettings"]["genericSystemPrompt"]中的{{user}}为settings["memorySettings"]["userName"]
                settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{user}}", settings["memorySettings"]["userName"])
            # 替换cur_memory["systemPrompt"]中的{{char}}为cur_memory["name"]
            settings["memorySettings"]["genericSystemPrompt"] = settings["memorySettings"]["genericSystemPrompt"].replace("{{char}}", cur_memory["name"])
            logging.getLogger("app").info("添加系统提示：\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n系统提示结束\n\n")
            content_append(request.messages, 'system', "系统提示：\n\n" + settings["memorySettings"]["genericSystemPrompt"] + "\n\n系统提示结束\n\n")
                    
        if m0:
            memoryLimit = settings["memorySettings"]["memoryLimit"]
            # S83：日记平台扩大召回×3（下限 6）后随机抽样，主对话行为不变
            is_diary = getattr(request, "platform", "") == "diary"
            search_limit = max(memoryLimit * 3, 6) if is_diary else memoryLimit
            try:
                # 【核心修改】：使用 asyncio.to_thread 将同步的 search 方法放入线程池运行
                # 这样主线程（Event Loop）会被释放，可以去处理 /minilm/embeddings 请求，从而避免死锁
                relevant_memories = await asyncio.to_thread(
                    m0.search, 
                    query=user_prompt, 
                    user_id=memoryId, 
                    limit=search_limit
                )
                if is_diary:
                    relevant_memories = _diary_recall_sample(relevant_memories, memoryLimit)
                relevant_memories = json.dumps(relevant_memories, ensure_ascii=False)
            except Exception as e:
                print("m0.search error:",e)
                relevant_memories = ""
            logging.getLogger("app").info("添加相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n")
            content_append(request.messages, 'system', "之前的相关记忆：\n\n" + relevant_memories + "\n\n相关结束\n\n") 


async def _complete_web_search_setup(request, settings, user_prompt, tools, enable_web_search):
    """before_thinking search execution + after_thinking tool announcements."""
    from py.web_search import (
        DDGsearch, searxng, Tavily_search, Bing_search, Google_search,
        Brave_search, Exa_search, Serper_search, bochaai_search, youcom_search,
        duckduckgo_tool, searxng_tool, tavily_tool, bing_tool, google_tool,
        brave_tool, exa_tool, serper_tool, bochaai_tool, youcom_tool, jina_crawler_tool,
        simple_fetch_tool, Crawl4Ai_tool, firecrawl_tool, markdown_new_tool,
        websearch_with_fallback, browser_search_tool,
    )
    if settings['webSearch']['enabled'] or enable_web_search:
        if settings['webSearch']['when'] == 'before_thinking' or settings['webSearch']['when'] == 'both':
            # S90：统一入口——配置引擎失败自动走内置浏览器兜底
            results = await websearch_with_fallback(
                settings['webSearch']['engine'], user_prompt)
            if results:
                content_append(request.messages, 'user',  f"\n\n联网搜索结果：{results}")
        if settings['webSearch']['when'] == 'after_thinking' or settings['webSearch']['when'] == 'both':
            if settings['webSearch']['engine'] == 'duckduckgo':
                tools.append(duckduckgo_tool)
            elif settings['webSearch']['engine'] == 'searxng':
                tools.append(searxng_tool)
            elif settings['webSearch']['engine'] == 'tavily':
                tools.append(tavily_tool)
            elif settings['webSearch']['engine'] == 'bing':
                tools.append(bing_tool)
            elif settings['webSearch']['engine'] == 'google':
                tools.append(google_tool)
            elif settings['webSearch']['engine'] == 'brave':
                tools.append(brave_tool)
            elif settings['webSearch']['engine'] == 'exa':
                tools.append(exa_tool)
            elif settings['webSearch']['engine'] == 'serper':
                tools.append(serper_tool)
            elif settings['webSearch']['engine'] == 'bochaai':
                tools.append(bochaai_tool)
            elif settings['webSearch']['engine'] == 'youcom':
                tools.append(youcom_tool)
            elif settings['webSearch']['engine'] == 'browser':
                tools.append(browser_search_tool)

            if settings['webSearch']['crawler'] == 'jina':
                tools.append(jina_crawler_tool)
            elif settings['webSearch']['crawler'] == 'crawl4ai':
                tools.append(Crawl4Ai_tool)
            elif settings['webSearch']['crawler'] == 'firecrawl':
                tools.append(firecrawl_tool)
            elif settings['webSearch']['crawler'] == 'simpleRequest':
                tools.append(simple_fetch_tool)
            elif settings['webSearch']['crawler'] == 'mdnew':
                tools.append(markdown_new_tool)


async def _complete_reasoner_prep(request, reasoner_client, settings, chat_vendor, reasoner_vendor, images, tools, extra, reasoner_extra, open_tag, close_tag, enable_deep_research, enable_thinking, DRS_STAGE, user_prompt):
    """First reasoner pass: build reasoner_messages, fetch reasoning, prepend."""
    reasoner_messages = copy.deepcopy(request.messages)
    if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
        drs_msg = get_drs_stage(DRS_STAGE)
        if drs_msg:
            content_append(reasoner_messages, 'user',  f"\n\n{drs_msg}\n\n")
        content_append(reasoner_messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)   
    if chat_vendor == 'OpenAI':
        extra['max_completion_tokens'] = request.max_tokens or settings['max_tokens']
    else:
        extra['max_tokens'] = request.max_tokens or settings['max_tokens']
    if reasoner_vendor == 'OpenAI':
        reasoner_extra['max_completion_tokens'] = settings['reasoner']['max_tokens']
    else:
        reasoner_extra['max_tokens'] = settings['reasoner']['max_tokens']
    if request.reasoning_effort or settings['reasoning_effort']:
        extra['reasoning_effort'] = request.reasoning_effort or settings['reasoning_effort']
    if settings['reasoner']['reasoning_effort'] is not None:
        reasoner_extra['reasoning_effort'] = settings['reasoner']['reasoning_effort'] 
    if vendor == 'Ollama':
        reasoner_response = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            temperature=settings['reasoner']['temperature'],
            **reasoner_extra
        )
        reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']
        if reasoning_buffer:
            content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
        else:
            reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning']
            if reasoning_buffer:
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
            else:
                # 将推理结果中的思考内容提取出来
                reasoning_content = reasoner_response.model_dump()['choices'][0]['message']['content']
                # open_tag和close_tag之间的内容
                start_index = reasoning_content.find(open_tag) + len(open_tag)
                end_index = reasoning_content.find(close_tag)
                if start_index != -1 and end_index != -1:
                    reasoning_content = reasoning_content[start_index:end_index]
                else:
                    reasoning_content = ""
                content_prepend(request.messages, 'assistant', reasoning_content) # 可参考的推理过程
    else:
        reasoner_response = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            stop=settings['reasoner']['stop_words'],
            temperature=settings['reasoner']['temperature'],
            **reasoner_extra
        )
        reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']
        if reasoning_buffer:
            content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
        else:
            reasoning_buffer = reasoner_response.model_dump()['choices'][0]['message']['reasoning']
            if reasoning_buffer:
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
            else:
                reasoning_buffer = ""
                content_prepend(request.messages, 'assistant', reasoning_buffer) # 可参考的推理过程
    return vendor


async def _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty):
    """Deep-research stage machine shared by the pre-loop and in-loop copies.
    none_to_empty=True preserves the pre-loop copy's None guard; the in-loop
    copy never had one (raw behaviour kept)."""
    search_prompt = get_drs_stage_system_message(DRS_STAGE,user_prompt,response.choices[0].message.content)
    research_response = await client.chat.completions.create(
        model=model,
        messages=[
            {
            "role": "user",
            "content": search_prompt,
            }
        ],
        temperature=0.5,
        extra_body = extra_params, # 其他参数
    )
    response_content = research_response.choices[0].message.content
    if none_to_empty and response_content is None:
        response_content = ""

    # 用re 提取```json 包裹json字符串 ```
    if "```json" in response_content:
        try:
            response_content = re.search(r'```json(.*?)```', response_content, re.DOTALL).group(1)
        except:
            # 用re 提取```json 之后的内容
            response_content = re.search(r'```json(.*?)', response_content, re.DOTALL).group(1)
    response_content = json.loads(response_content)
    if response_content["status"] == "done":
        search_not_done = False
    elif response_content["status"] == "not_done":
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续完成初始任务中未完成的任务：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n最后，请给出完整的初始任务的最终结果。"
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "need_more_info":
        DRS_STAGE = 2
        search_not_done = False
    elif response_content["status"] == "need_work":
        DRS_STAGE = 2
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )
    elif response_content["status"] == "need_more_work":
        DRS_STAGE = 2
        search_not_done = True
        search_task = response_content["unfinished_task"]
        task_prompt = f"请继续查询如下信息：\n\n{search_task}\n\n初始任务：{user_prompt}\n\n"
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": task_prompt,
            }
        )
    elif response_content["status"] == "answer":
        DRS_STAGE = 3
        search_not_done = True
        drs_msg = get_drs_stage(DRS_STAGE)
        request.messages.append(
            {
                "role": "assistant",
                "content": research_response.choices[0].message.content,
                "reasoning_content": "",
            }
        )
        request.messages.append(
            {
                "role": "user",
                "content": drs_msg,
            }
        )
    return DRS_STAGE, search_not_done, search_task


async def _ns_tool_round(request, reasoner_messages, settings, user_prompt, response):
    """Non-stream tool_calls round: dispatch, ack, approval abort. Returns abort."""
    from py.know_base import rerank_knowledge_base
    assistant_message = response.choices[0].message
    ns_tool_calls_meta = []
    for _tc in assistant_message.tool_calls:
        ns_tool_calls_meta.append({
            "id": _tc.id or f"call_{uuid.uuid4().hex[:12]}",
            "function": {
                "arguments": _tc.function.arguments or "",
                "name": _tc.function.name,
            },
            "type": getattr(_tc, "type", None) or "function",
        })
    request.messages.append({
        "role": "assistant",
        "content": assistant_message.content or "",
        "tool_calls": ns_tool_calls_meta,
        "reasoning_content": "",
    })
    ns_pending_abort = False
    ns_acked_ids = set()
    for _ti, _tc in enumerate(assistant_message.tool_calls):
        # T-8: 取消围栏——取消后不再调度任何工具
        _cur_entry = _current_stream_entry.get()
        if _cur_entry and _cur_entry.get("cancelled"):
            ns_pending_abort = True
            break
        tool_call_id = ns_tool_calls_meta[_ti]["id"]
        response_content = _tc.function
        logging.getLogger("app").info(response_content.name)
        args_dict, arg_err = parse_tool_arguments(_tc.function.arguments)
        if arg_err is not None:
            err_text = arg_error_text(arg_err)
            ns_acked_ids.add(tool_call_id)
            reasoner_messages.append({
                "role": "assistant",
                "content": f"{response_content.name}({_tc.function.arguments})",
                "reasoning_content": "",
            })
            reasoner_messages.append({
                "role": "user",
                "content": f"{response_content.name}工具结果：" + truncate_tool_result(err_text, 8000),
            })
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": err_text,
            })
            continue
        try:
            results = await dispatch_tool(response_content.name, args_dict, settings)
        except Exception as e:
            results = TOOL_EXC_TMPL.format(type=type(e).__name__, exc=e)
        if isinstance(results, AsyncIterator):
            buffer = []
            async for chunk in results:
                buffer.append(chunk)
            results = "".join(buffer)
        if results is None:
            ns_acked_ids.add(tool_call_id)
            request.messages.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": response_content.name,
                "content": NONE_TEXT,
            })
            ns_pending_abort = True
            break
        if response_content.name in ["query_knowledge_base"] and isinstance(results, list):
            if settings["KBSettings"]["is_rerank"]:
                results = await rerank_knowledge_base(user_prompt, results)
            results = json.dumps(results, ensure_ascii=False, indent=4)
        tool_result_text = str(results)
        ns_acked_ids.add(tool_call_id)
        request.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": response_content.name,
            "content": truncate_tool_result(tool_result_text),
        })
        reasoner_messages.append({
            "role": "assistant",
            "content": f"{response_content.name}({json.dumps(args_dict, ensure_ascii=False)})",
            "reasoning_content": "",
        })
        reasoner_messages.append({
            "role": "user",
            "content": f"{response_content.name}工具结果：" + truncate_tool_result(tool_result_text, 8000),
        })
        # T-9: 结构化哨兵判定（与 stream 路径同源）
        if _is_approval_result(results) is not None:
            ns_pending_abort = True
            break
    # 为未执行的调用补上说明性 tool 结果，保证成对闭合
    append_missing_results(request.messages, ns_tool_calls_meta, ns_acked_ids)
    if ns_pending_abort:
        return True
    return False


async def _ns_reasoner_pass(request, reasoner_client, reasoner_messages, settings, images, reasoner_extra, open_tag, close_tag, tools, vendor):
    """In-loop reasoner refresh: re-run reasoner, prepend its reasoning."""
    if tools:
        content_append(reasoner_messages, 'system',  f"可用工具：{json.dumps(tools)}")
    for modelProvider in settings['modelProviders']: 
        if modelProvider['id'] == settings['reasoner']['selectedProvider']:
            vendor = modelProvider['vendor']
            break
    msg = await images_add_in_messages(reasoner_messages, images,settings)
    if vendor == 'Ollama':
        reasoner_response = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            temperature=settings['reasoner']['temperature'],
            **reasoner_extra
        )
        # 将推理结果中的思考内容提取出来
        reasoning_content = reasoner_response.model_dump()['choices'][0]['message']['content']
        # open_tag和close_tag之间的内容
        start_index = reasoning_content.find(open_tag) + len(open_tag)
        end_index = reasoning_content.find(close_tag)
        if start_index != -1 and end_index != -1:
            reasoning_content = reasoning_content[start_index:end_index]
        else:
            reasoning_content = ""
        content_prepend(request.messages, 'assistant', reasoning_content) # 可参考的推理过程
    else:
        reasoner_response = await reasoner_client.chat.completions.create(
            model=settings['reasoner']['model'],
            messages=msg,
            stream=False,
            stop=settings['reasoner']['stop_words'],
            temperature=settings['reasoner']['temperature'],
            **reasoner_extra
        )
        content_prepend(request.messages, 'assistant', reasoner_response.model_dump()['choices'][0]['message']['reasoning_content']) # 可参考的推理过程
    return vendor


async def _complete_finalize(request, settings, response, m0, memoryId, cur_memory, user_prompt, open_tag, close_tag):
    """response_dict normalization + mem0 write job + turn-log shadow append."""
    response_dict = response.model_dump()
    content = response_dict["choices"][0]['message']['content']
    if response_dict["choices"][0]['message'].get('reasoning_content',""):
        pass
    else:
        response_dict["choices"][0]['message']['reasoning_content'] = response_dict["choices"][0]['message'].get('reasoning',"")
    if open_tag in content and close_tag in content:
        reasoning_content = re.search(fr'{open_tag}(.*?)\{close_tag}', content, re.DOTALL)
        if reasoning_content:
            # 存储到 reasoning_content 字段
            response_dict["choices"][0]['message']['reasoning_content'] = reasoning_content.group(1).strip()
            # 移除原内容中的标签部分
            response_dict["choices"][0]['message']['content'] = re.sub(fr'{open_tag}(.*?)\{close_tag}', '', content, flags=re.DOTALL).strip()
    if m0:
        messages=f"用户说：{user_prompt}\n\n---\n\n你说：{response_dict["choices"][0]['message']['content']}"
        infer = cur_memory.get('infer') or False
        _m0_job = m0
        _mid = memoryId
        _job_msgs = messages

        def _mem_job():
            metadata = {
                "timetamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            _m0_job.add(_job_msgs, user_id=_mid, metadata=metadata, infer=infer)
            logging.getLogger("app").info("知识库更新完成")

        llm_gate.submit_memory_job(
            _mid, _mem_job, name="mem0-add-complete",
            debounce=float((settings.get('llmGuardSettings') or {}).get('debounceSeconds', 20) or 0)
                     if (settings.get('llmGuardSettings') or {}).get('enabled', True) else 0.0,
            wait_idle=(settings.get('llmGuardSettings') or {}).get('enabled', True))
    try:
        from py.turn_log import shadow_append as _shadow_append
        await _shadow_append(request.conversation_id, request.messages, log=print)
    except Exception as _tle:
        logging.getLogger("app").info(f"[TurnLog] complete shadow skip: {_tle}")
    return response_dict
async def _generate_complete_impl(client,reasoner_client, request: ChatRequest, settings: dict,fastapi_base_url,enable_thinking,enable_deep_research,enable_web_search):
    # (global decl cleared: migrated to py/app_state.py)
    
    # 设置对话上下文，供 review_image 等工具使用
    current_request_messages.set(request.messages)
    
    DRS_STAGE = 1 # 1: 明确用户需求阶段 2: 工具调用阶段 3: 生成结果阶段
    DRS_STAGE = _apply_context_compression(request, DRS_STAGE)
        # =========================================================================

    from py.load_files import get_files_content,file_tool,image_tool,analyze_image_tool,review_image_tool,analyze_images_tool
    from py.web_search import (
        DDGsearch, 
        searxng, 
        Tavily_search,
        Bing_search,
        Google_search,
        Brave_search,
        Exa_search,
        Serper_search,
        bochaai_search,
        youcom_search,
        duckduckgo_tool, 
        searxng_tool, 
        tavily_tool, 
        bing_tool,
        google_tool,
        brave_tool,
        exa_tool,
        serper_tool,
        bochaai_tool,
        youcom_tool,
        jina_crawler_tool, 
        simple_fetch_tool,
        Crawl4Ai_tool,
        firecrawl_tool,
        markdown_new_tool,
    )
    from py.know_base import kb_tool,query_knowledge_base,rerank_knowledge_base
    from py.agent_tool import get_agent_tool
    from py.a2a_tool import get_a2a_tool
    from py.llm_tool import get_llm_tool
    from py.pollinations import pollinations_image_tool,openai_image_tool,openai_chat_image_tool
    from py.code_interpreter import e2b_code_tool,local_run_code_tool
    from py.utility_tools import time_tool
    from py.utility_tools import (
        time_tool, 
        weather_tool,
        location_tool,
        timer_weather_tool,
        wikipedia_summary_tool,
        wikipedia_section_tool,
        arxiv_tool
    ) 
    from py.autoBehavior import auto_behavior_tool
    from py.cli_tool import get_tools_for_mode,get_local_tools_for_mode,get_tools_for_permission,get_local_tools_for_permission
    from py.cdp_tool import all_cdp_tools
    from py.random_topic import random_topics_tools
    from py.computer_use_tool import computer_use_tools,mouse_use_tools,keyboard_use_tools,desktopVision_use_tools
    
    from py.mode_change import mode_change_tool
    from py.acpx_tools import acp_agent_tool
    m0 = None
    memoryId = None
    cur_memory = None
    if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
        memoryId = settings["memorySettings"]["selectedMemory"]
        cur_memory = None
        for memory in settings["memories"]:
            if memory["id"] == memoryId:
                cur_memory = memory
                break
        if cur_memory and cur_memory["providerId"]:
            logging.getLogger("app").info("长期记忆启用")
            m0 = llm_gate.get_mem0_instance(memoryId, cur_memory, settings)
    images = await images_in_messages(request.messages,fastapi_base_url)
    request.messages = await message_without_images(request.messages)
    open_tag = "<think>"
    close_tag = "</think>"
    tools = await build_llm_tools(request, settings, _assemble_toolkit())
    extra = {}
    reasoner_extra = {}
    search_not_done = False
    search_task = ""
    try:
        model = settings['model']
        extra_params = settings['extra_params']
        # 移除extra_params这个list中"name"不包含非空白符的键值对
        if extra_params:
            for extra_param in extra_params:
                if not extra_param['name'].strip():
                    extra_params.remove(extra_param)
            # 列表转换为字典
            extra_params = process_extra_params(extra_params)
        else:
            extra_params = {}
        if request.fileLinks:
            # 异步获取文件内容
            files_content = await get_files_content(request.fileLinks)
            system_message = f"\n\n相关文件内容：{files_content}"
            
            # 修复字符串拼接错误
            content_append(request.messages, 'system', system_message)
        kb_list = []
        user_prompt = request.messages[-1].get('content') or ""
        if settings["memorySettings"]["is_memory"] and settings["memorySettings"]["selectedMemory"] and settings["memorySettings"]["selectedMemory"] != "":
            await _complete_character_context(request, settings, user_prompt, cur_memory, memoryId, m0)
        if settings["knowledgeBases"]:
            for kb in settings["knowledgeBases"]:
                if kb["enabled"] and kb["processingStatus"] == "completed":
                    kb_list.append({"kb_id":kb["id"],"name": kb["name"],"introduction":kb["introduction"]})
        if settings["KBSettings"]["when"] == "before_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                all_kb_content = []
                # 用query_knowledge_base函数查询kb_list中所有的知识库
                for kb in kb_list:
                    kb_content = await query_knowledge_base(kb["kb_id"],user_prompt)
                    all_kb_content.extend(kb_content)
                    if settings["KBSettings"]["is_rerank"]:
                        all_kb_content = await rerank_knowledge_base(user_prompt,all_kb_content)
                if all_kb_content:
                    kb_message = f"\n\n可参考的知识库内容：{all_kb_content}"
                    content_append(request.messages, 'user',  f"{kb_message}\n\n用户：{user_prompt}")
        if settings["KBSettings"]["when"] == "after_thinking" or settings["KBSettings"]["when"] == "both":
            if kb_list:
                kb_list_message = f"\n\n可调用的知识库列表：{json.dumps(kb_list, ensure_ascii=False)}"
                content_append(request.messages, 'system', kb_list_message)
        else:
            kb_list = []
        request = await tools_change_messages(request, settings)
        # 如果系统消息为空字符串或者仅包含空白符，则将系统消息改成"you are a helpful assistant."
        if request.messages[0]['role'] == 'system' and not request.messages[0]['content'].strip():
            request.messages[0]['content'] = "you are a helpful assistant."
        append_resume_nudge(request.messages)
        chat_vendor = 'OpenAI'
        reasoner_vendor = 'OpenAI'
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['selectedProvider']:
                chat_vendor = modelProvider['vendor']
                break
        for modelProvider in settings['modelProviders']: 
            if modelProvider['id'] == settings['reasoner']['selectedProvider']:
                reasoner_vendor = modelProvider['vendor']
                break
        if chat_vendor == 'Dify':
            try:
                if len(request.messages) >= 3:
                    if request.messages[2]['role'] == 'user':
                        if request.messages[1]['role'] == 'assistant':
                            request.messages[2]['content'] = "你上一次的发言：\n" +request.messages[0]['content'] + "\n你上一次的发言结束\n\n用户：" + request.messages[2]['content']
                        if request.messages[0]['role'] == 'system':
                            request.messages[2]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n" + request.messages[2]['content']
                elif len(request.messages) >= 2:
                    if request.messages[1]['role'] == 'user':
                        if request.messages[0]['role'] == 'system':
                            request.messages[1]['content'] = "系统提示：\n" +request.messages[0]['content'] + "\n系统提示结束\n\n用户：" + request.messages[1]['content']
            except Exception as e:
                print("Dify error:",e)
        await _complete_web_search_setup(request, settings, user_prompt, tools, enable_web_search)
        if kb_list:
            tools.append(kb_tool)
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            deepsearch_messages = copy.deepcopy(request.messages)
            content_append(deepsearch_messages, 'user',  "\n\n将用户提出的问题或给出的当前任务拆分成多个步骤，每一个步骤用一句简短的话概括即可，无需回答或执行这些内容，直接返回总结即可，但不能省略问题或任务的细节。如果用户输入的只是闲聊或者不包含任务和问题，直接把用户输入重复输出一遍即可。如果是非常简单的问题，也可以只给出一个步骤即可。一般情况下都是需要拆分成多个步骤的。")
            response = await client.chat.completions.create(
                model=model,
                messages=deepsearch_messages,
                temperature=0.5, 
                extra_body = extra_params, # 其他参数
            )
            user_prompt = response.choices[0].message.content
            content_append(request.messages, 'user',  f"\n\n如果用户没有提出问题或者任务，直接闲聊即可，如果用户提出了问题或者任务，任务描述不清晰或者你需要进一步了解用户的真实需求，你可以暂时不完成任务，而是分析需要让用户进一步明确哪些需求。")
        if settings['reasoner']['enabled'] or enable_thinking:
            vendor = await _complete_reasoner_prep(request, reasoner_client, settings, chat_vendor, reasoner_vendor, images, tools, extra, reasoner_extra, open_tag, close_tag, enable_deep_research, enable_thinking, DRS_STAGE, user_prompt)
        if settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            content_append(request.messages, 'user',  f"\n\n可参考的步骤：{user_prompt}\n\n")
            drs_msg = get_drs_stage(DRS_STAGE)
            if drs_msg:
                content_append(request.messages, 'user',  f"\n\n{drs_msg}\n\n")
        # ===== 上下文管理管线：L1 修剪 -> L2 自动摘要（agent 模式；非流式通道不下发事件） =====
        await _run_context_pipeline(request, settings, client, model, extra_params, reasoner_client, tools)
        msg = await images_add_in_messages(request.messages, images,settings)
        if request.top_p != 1 or settings['top_p'] != 1:
            extra['top_p'] = request.top_p or settings['top_p']
        if tools:
            response = await client.chat.completions.create(
                model=model,
                messages=msg,  # 添加图片信息到消息
                temperature=request.temperature or settings['temperature'],
                tools=tools,
                stream=False,
                extra_body = extra_params, # 其他参数
                **extra
            )
        else:
            response = await client.chat.completions.create(
                model=model,
                messages=msg,  # 添加图片信息到消息
                temperature=request.temperature or settings['temperature'],
                stream=False,
                extra_body = extra_params, # 其他参数
                **extra
            )
        if response.choices[0].message and response.choices[0].message.tool_calls:  # B1: message 可能为 None
            pass
        elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
            DRS_STAGE, search_not_done, search_task = await _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty=True)
        reasoner_messages = copy.deepcopy(request.messages)
        _ns_loop_count = 0
        _ns_max_iterations = int(settings.get("max_tool_iterations", 100) or 100)
        ns_force_no_tools = False
        while response.choices[0].message and (response.choices[0].message.tool_calls or search_not_done):  # B1: None 守卫
            _ns_loop_count += 1
            # T-8: 取消围栏——后续 LLM 轮次前检查（cancel 端点可停不可停工具链的漏洞封堵）
            _cur_entry = _current_stream_entry.get()
            if _cur_entry and _cur_entry.get("cancelled"):
                break
            if not _drs_round_cap(_ns_loop_count, _ns_max_iterations, search_not_done, response.choices[0].message.tool_calls, "非流式"):
                search_not_done = False
                response.choices[0].message.tool_calls = None
                break
            if response.choices[0].message.tool_calls and _ns_loop_count > _ns_max_iterations:
                _append_loopcap_hint(request, "非流式")
                ns_force_no_tools = True
                response.choices[0].message.tool_calls = None
            if response.choices[0].message.tool_calls:
                abort = await _ns_tool_round(request, reasoner_messages, settings, user_prompt, response)
                if abort:
                    break
            if settings['webSearch']['when'] == 'after_thinking' or settings['webSearch']['when'] == 'both':
                content_append(request.messages, 'user',  f"\n对于联网搜索的结果，如果联网搜索的信息不足以回答问题时，你可以进一步使用联网搜索查询还未给出的必要信息。如果已经足够回答问题，请直接回答问题。")
            if settings['reasoner']['enabled'] or enable_thinking:
                vendor = await _ns_reasoner_pass(request, reasoner_client, reasoner_messages, settings, images, reasoner_extra, open_tag, close_tag, tools, vendor)
            msg = await images_add_in_messages(request.messages, images,settings)
            if request.top_p != 1 or settings['top_p'] != 1:
                extra['top_p'] = request.top_p or settings['top_p']
            if tools and not ns_force_no_tools:
                response = await client.chat.completions.create(
                    model=model,
                    messages=msg,  # 添加图片信息到消息
                    temperature=request.temperature or settings['temperature'],
                    tools=tools,
                    stream=False,
                    extra_body = extra_params, # 其他参数
                    **extra
                )
            else:
                response = await client.chat.completions.create(
                    model=model,
                    messages=msg,  # 添加图片信息到消息
                    temperature=request.temperature or settings['temperature'],
                    stream=False,
                    extra_body = extra_params, # 其他参数
                    **extra
                )
            if response.choices[0].message and response.choices[0].message.tool_calls:  # B1: 再生成后 message 可能为 None
                pass
            elif settings['tools']['deepsearch']['enabled'] or enable_deep_research: 
                DRS_STAGE, search_not_done, search_task = await _complete_drs_step(client, model, extra_params, request, user_prompt, response, DRS_STAGE, search_not_done, search_task, none_to_empty=False)
       # 处理响应内容
        response_dict = await _complete_finalize(request, settings, response, m0, memoryId, cur_memory, user_prompt, open_tag, close_tag)
        return JSONResponse(content=response_dict)
    except Exception as e:
        return JSONResponse(
            content={"error": {"message": str(e), "type": "api_error"}}
        )

@app.post("/execute_tool_manually")
async def execute_tool_manually(request: Request):
    """
    前端点击审批按钮后调用的接口
    """
    data = await request.json()
    tool_name = data.get("tool_name")
    tool_params = data.get("tool_params")
    approval_type = data.get("approval_type") # 'once' 或 'always'

    # 安全围栏：所属生成流已被用户取消时，拒绝执行审批工具
    _appr_stream_id = data.get("stream_id")
    if _appr_stream_id:
        _appr_entry = _active_streams.get(_appr_stream_id)
        if _appr_entry and _appr_entry.get("cancelled"):
            logging.getLogger("app").info(f"[Cancel] 拒绝执行工具 {tool_name}：其生成流 {_appr_stream_id} 已被取消")
            return {"result": "[Cancelled] 该工具所属的生成已被用户取消，拒绝执行"}

    # 获取当前配置
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    
    # ==================== 核心逻辑：处理 "Always" ====================
    if approval_type == "always":
        # 如果用户选择“不再询问”，则将该工具写入当前项目的 .agent/config.json
        if cwd:
            try:
                add_tool_to_project_config(cwd, tool_name)
                logging.getLogger("app").info(f"[Permission] Added {tool_name} to whitelist for project {cwd}")
            except Exception as e:
                return {"result": f"[System Error] Failed to save permission: {str(e)}"}
        else:
             return {"result": "[System Error] No working directory found to save config."}

    # ==================== 1. 导入所有工具函数 ====================
    from py.web_search import (
        DDGsearch, 
        searxng,
        Tavily_search,
        Bing_search,
        Google_search,
        Brave_search,
        Exa_search,
        Serper_search,
        bochaai_search,
        youcom_search,
        jina_crawler,
        Crawl4Ai_search,
        firecrawl_search,
        simple_fetch,
        markdown_new,
        make_engine_with_fallback as _fb, browser_search,
    )
    from py.know_base import query_knowledge_base
    from py.agent_tool import agent_tool_call
    from py.a2a_tool import a2a_tool_call
    from py.llm_tool import custom_llm_tool
    from py.pollinations import pollinations_image,openai_image,openai_chat_image
    from py.load_files import get_file_content
    from py.code_interpreter import e2b_code,local_run_code
    from py.custom_http import fetch_custom_http
    from py.comfyui_tool import comfyui_tool_call
    from py.utility_tools import (
        time,
        get_weather,
        get_location_coordinates,
        get_weather_by_city,
        get_wikipedia_summary_and_sections,
        get_wikipedia_section_content,
        search_arxiv_papers
    )
    from py.autoBehavior import auto_behavior

    # Docker CLI 工具（原有）
    from py.cli_tool import (
        docker_sandbox,
        list_files_tool,
        read_file_tool,
        read_file_range_tool, 
        tail_file_tool,     
        search_files_tool,
        edit_file_tool,
        edit_file_patch_tool, 
        glob_files_tool,       
        todo_write_tool, 
        list_processes_tool,
        get_process_logs_tool,
        kill_process_tool,
        docker_manage_ports_tool,
        read_skill_tool,
    )

    # 新增：本地环境 CLI 工具（假设保存在 py/local_cli_tool.py）
    from py.cli_tool import (
        shell_tool_local,           # 本地 bash 执行（对应 docker_sandbox）
        list_files_tool_local,     # 本地文件列表
        read_file_tool_local,      # 本地文件读取
        read_file_range_tool_local, # <--- 新增导入
        tail_file_tool_local,       # <--- 新增导入
        search_files_tool_local,   # 本地文件搜索
        edit_file_tool_local,      # 本地文件写入
        edit_file_patch_tool_local,# 本地精确替换
        glob_files_tool_local,     # 本地 glob 查找
        todo_write_tool_local,     # 本地任务管理
        local_net_tool,            # 本地网络工具
        read_skill_tool_local,
    )

    from py.cdp_tool import (
        list_pages,
        navigate_page,
        new_page,
        close_page,
        select_page,
        take_snapshot,
        wait_for,
        click,
        fill,
        hover,
        press_key,
        evaluate_script,
        take_screenshot,
        fill_form,
        drag,
        handle_dialog
    )
    from py.random_topic import get_random_topics,get_categories

    from py.task_tools import (
        create_subtask,
        query_task_progress,
        cancel_subtask,
        finish_task
    )
    
    from py.computer_use_tool import (
        mouse_move,
        mouse_click,
        mouse_double_click,
        mouse_drag,
        mouse_scroll,
        mouse_hold,
        copy_to_input_box,
        keyboard_press,
        keyboard_sequence,
        keyboard_hotkey,
        keyboard_hold,
        wait,
        screenshot
    )

    from py.mode_change import update_workspace_settings
    from py.acpx_tools import acpx_agent

    # ==================== 2. 定义工具映射表 ====================
    _TOOL_HOOKS = {
        "DDGsearch": _fb("duckduckgo", DDGsearch), "browser_lookup": browser_search, "searxng": _fb("searxng", searxng),
        "Tavily_search": _fb("tavily", Tavily_search),
        "query_knowledge_base": query_knowledge_base,
        "jina_crawler": jina_crawler,
        "Crawl4Ai_search": Crawl4Ai_search,
        "firecrawl_search": firecrawl_search,
        "simple_fetch":simple_fetch,
        "markdown_new":markdown_new,
        "agent_tool_call": agent_tool_call,
        "a2a_tool_call": a2a_tool_call,
        "custom_llm_tool": custom_llm_tool,
        "pollinations_image":pollinations_image,
        "get_file_content":get_file_content,
        "get_image_content": get_image_content,
        "analyze_image": analyze_image,
        "review_image": review_image,
        "analyze_images": analyze_images,
        "e2b_code": e2b_code,
        "local_run_code": local_run_code,
        "openai_image": openai_image,
        "openai_chat_image":openai_chat_image,
        "query_diary": handle_query_diary,
        "list_diary_books": handle_list_diary_books,
        "Bing_search": _fb("bing", Bing_search),
        "Google_search": _fb("google", Google_search),
        "Brave_search": _fb("brave", Brave_search),
        "Exa_search": _fb("exa", Exa_search),
        "Serper_search": _fb("serper", Serper_search),
        "bochaai_search": _fb("bochaai", bochaai_search),
        "youcom_search": _fb("youcom", youcom_search),
        "comfyui_tool_call": comfyui_tool_call,
        "time": time,
        "get_weather": get_weather,
        "get_location_coordinates": get_location_coordinates,
        "get_weather_by_city":get_weather_by_city,
        "get_wikipedia_summary_and_sections": get_wikipedia_summary_and_sections,
        "get_wikipedia_section_content": get_wikipedia_section_content,
        "search_arxiv_papers": search_arxiv_papers,
        "auto_behavior": auto_behavior,
        "list_pages": list_pages,
        "new_page": new_page,
        "close_page": close_page,
        "select_page": select_page,
        "navigate_page": navigate_page,
        "take_snapshot": take_snapshot,
        "click": click,
        "fill": fill,
        "evaluate_script": evaluate_script,
        "take_screenshot": take_screenshot,
        "hover": hover,
        "press_key": press_key,
        "wait_for": wait_for,
        "fill_form":fill_form,
        "drag": drag,
        "handle_dialog": handle_dialog,
        "get_random_topics":get_random_topics,
        "get_categories":get_categories,
        
        # Docker Sandbox 相关工具（原有）
        "docker_sandbox": docker_sandbox,
        "list_files_tool": list_files_tool,
        "read_file_tool": read_file_tool,
        "read_file_range_tool": read_file_range_tool, # <--- 映射新工具
        "tail_file_tool": tail_file_tool,             # <--- 映射新工具
        "search_files_tool": search_files_tool,
        "edit_file_tool": edit_file_tool,
        "edit_file_patch_tool": edit_file_patch_tool,
        "glob_files_tool": glob_files_tool,
        "todo_write_tool": todo_write_tool,
        "list_processes_tool": list_processes_tool,
        "get_process_logs_tool": get_process_logs_tool,
        "kill_process_tool": kill_process_tool,
        "docker_manage_ports_tool": docker_manage_ports_tool,
        "read_skill_tool": read_skill_tool,
        
        # 本地环境工具（新增）- 与 Docker 版本功能相同但操作本地文件系统
        "shell_tool_local": shell_tool_local,                     # 本地 bash 执行
        "list_files_tool_local": list_files_tool_local,         # 本地文件列表
        "read_file_tool_local": read_file_tool_local,           # 本地文件读取
        "read_file_range_tool_local": read_file_range_tool_local, # <--- 映射新工具
        "tail_file_tool_local": tail_file_tool_local,             # <--- 映射新工具
        "search_files_tool_local": search_files_tool_local,     # 本地文件搜索
        "edit_file_tool_local": edit_file_tool_local,           # 本地文件写入
        "edit_file_patch_tool_local": edit_file_patch_tool_local,  # 本地精确替换
        "glob_files_tool_local": glob_files_tool_local,         # 本地 glob 查找
        "todo_write_tool_local": todo_write_tool_local,         # 本地任务管理
        "local_net_tool": local_net_tool,                       # 本地网络工具
        "read_skill_tool_local": read_skill_tool_local,         # 本地技能读取

        # 任务中心工具（新增）
        "create_subtask": create_subtask,
        "query_task_progress": query_task_progress,
        "cancel_subtask": cancel_subtask,
        "finish_task":finish_task,

        # 鼠标键盘控制
        "mouse_move":mouse_move,
        "mouse_click":mouse_click,
        "mouse_double_click":mouse_double_click,
        "mouse_drag":mouse_drag,
        "mouse_scroll":mouse_scroll,
        "mouse_hold":mouse_hold,
        "copy_to_input_box":copy_to_input_box,
        "keyboard_press":keyboard_press,
        "keyboard_sequence":keyboard_sequence,
        "keyboard_hotkey":keyboard_hotkey,
        "keyboard_hold":keyboard_hold,
        "wait":wait,
        "screenshot":screenshot,

        "update_workspace_settings":update_workspace_settings,
        "acpx_agent":acpx_agent,
    }
    

    if tool_name not in _TOOL_HOOKS:
        return {"result": f"Tool {tool_name} not found in backend registry."}
    
    tool_func = _TOOL_HOOKS[tool_name]
    
    try:
        if tool_name in ("shell_tool_local", "docker_sandbox"):
            # 异步生成器：调用即返回 AsyncIterator，无需 await
            result = tool_func(**tool_params)
        elif tool_name == "acpx_agent":
            # 常规异步函数：必须 await 才能获得实际结果
            result = await tool_func(**tool_params)
        else:
            # 2. 执行工具
            result = await tool_func(**tool_params)
        
        # 3. 处理流式输出 (AsyncIterator)
        # 如果是流，我们需要将其消耗完合并成字符串返回给前端一次性显示
        # 因为手动执行通常不再支持流式打字机效果（或者前端处理会比较复杂）
        if hasattr(result, "__aiter__"):
            output_buffer = []
            async for chunk in result:
                output_buffer.append(chunk)
            return {"result": "".join(output_buffer)}
        
        return {"result": str(result)}
        
    except Exception as e:
        return {"result": f"Error executing {tool_name}: {str(e)}"}

# 在现有路由后添加以下代码

# 在现有路由后添加以下代码



@app.post("/v1/chat/completions", operation_id="chat_with_agent_party")
async def chat_endpoint(request: ChatRequest, fastapi_request: Request):
    """
    用来与agent party中的模型聊天
    """
    fastapi_base_url = str(fastapi_request.base_url)
    # 【注意】引入全局 fast_client
    global client, reasoner_client, fast_client, settings
    
    raw_model = request.model or 'super-model'
    override_memory_id = None
    
    if raw_model.startswith("memory/"):
        parts = raw_model.split('/', 2) 
        if len(parts) >= 2:
            override_memory_id = parts[1]
            request.model = parts[2] if len(parts) > 2 else 'super-model'
            logging.getLogger("app").info(f"检测到动态 Memory ID: {override_memory_id}, 目标模型更新为: {request.model}")
    
    model = request.model or 'super-model'
    enable_thinking = request.enable_thinking or False
    enable_deep_research = request.enable_deep_research or False
    enable_web_search = request.enable_web_search or False
    async_tools_id = request.asyncToolsID or None
    if model != 'super-model':
        _agents_map = (settings or {}).get('agents') or {}
        if model not in _agents_map and not any((a or {}).get('name') == model for a in _agents_map.values()):
            _fresh_agents = (await load_settings()).get('agents') or {}
            if model not in _fresh_agents and not any((a or {}).get('name') == model for a in _fresh_agents.values()):
                logging.getLogger("app").info(f"[Chat] 警告: Agent '{model}' 不存在于 agents 配置（共 {len(_fresh_agents)} 个），自动回落 super-model")
                model = 'super-model'
                request.model = 'super-model'
    await _apply_group_memory_context(request)

    if model == 'super-model':
        current_settings = await load_settings()
        
        # 【修改点1】创建当前请求的专属配置，避免污染全局
        request_settings = current_settings.copy()
        active_client = client  # 默认使用主模型
        
        if current_settings['fast']['enabled'] and not request.is_sub_agent:
            fast_cfg = current_settings['fast']
            use_fast_model = False
            
            if fast_cfg.get('triggerMode') == 'always':
                use_fast_model = True
            elif fast_cfg.get('triggerMode') == 'conditional':
                last_user_text = ""
                has_image = False
                for msg in reversed(request.messages):
                    if msg.get('role') == 'user':
                        content = msg.get('content')
                        if isinstance(content, str):
                            last_user_text = content
                        elif isinstance(content, list):
                            texts = []
                            for item in content:
                                if item.get('type') == 'text':
                                    texts.append(item.get('text', ''))
                                elif item.get('type') == 'image_url':
                                    has_image = True
                            last_user_text = "".join(texts)
                        break
                
                has_files = bool(request.fileLinks) 
                condition_pass = True
                
                max_len = fast_cfg.get('conditionMaxLen', 0)
                if max_len > 0 and len(last_user_text) > max_len:
                    condition_pass = False
                if condition_pass and fast_cfg.get('conditionNoNewline', False):
                    if '\n' in last_user_text:
                        condition_pass = False
                if condition_pass and fast_cfg.get('conditionNoFiles', True):
                    if has_image or has_files:
                        condition_pass = False
                        
                if condition_pass:
                    use_fast_model = True

            if use_fast_model:
                exclude_keys = ['enabled', 'triggerMode', 'conditionMaxLen', 'conditionNoNewline', 'conditionNoFiles']
                fast_config = {k: v for k, v in fast_cfg.items() if k not in exclude_keys}
                
                # 更新专属配置，不影响 current_settings
                request_settings.update(fast_config)
                
                # 【修改点2】动态检查并更新快速模型的 Client (仅配置被修改时触发)
                old_fast_cfg = settings.get('fast', {}) if settings else {}
                if (fast_client is None 
                    or fast_cfg.get('api_key') != old_fast_cfg.get('api_key') 
                    or fast_cfg.get('base_url') != old_fast_cfg.get('base_url')):
                    
                    f_provider = fast_cfg.get('selectedProvider', current_settings.get('selectedProvider'))
                    f_class = get_client_class(current_settings, f_provider)
                    fast_client = f_class(
                        api_key=fast_cfg.get('api_key') or current_settings.get('api_key'),
                        base_url=fast_cfg.get('base_url') or current_settings.get('base_url') or "https://api.openai.com/v1"
                    )
                
                # 当前请求切花为快速 Client
                active_client = fast_client

        if override_memory_id:
            request_settings["memorySettings"]["is_memory"] = True
            request_settings["memorySettings"]["selectedMemory"] = override_memory_id
            
        if len(current_settings['modelProviders']) <= 0:
            return JSONResponse(status_code=500, content={"error": {"message": await t("NoModelProvidersConfigured"), "type": "server_error", "code": 500}})

        # 【修改点3】动态更新主模型 Client (仅主配置修改时)
        if (current_settings['api_key'] != settings['api_key'] 
            or current_settings['base_url'] != settings['base_url']
            or client is None):
            c_class = get_client_class(current_settings, current_settings['selectedProvider'])
            client = c_class(
                api_key=current_settings['api_key'],
                base_url=current_settings['base_url'] or "https://api.openai.com/v1",
            )
            # 如果当前没有触发快速模型，需要确保 active_client 指向最新的主 client
            if active_client != fast_client:
                active_client = client

        # 动态更新推理模型 Client
        if (current_settings['reasoner']['api_key'] != settings['reasoner']['api_key'] 
            or current_settings['reasoner']['base_url'] != settings['reasoner']['base_url']
            or reasoner_client is None):
            r_class = get_client_class(current_settings, current_settings['reasoner']['selectedProvider'])
            reasoner_client = r_class(
                api_key=current_settings['reasoner']['api_key'],
                base_url=current_settings['reasoner']['base_url'] or "https://api.openai.com/v1",
            )

        print('model:', request_settings['model'])
        
        # 将"system_prompt"插入到request.messages[0].content中 (注意这里使用的是 request_settings)
        if request_settings['system_prompt']:
            content_prepend(request.messages, 'system', request_settings['system_prompt'] + "\n\n")
            
        # 【核心修正】因为之前我们没污染 current_settings，所以这里的比较才是真实的配置对比
        if current_settings != settings:
            settings = current_settings
            
        try:
            # 传入 active_client (0延迟切换) 和 request_settings
            if request.stream:
                return await generate_stream_response(active_client, reasoner_client, request, request_settings, fastapi_base_url, enable_thinking, enable_deep_research, enable_web_search, async_tools_id)
            return await generate_complete_response(active_client, reasoner_client, request, request_settings, fastapi_base_url, enable_thinking, enable_deep_research, enable_web_search)
        except asyncio.CancelledError:
            logging.getLogger("app").info("Client disconnected")
            raise
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": "server_error", "code": 500}})
            
    else:
        # ===== Agent 部分逻辑 ===== 
        # (因为 agent_settings 每次请求都是从本地 json.load 创建的新字典，
        # 所以它天生就不会产生你主模型遇到的“全局污染”问题，这里的代码可以基本保留原样)
        
        current_settings = await load_settings()
        agentSettings = current_settings['agents'].get(model, {})
        if not agentSettings:
            for agentId , agentConfig in current_settings['agents'].items():
                if current_settings['agents'][agentId]['name'] == model:
                    agentSettings = current_settings['agents'][agentId]
                    break
        if not agentSettings:
            logging.getLogger("app").info(f"[Chat] 404: Agent '{model}' not found in settings['agents']")
            return JSONResponse(status_code=404, content={"error": {"message": f"Agent {model} not found", "type": "not_found", "code": 404}})
            
        # 每次读取文件生成新的 agent_settings 字典
        if agentSettings['config_path']:
            with open(agentSettings['config_path'], 'r' , encoding='utf-8') as f:
                agent_settings = json.load(f)
            if agentSettings['system_prompt']:
                content_prepend(request.messages, 'user', agentSettings['system_prompt'] + "\n\n")
        
        if agent_settings['fast']['enabled'] and not request.is_sub_agent:
            fast_cfg = agent_settings['fast']
            use_fast_model = False
            
            if fast_cfg.get('triggerMode') == 'always':
                use_fast_model = True
            elif fast_cfg.get('triggerMode') == 'conditional':
                last_user_text = ""
                has_image = False
                for msg in reversed(request.messages):
                    if msg.get('role') == 'user':
                        content = msg.get('content')
                        if isinstance(content, str):
                            last_user_text = content
                        elif isinstance(content, list):
                            texts = []
                            for item in content:
                                if item.get('type') == 'text':
                                    texts.append(item.get('text', ''))
                                elif item.get('type') == 'image_url':
                                    has_image = True
                            last_user_text = "".join(texts)
                        break
                
                has_files = bool(request.fileLinks)
                condition_pass = True
                max_len = fast_cfg.get('conditionMaxLen', 0)
                if max_len > 0 and len(last_user_text) > max_len: condition_pass = False
                if condition_pass and fast_cfg.get('conditionNoNewline', False):
                    if '\n' in last_user_text: condition_pass = False
                if condition_pass and fast_cfg.get('conditionNoFiles', True):
                    if has_image or has_files: condition_pass = False
                        
                if condition_pass:
                    use_fast_model = True

            if use_fast_model:
                exclude_keys = ['enabled', 'triggerMode', 'conditionMaxLen', 'conditionNoNewline', 'conditionNoFiles']
                fast_config = {k: v for k, v in fast_cfg.items() if k not in exclude_keys}
                agent_settings.update(fast_config) # Agent 这里更新无所谓，因为它是局部变量
                
        # 顺便用上刚才写的辅助函数简化代码
        a_client_class = get_client_class(agent_settings, agent_settings.get('selectedProvider'))
        agent_client = a_client_class(
            api_key=agent_settings.get('api_key', ''),
            base_url=agent_settings.get('base_url') or "https://api.openai.com/v1"
        )
        
        ar_client_class = get_client_class(agent_settings, agent_settings.get('reasoner', {}).get('selectedProvider'))
        agent_reasoner_client = ar_client_class(
            api_key=agent_settings.get('reasoner', {}).get('api_key', ''),
            base_url=agent_settings.get('reasoner', {}).get('base_url') or "https://api.openai.com/v1"
        )
        
        try:
            if request.stream:
                return await generate_stream_response(agent_client, agent_reasoner_client, request, agent_settings, fastapi_base_url, enable_thinking, enable_deep_research, enable_web_search, async_tools_id)
            return await generate_complete_response(agent_client, agent_reasoner_client, request, agent_settings, fastapi_base_url, enable_thinking, enable_deep_research, enable_web_search)
        except asyncio.CancelledError:
            logging.getLogger("app").info("Client disconnected")
            raise
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": "server_error", "code": 500}})






@app.post("/simple_chat")
async def simple_chat_endpoint(request: ChatRequest):

    """
    同时支持流式(stream=true)与非流式(stream=false)
    默认使用 fast_client 以提高响应速度
    """
    global fast_client, settings

    current_settings = await load_settings()
    if len(current_settings['modelProviders']) <= 0:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": await t("NoModelProvidersConfigured"),
                               "type": "server_error", "code": 500}}
        )

    # --------------- 无脑使用 fast_client ---------------
    fast_cfg = current_settings.get('fast', {})
    
    # 初始化或更新 fast_client
    if (fast_client is None 
        or fast_cfg.get('api_key') != settings.get('fast', {}).get('api_key')
        or fast_cfg.get('base_url') != settings.get('fast', {}).get('base_url')):
        
        f_provider = fast_cfg.get('selectedProvider', current_settings.get('selectedProvider'))
        f_class = get_client_class(current_settings, f_provider)
        fast_client = f_class(
            api_key=fast_cfg.get('api_key') or current_settings.get('api_key'),
            base_url=fast_cfg.get('base_url') or current_settings.get('base_url') or "https://api.openai.com/v1"
        )
    
    # 使用 fast 配置覆盖当前配置
    if fast_cfg:
        exclude_keys = ['enabled', 'triggerMode', 'conditionMaxLen', 'conditionNoNewline', 'conditionNoFiles']
        fast_config = {k: v for k, v in fast_cfg.items() if k not in exclude_keys}
        for key, value in fast_config.items():
            current_settings[key] = value

    # --------------- 调用大模型（T-5: 入 llm_gate 闸门，mem0 防撞不再失明） ---------------
    llm_gate.enter()
    try:
        response = await fast_client.chat.completions.create(
            model=current_settings['model'],
            messages=request.messages,
            stream=request.stream,
            temperature=request.temperature or settings.get('temperature', 0.7),
        )
    except BaseException:
        llm_gate.leave()
        raise

    # --------------- 非流式：一次性返回 JSON ---------------
    if not request.stream:
        # 注意：openai 返回的是 ChatCompletion 对象
        try:
            return JSONResponse(content=response.model_dump())
        finally:
            llm_gate.leave()

    # --------------- 流式：保持原来的 StreamingResponse ---------------
    async def openai_raw_stream():
        try:
            async for chunk in response:
                yield chunk.model_dump_json() + '\n'
        finally:
            llm_gate.leave()
        # 不发送 [DONE]

    return StreamingResponse(
        openai_raw_stream(),
        media_type="text/plain",      # 也可以保持 "text/event-stream"
        headers={"Cache-Control": "no-cache"}
    )










from py.task_center import get_task_center
from py.sub_agent import run_subtask_in_background

# --- 新增任务中心 API ---



    


def sanitize_proxy_url(input_url: str) -> str:
    """
    针对代理场景优化的 URL 安全过滤
    """
    if not input_url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    
    # 1. 解析 URL
    parsed = urlparse(input_url)
    
    # 2. 验证协议 (禁止 file://, gopher:// 等协议)
    if parsed.scheme not in ["http", "https"]:
        raise HTTPException(status_code=400, detail="仅支持 http 或 https 协议")
    
    if not parsed.netloc:
        raise HTTPException(status_code=400, detail="无效的域名或 IP")

    # 3. 重新构造 URL (消除 SSRF 污点)
    # 排除 userinfo, 只保留必要部分
    safe_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    if parsed.query:
        safe_url += f"?{parsed.query}"
    if parsed.fragment:
        safe_url += f"#{parsed.fragment}"

    # 4. 内网拦截 (M2/X-8): loopback 放行（本机服务是生态刚需），私网/保留/元数据拒绝
    from py.net_guard import url_public_ok
    if not url_public_ok(safe_url, allow_loopback=True):
        raise HTTPException(status_code=403, detail="blocked target (private/reserved address)")

    return safe_url

@app.api_route("/extension_proxy", methods=["GET", "POST"])
async def extension_proxy(request: Request, url: str):
    """
    方便SAP插件调用的通用代理接口，让插件能够绕过 CORS 限制访问任意 URL。
    """
    BROWSER_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    # --- 阶段 A: 安全校验 (保留，防止 SSRF 攻击内网) ---
    try:
        target_url = sanitize_proxy_url(url)
    except HTTPException as e:
        return Response(content=e.detail, status_code=e.status_code)
    
    # --- 阶段 B: 执行代理请求 ---
    method = request.method
    body = await request.body()
    
    # 构造 Header：只保留必要的，去除杂质，添加身份标识
    # 排除可能导致指纹泄露或被拒绝的 Header
    excluded_headers = {
        'host', 'content-length', 'connection', 'keep-alive', 
        'upgrade-insecure-requests', 'accept-encoding', 'cookie', 'user-agent'
    }
    
    headers = {
        k: v for k, v in request.headers.items() 
        if k.lower() not in excluded_headers
    }
    
    # 【关键点 1】：使用标准浏览器 UA，声明这是用户阅读行为
    headers["User-Agent"] = BROWSER_USER_AGENT
    
    # 【关键点 2】：明确告诉服务器我们接受 XML/RSS 格式，这显得更像一个良性阅读器
    if "accept" not in headers or "*/*" in headers["accept"]:
        headers["Accept"] = "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"

    # 【关键点 3】：处理 Referer。有些防盗链机制需要 Referer，有些（如 Reddit）看到奇怪的 Referer 会拦截
    # 最安全的做法是不发送 Referer，或者设为目标域名的根目录
    headers.pop("Referer", None) 
    
    logging.getLogger("app").info(f"--- [Extension Proxy] ---")
    logging.getLogger("app").info(f"Target: {target_url} | Method: {method} | Mode: Browser Emulation")
    
    # trust_env=False: 防止你的 Python 代码意外使用了系统层的 HTTP 代理
    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=30.0, trust_env=False) as client:
        try:
            resp = await client.request(
                method=method,
                url=target_url,
                headers=headers,
                content=body
            )
            
            # 清洗响应头：防止将压缩编码或分块传输透传给前端导致解析错误
            resp_headers = {
                k: v for k, v in resp.headers.items()
                if k.lower() not in {
                    'content-encoding', 'content-length', 'transfer-encoding', 
                    'server', 'set-cookie' # 也不要透传 Set-Cookie，保护用户隐私
                }
            }
            
            # 如果 Reddit 依然返回 403，通常内容里会有错误提示，照样返回给前端便于调试
            if resp.status_code == 403:
                logging.getLogger("app").info(f"[Proxy Warning] Target returned 403. Body sample: {resp.content[:100]}")

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type", "application/octet-stream")
            )

        except httpx.ConnectError as e:
            err_msg = f"Proxy Connect Error: {e}"
            # 返回 JSON 格式错误以便前端优雅处理
            return Response(content=f'{{"error": "{err_msg}"}}', status_code=502, media_type="application/json")
            
        except Exception as e:
            logging.getLogger("app").info(f"[Proxy Error] System: {repr(e)}")
            return Response(content='{"error": "Internal Proxy Error"}', status_code=500, media_type="application/json")

        
async def _persist_mcp_status(mcp_id: str, status: str):
    """MCP 连接状态的单一写者（S62 裁决 C）：内存 mcp_status + 磁盘 processingStatus + WS 推送。

    磁盘 processingStatus 此前只靠前端 pollMCPStatus 写回（且漏调 autoSaveSettings），
    bot 会话（xmpp 等，settings 一律 load_settings 读盘）要等主界面下次落盘才看到新
    工具；现由后端在状态迁移点直接落盘，前端退化为纯显示。
    """
    app_state.mcp_status[mcp_id] = status
    disk_status = "ready" if status == "ready" else (
        "initializing" if status == "initializing" else "server_error")
    try:
        cur = await load_settings()
        cfg = cur.setdefault("mcpServers", {}).setdefault(mcp_id, {})
        if cfg.get("processingStatus") != disk_status:
            cfg["processingStatus"] = disk_status
            await save_settings(cur)
        await ws_manager.broadcast_settings_update(cur)
    except Exception as e:
        logging.getLogger("app").warning(f"MCP 状态落盘失败({mcp_id}/{status}): {e}")


async def process_mcp(mcp_id: str):
    """
    初始化单个 MCP 服务器，带失败回调同步，无需 sleep。
    """
    # (global decl cleared: migrated to py/app_state.py)

    # 1. 同步原语：事件 + 失败原因
    init_done = asyncio.Event()
    fail_reason: str | None = None

    async def on_failure(error_message: str):
        nonlocal fail_reason
        # 仅第一次生效
        if fail_reason is not None:
            return
        fail_reason = error_message
        await _persist_mcp_status(mcp_id, f"failed: {error_message}")

        # 容错：只有客户端已创建才标记 disabled
        if mcp_id in app_state.mcp_client_list:
            app_state.mcp_client_list[mcp_id].disabled = True
            await app_state.mcp_client_list[mcp_id].close()
            logging.getLogger("app").info(f"关闭MCP服务器: {mcp_id}")

        init_done.set()          # 唤醒主协程

    # 2. 开始初始化
    await _persist_mcp_status(mcp_id, "initializing")
    try:
        cur_settings = await load_settings()
        server_config = cur_settings["mcpServers"][mcp_id]

        app_state.mcp_client_list[mcp_id] = McpClient()
        init_task = asyncio.create_task(
            app_state.mcp_client_list[mcp_id].initialize(
                mcp_id,
                server_config,
                on_failure_callback=on_failure
            )
        )
        # 2.1 先等初始化本身（最多 6 秒）
        await asyncio.wait_for(init_task, timeout=6)

        # 2.2 再等看 on_failure 会不会被触发（最多 5 秒）
        try:
            await asyncio.wait_for(init_done.wait(), timeout=5)
        except asyncio.TimeoutError:
            # 5 秒内没收到失败回调，认为成功
            pass

        # 3. 最终状态判定
        if fail_reason:
            # 回调里已经关过 client，这里只需保证状态一致
            app_state.mcp_client_list[mcp_id].disabled = True
            return
        tool = []
        retry = 0 
        while tool == [] and retry < 10:
            try:
                tool = await app_state.mcp_client_list[mcp_id].get_openai_functions(disable_tools=[])
            except Exception as e:
                logging.getLogger("app").info(f"获取工具失败: {str(e)}")
            finally:
                retry += 1
                await asyncio.sleep(0.5)
        await _persist_mcp_status(mcp_id, "ready")
        app_state.mcp_client_list[mcp_id].disabled = False

    except Exception as e:
        # 任何异常（超时、崩溃）都走这里
        await _persist_mcp_status(mcp_id, f"failed: {str(e)}")
        app_state.mcp_client_list[mcp_id].disabled = True
        await app_state.mcp_client_list[mcp_id].close()

    finally:
        # 如果任务还活着，保险起见取消掉
        if "init_task" in locals() and not init_task.done():
            init_task.cancel()
            try:
                await init_task
            except asyncio.CancelledError:
                pass





    


# 停止接口保持不变



# 在现有路由之后添加health路由
@app.get("/health")
async def health_check():
    return {"status": "ok"}












# 修改删除VRM模型的接口，添加安全检查





# 删除知识库
async def remove_kb(kb_id):
    # 删除KB_DIR/kb_id目录
    kb_dir = os.path.join(KB_DIR, str(kb_id))
    if os.path.exists(kb_dir):
        shutil.rmtree(kb_dir)
    else:
        logging.getLogger("app").info(f"KB directory {kb_dir} does not exist.")
    return

# 添加状态存储
# 修改 process_kb
async def process_kb(kb_id):
    app_state.kb_status[kb_id] = "processing"
    try:
        from py.know_base import process_knowledge_base
        await process_knowledge_base(kb_id)
        app_state.kb_status[kb_id] = "completed"
    except Exception as e:
        app_state.kb_status[kb_id] = f"failed: {str(e)}"


# ==========================================
# 机器人管理器延迟加载容器 (Lazy Container)
# ==========================================
from py.live_router import router as live_router, ws_router as live_ws_router

# 2. 分别挂载
app.include_router(live_router)     # /api/live/*
app.include_router(live_ws_router)  # /ws/live/*


from py.overlay_router import router as overlay_router
app.include_router(overlay_router)


# ---------- 模型 ----------

# ---------- 1. 读取（平铺） ----------




# ---------- 1.5 新增原始记忆行（C-5：此前双端皆缺=新增按钮静默必败） ----------

# ---------- M4-lite: 数据快照滚动备份（列表 / 手动快照 / 校验演练） ----------



# ---------- 2. 修改（只改 data） ----------


# ---------- 3. 删除（按行号） ----------





settings_lock = asyncio.Lock()


def _apply_proxy_env_safe(settings):
    """S85-D：代理设置保存后即时同步进程 env（manual=注入/system=探测/none=清除）。"""
    try:
        from py.proxy_util import apply_env_proxy
        apply_env_proxy(settings)
    except Exception as e:
        logger.info(f"代理环境同步异常: {e}")


async def _ws_save_settings(websocket: WebSocket, data: dict):
    """B8(b03e7c0e): ws save_settings 单点——读现库深合并后落盘，部分载荷
    不再整库覆盖。C-15: 失败必须回 save_error（此前异常被外层吞=前端白等超时）。"""
    settings_dict = data.get("data", {})
    try:
        current = await load_settings()
        deep_update(current, settings_dict)
        await save_settings(current)
        _apply_proxy_env_safe(current)
        await sync_all_bots_behavior(current)
        try:
            from py.diary_engine import global_diary_engine
            global_diary_engine.update_config(current.get("diarySettings"))
        except Exception as _de:
            logger.info(f"日记引擎配置同步异常: {_de}")
    except Exception as _save_e:
        logger.error(f"[WS] save_settings 失败: {_save_e}")
        await ws_manager.send_json({
            "type": "save_error",
            "correlationId": data.get("correlationId"),
            "success": False,
            "error": str(_save_e),
        }, websocket)
        return
    await ws_manager.send_json({
        "type": "settings_saved",
        "correlationId": data.get("correlationId"),
        "success": True
    }, websocket)
    # 广播合并后的权威全量（不含自己）
    await ws_manager.broadcast_settings_update(current, exclude=websocket)


async def _ws_diary_im_targets(websocket: WebSocket):
    """S71：日记主动推送目标候选 = 运行时活跃 ∪ 各平台已配置行为目标 ∪ 落盘 bot 会话。"""
    try:
        from py.behavior_engine import global_behavior_engine
        from py.get_setting import load_settings
        cfg_src = {
            "wechat": ("wechatBotConfig", "behaviorTargetChatIds"),
            "feishu": ("feishuBotConfig", "behaviorTargetChatIds"),
            "dingtalk": ("dingtalkBotConfig", "behaviorTargetChatIds"),
            "wecom": ("weComBotConfig", "behaviorTargetChatIds"),
            "telegram": ("telegramBotConfig", "behaviorTargetChatIds"),
            "discord": ("discordBotConfig", "behaviorTargetChatIds"),
            "slack": ("slackBotConfig", "behaviorTargetChatIds"),
            "xmpp": ("xmppBotConfig", "behaviorTargetJids"),
        }
        settings_now = await load_settings()
        entries_by_p = {p: {} for p in cfg_src}
        for p, act in (global_behavior_engine.platform_activity or {}).items():
            if p in entries_by_p:
                for cid, ts in (act or {}).items():
                    entries_by_p[p][str(cid)] = {
                        "id": str(cid), "last_active": ts, "source": "activity"}
        for p, (sk, tf) in cfg_src.items():
            for cid in ((settings_now.get(sk) or {}).get(tf) or []):
                entries_by_p[p].setdefault(str(cid), {
                    "id": str(cid), "last_active": None, "source": "config"})
        try:
            from py.get_setting import list_bot_convs
            for row in await list_bot_convs():
                parts = str(row.get("conv_id", "")).split(":", 2)
                if len(parts) == 3 and parts[0] == "bot" and parts[1] in entries_by_p:
                    entries_by_p[parts[1]].setdefault(parts[2], {
                        "id": parts[2], "last_active": row.get("updated_at"),
                        "source": "conv"})
        except Exception as _ce:
            logger.info(f"[WS] diary_im_targets 会话表读取跳过: {_ce}")
        out = {}
        for p, ent in entries_by_p.items():
            lst = list(ent.values())
            main = max((e for e in lst if e.get("last_active")),
                       key=lambda e: e["last_active"], default=None)
            for e in lst:
                e["is_main"] = (main is not None and e["id"] == main["id"])
            out[p] = lst
        await ws_manager.send_json({"type": "diary_im_targets", "targets": out}, websocket)
    except Exception as _te:
        logger.error(f"[WS] get_diary_im_targets 失败: {_te}")
        try:
            await ws_manager.send_json(
                {"type": "diary_im_targets", "targets": {}, "error": str(_te)}, websocket)
        except Exception:
            pass


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    if not sap_auth.ws_auth_ok(websocket):
        await websocket.close(code=4401)
        return
    # 1. 建立连接
    await ws_manager.connect(websocket)
    logging.getLogger("app").info(f"[DEBUG] WebSocket连接建立成功")
    # [状态标记] 为当前连接生成唯一ID并初始化状态
    connection_id = str(shortuuid.ShortUUID().random(length=8))
    logging.getLogger("app").info(f"[DEBUG] 连接ID: {connection_id}")
    has_sent_prompt = False
    has_start_tts = False
    registered_ext_ids = set()
    try:
        # 2. 初始数据推送
        async with settings_lock:
            current_settings = await load_settings()
            # 兼容旧逻辑：将 conversations 移出 settings 独立存储
            if current_settings.get("conversations", None):
                await save_covs({
                    "conversations": current_settings["conversations"],
                    "conversationGroups": current_settings.get("conversationGroups", [])
                })
                del current_settings["conversations"]
                if current_settings.get("conversationGroups", None) is not None:
                    del current_settings["conversationGroups"]
                await save_settings(current_settings)
            
            covs = await load_covs()
            current_settings["conversations"] = covs.get("conversations", [])
            current_settings["conversationGroups"] = covs.get("conversationGroups", [])
        
        await ws_manager.send_json({"type": "settings", "data": current_settings}, websocket)
        
        # 3. 消息处理循环
        while True:
            try:
                # ✨ 核心修复：添加接收超时，防止无限阻塞在已死亡的连接上
                # 超时后主动探测连接是否还活着，避免事件循环饥饿时无法感知断开
                data = await asyncio.wait_for(websocket.receive_json(), timeout=120.0)
            except asyncio.TimeoutError:
                # 客户端长时间没发消息，主动探测连接是否还活着
                try:
                    await ws_manager.send_json({"type": "ping"}, websocket)
                except Exception:
                    logging.getLogger("app").info(f"[WS] Ping probe failed for {connection_id}, connection is dead")
                    break
                continue
            except WebSocketDisconnect as e:
                logging.getLogger("app").info(f"[WS] Client {connection_id} disconnected with code={e.code} reason={e.reason or ''}")
                # 1006 = 异常关闭（无close frame），通常意味着连接被中间代理/网络层切断
                if e.code == 1006:
                    logger.warning(f"[WS] Client {connection_id} 异常断开(1006)，可能原因：心跳超时/事件循环饥饿/网络中断")
                break
            except RuntimeError as e:
                # ✨ 核心修复：捕获"接收已断开连接的消息"错误
                if "receive" in str(e):
                    logging.getLogger("app").info(f"[WS] Client {connection_id} RuntimeError on receive: {e}")
                    break # 退出循环
                raise e # 其他运行时错误继续抛出
            
            msg_type = data.get("type")
            
            # 定期让出控制权，确保事件循环能处理WebSocket ping/pong和心跳
            await asyncio.sleep(0)
            
            if msg_type == "ping":
                await ws_manager.send_json({"type": "pong"}, websocket)

            elif msg_type == "get_diary_im_targets":
                # S71：日记主动推送目标候选（重活在 _ws_diary_im_targets，保 ws 循环壳尺寸）
                await _ws_diary_im_targets(websocket)

            elif msg_type == "live_enqueue":
                # S80(B6/9a30de93): 扩展（如 sap-snack-director）推的请求不直接 sendMessage
                # （会打断播报/isTyping 静默丢），广播给主窗口塞弹幕队列由闸门串行调度
                await ws_manager.broadcast({
                    "type": "live_enqueue",
                    "data": data.get("data", {}) or {}
                }, exclude=websocket)

            elif msg_type == "save_settings":
                # B8(b03e7c0e): 深合并落盘；重活在 _ws_save_settings（保 ws 循环壳尺寸）
                await _ws_save_settings(websocket, data)

            elif msg_type == "save_conversations":
                try:
                    await save_covs(data.get("data", {}))
                except Exception as _save_e:
                    logger.error(f"[WS] save_conversations 失败: {_save_e}")
                    await ws_manager.send_json({
                        "type": "save_error",
                        "correlationId": data.get("correlationId"),
                        "success": False,
                        "error": str(_save_e),
                    }, websocket)
                    continue
                await ws_manager.send_json({
                    "type": "conversations_saved",
                    "correlationId": data.get("correlationId"),
                    "success": True
                }, websocket)

            elif msg_type == "save_conversations_delta":
                # 增量保存：仅 upsert 前端 dirty 的会话，避免每次全量搬运整棵会话树
                payload = data.get("data", {}) or {}
                incoming = [c for c in (payload.get("conversations") or []) if isinstance(c, dict) and c.get("id") is not None]
                covs = await load_covs()
                existing = [c for c in (covs.get("conversations") or []) if isinstance(c, dict)]
                by_id = {str(c.get("id")): c for c in existing}
                fresh = [c for c in incoming if str(c.get("id")) not in by_id]
                for c in incoming:
                    by_id[str(c.get("id"))] = c
                covs["conversations"] = fresh + list(by_id.values())
                if payload.get("conversationGroups") is not None:
                    covs["conversationGroups"] = payload["conversationGroups"]
                await save_covs(covs)
                await ws_manager.send_json({
                    "type": "conversations_delta_saved",
                    "correlationId": data.get("correlationId"),
                    "success": True
                }, websocket)

            elif msg_type == "get_settings":
                settings = await load_settings()
                if settings.get("conversations", None):
                    await save_covs({
                        "conversations": settings["conversations"],
                        "conversationGroups": settings.get("conversationGroups", [])
                    })
                    del settings["conversations"]
                    if settings.get("conversationGroups", None) is not None:
                        del settings["conversationGroups"]
                    await save_settings(settings)
                covs = await load_covs()
                settings["conversations"] = covs.get("conversations", [])
                settings["conversationGroups"] = covs.get("conversationGroups", [])
                await ws_manager.send_json({"type": "settings", "data": settings}, websocket)

            elif msg_type == "save_agent":
                current_settings = await load_settings()
                agent_id = str(shortuuid.ShortUUID().random(length=8))
                config_path = os.path.join(AGENT_DIR, f"{agent_id}.json")
                with open(config_path, 'w', encoding='utf-8') as f:
                    json.dump(current_settings, f, indent=4, ensure_ascii=False)
                
                current_settings['agents'][agent_id] = {
                    "id": agent_id,
                    "name": data['data']['name'],
                    "system_prompt": data['data']['system_prompt'],
                    "config_path": config_path,
                    "enabled": False,
                }
                await save_settings(current_settings)
                await ws_manager.send_json({"type": "settings", "data": current_settings}, websocket)
            
            elif msg_type == "set_user_input":
                user_input = data.get("data", {}).get("text", "")
                # [XMPP Bridge] 透传扩展注入的图片附件（已上传到 uploaded_files，形如 {path, name, type}）
                extension_images = data.get("data", {}).get("images") or []
                await ws_manager.broadcast({
                    "type": "update_user_input",
                    "data": {"text": user_input, "images": extension_images}
                })

            elif msg_type == "set_system_prompt":
                has_sent_prompt = True # 标记该连接发送过 Prompt
                extension_system_prompt = data.get("data", {}).get("text", "")
                await ws_manager.broadcast({
                    "type": "update_system_prompt",
                    "data": {
                        "id": connection_id,
                        "text": extension_system_prompt
                    }
                })

            elif msg_type == "set_tool_input":
                tool_input = data.get("data", {}).get("text", "")
                await ws_manager.broadcast({
                    "type": "update_tool_input",
                    "data": {"text": tool_input}
                })

            elif msg_type == "start_read":
                has_start_tts = True
                read_input = data.get("data", {}).get("text", "")
                await ws_manager.broadcast({
                    "type": "start_tts",
                    "data": {"text": read_input}
                })

            elif msg_type == "stop_read":
                await ws_manager.broadcast({
                    "type": "stop_tts",
                    "data": {}
                })

            elif msg_type == "register_node_extension_mcp":
                ext_id = data.get("data", {}).get("ext_id")
                tools = data.get("data", {}).get("tools", [])
                
                if ext_id and tools:
                    node_ext_mcp_tools[ext_id] = tools
                    registered_ext_ids.add(ext_id)  # 🔥 记录
                    logging.getLogger("app").info(f"[MCP] Node扩展 {ext_id} 注册了 {len(tools)} 个工具")
                    
                    # 通知所有客户端更新工具列表
                    await ws_manager.broadcast({
                        "type": "node_ext_mcp_registered",
                        "data": {
                            "ext_id": ext_id,
                            "tools": tools
                        }
                    })
                    
                    # 可选：返回注册成功消息
                    await websocket.send_json({
                        "type": "mcp_registered",
                        "data": {"ext_id": ext_id, "status": "success"}
                    })

            elif msg_type == "unregister_node_extension_mcp":
                ext_id = data.get("data", {}).get("ext_id")
                if ext_id in node_ext_mcp_tools:
                    del node_ext_mcp_tools[ext_id]
                    registered_ext_ids.discard(ext_id)  # 🔥 移除记录
                    logging.getLogger("app").info(f"[MCP] Node扩展 {ext_id} 已主动注销")
                    
                    await ws_manager.broadcast({
                        "type": "node_ext_mcp_unregistered",
                        "data": {"ext_id": ext_id}
                    })

            elif msg_type == "mcp_tool_result":
                call_id = data.get("data", {}).get("call_id")
                result = data.get("data", {}).get("result")
                
                if call_id in mcp_call_results:
                    mcp_call_results[call_id].set_result(result)

            elif msg_type == "trigger_close_extension":
                await ws_manager.broadcast({"type": "trigger_close_extension", "data": {}})

            elif msg_type == "trigger_send_message":
                await ws_manager.broadcast({"type": "trigger_send_message", "data": {}})
                    
            elif msg_type == "trigger_clear_message":
                await ws_manager.broadcast({"type": "trigger_clear_message", "data": {}})

            elif msg_type == "get_messages":
                await ws_manager.broadcast({"type": "request_messages", "data": {}})

            elif msg_type == "broadcast_messages":
                messages_data = data.get("data", {})
                # 广播给除自己以外的所有人
                await ws_manager.broadcast({
                    "type": "messages_update",
                    "data": messages_data
                }, exclude=websocket)

    except Exception as e:
        logging.getLogger("app").info(f"WebSocket error for {connection_id}: {e}")
    finally:
        for ext_id in registered_ext_ids:
            if ext_id in node_ext_mcp_tools:
                del node_ext_mcp_tools[ext_id]
                logging.getLogger("app").info(f"[MCP] 连接断开，自动清理扩展 {ext_id}")
                
                await ws_manager.broadcast({
                    "type": "node_ext_mcp_unregistered",
                    "data": {"ext_id": ext_id}
                })

        # 4. 断开连接并清理
        ws_manager.disconnect(websocket)
        
        if has_sent_prompt:
            logging.getLogger("app").info(f"Extension {connection_id} disconnected. Removing prompt.")
            await ws_manager.broadcast({
                "type": "remove_system_prompt",
                "data": {"id": connection_id}
            })
            
        if has_start_tts:
            logging.getLogger("app").info(f"Extension {connection_id} disconnected. Stopping tts.")
            await ws_manager.broadcast({
                "type": "stop_tts",
                "data": {}
            })


from py.acpx_tools import check_acpx_available

from py.uv_api import router as uv_router
app.include_router(uv_router)

from py.node_api import router as node_router 
app.include_router(node_router)

from py.docker_api import router as docker_router 
app.include_router(docker_router)

from py.extensions import router as extensions_router

app.include_router(extensions_router)

from py.skills import router as skills_router

app.include_router(skills_router)

from py.sherpa_model_manager import router as sherpa_model_router
app.include_router(sherpa_model_router)

from py.moss_model_manager import router as moss_model_router
app.include_router(moss_model_router)

from py.ebd_model_manager import router as ebd_model_router
app.include_router(ebd_model_router)

from py.minilm_router import router as minilm_router
app.include_router(minilm_router)

from py.ebd_api import router as embedding_router
app.include_router(embedding_router)

from py.affection_api import router as affection_router
app.include_router(affection_router)

mcp = FastApiMCP(
    app,
    name="Agent party MCP - chat with multiple agents",
    include_operations=["get_agents", "chat_with_agent_party"],
)

mcp.mount()

app.mount("/vrm", StaticFiles(directory=DEFAULT_VRM_DIR), name="vrm")
app.mount("/tool_temp", StaticFiles(directory=TOOL_TEMP_DIR), name="tool_temp")
app.mount("/uploaded_files", StaticFiles(directory=UPLOAD_FILES_DIR), name="uploaded_files")
app.mount("/ext", StaticFiles(directory=EXT_DIR), name="ext")
app.mount("/", StaticFiles(directory=os.path.join(base_path, "static"), html=True), name="static")

# 简化main函数
if __name__ == "__main__":
    import uvicorn

    # 格式化显示地址
    display_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST
    
    logging.getLogger("app").info("\n" + "="*50)
    logging.getLogger("app").info(f"🚀 后端服务已启动")
    logging.getLogger("app").info(f"🔗 本地运行地址: http://{display_host}:{PORT}")
    logging.getLogger("app").info(f"📖 API 文档地址: http://{display_host}:{PORT}/docs") # 如果是 FastAPI
    logging.getLogger("app").info("="*50 + "\n")

    # 使用 uvicorn.Config + uvicorn.Server 方式启动，以支持 websocket_ping_interval 等高级参数
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        ws_ping_interval=20,   # 每20秒发送协议级ping，防止连接被静默断开
        ws_ping_timeout=180,   # ping响应超时180秒才断开，给复杂任务的事件循环足够喘息时间（防止1006异常断开）
        ws_max_size=64 * 1024 * 1024,  # 全量会话保存/大历史导入的 WS 消息上限（默认16MiB会被大会话顶爆）
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve())
