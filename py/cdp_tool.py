
import logging
import json
import os
import re
import time
import uuid
import requests
import asyncio
import websockets
from py import html_to_md
from py.get_setting import UPLOAD_FILES_DIR, get_port, load_settings

# 全局变量，用于保持当前上下文
CURRENT_PAGE_INDEX = 0

async def get_cdp_port():
    settings = await load_settings()
    # 默认回退到 9222，或者你的配置值
    return settings.get('chromeMCPSettings', {}).get('CDPport', 3456) # 假设你主进程默认端口是3456

async def get_targets():
    """获取所有 CDP 目标"""
    port = await get_cdp_port()
    try:
        resp = requests.get(f'http://127.0.0.1:{port}/json/list')
        return resp.json()
    except Exception as e:
        logging.getLogger("app").info(f"CDP Connection Error: {e}")
        return []

async def get_main_window_ws():
    """获取主窗口（Vue 控制器）的 WebSocket URL"""
    targets = await get_targets()
    
    # 调试：打印所有目标，方便你看清楚当前有哪些窗口
    # print("Current CDP Targets:", json.dumps(targets, indent=2))
    
    for t in targets:
        url = t.get('url', '')
        title = t.get('title', '')
        target_type = t.get('type')

        # 1. 必须是 page 类型 (排除 webview 标签页, service_worker 等)
        if target_type != 'page':
            continue

        # 2. ★ 关键：排除 VRM 窗口
        # VRM 窗口的 URL 通常包含 'vrm.html'
        if 'vrm.html' in url:
            continue
            
        # 3. ★ 关键：排除开发者工具窗口 (如果打开了 DevTools)
        if 'devtools://' in url:
            continue
            
        # 4. (可选) 排除扩展程序窗口
        if 'ext' in url:
            continue

        # 5. 找到主窗口
        # 主窗口的特征通常是：
        # - URL 包含 'skeleton.html' (骨架屏阶段)
        # - 或者 URL 是 'http://127.0.0.1:端口/' (加载完成阶段)
        # - 只要不是上面排除的特定窗口，剩下的 page 通常就是主窗口
        return t.get('webSocketDebuggerUrl')
        
    logging.getLogger("app").info("Error: Could not find Main Window in CDP targets.")
    return None

async def get_webview_ws(index=None):
    """获取具体网页的 WebSocket URL"""
    targets = await get_targets()
    # 过滤出所有 webview (实际的网页标签)
    webviews = [t for t in targets if t['type'] == 'webview']
    
    target_idx = index if index is not None else CURRENT_PAGE_INDEX
    
    if 0 <= target_idx < len(webviews):
        return webviews[target_idx].get('webSocketDebuggerUrl')
    return None

CDP_CALL_TIMEOUT = 30  # S95: 60→30，单次 CDP 往返上限；渲染进程繁忙时工具超时回错而非无限挂起


async def cdp_command(ws_url, method, params=None, timeout=None):
    """发送 CDP 命令的通用函数（S94：全链超时，渲染进程繁忙时不再无限挂起后端协程）"""
    if not ws_url:
        return {"error": "Target not found"}
    if timeout is None:
        timeout = CDP_CALL_TIMEOUT

    async def _exchange():
        # 修改这里：增加 max_size 参数
        # 设置为 None 表示不限制大小，或者设置为 10 * 1024 * 1024 (10MB)
        async with websockets.connect(ws_url, max_size=10 * 1024 * 1024) as ws:
            cmd_id = 1
            message = {
                "id": cmd_id,
                "method": method,
                "params": params or {}
            }
            await ws.send(json.dumps(message))

            while True:
                response = await ws.recv()
                data = json.loads(response)
                if data.get('id') == cmd_id:
                    return data.get('result', {})

    return await asyncio.wait_for(_exchange(), timeout=timeout)

# ==========================================
# Input Automation (Via Vue Controller)
# ==========================================

