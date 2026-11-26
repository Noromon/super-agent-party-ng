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
from py.context_builder import sanitize_tool_chains, sanitize_tool_chains_logged
from py import auth as sap_auth
from py.defaults import DEFAULT_SERVER_PORT, GSV_TTS_URL
from py.guard import load_safety_words, check_content_safety
from py.llm_recovery import (  # S207：瞬断故障恢复
    is_transient_transport_error, llm_retry_cfg, acreate,
    backoff_sleep as llm_backoff, stream_retry_chunk, stream_reset_chunk,
    retry_suffix, attach_retry_note as llm_attach)
from py.token_guard import neutralize as _neutralize, neutralize_deep, apply_eos_guard
from py.tool_registry import PLAN_BLOCKED_TOOLS, SENSITIVE_TOOLS
from py import agent_activity as _agent_activity  # S232：在途请求计数（对话/长任务繁忙信号）
from py import tool_cap as _tool_cap  # S233：工具轮数上限热值（轮边界动态读）
from py.prompt_assembly import (
    AUTO_BEHAVIOR_HINT, DOCKER_ENV_INFO, INFERENCE_THINK_HINT, LATEX_DELIM_HINT,
    STICKER_IMAGE_RULE, TEXT2IMG_IMAGE_RULE, WSL_ENV_INFO,
)
from py.model_params import effective_main_params, effective_role_params  # S206 每模型推理参数

from py.tool_assembly import build_llm_tools

# S120(上游 e03cedb3 同批 guard 族)：内容安全词表装载（无词表文件=自动禁用）
load_safety_words()


def _assemble_toolkit():
    """Toolkit snapshot for build_llm_tools; rebuilt per request so that
    module-level client rebindings (lifespan, MCP reload) are picked up."""
    from py.llm_tool import get_llm_tool
    from py.agent_tool import get_agent_tool
    from py.a2a_tool import get_a2a_tool
    from py.cli_tool import get_tools_for_permission, get_local_tools_for_permission, get_wsl_tools_for_permission
    from py.cli_tool import LOCAL_TOOLS_REGISTRY
    from py.load_files import file_tool, image_tool, analyze_image_tool, review_image_tool, analyze_images_tool, view_images_tool
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
    from py.agent_ext_tools import (LIST_EXTENSIONS_TOOL,  # S323：公告位=schema dict
                                    START_EXTENSION_NODE_TOOL)
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
        "get_wsl_tools_for_permission": get_wsl_tools_for_permission,
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
        "view_images_tool": view_images_tool,  # S243: 一手视觉
        "analyze_image_tool": analyze_image_tool,
        "review_image_tool": review_image_tool,
        "analyze_images_tool": analyze_images_tool,
        "auto_behavior_tool": auto_behavior_tool,
        "e2b_code_tool": e2b_code_tool,
        "local_run_code_tool": local_run_code_tool,
        # S210/S211：S209 恒定公告依赖此键（缺键=CLI 关/acp 每条消息 KeyError→500；
        # 绑成函数本体=公告位混入 callable→json.dumps TypeError，两事故均实证）。
        # 公告位值必须是 schema dict；执行层绑 callable 在 _TOOL_HOOKS。契约钉见 test_tool_assembly_parity
        "read_skill_tool_local": LOCAL_TOOLS_REGISTRY["read_skill_local"],
        "list_extensions_tool": LIST_EXTENSIONS_TOOL,               # S323(B)
        "start_extension_node_tool": START_EXTENSION_NODE_TOOL,     # S323(C)
    }

from py.tool_loop import (NONE_TEXT, TOOL_EXC_TMPL,
                        arg_error_text, append_missing_results)
from py.tool_spiral import SpiralWatch  # S296：相似调用绕圈熔断
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
from py import boot_utils  # S299：端口绑定/mac 环境/ONNX DLL（逐字搬移，执行序：本行必须先于模块级调用）





# 执行端口查找
FINAL_PORT = boot_utils.force_bind_or_fallback(HOST, PREFERED_PORT)
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

    
    # (可选) 打印调试信息
    # print(f"Fixed macOS PATH. Added: {paths_to_add}")

# --- 在程序最开始的地方调用这个函数 ---
boot_utils.fix_macos_environment()


boot_utils._fix_onnx_dll()

# 在程序最开始设置
if hasattr(sys, '_MEIPASS'):
    # 打包后的程序
    os.environ['PYTHONPATH'] = sys._MEIPASS
    os.environ['PATH'] = sys._MEIPASS + os.pathsep + os.environ.get('PATH', '')
import asyncio
import contextvars
import copy
from functools import partial

# 用于在工具调用时传递当前对话上下文（特别是 secondhand_review_image 工具需要）
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

from py.get_setting import EXT_DIR, IS_DOCKER, SKILLS_DIR, _copy_default_skills, convert_to_opus_simple, deep_update, load_covs, load_settings, save_covs,save_settings,clean_temp_files_task,base_path,configure_host_port,UPLOAD_FILES_DIR,AGENT_DIR,MEMORY_CACHE_DIR,KB_DIR,DEFAULT_VRM_DIR,USER_DATA_DIR,LOG_DIR,TOOL_TEMP_DIR,COVS_PATH,DEFAULT_THA_DIR,DEFAULT_SOULX_IMAGES_DIR,_SETTINGS_RMW_LOCK
from py.llm_tool import get_image_base64,get_image_media_type
from py.vision_tools import (get_image_content, analyze_image, analyze_images, _image_magic_ok,  # noqa: F401
                             _strip_image_parts_from_messages, view_images, review_image,  # S299：视觉域逐字搬移
                             message_without_images, images_in_messages, images_add_in_messages,
                             _attach_screen_image_for_behavior)
from py.tool_dispatch import (_APPROVAL_PREFIX, _approval_payload,
                              _is_approval_result, pending_approval_at_tail)
from py.ask_flow import is_ask_result as ask_flow_is_ask_result
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
screen_watcher_task = None
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
from py.image_draw import draw_grid_on_image, draw_action_feedback, scale_to_fit  # noqa: F401  # S299：网格/动作绘制/缩放适配（逐字搬移；_stream_desktop_capture/_stream_regrab 引用名）
import io
if platform.system() == "Windows":
    try:
        # 设置 DPI 感知，确保截屏尺寸和 size() 返回的一致
        ctypes.windll.shcore.SetProcessDpiAwareness(1) 
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()









configure_host_port(args.host, args.port)

from py.msg_utils import (_get_target_message, content_append,  # noqa: F401  # S300：消息工具逐字搬移（tools_change_messages/群记忆/提示词域共用）
                      content_prepend, content_replace, content_new,
                      _extract_text_content)

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
async def _t10_shutdown(temp_sweep_task, tool_output_task=None):
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
    if tool_output_task is not None:  # S184
        tool_output_task.cancel()


async def _temp_sweep_loop():
    """T-10：tool_temp/桌面截图等临时目录的周期清扫（原仅启动一次）。"""
    while True:
        await asyncio.sleep(24 * 3600)
        try:
            await clean_temp_files_task()
        except Exception as e:
            logging.getLogger("app").warning(f"T-10 周期临时目录清扫失败: {e}")


async def _tool_output_sweep_task(first_run):
    """S184：.agent/tool_output 周期清理。mtime 判龄天然跨重启；启动即扫一次，
    此后每日一次。retentionDays=0 → 关闭自动清理（手动清理端点不受影响）。"""
    while True:
        try:
            if first_run:
                await asyncio.sleep(30)  # 让初始化先走
            else:
                await asyncio.sleep(24 * 3600)
            from py import tool_output_store as _tos
            from py.get_setting import load_settings
            files, size, ws_n = await asyncio.to_thread(_tos.cleanup_all, await load_settings())
            if files:
                logging.getLogger("app").info(
                    "[ToolOutput] 周期清理: %d 个文件 / %.1f MB（扫描 %d 个工作区）",
                    files, size / 1048576.0, ws_n)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logging.getLogger("app").warning(f"[ToolOutput] 周期清理失败: {e}")
        finally:
            first_run = False


