# -*- coding: utf-8 -*-
"""System control endpoints (ChromeMCP / Home Assistant / SQL bridges,
shutdown, proxy, ip, storage, language) moved verbatim out of
server.py in the R1 router migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""

import logging
import sys as _sys
import asyncio
import os
import shutil
import signal
from fastapi import Request
from fastapi.responses import JSONResponse
from py.get_setting import IS_DOCKER, UPLOAD_FILES_DIR, load_settings
from py.mcp_clients import McpClient
from fastapi import APIRouter

# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/start_HA")
async def start_HA(request: Request):
    data = await request.json()
    API_TOKEN = data['data']['api_key']
    ha_config = {
        "type": "sse",
        "url": data['data']['url'].rstrip('/') + "/mcp_server/sse",
        "headers": {"Authorization": f"Bearer {API_TOKEN}"}
    }

    if _srv.HA_client is not None:
        # 已初始化过
        return JSONResponse({"status": "ready", "enabled": True})

    # 用来通知“连接失败”的事件
    conn_failed_event = asyncio.Event()
    failure_reason = None

    async def on_failure(error_message: str):
        nonlocal failure_reason
        failure_reason = error_message
        conn_failed_event.set()

    try:
        _srv.HA_client = McpClient()
        await _srv.HA_client.initialize("HA", ha_config, on_failure_callback=on_failure)

        # 等一小段时间验证连接确实活了
        try:
            # 5 秒内如果事件被 set，说明连接失败
            await asyncio.wait_for(conn_failed_event.wait(), timeout=5.0)
            # 走到这里说明失败了
            raise RuntimeError(f"HA client connection failed: {failure_reason}")
        except asyncio.TimeoutError:
            # 2 秒无事发生，认为连接成功
            pass

        return JSONResponse({"status": "ready", "enabled": True})

    except Exception as e:
        _srv.HA_client = None
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/stop_HA")
async def stop_HA():
    try:
        if _srv.HA_client is not None:
            await _srv.HA_client.close()
            _srv.HA_client = None
            logging.getLogger("app").info(f"HA client stopped")
        return JSONResponse({
            "status": "stopped",
            "enabled": False
        })
    except Exception as e:
        _srv.HA_client = None
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@router.post("/start_ChromeMCP")
async def start_ChromeMCP(request: Request):
    data = await request.json()
    chromeMCPSettings = data.get('data', {})

    # 1. 确定包名
    if chromeMCPSettings.get('mcpName', 'browser-mcp') == 'browser-mcp':
        target_package = "@browsermcp/mcp@latest"
    else:
        target_package = "@playwright/mcp@latest"

    # 2. 准备基础变量
    command = ""
    args = []
    
    # 3. 准备环境变量 (这是解决权限问题的关键！)
    env = os.environ.copy()

    # ★关键设置 A: 指定 Playwright 浏览器下载位置到用户可写目录
    # 避免它尝试写入系统目录或请求 sudo 权限
    # 获取当前应用运行目录下的 'browsers' 文件夹
    browser_storage = os.path.join(os.getcwd(), "browsers")
    if not os.path.exists(browser_storage):
        os.makedirs(browser_storage, exist_ok=True)
    
    env["PLAYWRIGHT_BROWSERS_PATH"] = browser_storage
    
    # ★关键设置 B: 告诉 npx 不要问 "Do you want to install..."
    # 虽然 args 里加了 -y，但设置这个环境变量是双重保险
    env["npm_config_yes"] = "true"

    # 4. 命令探测逻辑
    system_npx = shutil.which("npx")

    if system_npx:
        # --- 方案 A: 系统原生 npx (Docker 或 本地开发) ---
        logging.getLogger("app").info(f"Using system npx: {system_npx}")
        command = system_npx
        # 加上 -y 自动确认安装包
        args = ["-y", target_package] 
    
    else:
        # --- 方案 B: Electron 内部环境 ---
        electron_node = os.environ.get("ELECTRON_NODE_EXEC")
        electron_npm = os.environ.get("ELECTRON_NPM_CLI")
        
        if electron_node and electron_npm:
            logging.getLogger("app").info(f"System npx not found. Falling back to Electron Node.")
            command = electron_node
            # 构造: electron node npm-cli.js exec --yes -- @package
            # --yes 是 npm exec 的参数，表示自动安装缺失的包
            args = [electron_npm, "exec", "--yes", "--", target_package]
            
            # 必须设置，否则 Electron 会弹窗
            env["ELECTRON_RUN_AS_NODE"] = "1"
        else:
            return JSONResponse(
                status_code=500, 
                content={"error": "Node.js runtime not found."}
            )

    # 5. 组装配置
    Chrome_config = {
        "command": command,
        "args": args,
        "env": env
    }

    # ... (后续连接逻辑保持不变) ...
    if _srv.ChromeMCP_client is not None:
        return JSONResponse({"status": "ready", "enabled": True})

    conn_failed_event = asyncio.Event()
    failure_reason = None

    async def on_failure(error_message: str):
        nonlocal failure_reason
        failure_reason = error_message
        conn_failed_event.set()

    try:
        _srv.ChromeMCP_client = McpClient()
        await _srv.ChromeMCP_client.initialize(
            "ChromeMCP", 
            Chrome_config, 
            on_failure_callback=on_failure
        )
        
        # ... (等待连接逻辑) ...
        try:
            await asyncio.wait_for(conn_failed_event.wait(), timeout=5.0)
            raise RuntimeError(f"ChromeMCP client connection failed: {failure_reason}")
        except asyncio.TimeoutError:
            pass

        return JSONResponse({"status": "ready", "enabled": True})

    except Exception as e:
        _srv.ChromeMCP_client = None
        logging.getLogger("app").info(f"Start ChromeMCP Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/stop_ChromeMCP")
async def stop_ChromeMCP():
    try:
        if _srv.ChromeMCP_client is not None:
            await _srv.ChromeMCP_client.close()
            _srv.ChromeMCP_client = None
            logging.getLogger("app").info(f"ChromeMCP client stopped")
        return JSONResponse({
            "status": "stopped",
            "enabled": False
        })
    except Exception as e:
        _srv.ChromeMCP_client = None
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@router.post("/start_sql")
async def start_sql(request: Request):
    data = await request.json()
    sql_args = []
    user = str(data['data'].get('user', '')).strip()
    password = str(data['data'].get('password', '')).strip()
    host = str(data['data'].get('host', '')).strip()
    port = str(data['data'].get('port', '')).strip()
    dbname = str(data['data'].get('dbname', '')).strip()
    dbpath = str(data['data'].get('dbpath', '')).strip()
    sql_url = ""
    if (data['data']['engine']=='sqlite'):
        sql_args = ["--from", "mcp-alchemy==2025.8.15.91819",
               "--refresh-package", "mcp-alchemy", "mcp-alchemy"]
        sql_url = f"sqlite:///{dbpath}"
        logging.getLogger("app").info(sql_url)
    elif (data['data']['engine']=='mysql'):
        sql_args = ["--from", "mcp-alchemy==2025.8.15.91819", "--with", "pymysql",
               "--refresh-package", "mcp-alchemy", "mcp-alchemy"]
        sql_url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{dbname}"
    elif (data['data']['engine']=='postgres'):
        sql_args = ["--from", "mcp-alchemy==2025.8.15.91819", "--with", "psycopg2-binary",
               "--refresh-package", "mcp-alchemy", "mcp-alchemy"]
        sql_url = f"postgresql://{user}:{password}@{host}:{port}/{dbname}"
    elif (data['data']['engine']=='mssql'):
        sql_args = ["--from", "mcp-alchemy==2025.8.15.91819", "--with", "pymssql",
               "--refresh-package", "mcp-alchemy", "mcp-alchemy"]
        sql_url = f"mssql+pymssql://{user}:{password}@{host}:{port}/{dbname}"
    elif (data['data']['engine']=='oracle'):
        sql_args = ["--from", "mcp-alchemy==2025.8.15.91819", "--with", "oracledb",
               "--refresh-package", "mcp-alchemy", "mcp-alchemy"]
        sql_url = f"oracle+oracledb://{user}:{password}@{host}:{port}/{dbname}"

    sql_config = {
        "type": "stdio",
        "command": "uvx",
        "args": sql_args,
        "env": {
            "DB_URL": sql_url.strip(),
        }
    }

    if _srv.sql_client is not None:
        # 已初始化过
        return JSONResponse({"status": "ready", "enabled": True})

    # 用来通知“连接失败”的事件
    conn_failed_event = asyncio.Event()
    failure_reason = None

    async def on_failure(error_message: str):
        nonlocal failure_reason
        failure_reason = error_message
        conn_failed_event.set()

    try:
        _srv.sql_client = McpClient()
        await _srv.sql_client.initialize("sqlMCP", sql_config, on_failure_callback=on_failure)

        # 等一小段时间验证连接确实活了
        try:
            # 5 秒内如果事件被 set，说明连接失败
            await asyncio.wait_for(conn_failed_event.wait(), timeout=5.0)
            # 走到这里说明失败了
            raise RuntimeError(f"sqlMCP client connection failed: {failure_reason}")
        except asyncio.TimeoutError:
            # 2 秒无事发生，认为连接成功
            pass

        return JSONResponse({"status": "ready", "enabled": True})
    except Exception as e:
        _srv.sql_client = None
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/stop_sql")
async def stop_sql():
    try:
        if _srv.sql_client is not None:
            await _srv.sql_client.close()
            _srv.sql_client = None
            logging.getLogger("app").info(f"sqlMCP client stopped")
        return JSONResponse({
            "status": "stopped",
            "enabled": False
        })
    except Exception as e:
        _srv.sql_client = None
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@router.get("/update_storage")
async def update_storage_endpoint(request: Request):
    settings = await load_settings()
    textFiles = settings.get("textFiles") or []
    imageFiles = settings.get("imageFiles") or []
    videoFiles = settings.get("videoFiles") or []
    # 检查UPLOAD_FILES_DIR目录中的文件，根据ALLOWED_EXTENSIONS、ALLOWED_IMAGE_EXTENSIONS、ALLOWED_VIDEO_EXTENSIONS分类，如果不存在于textFiles、imageFiles、videoFiles中则添加进去
    # 三个列表的元素是字典，包含"unique_filename"和"original_filename"两个键
    
    for file in os.listdir(UPLOAD_FILES_DIR):
        file_path = os.path.join(UPLOAD_FILES_DIR, file)
        if os.path.isfile(file_path):
            file_extension = os.path.splitext(file)[1][1:]
            if file_extension in _srv.ALLOWED_EXTENSIONS:
                if file not in [item["unique_filename"] for item in textFiles]:
                    textFiles.append({"unique_filename": file, "original_filename": file})
            elif file_extension in _srv.ALLOWED_IMAGE_EXTENSIONS:
                if file not in [item["unique_filename"] for item in imageFiles]:
                    imageFiles.append({"unique_filename": file, "original_filename": file})
            elif file_extension in _srv.ALLOWED_VIDEO_EXTENSIONS:
                if file not in [item["unique_filename"] for item in videoFiles]:
                    videoFiles.append({"unique_filename": file, "original_filename": file})

    # 发给前端
    return JSONResponse(content={"textFiles": textFiles, "imageFiles": imageFiles, "videoFiles": videoFiles})


@router.get("/cur_language")
async def cur_language():
    settings = await load_settings()
    target_language = settings["currentLanguage"]
    return {"language": target_language}


@router.post("/api/update_proxy") # 建议改用 POST 表达状态变更
async def update_proxy():
    try:
        from py.get_setting import load_settings  # 确保引用正确
        settings = await load_settings()
        
        if not settings:
            return {"message": "Settings not found", "success": False}

        sys_set = settings.get("systemSettings", {})
        mode = sys_set.get("proxyMode")
        manual_url = sys_set.get("proxy", "").strip()
        is_china_proxy = sys_set.get("isChinaProxy", False)

        # 所有的代理相关环境变量键
        proxy_keys = ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'all_proxy']

        # --- 1. 处理 Node.js / UV 镜像源 (与 lifespan 一致) ---
        if is_china_proxy:
            os.environ["npm_config_registry"] = "https://registry.npmmirror.com/"
            os.environ["UV_INDEX_URL"] = "https://mirrors.aliyun.com/pypi/simple/"
        else:
            # 如果关闭了中国加速，移除这些变量（恢复默认）
            os.environ.pop("npm_config_registry", None)
            os.environ.pop("UV_INDEX_URL", None)

        # --- 2. 处理网络代理环境变量 ---
        if mode == "manual" and manual_url:
            # [防御] 如果是 socks，强制清理并警告，防止 httpx 崩溃
            if manual_url.lower().startswith("socks"):
                for key in proxy_keys:
                    os.environ.pop(key, None)
                return {"message": "Detected SOCKS proxy, disabled to prevent crash. Please use HTTP/HTTPS proxy.", "success": False}
            
            # 设置手动代理
            for key in proxy_keys:
                os.environ[key] = manual_url
                
        elif mode == "system":
            # 系统模式：移除 Python 显式设置的环境变量，让底层读取系统全局配置
            for key in proxy_keys:
                os.environ.pop(key, None)
        else:
            # 关闭代理模式：将变量设为空字符串或直接移除
            for key in proxy_keys:
                os.environ[key] = "" 

        # --- 3. [进阶] 尝试动态更新全局 global_http_client ---
        # 注意：修改 os.environ 只对后续创建的子进程有效。
        # 如果你想让当前运行中的 OpenAI 请求也立即切换代理，
        # 最好在这里重新初始化你的 global_http_client（参考下文建议）。

        return {
            "message": "Proxy and mirrors updated successfully", 
            "success": True, 
            "current_mode": mode,
            "china_mirror": is_china_proxy
        }
    except Exception as e:
        return {"message": str(e), "success": False}


@router.get("/api/ip")
def get_ip():
    ip = _srv.get_internal_ip()
    return {"ip": ip}


@router.post("/sys/shutdown")
async def shutdown_server():
    """
    接收到此请求后，向自己发送 SIGTERM 信号，
    这将触发 FastAPI 的 lifespan 关闭流程（清理 Node 进程）。
    """
    if IS_DOCKER:
        return {"message": "Not allowed in Docker mode."}

    logging.getLogger("app").info("Received shutdown request via API...")
    # 获取当前进程 ID 并发送终止信号
    # Windows 和 Linux/Mac 都支持 SIGTERM
    os.kill(os.getpid(), signal.SIGTERM)
    return {"message": "Shutting down..."}