async def call_vue_method(method_name, args_list=None, timeout=None):
    """
    通用函数：调用 window.aiBrowser 的方法 (带重试机制)
    timeout: 单次 CDP 往返秒数；长耗时操作（如离屏渲染）可放宽，默认沿用 CDP_CALL_TIMEOUT。
    """
    max_retries = 3
    retry_delay = 1.0 # 1秒等待
    if timeout is None:
        timeout = CDP_CALL_TIMEOUT

    ws_url = await get_main_window_ws()
    if not ws_url:
        return {"error": "Main window not found"}

    # 构造参数字符串
    if args_list:
        json_args = [json.dumps(arg) for arg in args_list]
        args_str = ", ".join(json_args)
    else:
        args_str = ""
    
    expression = f"window.aiBrowser.{method_name}({args_str})"

    for attempt in range(max_retries):
        # 每次重试都重新连接 WebSocket，防止 WS 链接本身断开
        try:
            res = await cdp_command(ws_url, "Runtime.evaluate", {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": True
            }, timeout=timeout)
            
            # 1. 检查 CDP 协议本身的异常
            if 'exceptionDetails' in res:
                exc = res['exceptionDetails']
                msg = exc.get('text', 'Unknown Error')
                if 'exception' in exc and 'description' in exc['exception']:
                    msg = f"{msg}: {exc['exception']['description']}"
                
                # ★ 关键：如果遇到 Illegal invocation，抛出异常以触发重试
                if "Illegal invocation" in msg or "GUEST_VIEW_MANAGER_CALL" in msg:
                    logging.getLogger("app").info(f"[Warn] Retrying {method_name} due to Electron error: {msg}")
                    raise ValueError("Electron Webview Error") # 触发 except 重试
                
                return f"Error executing {method_name}: {msg}"

            # 2. 检查返回值是否包含错误信息 (因为你的 JS 代码里 try-catch 后返回了 "Fill Error: ...")
            remote_object = res.get('result', {})
            value = remote_object.get('value', "")
            
            # 如果返回值是字符串且包含 Electron 内部错误，也视为失败进行重试
            if isinstance(value, str) and ("Illegal invocation" in value or "GUEST_VIEW_MANAGER_CALL" in value):
                logging.getLogger("app").info(f"[Warn] Retrying {method_name} due to JS Result error: {value}")
                raise ValueError("Electron Webview Error")

            if 'value' in remote_object:
                return remote_object['value']
            
            if remote_object.get('type') == 'undefined':
                return "Success"
                
            return f"Operation completed (Type: {remote_object.get('type')})"

        except asyncio.TimeoutError:
            # S94：渲染进程繁忙/页面加载中——超时不重试（防 new_page 等副作用重复执行），
            # 直接回可读错误让 LLM 继续推理，后端协程不再无限挂起
            logging.getLogger("app").info(f"[Warn] {method_name} 超时（渲染进程繁忙）")
            return ("浏览器操作超时：页面仍在加载或浏览器界面繁忙。"
                    "请稍后重试该操作，或减少同时打开的标签页数量。")
        except Exception as e:
            # 如果是最后一次尝试，则放弃
            if attempt == max_retries - 1:
                return f"Failed {method_name} after {max_retries} retries. Last error: {str(e)}"
            
            # 等待后重试
            await asyncio.sleep(retry_delay)
            # 有时候主窗口 WS URL 也会变，重新获取一下更稳妥
            ws_url = await get_main_window_ws() or ws_url

# ------------------------------------------
# Interaction Tools (Complete List)
# ------------------------------------------

async def take_snapshot(filePath=None, verbose=False):
    """
    获取页面可交互元素的 DOM 树快照。
    """
    # 调用 Vue 方法生成快照字符串
    result = await call_vue_method('getWebviewSnapshot', [verbose])
    
    # 如果指定了 filePath，则保存到文件（模拟 Agent 行为）
    if filePath and result and isinstance(result, str):
        try:
            with open(filePath, 'w', encoding='utf-8') as f:
                f.write(result)
            return f"Snapshot saved to {filePath}"
        except Exception as e:
            return f"Error saving snapshot: {str(e)}"
            
    # 否则直接返回快照内容
    return result