def _notify_center_startup():
    """S151：通知中心绑定 uvicorn 主 loop（ws 广播桥）并发射启动事件。"""
    from py import notification_center as _notifc
    _notifc.bind_loop(asyncio.get_running_loop())
    _notifc.emit("system", "后端启动完成")


def _boot_background_engines(settings):
    """M3(S215)：日记+旁观者后台引擎启动（自 lifespan 抽出，保持 lifespan 只减不涨）。
    循环常驻、未启用时空转；保存设置经 update_config 热更新。返回 (diary, watcher) task。"""
    diary_task = watcher_task = None
    try:
        # S222：island HUD 行为频道注册（本地伪平台恒可用，幂等覆盖安全）
        from py.island_channel import register_island_channel
        register_island_channel()
    except Exception as e:
        logging.getLogger("app").error(f"IslandHUD 频道注册异常: {e}")
    try:
        from py.diary_engine import global_diary_engine
        global_diary_engine.update_config((settings or {}).get("diarySettings"))
        diary_task = asyncio.create_task(global_diary_engine.start())
    except Exception as e:
        logging.getLogger("app").error(f"日记引擎启动异常: {e}")
    try:
        from py.screen_watcher import global_screen_watcher
        global_screen_watcher.update_config((settings or {}).get("screenWatchSettings"))
        watcher_task = asyncio.create_task(global_screen_watcher.start())
    except Exception as e:
        logging.getLogger("app").error(f"旁观引擎启动异常: {e}")
    return diary_task, watcher_task


def _shutdown_background_engines(diary_task, watcher_task):
    """M3(S215)：日记+旁观者后台引擎停止（自 lifespan 抽出，保持 lifespan 只减不涨）。"""
    try:
        if diary_task:
            from py.diary_engine import global_diary_engine
            global_diary_engine.stop()
            diary_task.cancel()
    except Exception as e:
        logging.getLogger("app").info(f"日记引擎停止异常: {e}")
    try:
        if watcher_task:
            from py.screen_watcher import global_screen_watcher
            global_screen_watcher.stop()
            watcher_task.cancel()
    except Exception as e:
        logging.getLogger("app").info(f"旁观引擎停止异常: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sap_auth.write_token_file(USER_DATA_DIR)
    sap_auth.ensure_machine_token(USER_DATA_DIR)
    # M5：外联 API（/v1 /mcp）免 token 开关初始态；后续随 save_settings 刷新
    await _sync_external_api_token_flag()
    # S233：工具轮数上限/破限开关初始态（重启后破限须随已存设置恢复）；后续随 save_settings 刷新
    try:
        from py import get_setting as _gs
        _tool_cap.apply_setting(await _gs.load_settings())
    except Exception as _tc_boot_e:
        logging.getLogger("app").info(f"[S233] 工具上限热值初始化失败(用默认): {_tc_boot_e}")
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
    temp_sweep_task, tool_output_task = asyncio.create_task(_temp_sweep_loop()), asyncio.create_task(_tool_output_sweep_task(first_run=True))  # T-10 | S184
    
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
    global settings, client, reasoner_client, fast_client, local_timezone, logger, locales, scheduler_task, sleep_guard, diary_engine_task, screen_watcher_task
    _, _, locales, settings, local_timezone = results

    # S267: backupIncludeUploads 旧默认残留迁移（一次性；标记落库后尊重用户显式选择）
    await _migrate_backup_uploads_flag_s267(settings)
    
    # --- [M4-lite: 启动数据快照（滚动5份、1h 节流、失败不阻塞启动）] ---
    async def _startup_snapshot():
        try:
            from py.data_backup import BACKUP_ITEM_IDS, snapshot_data_dir
            # S280: 自动备份构成 = systemSettings.backupAutoItems；未配置时按旧开关
            # backupIncludeUploads 推导（False→排除上传文件），缺省全选（S267 语义延续）
            _s = settings or {}
            _auto = ((_s.get("systemSettings") or {}).get("backupAutoItems"))
            if _auto is None:
                _auto = _s.get("backupAutoItems")
            include = [x for x in (_auto or []) if x in BACKUP_ITEM_IDS]
            if not include:
                _raw_inc = ((_s.get("systemSettings") or {}).get("backupIncludeUploads"))
                if _raw_inc is None:
                    _raw_inc = _s.get("backupIncludeUploads")
                inc_up = bool(_raw_inc) if _raw_inc is not None else True
                include = list(BACKUP_ITEM_IDS) if inc_up else [x for x in BACKUP_ITEM_IDS if x != "uploads"]
            res = await asyncio.to_thread(snapshot_data_dir, USER_DATA_DIR, 5, True,
                                          3600.0, None, "auto", include)
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

    # --- [后台引擎：日记 + S215 旁观者] ---
    diary_engine_task, screen_watcher_task = _boot_background_engines(settings)

    # --- [日志系统初始化] ---
    from py.log_setup import setup_logger
    logger = setup_logger(LOG_DIR)
    logger.info("===== 日志系统初始化成功 =====\n[Version] " + _version_fingerprint())

    # --- [代理与 HTTP 客户端初始化] ---
    proxy_url = None

    if settings:
        isChinaProxy = settings.get("systemSettings", {}).get("isChinaProxy", False)

        # S85-D：normalize 容错——代理栏任何形态（http/socks5h/裸host:port/垃圾）
        # 都只会得到 None+warning，永不炸启动；env 兜底让全部 SDK 同步生效
        # S239：三模式统一走 active_proxy（manual/system 探测/旧库兼容/none=None），
        # httpx 出口改为显式 transport，不再依赖 trust_env（与热 swap 同一通道）
        from py.proxy_util import active_proxy, apply_env_proxy
        proxy_url = active_proxy(settings)
        apply_env_proxy(settings)
        _announce_agent_proxy(settings)  # S236：启动即下发 agent-proxy 分区代理
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
            timeout=timeout_config, transport=_build_proxy_transport(proxy_url),
            trust_env=False)
    except Exception as _px_e:  # S85-D：socks 依赖缺失等 → 降级直连，绝不阻断启动
        logger.error(f"HTTP 客户端带代理初始化失败（{_px_e}），已降级为直连")
        app_state.global_http_client = httpx.AsyncClient(
            timeout=timeout_config, transport=_build_proxy_transport(),
            trust_env=False)

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
                    await asyncio.to_thread(getattr(BotContainer, getter_map[cfg_key])().start_bot, cfg_cls(**raw))
                    logger.info(f"IM 自动连接成功: {cfg_key}")
                except Exception as e:
                    logger.warning(f"IM 自动连接失败 {cfg_key}: {e}")
            asyncio.create_task(_boot())

    asyncio.create_task(autostart_im_bots())

    # --- [T-4 流缓存 TTL 清扫] ---
    stream_ttl_task = asyncio.create_task(_stream_ttl_loop())

    _notify_center_startup()  # S151：通知中心主 loop 绑定（ws 广播桥）+ 启动事件
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
    _shutdown_background_engines(diary_engine_task, screen_watcher_task)
    ext_ids = list(node_mgr.exts.keys())
    for ext_id in ext_ids:
        try: await node_mgr.stop(ext_id)
        except: pass
        
    await _t10_shutdown(temp_sweep_task, tool_output_task)
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
    _active_streams, _active_streams_lock, _current_stream_entry,
    _st_cancelled, _stream_producer_wrapper, _stream_consumer_generator,
    _stream_ttl_loop, _cleanup_stream,
)