async def click(uid, dblClick=False):
    """点击元素"""
    return await call_vue_method('webviewClick', [uid, dblClick])

async def fill(uid, value):
    """填写输入框"""
    return await call_vue_method('webviewFill', [uid, value])

async def fill_form(elements):
    """
    批量填写表单
    elements: [{'uid': '...', 'value': '...'}, ...]
    """
    return await call_vue_method('webviewFillForm', [elements])

async def drag(from_uid, to_uid):
    """拖拽元素"""
    return await call_vue_method('webviewDrag', [from_uid, to_uid])

async def handle_dialog(action, promptText=None):
    """处理弹窗 (alert/confirm/prompt)"""
    return await call_vue_method('webviewHandleDialog', [action, promptText])

async def hover(uid):
    """悬停"""
    return await call_vue_method('webviewHover', [uid])

async def press_key(key,uid):
    """按键"""
    return await call_vue_method('webviewPressKey', [key, uid])

# ------------------------------------------
# Navigation Tools
# ------------------------------------------

async def list_pages():
    """列出所有标签页"""
    return await call_vue_method('getPagesInfo')

async def new_page(url, timeout=0, background=False, mobile=False):
    """新建标签页；background=True 时后台打开（不抢占用户可见面板）；mobile=True 用移动端 UA + 手机视口渲染。"""
    if background:
        res = await call_vue_method('openUrlInBackground', [url])
    else:
        res = await call_vue_method('openUrlInNewTab', [url])
    if mobile:
        try:
            await call_vue_method('setTabMobile', [None, True, True])
        except Exception:  # noqa: BLE001
            pass
    return res

async def close_page(pageIdx):
    """关闭标签页"""
    return await call_vue_method('closeTabByIndex', [pageIdx])

async def select_page(pageIdx, bringToFront=True):
    """选择/切换标签页"""
    return await call_vue_method('switchTabByIndex', [pageIdx])

async def navigate_page(type="url", url=None, ignoreCache=False, timeout=8, mobile=None):
    """页面导航。默认等待页面加载完成（最多 timeout 秒，加载完成即提前返回），结果带 (loaded)/(still loading)；timeout=0 不等待立即返回。
    mobile=True/False 切换当前标签页移动/桌面模式（None 不改，移动模式需重新加载才生效）。"""
    try:
        t = int(timeout)
    except (TypeError, ValueError):
        t = 8
    t = max(0, min(t, 30))
    if mobile is not None:
        try:
            await call_vue_method('setTabMobile', [None, bool(mobile), False])
        except Exception:  # noqa: BLE001
            pass
    return await call_vue_method('browserNavigate', [type, url, ignoreCache, t], timeout=t + 20)

async def wait_for(text, timeout=1000):
    """等待文本出现"""
    return await call_vue_method('webviewWaitFor', [text, timeout])

# ------------------------------------------
# Debugging Tools
# ------------------------------------------

async def evaluate_script(script_code, args=None):
    """执行 JS (极强容错版)"""
    
    # 1. 清理字符串前后的空白和反引号（AI有时候会自作聪明加上 ```javascript 的Markdown代码块）
    clean_code = script_code.strip().strip('`')
    if clean_code.startswith('javascript'):
        clean_code = clean_code[10:].strip()

    # 2. 兜底容错：如果 AI 还是只输出了函数体（比如包含 return 但没写 function）
    if not clean_code.startswith("function") and not clean_code.startswith("() =>") and not clean_code.startswith("async function"):
        logging.getLogger("app").info(f"[Agent Warning] AI forgot to wrap function, auto-wrapping it...")
        # 帮它包一层标准函数
        clean_code = f"function() {{\n{clean_code}\n}}"
        
    # 3. S230 导航写护栏：只拦"真会换页/提交表单"的写操作（location 赋值/assign/replace/reload、submit()），
    #    避免把 location.href 之类的纯读取脚本误判为导航而吞掉返回值。写操作仍异步调度（防上下文丢失断连）。
    if re.search(r"(location\s*\.\s*(href|assign|replace|reload)\s*[=(]|location\s*=[^=]|submit\s*\()", clean_code):
        safe_code = f"""
        function() {{
            setTimeout(function() {{
                ({clean_code})();
            }}, 100);
            return 'scheduled';
        }}
        """
        await call_vue_method('executeInActiveWebview', [safe_code, args or []])
        return ('[Navigation scheduled] 导航/提交脚本已异步调度执行；页面上下文将被替换，本次调用拿不到返回值。'
                '请等待导航完成后重新调用 take_snapshot / get_page_markdown / evaluate_script 读取结果。')
    
    # 4. 正常执行
    return await call_vue_method('executeInActiveWebview', [clean_code, args or []])

async def take_screenshot(fullPage=False, uid=None):
    """
    截图
    Vue 端已将图片保存到 uploaded_files 目录，并返回了 URL。
    """
    # 直接调用，返回值就是 URL (例如: http://127.0.0.1:3456/uploaded_files/xxx.jpg)
    result = await call_vue_method('captureWebviewScreenshot', [fullPage, uid])
    
    # 简单的错误检查
    if not result or result.startswith("Error") or result.startswith("Screenshot Error"):
        return f"Failed to capture screenshot: {result}"
        
    return f"Screenshot saved to {result}"


# ==========================================
# S227: 本地无头渲染动态页 -> Markdown（一次性）
# ==========================================

async def web_render(original_url, wait_text=None, timeout=45, mobile=False):
    """用内置浏览器在离屏隐藏 webview 渲染动态(含JavaScript)页面，本地转 Markdown 回传，无云。

    仅 Electron 桌面版且启用内置浏览器时有效；可访问本机/内网地址（异于云端 markdown_new）。
    慢站超时前会尽量回传已加载到的部分内容(标注 partial)；重站可加大 timeout 或用 wait_text 等关键文本。
    mobile=True 用移动端 UA + 手机视口渲染（针对移动端 H5/公众号/贴吧/知乎等只给移动端内容的站点）。
    """
    url = (original_url or "").strip()
    if not url:
        return "[Error] web_render: 缺少 url。"
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    if not await get_targets():
        return ("[Error] 内置浏览器通道不可用：仅 Electron 桌面版且已启用“内置浏览器”时有效。"
                "可改用 markdown_new / simple_fetch 等抓取工具。")
    t = int(timeout or 45)
    t = max(5, min(t, 60))
    opts = {"waitText": wait_text or "", "timeout": t, "mobile": bool(mobile)}
    res = await call_vue_method("renderOffscreenPage", [url, opts], timeout=t + 20)
    if not isinstance(res, str):
        res = json.dumps(res or {})
    data = None
    s = res.strip()
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except Exception:  # noqa: BLE001
            data = None
    if not isinstance(data, dict) or not data.get("ok"):
        e = str((data.get("error") if isinstance(data, dict) else s) or "unknown")
        if "render timeout" in e:
            hint = ("超时未加载完成：站可能很慢或被墙/需代理（内置浏览器不走 SAP 应用内代理）。"
                    "可加大 timeout、提供 wait_text，或改用可直连的镜像/来源。")
        elif "no-content" in e:
            hint = "已连接但未抓到正文：可能需登录或被反爬，可加 wait_text 指定正文关键句后重试。"
        elif "wait-text-timeout" in e:
            hint = "等待的 wait_text 未出现：文本可能不对或被延迟，校正 wait_text 或加大 timeout。"
        elif "load failed" in e:
            hint = "加载失败：检查该地址是否可达/被墙（内置浏览器不走 SAP 代理），或换其它来源。"
        else:
            hint = "可稍后重试、提供 wait_text、加大 timeout，或改用其它来源。"
        return f"[Fetch failed] 本地渲染 {url} 未成功：{e[:160]}。{hint}"
    html = data.get("html") or ""
    md = html_to_md.html_to_markdown(html, max_chars=120000)
    if not md.strip():
        return (f"[Empty] 本地渲染 {url} 成功但正文为空（可能需登录、被反爬，或纯 SPA 未渲染出内容）。"
                "可加 wait_text 等待关键文本出现后重试，或加大 timeout。")
    title = (data.get("title") or "").strip()
    final_url = data.get("finalUrl") or url
    partial = bool(data.get("partial"))
    src = f"Source: {final_url} (partial)" if partial else f"Source: {final_url}"
    head = f"# {title}\n{src}\n\n" if title else f"{src}\n\n"
    if partial:
        head += "> 注意：页面在超时前未完全加载，以下为已加载到的部分内容。\n\n"
    return head + md