from py import interject as _interject  # S188：插话队列（轮边界注入/审批挂起区）

# S185：审批执行一次性消费幂等表（锁内读写；FIFO 截断防无界增长）
_approval_exec_once: set = set()
_approval_exec_once_lock = asyncio.Lock()


def _approval_prune_locked():
    """锁内调用：幂等表超限时截断保留最近条目（防无界增长）。"""
    global _approval_exec_once
    _approval_exec_once = set(list(_approval_exec_once)[-400:])


async def _approval_exec_dedup(stream_id, tool_name, tool_params, approval_type):
    """S185：审批执行一次性消费——同流/同工具/同参数批复只执行一次；
    重复请求返回幂等提示 dict，首次返回 None（放行）。锁内读写，FIFO 截断。"""
    import hashlib as _hl
    _exec_key = _hl.sha256(("|".join([
        str(stream_id or ""), str(tool_name or ""),
        json.dumps(tool_params if tool_params is not None else {},
                   sort_keys=True, ensure_ascii=False, default=str),
        str(approval_type or "")])).encode("utf-8")).hexdigest()[:32]
    async with _approval_exec_once_lock:
        if _exec_key in _approval_exec_once:
            logging.getLogger("app").warning(
                "[S185] 重复批复请求已幂等吞掉（未重复执行）: %s stream=%s",
                tool_name, (stream_id or "-")[:8])
            return {"result": "[已处理] 该批复的执行请求已消费完毕，请勿重复提交。"}
        _approval_exec_once.add(_exec_key)
        if len(_approval_exec_once) > 500:
            _approval_prune_locked()
    return None


from py.tool_call_guard import neutralize_leaked_blocks as _tcg_neutralize
from py.routers import (media, bots, memories, system, files,
                        bot_conversations, tasks, agents, workflows,
                        status, notifications, transfer, permissions)
app.include_router(permissions.router)  # S324：授权管理面板（总是允许白名单存/取）
app.include_router(notifications.router)  # S151：通知中心
app.include_router(transfer.router)  # S161：记忆/日记导入导出
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
from py.routers.tha import router as tha_router  # S91(THA)：/tha_* 端点 + /ws/tha
app.include_router(tha_router)
from py.routers.soulx import router as soulx_router  # S136(SoulX)：/soulx_* 端点 + /ws/soulx
app.include_router(soulx_router)
from py.routers.island import notify_island_reply_done, router as island_router  # S139(R6)：/api/heatmap|weather|ip-city|geocode + /cur_language
from py.routers.island import _ws_island  # S139(R6)：island_* ws 消息卸载（S71 惯例）
app.include_router(island_router)
from py.routers.peers import router as peers_router  # S145：/api/peers-seen
app.include_router(peers_router)
from py.peer_identity import build_peer_identity_block, display_name, record_seen, resolve_entry  # S145：对端身份注入
from py.diary_api import router as diary_router  # A5：/api/diary/*（book CRUD + 查询）
app.include_router(diary_router)
from py.routers.eos_guard import router as eos_guard_router  # S160：/api/eos_guard/*（潜龙勿用面板）
app.include_router(eos_guard_router)

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

# ── S120(上游 e03cedb3) 前端静态资源内容版本号注入 ────────────────────────────
# 原理：HTML 始终 no-cache（每次重新校验），其中引用的 js/css/图片 统一改写为
#       "path.ext?v=<内容md5前8位>"。文件没变 → hash 不变 → URL 不变 → 缓存命中秒开；
#       文件变了 → hash 变 → URL 变 → 旧缓存自动作废 → 必然加载新代码（无需强刷）。
# 配套前端 static/sw.js（sap-cache-v2）对带 ?v= 的资源采用 cache-first。
_ASSET_VERSION_CACHE = {}   # 文件绝对路径 -> (mtime_ns, hash)
# S123: TTFB 分段锚点——中间件 recv 时刻下传（call_next 前的 set 可被内层
# task 继承），端点/流响应入口各自发声一行，把 assemble 静默段剥细。
_TTFB_T0 = contextvars.ContextVar("_ttfb_t0", default=None)
_ASSET_VERSION_RE = re.compile(r'(src|href)="([^"]+?\.(?:css|js|png|jpe?g|svg|gif|webp|ico|woff2?|ttf|eot|mp4|webm))([^"]*)"')


def _asset_version_hash(base_dir, url):
    if url.startswith(('http:', 'https:', '//', 'data:')):
        return ''
    clean = url.split('?', 1)[0].lstrip('/')
    if not clean:
        return ''
    fp = os.path.normpath(os.path.join(base_dir, clean.replace('/', os.sep)))
    if not fp.startswith(os.path.normpath(base_dir) + os.sep):
        return ''
    try:
        if not os.path.isfile(fp):
            return ''
        st = os.stat(fp)
    except OSError:
        return ''
    cached = _ASSET_VERSION_CACHE.get(fp)
    if cached and cached[0] == st.st_mtime_ns:
        return cached[1]
    try:
        with open(fp, 'rb') as f:
            h = hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        return ''
    _ASSET_VERSION_CACHE[fp] = (st.st_mtime_ns, h)
    return h


_UI_BUILD = None


def _ui_build_stamp():
    """S327: static 内容指纹（文件路径+mtime），首个 HTML 响应时懒算一次。
    前端任何文件变更 → 指纹必变 → 用户肉眼即可判断窗口加载的是哪版前端。"""
    global _UI_BUILD
    if _UI_BUILD is None:
        base = os.path.join(base_path, "static")
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
        stamp = time.strftime("%Y%m%d-%H%M", time.gmtime(latest / 1e9)) if latest else "0"
        _UI_BUILD = f"{stamp}-n{n}-{h.hexdigest()[:8]}"
    return _UI_BUILD


@app.middleware("http")
async def inject_asset_versions(request: Request, call_next):
    _tt0 = time.monotonic()
    if request.url.path.endswith("/chat/completions"):
        _TTFB_T0.set(_tt0)
    response = await call_next(request)
    ctype = response.headers.get("content-type", "")
    # S121: TTFB 分账哨兵——assemble=请求进入→响应头（含入站/组装/记忆检索），
    # first-chunk=响应头→LLM 首块（≈prefill）。仅 chat/completions SSE。
    if "text/event-stream" in ctype and request.url.path.endswith("/chat/completions"):
        _t1 = time.monotonic()
        _orig_iter = response.body_iterator
        _st = {"done": False}

        async def _ttfb_tap():
            async for _c in _orig_iter:
                if not _st["done"]:
                    _st["done"] = True
                    logging.getLogger("app").info(
                        f"[TTFBbrk] assemble={int((_t1 - _tt0) * 1000)}ms "
                        f"to-first-chunk={int((time.monotonic() - _t1) * 1000)}ms")
                yield _c
        response.body_iterator = _ttfb_tap()
        return response
    if "text/html" not in ctype:
        return response
    # 扩展/上传/临时/模型等挂载点下的 HTML 不做版本化处理
    if request.url.path.startswith(("/ext", "/uploaded_files", "/tool_temp", "/vrm", "/tha_models")):
        return response
    body = b""
    async for chunk in response.body_iterator:
        body += chunk
    body_str = body.decode("utf-8")
    base_dir = os.path.join(base_path, "static")

    def _repl(m):
        url = m.group(2)
        h = _asset_version_hash(base_dir, url)
        if not h:
            return m.group(0)
        sep = '&' if '?' in m.group(3) else '?'
        return f'{m.group(1)}="{url}{sep}v={h}"'

    new_str = _ASSET_VERSION_RE.sub(_repl, body_str)
    # S327: 注入 UI 构建指纹（与 renderer [Probe] 日志、页面可见文本三处自证）
    if "__UI_BUILD" not in new_str:
        _tag = f'<script>window.__UI_BUILD="{_ui_build_stamp()}";</script>'
        _i = new_str.lower().find("<head>")
        new_str = (new_str[:_i + 6] + _tag + new_str[_i + 6:]) if _i >= 0 else (_tag + new_str)
    headers = dict(response.headers)
    headers.pop("content-length", None)
    headers["Cache-Control"] = "no-cache"
    return HTMLResponse(content=new_str, status_code=response.status_code, headers=headers)

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
from py.tool_hooks import (execute_tool, call_node_extension_tool,  # S301：工具钩子域逐字搬移
                        _build_tool_hooks, _plan_mode_block, _sensitive_approval,
                        _approval_precheck, _pending_approval_reply_dict,
                        _im_approval_hangup, _invoke_tool_hook, dispatch_tool)  # noqa: F401
async_tools = {}
async_tools_lock = asyncio.Lock()












# 存储等待中的MCP调用结果
mcp_call_results: Dict[str, asyncio.Future] = {}






















from py.group_memory import (_memory_tokens, _normalize_memory_text, _normalize_entity_id,  # noqa: F401
                         _merge_group_memories, _load_group_map, _fetch_group_memories,
                         _build_group_memory_prompt, _trim_request_messages,  # S300：群记忆域逐字搬移
                         _apply_group_memory_context, _extract_group_memories,
                         _upsert_group_memories, _invalidate_group_memories_by_chat,
                         _invalidate_group_memories_by_group, _invalidate_all_group_memories)

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
    behavior_trigger: bool = False  # S203：IM 行为/主动外发轮（ns 通道原样送文本，强制无工具+尸块中和）
    sanitize_plain_output: bool = False  # S204：输出会被原样归档/转达的自动化轮（diary 等）——正文尸块剥除兜底
    is_sub_agent: bool = False
    is_quarantined: bool = False  # S160：受污染话题会话——跳过 mem0/日记/总结等一切持久化写入，保留读侧
    recall_query: str = None
    enable_tools : List[str] = None
    disable_tools: List[str] = None
    conversation_id: Optional[Union[str, int, float]] = None
    group_id: Optional[Union[str, int, float]] = None
    user_message_id: Optional[Union[str, int, float]] = None
    peer_id: Optional[str] = None  # S145：bot 频道对端平台 id（xmpp jid 等），身份注入用
    screen_image: Optional[str] = None  # S225：旁观发言附截图（jpeg base64，无 data: 前缀）；仅行为轮附帧经 extra_body 透传，中央注入本次模型调用消息，不入库/落盘


















def _append_note(content, note: str):
    """Append a text note to str-or-list message content.
    Caution: list += str would splat the string character-by-character."""
    if isinstance(content, list):
        return content + [{"type": "text", "text": note}]
    return content + note














            # --- (2) 处理 '/' : 由 _inject_triggered_skill 承担（S209：与 CLI 总开关解绑）---





























from py.prompt_builders import (read_todos_local, read_agents_md, get_system_context,  # noqa: F401
                              get_project_skills_summary, _inject_workspace_memory,
                              _resolve_skill_dir, _inject_triggered_skill,
                              _append_permission_mode_message, _append_todos_context,
                              _append_agents_md, _append_project_skills, _resolve_agent_name,
                              _append_tts_voice_prompts, _append_avatar_prompts, _append_tha_prompt,
                              _append_affection_prompt, _append_a2ui_prompt, _inject_screen_context,
                              _inject_task_checkpoint, _append_browser_rules)  # S300：提示词装配域逐字搬移 / S319：浏览器先验规矩

async def tools_change_messages(request: ChatRequest, settings: dict):
    # S194：web 主对话答案拦截——本会话有挂起提问卡时，本条消息即答案，
    # 就地替换哨兵后原位续跑（bot 重放不受影响）
    try:
        from py import ask_flow
        await ask_flow.web_resolve_incoming(request)
    except Exception as _ask_e:
        logging.getLogger("app").info(f"[Ask] web 答案拦截异常（跳过）: {_ask_e!r}")
    # S150：模型面人话化——历史中残留的审批哨兵 JSON 换成人类可读说明
    # （事故根因之一：哨兵原文随历史回灌诱发本地底模泄漏漂移；
    # 前端审批卡嗅探的是实时流帧，不经过此处，不受影响）
    try:
        from py import approval_im
        approval_im.sanitize_incoming(request.messages)
    except Exception:
        pass

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
    elif engine == "wsl":
        env_settings = settings.get("wslSettings", {})
    else:
        env_settings = settings.get("acpSettings", {})

    permissionMode = cli_permission_mode_for(settings)
    
    if cwd and Path(cwd).exists() and cli_settings.get("enabled", False):
        
        await _inject_workspace_memory(request, cwd, cli_settings)

    # S209：/<skill> 只认 shortcut 双开关、与 CLI.enabled 解绑（CLI 关=无工作区仅全局）
    await _inject_triggered_skill(request, cwd, cli_settings)

    if request.is_app_bot and request.platform and request.platform != "diary":
        # S145：对端名录——来源行升级（别名+ID）+ 身份/名录注入 + seen 登记
        # S165：diary 独处书写非对话语境，「用户正在使用 diary 软件与你交流」
        # 与日记引擎「用户并没有主动与你说话」正面矛盾（认知扭曲源头），整块跳过
        _pid = request.peer_id
        _peer_ent = resolve_entry(request.platform, _pid, settings) if _pid else None
        if _peer_ent:
            platform_message = f"\n\n用户正在使用 {request.platform} 软件与你交流（当前对端：{display_name(request.platform, _pid, settings)} <{_pid}>）\n\n"
        else:
            platform_message = f"\n\n用户正在使用 {request.platform} 软件与你交流\n\n"
        content_append(request.messages, 'system', platform_message)
        if _pid:
            record_seen(request.platform, _pid)
            _blk = build_peer_identity_block(request.platform, _pid, settings)
            if _blk:
                content_append(request.messages, 'system', _blk)

    if cwd and Path(cwd).exists() and cli_settings.get("enabled", False):
        _append_permission_mode_message(request, permissionMode)

    if permissionMode == "cowork" and not request.is_sub_agent:
        if cwd and Path(cwd).exists() and cli_settings.get("enabled", False) and engine in ["ds", "local", "wsl"]:
            sub_task_context = await query_task_progress(cwd)
            content_append(request.messages, 'system', sub_task_context)
    elif cwd and Path(cwd).exists() and cli_settings.get("enabled", False) and engine in ["ds", "local", "wsl"]:
        
        if engine == "local":
            # 在本地环境下，首先注入系统环境信息
            system_context = get_system_context(cwd=cwd)
            content_append(request.messages, 'system', system_context)
        elif engine == "ds":
            # 在 Docker 环境下，注入系统环境信息
            system_context = DOCKER_ENV_INFO
            content_append(request.messages, 'system', system_context)
        elif engine == "wsl":
            # 在 WSL 环境下，注入 Linux (WSL2) 环境信息（S132/A13）
            system_context_wsl = WSL_ENV_INFO
            content_append(request.messages, 'system', system_context_wsl)

        await _append_todos_context(request, cwd)

        await _append_agents_md(request, cwd)

    # S209：技能索引与 CLI/engine 门槛解绑——全局块恒定，工作区块=cwd 存在+CLI 开
    await _append_project_skills(request, cwd, cli_settings, visibilityScope)

    if request.messages[-1]['role'] == 'system' and settings['tools']['autoBehavior']['enabled'] and not request.is_app_bot and not request.is_sub_agent:
        language_message = AUTO_BEHAVIOR_HINT
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
        inference_message = INFERENCE_THINK_HINT
        content_prepend(request.messages, 'user', f"{inference_message}\n\n用户：")
    if settings['tools']['formula']['enabled']:
        latex_message = LATEX_DELIM_HINT
        content_append(request.messages, 'system', latex_message)
    if settings['tools']['language']['enabled']:
        language_message = f"请使用{settings['tools']['language']['language']}语言说话！，不要使用其他语言，语气风格为{settings['tools']['language']['tone']}\n\n"
        content_append(request.messages, 'system', language_message)
    if settings["stickerPacks"]:
        for stickerPack in settings["stickerPacks"]:
            if stickerPack["enabled"]:
                sticker_message = f"\n\n图片库名称：{stickerPack['name']}，包含的图片：{json.dumps(stickerPack['stickers'])}\n\n"
                content_append(request.messages, 'system', sticker_message)
        content_append(request.messages, 'system', STICKER_IMAGE_RULE)
    if settings['text2imgSettings']['enabled']:
        text2img_messages = TEXT2IMG_IMAGE_RULE
        content_append(request.messages, 'system', text2img_messages)
    _append_avatar_prompts(request, settings)
    _append_tha_prompt(request, settings)  # S91(THA)
    await _append_affection_prompt(request, settings)
    # ==================== 好感度系统注入结束 ====================

    _append_a2ui_prompt(request)
    _append_browser_rules(request, settings)  # S319：内置浏览器「接口优先」先验规矩（stream/complete 汇流单点，每轮一次）
    # S323(A)：宿主 API base + 已装扩展摘要——根治「拿 Electron UI 口当 API 口→404→
    # 误诊框架没挂载」与「扩展对 agent 完全不可见」。失败静默跳过，不断主流程。
    try:
        from py.agent_ext_tools import build_host_context
        # S324：关闭态扩展仅对「允许AI主动拉起」开启者可见（settings 本轮已在手，零额外 IO）
        _acc = settings.get("extensionAgentAccess")
        _host_ctx = build_host_context(_acc if isinstance(_acc, dict) else {})
        if _host_ctx:
            content_append(request.messages, 'system', _host_ctx)
    except Exception as _hce:
        logging.getLogger("app").info("[S323] 宿主环境注入跳过: %r", _hce)

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