# ==========================================
# S227: 浏览器增强（反弹窗/拔元素/急停后退/当前页转MD）
# ==========================================

async def clean_dom(force=False):
    """清除当前页弹窗/遮罩/Cookie同意条/广告占位（仅 DOM 层）。force=True 启用激进档（含 modal/paywall）。"""
    return await call_vue_method('cleanPage', [bool(force)])


async def remove_element(target):
    """拔除元素：target 为快照 uid（如 ai-12）或任意 CSS 选择器。"""
    if not (target or "").strip():
        return "[Error] remove_element: 缺少 target（uid 或 CSS 选择器）。"
    return await call_vue_method('removeElement', [target])


async def stop_loading():
    """急停：停止当前页加载（误跳/卡死时逃生）。"""
    return await call_vue_method('stopLoading', [])


async def escape_back():
    """急停并后退到上一页（从误跳转/弹窗快速撤回）。"""
    return await call_vue_method('escapeBack', [])


async def get_page_markdown():
    """把当前活动标签页就地清洗并转 Markdown 返回（本地，无云）。"""
    res = await call_vue_method('getPageHtml', [])
    s = res if isinstance(res, str) else json.dumps(res or {})
    if s.startswith("Error"):
        return s
    md = html_to_md.html_to_markdown(s, max_chars=120000)
    if not md.strip():
        return "[Empty] 当前页无可抽取正文（可能需登录或纯 SPA 未渲染出内容）。"
    return md


# ==========================================
# S227: 重定向护栏（guardRedirect 开启时）
# ==========================================

async def check_redirect():
    """查询被重定向护栏挂起的跳转列表（[{id,url}]）。guardRedirect 关闭时恒为 []。"""
    res = await call_vue_method('listPendingRedirects', [])
    return res if isinstance(res, str) else json.dumps(res or [])


async def approve_navigation(allow=True, tab_id=None):
    """裁决挂起的重定向：allow=True 放行该跳转，否则维持拦截。tab_id 省略则作用于当前活动页。

    放行=主进程以授权方式加载目标 URL；拦截=保持停留在原页面。
    """
    return await call_vue_method('resolveRedirect', [bool(allow), tab_id])


# ==========================================
# Tool Definitions (JSON Schemas)
# ==========================================