# S302a：流式域逐字搬移——re-export 保 server 面兼容（import-server 测试/延迟调用方）
from py.stream_prep import (  # noqa: F401
    get_drs_stage, get_drs_stage_name, get_drs_stage_system_message, get_role, get_tcs, _ARG_SHELL_KEYS,
    _unwrap_arg_shell, _merge_tool_delta, parse_tool_arguments, truncate_tool_result, _tcg_display_slice, _robust_cfg, _tool_notice_chunk, _approval_pending_event_chunk, _ask_pending_event_chunk, GATE_MAX, _gate_note_text, _anchor_note_text, _todo_open_items, _stream_anchor_inject, _ask_channel, _ask_tool_handle, _stream_ask_hang, _stream_im_approval_hang,
    _stream_gate_check, _stream_first_round_leak_note, RESUME_NUDGE_TEXT, append_resume_nudge, ensure_thinking_fields, _cm_context_enabled, _write_context_state, _run_context_pipeline, _boundary_l1_recheck, _bound_tool_output, _bound_tool_output_async, _apply_ctx_guardrail, _breakdown_tokens, _stream_desktop_capture, _stream_context_compress, _stream_character_context, _stream_async_tools, _stream_kb_before, _stream_web_search_pre, _stream_filter_tools, _stream_deepsearch_pre, _stream_reasoner_prep)
from py.stream_engine import (  # noqa: F401
    _stream_first_pass, _stream_drs_round, _stream_round_compress, _notify_web_approval_pending, _stream_first_round_with_recovery, _stream_second_round, _todo_stats_event_chunk, _spiral_observe, _spiral_drain, _stream_tool_round, _stream_reasoner_update, _stream_regrab,
    _BROWSER_VISION_TOOLS, _collect_new_vision_requests, _collect_new_browser_screenshots, _maybe_inject_browser_vision, _stream_loop_pass, _stream_drs_loop_round, _stream_usage_event, _stream_finalize_jobs, _append_loopcap_hint, _drs_round_cap, SAFETY_REPLACEMENT_TEXT, _stream_final_guard)



# =========================================================================
# 第二阶段：强制合法性清洗 (Sanitizer) - 无论是否压缩都必须执行
# 目标：彻底杜绝 Messages with role 'tool' must be a response... 报错
# =========================================================================









def cli_permission_mode_for(settings: dict) -> str:
    """读取当前 CLI 引擎对应的权限模式（值域已归一化）
    S153: 逻辑平移至 py.path_scope.permission_mode_for，此处委托保持既有调用点。"""
    from py.path_scope import permission_mode_for
    return permission_mode_for(settings)



































# =========================================================================
# 第三阶段：思考模式字段填充 (Thinking Mode Sanitizer)
# 目标：防止 "reasoning_content must be passed back" 错误
# 策略：为所有 assistant 消息添加 reasoning_content: ""
# =========================================================================













async def _migrate_backup_uploads_flag_s267(settings):
    """S267: backupIncludeUploads 旧默认残留一次性迁移——S267 前该键不存在，前端
    data 默认 false 随任意设置保存写入 db（并非用户显式关）。仅此一次翻 true 让
    用户资产入快照；标记落库后永远尊重用户显式选择。"""
    try:
        ss = (settings or {}).setdefault("systemSettings", {})
        if ss.get("backupIncludeUploads") is False and not ss.get("backupUploadsS267Migrated"):
            ss["backupIncludeUploads"] = True
            ss["backupUploadsS267Migrated"] = True
            from py.get_setting import save_settings
            await save_settings(settings)
            logging.info("[S267] backupIncludeUploads 旧默认 false 已迁移为 true（快照纳入 uploaded_files）")
    except Exception as e:
        logging.warning("[S267] backupIncludeUploads 迁移失败: %r", e)







































































# S304：响应装配/批复执行域逐字搬移——re-export 保 server 面兼容
from py.approval_exec import execute_approved_tool  # noqa: F401
from py.complete_engine import _generate_complete_impl  # noqa: F401
from py.stream_response import (  # noqa: F401
    generate_stream_response, stream_generator)



async def generate_complete_response(*args, **kwargs):
    """T-8/T-5: complete 路径统一闸门+取消围栏入口层（与 stream 共用
    _active_streams/cancel 端点/llm_gate 基建）。实现体在 _generate_complete_impl。"""
    # S185：与 stream 入口同构的审批尾卫兵——历史尾部=未批复审批哨兵 →
    # 静止态直接回执，不进模型（掐灭审批未决期间的重放推理/拥塞）。
    try:
        _req = args[2] if len(args) > 2 else kwargs.get("request")
        _msgs = getattr(_req, "messages", None)
        _ap_tail = pending_approval_at_tail(_msgs)
        if _ap_tail is not None:
            logging.getLogger("app").warning(
                "[S185] complete 入口检出未批复审批尾部，静止态回执（不进模型）: %s",
                _ap_tail.get("tool_name", "?"))
            return JSONResponse(content=_pending_approval_reply_dict(
                _ap_tail, getattr(_req, "model", "")))
    except Exception as _ape:
        logging.getLogger("app").warning("[S185] complete 审批尾卫兵异常（放行原流程）: %r", _ape)
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