all_cdp_tools = [
    # --- Navigation ---
    {
        "type": "function",
        "function": {
            "name": "list_pages",
            "description": "Get a list of pages open in the browser.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "new_page",
            "description": "Creates a new page in the browser tab bar.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to load"},
                    "timeout": {"type": "integer"},
                    "background": {"type": "boolean", "description": "true=后台打开新标签，不抢占用户可见面板（默认 false）。"},
                    "mobile": {"type": "boolean", "description": "true=用移动端 UA + 手机视口打开（针对只给移动端内容/有App墙的站点）。默认 false。"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_page",
            "description": "Closes the page by its index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pageIdx": {"type": "integer", "description": "Index of the page to close"}
                },
                "required": ["pageIdx"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_page",
            "description": "Switch tab to the specified page index.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pageIdx": {"type": "integer"},
                    "bringToFront": {"type": "boolean"}
                },
                "required": ["pageIdx"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_page",
            "description": "Navigates the currently selected page. By default it WAITS for the page to finish loading (up to `timeout` seconds, returns early when done) and the result ends with '(loaded)' or '(still loading)' — so you can usually take_snapshot right after without a separate wait. Pass timeout=0 to return immediately (old fire-and-forget behavior). Set mobile=true/false to switch the tab between mobile (phone UA + viewport) and desktop rendering before navigating.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["url", "back", "forward", "reload"]},
                    "url": {"type": "string"},
                    "ignoreCache": {"type": "boolean"},
                    "timeout": {"type": "integer", "description": "等待页面加载完成的秒数（0-30，默认 8）。加载完成会提前返回；超时返回 (still loading)，可再 wait_for/take_snapshot。0=不等待立即返回。"},
                    "mobile": {"type": "boolean", "description": "true=以移动端模式导航（手机UA+手机视口，绕过App墙/拿移动端内容）；false=恢复桌面；省略=不改变当前模式。"}
                },
                "required": ["type"]
            }
        }
    },
    
    # --- Debugging & Input ---
    {
        "type": "function",
        "function": {
            "name": "take_snapshot",
            "description": "Get the accessibility tree of the current page to find UIDs for interaction. Besides interactive elements it also lists content images/canvas with UIDs (alt/size/loaded/offscreen), so you can target them with take_screenshot(uid) or remove_element(uid). If the page is still loading it waits up to ~3s; if still not done it returns a possibly-PARTIAL snapshot ending with '(note: page still loading...)'. Tip: call right after navigate_page, which already waits for load by default.",
            "parameters": {
                "type": "object",
                "properties": {
                    "verbose": {"type": "boolean"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click",
            "description": "Clicks an element identified by UID from take_snapshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "The BackendNodeId from snapshot"},
                    "dblClick": {"type": "boolean"}
                },
                "required": ["uid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fill",
            "description": "Type text into an input element.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string"},
                    "value": {"type": "string"}
                },
                "required": ["uid", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "evaluate_script",
            "description": "Run JS in the current page. You MUST wrap your code in a valid Javascript function expression.\n\nGOOD Example:\n`function() { return document.title; }`\n\nBAD Example (DO NOT DO THIS):\n`return document.title;`",
            "parameters": {
                "type": "object",
                "properties": {
                    "script_code": {
                        "type": "string", 
                        "description": "The complete JS function expression to execute."
                    },
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Arguments to pass into the function."
                    }
                },
                "required": ["script_code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "hover",
            "description": "Hover over an element identified by UID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "uid": {"type": "string", "description": "The BackendNodeId from snapshot"}
                },
                "required": ["uid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "press_key",
            "description": "Press a key or key combination (e.g. 'Enter', 'Control+a', 'ArrowDown').",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "The key combination to press."},
                    "uid": {"type": "string", "description": "The BackendNodeId from snapshot"}
                },
                "required": ["key","uid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for",
            "description": "Wait for specific text to appear on the page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "The text to wait for."},
                    "timeout": {"type": "integer", "description": "Timeout in milliseconds (default 1000).","minimum": 100,"default": 1000,"maximum": 10000}
                },
                "required": ["text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take a screenshot of the current page (or a specific element). Captures rendered pixels, so static images, dynamically rendered images and canvas are all visible. The result is shown back to you visually, so you can look at it directly without a separate analyze_image call.",
            "parameters": {
                "type": "object",
                "properties": {
                    "fullPage": {"type": "boolean", "description": "If set to true takes a screenshot of the full page instead of the currently visible viewport. Incompatible with uid."},
                    "uid": {"type": "string", "description": "Crop to this element only (uid like 'ai-12' from the snapshot, or any CSS selector). The element is auto-scrolled into view; no click is performed. Omit to capture the whole viewport."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fill_form",
            "description": "Fill multiple form fields at once efficiently.",
            "parameters": {
                "type": "object",
                "properties": {
                    "elements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "uid": {"type": "string", "description": "The UID of the input element."},
                                "value": {"type": "string", "description": "The value to fill."}
                            },
                            "required": ["uid", "value"]
                        },
                        "description": "List of elements to fill, e.g., [{'uid': 'ai-1', 'value': 'john'}, ...]"
                    }
                },
                "required": ["elements"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "drag",
            "description": "Drag an element from one position to another using UIDs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_uid": {"type": "string", "description": "The UID of the element to drag."},
                    "to_uid": {"type": "string", "description": "The UID of the target element to drop onto."}
                },
                "required": ["from_uid", "to_uid"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "handle_dialog",
            "description": "Handle JavaScript dialogs (alert, confirm, prompt).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["accept", "dismiss"], "description": "Whether to accept or dismiss the dialog."},
                    "promptText": {"type": "string", "description": "Text to enter if the dialog is a prompt."}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_render",
            "description": (
                "用内置浏览器在离屏隐藏页面渲染动态(含JavaScript)网页，并把正文转成 Markdown "
                "返回给你。纯本地、无第三方云端，适合 markdown_new 抓不到的动态页/SPA。"
                "可访问本机或内网地址。若页面需滚动加载或异步渲染，可用 wait_text 指定等待出现的文本。"
                "慢站超时前会尽量返回已加载到的部分内容(标注 partial)。"
                "若站点只向移动端吐内容或弹「打开App/扫码登录」墙，设 mobile=true 用手机UA+视口渲染。"
                "仅 Electron 桌面版且已启用内置浏览器时有效。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "original_url": {
                        "type": "string",
                        "description": "要渲染的完整 URL（http/https）。",
                    },
                    "wait_text": {
                        "type": "string",
                        "description": "可选：等待页面出现该文本后再抽取（用于异步/懒加载内容）。",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "可选：渲染等待秒数（5-60，默认45）。慢站/重站可调大；超时仍会尽量返回部分内容(partial)。",
                    },
                    "mobile": {
                        "type": "boolean",
                        "description": "可选：true=用移动端 UA + 手机视口渲染。针对只向移动端吐内容的站点（手机H5/公众号/贴吧/知乎 App 墙等），可绕开「请打开App/扫码登录」桌面墙。默认 false。",
                    },
                },
                "required": ["original_url"],
            },
        }
    },
    {
        "type": "function",
        "function": {
            "name": "clean_dom",
            "description": (
                "清除当前页上的弹窗/遮罩/Cookie同意条/广告占位（仅 DOM 层，不影响网络）。"
                "多数弹窗已在页面加载时自动软清理；本工具用于按需再次清理或对未及时出现的弹窗做即时清理。"
                "force=true 启用激进档（额外隐藏 modal/paywall/遮罩，可能误伤正文，慎用）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "force": {"type": "boolean", "description": "激进档，默认 false。"},
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "remove_element",
            "description": "从当前页拔除元素：可传快照里的 uid（如 ai-12），或任意 CSS 选择器。",
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "uid（ai-N）或 CSS 选择器（如 '#banner', '.popup-close'）。"},
                },
                "required": ["target"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "stop_loading",
            "description": "急停：停止当前页的加载（页面卡死、被恶意重定向时的逃生手段）。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "escape_back",
            "description": "急停并后退到上一页（从误跳转/误入页面快速撤回）。",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_page_markdown",
            "description": "把当前活动标签页就地清洗并转换为 Markdown 文本返回（本地，无云）。适合读取已在浏览器打开的页面正文。",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_redirect",
            "description": (
                "查询被“重定向护栏”挂起、等待你裁决的页面跳转，返回 [{id,url}] 列表。"
                "仅当用户在设置里开启“重定向护栏”时才会产生挂起；否则返回空列表 []。"
                "你在点击/提交表单后若怀疑发生跳转，可调用本工具查看是否有待裁决跳转，再用 approve_navigation 放行或拦截。"
            ),
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "approve_navigation",
            "description": "对挂起的重定向做出裁决：allow=true 放行该跳转（继续前往目标 URL），false 维持拦截（留在原页）。tab_id 可省略（默认作用于当前活动页/或唯一挂起项）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "allow": {"type": "boolean", "description": "true=放行，false=拦截。默认 true。"},
                    "tab_id": {"type": "integer", "description": "可选：挂起项的 webContents id（来自 redirect_pending 的 id）。"},
                },
                "required": []
            }
        }
    }
]