# S303：complete 引擎域逐字搬移——re-export 保 server 面兼容
from py.complete_engine import (  # noqa: F401
    _apply_context_compression, _diary_recall_sample,
    _complete_character_context, _complete_web_search_setup,
    _complete_reasoner_prep, _complete_drs_step, _spiral_observe_ns,
    _spiral_drain_ns, _ns_tool_round, _ns_reasoner_pass,
    _complete_finalize, _ns_behavior_sanitize)




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
    static_fp = "-"
    try:
        import hashlib
        rp = os.path.join(root, "static", "js", "renderer.js")
        st = os.stat(rp)
        with open(rp, "rb") as _f:
            h = hashlib.sha1(_f.read()).hexdigest()[:8]
        static_fp = (f" renderer={time.strftime('%m-%d %H:%M', time.localtime(st.st_mtime))}"
                     f"+{st.st_size}+{h}")
    except Exception:
        pass
    return f"tree={root} HEAD={head}{dirty} server.py-mtime={mtime}{static_fp}"


















def _role_param(settings, role_key, key):
    """S206：角色参数有效值（模型卡片覆盖 > 角色默认）。"""
    eff = effective_role_params(settings, settings.get(role_key) or {})
    v = eff.get(key)
    if v is None:
        return (settings.get(role_key) or {}).get(key)
    return v


def _main_param(settings, key):
    """S206：主角色参数有效值（模型卡片覆盖 > 角色默认）。"""
    return effective_main_params(settings).get(key)


def _inject_tool_discipline(request, tools):
    """S204：工具纪律+能力索引按本轮有效声明集注入（不受 CLISettings 开关支配；
    授权链 enable_tools→tools 参数不动，此处只让提示词跟随能力世界）。"""
    try:
        from py.tool_discipline import MARKER, render_tool_discipline
        if request.messages and request.messages[0].get("role") == "system" \
                and MARKER in (request.messages[0].get("content") or ""):
            return
        names = []
        for t in tools or []:
            try:
                n = t.get("function", {}).get("name") or t.get("name")
            except Exception:
                n = None
            if n:
                names.append(n)
        content_prepend(request.messages, 'system', "\n\n" + render_tool_discipline(names) + "\n\n")
    except Exception:
        logging.getLogger("app").warning("[Discipline] 能力索引注入失败（跳过）", exc_info=True)







@app.post("/execute_tool_manually")
async def execute_tool_manually(request: Request):
    """
    前端点击审批按钮后调用的接口
    """
    data = await request.json()
    result = await execute_approved_tool(
        data.get("tool_name"), data.get("tool_params"),
        data.get("approval_type"), data.get("stream_id"))
    # S151：Web 审批决策落通知中心（面板销账 + 审计）
    try:
        from py import notification_center
        _t = data.get("approval_type") or "once"
        _label = {"once": "已批准", "approve": "已批准", "always": "已批准并加白名单"}.get(_t, _t)
        notification_center.emit(
            "approval", f"Web 审批{_label}：{data.get('tool_name')}",
            extra={"pending_key": data.get("stream_id") or "web-anon",
                   "source": "web", "decision": _t,
                   "tool_name": data.get("tool_name"), "status": "resolved"})
    except Exception:
        pass
    return result


@app.post("/ask_card_answer")
async def ask_card_answer(request: Request):
    """S198：web 提问卡提交——服务端解析并结算，返回格式化结果文本；前端回写
    tool 条目后走审批式无 user 消息重放续跑，答案不再以工具结果+用户消息双份
    出现。缺选项题按「（未答复）」结算（与手输拦截的 web-v1 语义一致）。
    无挂起卡 → ok=False（前端降级为普通消息发送，不丢答案）。"""
    from py import approval_store, ask_flow
    data = await request.json()
    conv = str(data.get("conversation_id") or "") or "web-default"
    text = str(data.get("answer_text") or "")
    rec = approval_store.latest_pending_ask("web", conv)
    if rec is None:
        return {"ok": False, "reason": "no_pending"}
    ans, _missing = ask_flow.parse_answers(rec, text)
    popped, _e = await approval_store.resolve("web", conv, "answers", kind="ask")
    if popped is None:
        return {"ok": False, "reason": "no_pending"}
    result_text = ask_flow.format_result_text(rec, ans)
    try:
        asyncio.create_task(approval_store._fire(popped, "answers", "", result_text))
    except Exception:
        pass
    logging.getLogger("app").info("[Ask] web 卡片提交: conv=%s id=%s 已答=%d 未答=%d",
                                  conv, rec.get("approval_id"), len(ans),
                                  len(rec.get("questions") or []) - len(ans))
    return {"ok": True, "result_text": result_text}


# S150：IM 审批闭环——把审批执行器交给编排模块（bot 侧 /y /a 批复经此执行工具）
from py import approval_im as _approval_im
_approval_im.set_executor(execute_approved_tool)

# 在现有路由后添加以下代码

# 在现有路由后添加以下代码



@app.post("/v1/chat/completions", operation_id="chat_with_agent_party")
async def chat_endpoint(request: ChatRequest, fastapi_request: Request):
    """S232：在途计数包装——非流式长任务（IM bot/子代理/complete 路径）的
    handler 全程计入繁忙信号；日记自调用（platform=diary）不计，防触发暂停自锁。
    流式任务由 stream_relay._active_streams 覆盖，不依赖本计数。"""
    # S330：(platform, peer) 绑入本请求任务上下文——hook 审批门消费 one-shot grant 用
    from py.approval_store import set_current_im_ctx as _sc
    _sc(getattr(request, "platform", ""), getattr(request, "peer_id", ""))
    _counted = (getattr(request, "platform", "") or "") != "diary"
    if _counted:
        _agent_activity.begin()
    try:
        return await _chat_endpoint_impl(request, fastapi_request)
    finally:
        if _counted:
            _agent_activity.end()


async def _chat_endpoint_impl(request: ChatRequest, fastapi_request: Request):
    """
    用来与agent party中的模型聊天
    """
    _tt0 = _TTFB_T0.get()
    _ua = (fastapi_request.headers.get("user-agent") or "-")[:60]
    logging.getLogger("app").info(
        f"[TTFBbrk] endpoint-enter +{int((time.monotonic() - _tt0) * 1000) if _tt0 else -1}ms"
        f" stream={bool(getattr(request, 'stream', False))} bot={int(bool(getattr(request, 'is_app_bot', False)))}"
        f" plat={getattr(request, 'platform', '') or '-'} ua={_ua}")  # S172：请求来源指纹
    fastapi_base_url = str(fastapi_request.base_url)
    # S188：IM 渠道插话拦截——同 peer 存在活跃生成流/审批未决 → 入队+静态回执，
    # 不起新流（消除并发推理；轮边界/批复闭环时并入处理）
    if (getattr(request, "is_app_bot", False) and getattr(request, "platform", "")
            and getattr(request, "peer_id", "")):
        _ij_rep = _interject.im_intercept(request)
        if _ij_rep is not None:
            if getattr(request, "stream", False):
                async def _ij_hold_stream():
                    _c = {"id": "agentParty", "object": "chat.completion.chunk",
                          "created": int(time.time()), "model": _ij_rep["model"],
                          "choices": [{"index": 0, "finish_reason": None,
                                       "delta": {"role": "assistant",
                                                 "content": _ij_rep["choices"][0]["message"]["content"]}}]}
                    yield f"data: {json.dumps(_c, ensure_ascii=False)}\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(_ij_hold_stream(), media_type="text/event-stream")
            return JSONResponse(content=_ij_rep)
    # S172：尾部=未批复审批 → 静止态直接回执，不进模型（掐灭审批未决期间的自动重放风暴）
    _ap_tail = pending_approval_at_tail(request.messages)
    if _ap_tail is not None:
        _rep = _pending_approval_reply_dict(_ap_tail, request.model)
        if getattr(request, "stream", False):
            async def _ap_hold_stream():
                _c = {"id": "agentParty", "object": "chat.completion.chunk", "created": int(time.time()),
                      "model": _rep["model"],
                      "choices": [{"index": 0, "finish_reason": None,
                                   "delta": {"role": "assistant", "content": _rep["choices"][0]["message"]["content"]}}]}
                yield f"data: {json.dumps(_c, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(_ap_hold_stream(), media_type="text/event-stream")
        return JSONResponse(content=_rep)
    # 【注意】引入全局 fast_client
    global client, reasoner_client, fast_client, settings
    
    raw_model = request.model or 'super-model'
    override_memory_id = None
    
    if raw_model.startswith("memory/"):
        parts = raw_model.split('/', 2) 
        if len(parts) >= 2:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", parts[1] or ""):
                raise HTTPException(status_code=400, detail="invalid memory id in model")
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
        
        # S120(上游 guard 族)：内容安全——入站全量文本 403 拦截
        if current_settings.get("systemSettings", {}).get("contentSafety", False):
            all_text = ""
            for msg in request.messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    all_text += " " + content
                elif isinstance(content, list):
                    all_text += " " + " ".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
            is_safe, matched = await check_content_safety(all_text)
            if not is_safe:
                logging.getLogger("app").warning(f"[content_safety] input blocked words: {matched}")
                return JSONResponse(
                    status_code=403,
                    content={"error": {"message": "您的输入包含敏感内容，已被安全策略拦截。", "type": "content_safety", "code": 403}}
                )
        
        # 【修改点1】创建当前请求的专属配置，避免污染全局
        request_settings = current_settings.copy()
        # S224 统一交给主模型：推理走主模型——请求期副本关闭独立 reasoner（新嵌套 dict 不污染 global，complete+stream 两路均以此为准）
        if current_settings.get('unifiedModel'):
            request_settings['reasoner'] = {**current_settings['reasoner'], 'enabled': False}
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

        logging.getLogger("app").debug(f"model: {request_settings.get('model')}")
        
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
    # S120(上游 guard 族)：内容安全——simple_chat 入站拦截（含 system prompt）
    if current_settings.get("systemSettings", {}).get("contentSafety", False):
        all_text = ""
        for msg in request.messages:
            all_text += " " + _extract_text_content(msg.get("content", ""))
        is_safe, matched = await check_content_safety(all_text)
        if not is_safe:
            logging.getLogger("app").warning(f"[content_safety] blocked words: {matched}")
            return JSONResponse(
                status_code=403,
                content={"error": {"message": "您的输入包含敏感内容，已被安全策略拦截。",
                                   "type": "content_safety", "code": 403}}
            )
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
        # S206：每模型推理参数（卡片级覆盖 > 角色默认）
        _f_eff = effective_role_params(current_settings, fast_cfg)
        for _k in ('temperature', 'top_p', 'max_tokens'):
            if _f_eff.get(_k) is not None:
                current_settings[_k] = _f_eff[_k]

    # --------------- 调用大模型（T-5: 入 llm_gate 闸门，mem0 防撞不再失明） ---------------
    llm_gate.enter()
    try:
        # S207：瞬断重试仅覆盖 create 本身（首字节前）；流式消费出错照旧透传
        response = await acreate(
            lambda: fast_client.chat.completions.create(
                model=current_settings['model'],
                messages=request.messages,
                stream=request.stream,
                temperature=request.temperature or settings.get('temperature', 0.7),
            ), attempts=llm_retry_cfg(settings)[0],
            base_delay=llm_retry_cfg(settings)[1], label="fast")
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


async def _sync_external_api_token_flag():
    """M5：把 systemSettings.externalApiRequireToken 同步进 auth 模块；
    免 token 模式启动时打一条 warning 提醒配额暴露面。"""
    try:
        from py import get_setting as _gs
        settings = await _gs.load_settings()
        sap_auth.EXTERNAL_TOKEN_FREE = not bool(
            settings.get("systemSettings", {}).get("externalApiRequireToken", False))
    except Exception:
        return
    if sap_auth.EXTERNAL_TOKEN_FREE:
        logging.getLogger("app").warning(
            "[Auth] /v1 /mcp 外联 API 当前免 token（本机其他程序/局域网可直调，消耗模型配额）。"
            "可在设置开启「外联 API 需要令牌」改用 Authorization: Bearer <MACHINE_TOKEN>。")


def _announce_agent_proxy(settings):
    """S236：向主进程 stdout 协议行下发规范化代理地址，供 agent 专用
    persist:agent-proxy 分区 setProxy（Electron 侧此前完全无代理接线）。"""
    try:
        from py.proxy_util import (active_proxy, mask_proxy_url,
                                   proxy_bypass_rules)
        px = active_proxy(settings)
        print(f"SAP_PROXY:{px}" if px else "SAP_PROXY:null", flush=True)
        # S239：自定义直连白名单第二协议线 + 后端留痕（此前只走 stdout，
        # backend.log 零痕迹=agent 报代理问题时全链路无从对案）
        bl = proxy_bypass_rules(settings)
        print(f"SAP_PROXY_BYPASS:{bl}" if bl else "SAP_PROXY_BYPASS:none", flush=True)
        logger.info(f"[Proxy] SAP_PROXY 下发 proxy={mask_proxy_url(px) or 'null'} "
                    f"bypass={bl or '(仅内置内网)'}")
    except Exception as e:
        logger.info(f"SAP_PROXY 播报异常: {e}")


def _build_proxy_transport(px=None):
    """S239：global_http_client 唯一代理通道=显式 transport（trust_env 恒 False）。
    px 为 active_proxy 规范化值（http/https/socks*），None=直连。"""
    return httpx.AsyncHTTPTransport(proxy=px) if px else httpx.AsyncHTTPTransport()


def _swap_global_http_proxy(px):
    """S239：原地热 swap global_http_client 的 transport——修「启动值钉死」。
    不换客户端实例：AsyncOpenAI/各工具持同一引用，原地替换引用零波及即全链路
    实时生效（agent 看到的出口=设置实时值）。失败保持原出口，绝不 raise。"""
    try:
        client = getattr(app_state, "global_http_client", None)
        if client is None:
            return
        client._transport = _build_proxy_transport(px)
        from py.proxy_util import mask_proxy_url
        logger.info(f"[Proxy] global HTTP 客户端出口已切换 -> "
                    f"{mask_proxy_url(px) or 'direct'}")
    except Exception as e:
        logger.info(f"[Proxy] global HTTP 客户端代理热切换失败（保持原出口）: {e}")


def _apply_proxy_env_safe(settings):
    """S85-D：代理设置保存后即时同步进程 env（manual=注入/system=探测/none=清除）。"""
    px = None
    try:
        from py.proxy_util import apply_env_proxy
        px = apply_env_proxy(settings)
    except Exception as e:
        logger.info(f"代理环境同步异常: {e}")
    _announce_agent_proxy(settings)  # S236：Electron agent-proxy 分区随设置热更新
    _swap_global_http_proxy(px)      # S239：全局 HTTP 客户端出口随设置热更新


async def _sanitize_conversations_safety(covs: list) -> None:
    """S120(上游 guard 族)：ws 会话落库前 assistant 命中敏感词即写时替换
    （save_conversations 与 _delta 共用；开关关=零开销直通）。"""
    cur = await load_settings()
    if not cur.get("systemSettings", {}).get("contentSafety", False):
        return
    for conv in covs:
        for msg in conv.get("messages", []):
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = " ".join(item.get("text", "") for item in content if isinstance(item, dict))
            else:
                continue
            if not text:
                continue
            is_safe, matched = await check_content_safety(text, min_cjk_chars=3)
            if not is_safe:
                logger.warning(f"[content_safety] ws save_conversations blocked words: {matched}")
                msg["content"] = "[该回复已被内容安全策略自动替换]"
                msg["_safety_filtered"] = True


async def _ws_save_conversations(websocket: WebSocket, data: dict):
    """S120(上游 guard 族)：ws save_conversations 单点（B8 出壳惯例），
    落库前敏感词净化；失败必须回 save_error（C-15）。"""
    try:
        cov_data = data.get("data", {})
        await _sanitize_conversations_safety(cov_data.get("conversations") or [])
        await save_covs(cov_data)
    except Exception as _save_e:
        logger.error(f"[WS] save_conversations 失败: {_save_e}")
        await ws_manager.send_json({
            "type": "save_error",
            "correlationId": data.get("correlationId"),
            "success": False,
            "error": str(_save_e),
        }, websocket)
        return
    await ws_manager.send_json({
        "type": "conversations_saved",
        "correlationId": data.get("correlationId"),
        "success": True
    }, websocket)


async def _ws_save_conversations_delta(websocket: WebSocket, data: dict):
    """S120(上游 guard 族)：增量保存单点——仅 upsert dirty 会话 + 同款净化。
    S189：失败必须回 save_error+日志（2026-11-01 事故：异常被外层吞，前端白等
    20s 超时后 2s 间隔无限重试，保存通道瘫痪一夜且零痕迹）。"""
    import time as _t
    _m0 = _t.monotonic()
    payload = data.get("data", {}) or {}
    incoming = [c for c in (payload.get("conversations") or []) if isinstance(c, dict) and c.get("id") is not None]
    try:
        _sz = len(json.dumps(payload, ensure_ascii=False, default=str))
    except Exception:
        _sz = -1
    try:
        await _sanitize_conversations_safety(incoming)
        # S190 rows-first：只写 dirty 行，26MB blob 不再参与增量保存。
        from py.get_setting import save_covs_delta_rows
        await save_covs_delta_rows(incoming, payload.get("conversationGroups"))
    except Exception as _de:
        logging.getLogger("app").error(
            f"[Covs] delta 保存失败 rows={len(incoming)} bytes={_sz} "
            f"{round((_t.monotonic() - _m0) * 1000)}ms: {_de!r}")
        await ws_manager.send_json({
            "type": "save_error",
            "correlationId": data.get("correlationId"),
            "success": False,
            "error": str(_de),
        }, websocket)
        return
    logging.getLogger("app").info(
        f"[Covs] delta 保存 rows={len(incoming)} bytes={_sz} "
        f"{round((_t.monotonic() - _m0) * 1000)}ms")
    await ws_manager.send_json({
        "type": "conversations_delta_saved",
        "correlationId": data.get("correlationId"),
        "success": True
    }, websocket)


async def _ws_save_settings(websocket: WebSocket, data: dict):
    """B8(b03e7c0e): ws save_settings 单点——读现库深合并后落盘，部分载荷
    不再整库覆盖。C-15: 失败必须回 save_error（此前异常被外层吞=前端白等超时）。"""
    settings_dict = data.get("data", {})
    try:
        # D-1：load→merge→save 全程持事务锁，堵死并发保存的 lost-update 窗口
        async with _SETTINGS_RMW_LOCK:
            current = await load_settings()
            # S120(上游 guard 族)：内容安全——系统提示词含敏感词则拒绝保存
            if current.get("systemSettings", {}).get("contentSafety", False):
                sys_prompt = settings_dict.get("system_prompt", "")
                if sys_prompt:
                    is_safe, matched = await check_content_safety(sys_prompt)
                    if not is_safe:
                        logger.warning(f"[content_safety] ws save_settings blocked words: {matched}")
                        await ws_manager.send_json({
                            "type": "save_error",
                            "correlationId": data.get("correlationId"),
                            "success": False,
                            "error": "系统提示词包含敏感内容，设置未保存。",
                        }, websocket)
                        return
            deep_update(current, settings_dict)
            await save_settings(current, _rmw_held=True)
        _apply_proxy_env_safe(current)
        # M5：外联 API 免 token 开关随设置热更新
        sap_auth.EXTERNAL_TOKEN_FREE = not bool(
            current.get("systemSettings", {}).get("externalApiRequireToken", False))
        await sync_all_bots_behavior(current)
        try:
            from py.diary_engine import global_diary_engine
            global_diary_engine.update_config(current.get("diarySettings"))
        except Exception as _de:
            logger.info(f"日记引擎配置同步异常: {_de}")
        try:
            from py.screen_watcher import global_screen_watcher
            global_screen_watcher.update_config(current.get("screenWatchSettings"))
        except Exception as _swe:
            logger.info(f"旁观引擎配置同步异常: {_swe}")
        try:
            from py.token_guard import apply_setting as _tg_apply_setting
            _tg_apply_setting(current.get("eosGuard"))  # S160：净化总开关热更新
        except Exception as _te:
            logger.info(f"EOS 净化开关同步异常: {_te}")
        try:
            _tool_cap.apply_setting(current)  # S233：工具轮数上限/破限开关热更新（在途任务下一轮边界生效）
        except Exception as _tce:
            logger.info(f"工具上限热值同步异常: {_tce}")
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
        logging.getLogger("app").info("[WS] handshake rejected: auth failed (missing/invalid sap_token)")
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
                # S120: 重活出循环壳（B8 同款），含敏感词净化
                await _ws_save_conversations(websocket, data)

            elif msg_type == "save_conversations_delta":
                # 增量保存：仅 upsert 前端 dirty 的会话，避免每次全量搬运整棵会话树
                await _ws_save_conversations_delta(websocket, data)

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
                # S120(上游 guard 族)：内容安全——扩展系统提示词入站拦截
                cur_settings = await load_settings()
                if cur_settings.get("systemSettings", {}).get("contentSafety", False):
                    is_safe, matched = await check_content_safety(extension_system_prompt)
                    if not is_safe:
                        logger.warning(f"[content_safety] ws set_system_prompt blocked words: {matched}")
                        await ws_manager.send_json({
                            "type": "error",
                            "message": "系统提示词包含敏感内容，已被安全策略拦截。",
                        }, websocket)
                        continue
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

            elif msg_type.startswith("island_"):
                # S139(R6)：灵动岛 8 类消息，重活在 _ws_island（保 ws 循环壳尺寸）
                await _ws_island(websocket, msg_type, data)

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
# S91(THA)：桌宠默认模型静态分发（必须在 "/" catch-all 之前）
app.mount("/tha_models", StaticFiles(directory=DEFAULT_THA_DIR), name="tha_models")
# S136(SoulX)：真人伴侣默认参考图静态分发（上游无条件挂载；fork 加 isdir 守卫，
# 防打包缺目录时启动崩溃——挂载缺失仅丢默认图，不影响其余功能）
if os.path.isdir(DEFAULT_SOULX_IMAGES_DIR):
    app.mount("/default_soulx_images", StaticFiles(directory=DEFAULT_SOULX_IMAGES_DIR), name="default_soulx_images")
app.mount("/tool_temp", StaticFiles(directory=TOOL_TEMP_DIR), name="tool_temp")
app.mount("/uploaded_files", StaticFiles(directory=UPLOAD_FILES_DIR), name="uploaded_files")
app.mount("/ext", StaticFiles(directory=EXT_DIR), name="ext")
app.mount("/", StaticFiles(directory=os.path.join(base_path, "static"), html=True), name="static")

# 简化main函数
if __name__ == "__main__":
    import uvicorn

    # 格式化显示地址
    display_host = "127.0.0.1" if HOST == "0.0.0.0" else HOST

    # S328: 血缘自证——进程谱系一行写死进日志（双胞胎/复制品事故时
    # 一眼查谁生谁，不再靠 netstat+PPID 现场猜）
    logging.getLogger("app").info(
        f"[Boot] pid={os.getpid()} ppid={os.getppid()} "
        f"exe={sys.executable} argv={sys.argv}")
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
