
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
from py.get_setting import UPLOAD_FILES_DIR, LOG_DIR, get_port, load_settings
from py.proxy_util import active_proxy

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

WVACT_SLOW_MS = 2000  # S235：往返超阈的浏览器动作才落对账行（正常频次不刷屏）


def _wvact_evidence(ms, method_name, ret_preview):
    """S235：与主进程 [ProcHeat] 同一 evidence 文件按时序对账——
    整屏定格时段哪个 webview 动作卡了多久一目了然。小行即写即关，跨进程追加安全。"""
    try:
        line = "%s [WvAct] name=%s ms=%d ret=%s\n" % (
            time.strftime("%Y-%m-%dT%H:%M:%S"), method_name, ms,
            str(ret_preview).replace("\n", " ")[:60])
        with open(os.path.join(LOG_DIR, "frontend-evidence.log"), "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


async def call_vue_method(method_name, args_list=None, timeout=None):
    _t0 = time.monotonic()
    out = await _call_vue_method_impl(method_name, args_list, timeout)
    _ms = int((time.monotonic() - _t0) * 1000)
    if _ms >= WVACT_SLOW_MS:
        _wvact_evidence(_ms, method_name, out)
    return out


async def _call_vue_method_impl(method_name, args_list=None, timeout=None):
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
            if method_name == "renderOffscreenPage":
                return ("web_render 超时：页面 JS 过重或站点很慢，渲染器未吐可用 DOM，本轮无可返回的部分正文。"
                        "这通常与已开标签数无关，别靠减标签解决——改走 simple_fetch/markdown_new（只要静态文本时最快），"
                        "或 new_page 单独开标签 + wait_for(text/selector) 等就绪后 get_page_markdown。")
            return ("浏览器操作超时：渲染主线程繁忙——通常是某个重 JS 页面霸占渲染进程，与打开标签「数量」关系不大。"
                    "处置：list_pages 查看各标签，close_page(tab_id) 关掉疑似卡死的页面，或稍候 30s 重试；"
                    "本次操作未生效，可安全重发。")
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

async def _proxy_egress_precheck(use_proxy):
    """S236：use_proxy=true 但设置未配置可用代理 → 返回报错文案；None=放行。"""
    if not use_proxy:
        return None
    try:
        if not active_proxy(await load_settings()):
            return ("[Error] use_proxy=true 但应用未配置可用代理："
                    "请先在 设置→系统→代理 填写（http/socks5 均可）后重试，或改用默认直连。"
                    "(No valid proxy configured in Settings -> System -> Proxy.)")
    except Exception:  # noqa: BLE001
        return None  # 预检自身故障不拦调用
    return None


async def new_page(url, timeout=0, background=False, mobile=False, use_proxy=False):
    """新建标签页；background=True 时后台打开（不抢占用户可见面板）；mobile=True 用移动端 UA + 手机视口渲染；
    use_proxy=True 走应用内代理分区（默认直连分区，不受系统代理影响）。"""
    err = await _proxy_egress_precheck(use_proxy)
    if err:
        return err
    partition = "persist:agent-proxy" if use_proxy else "persist:agent-direct"
    if background:
        res = await call_vue_method('openUrlInBackground', [url, partition])
    else:
        res = await call_vue_method('openUrlInNewTab', [url, partition])
    if mobile:
        try:
            await call_vue_method('setTabMobile', [None, True, True])
        except Exception:  # noqa: BLE001
            pass
    return res

async def _resolve_tab_index(tab_id):
    """S247: 稳定 tab_id（list_pages 的 id）→ 当前 index。返回 (index, None) 或 (None, 报错)。"""
    try:
        info = await call_vue_method('getPagesInfo', [])
        info = json.loads(info) if isinstance(info, str) else info
    except Exception as e:  # noqa: BLE001
        return None, f"[Error] tab_id 解析失败: {e!r}"
    for t in info or []:
        if isinstance(t, dict) and t.get("id") == tab_id:
            return t.get("index"), None
    return None, (f"[Error] tab_id {tab_id} 不存在（标签已关闭？）。"
                  "注意：tab_id 必须是 list_pages 返回的长整型 id（如 1234567），不是 0 起的列表下标——"
                  "下标请填 pageIdx。用 list_pages 重新获取；id 跨轮稳定，index 会随开关标签平移。")


async def close_page(pageIdx=None, tab_id=None):
    """关闭标签页；tab_id（list_pages 的 id，跨轮稳定）优先于 pageIdx。"""
    if tab_id is not None:
        idx, err = await _resolve_tab_index(tab_id)
        if err:
            return err
        pageIdx = idx
    if pageIdx is None:
        return "[Error] close_page: 需要 pageIdx 或 tab_id 之一。"
    return await call_vue_method('closeTabByIndex', [pageIdx])

async def select_page(pageIdx=None, bringToFront=True, tab_id=None):
    """选择/切换标签页；tab_id（list_pages 的 id，跨轮稳定）优先于 pageIdx。"""
    if tab_id is not None:
        idx, err = await _resolve_tab_index(tab_id)
        if err:
            return err
        pageIdx = idx
    if pageIdx is None:
        return "[Error] select_page: 需要 pageIdx 或 tab_id 之一。"
    return await call_vue_method('switchTabByIndex', [pageIdx])

async def navigate_page(type="url", url=None, ignoreCache=False, timeout=8, mobile=None, tab_id=None):
    """页面导航（默认作用于活动标签；传 tab_id 先原子切换过去再导航）。
    默认等待页面加载完成（最多 timeout 秒，加载完成即提前返回），结果带 (loaded)/(still loading)；timeout=0 不等待立即返回。
    mobile=True/False 切换当前标签页移动/桌面模式（None 不改，移动模式需重新加载才生效）。"""
    if tab_id is not None:
        r = await select_page(tab_id=tab_id)
        if isinstance(r, str) and r.startswith("[Error]"):
            return r
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

async def scroll_and_find(match, action="none", max_scrolls=30, pause_ms=700, attribute=""):
    """S253: 虚拟滚动列表（贴吧/信息流：卡片无 href、滚出视口即卸载、点击才路由）的
    滚动搜索原语——滚动到目标挂载即命中，click 触发 SPA 路由并返回新 URL，
    extract 抠 href/data-*，none 仅报告命中。替代手搓滚动+轮询的十几次往返。"""
    try:
        rounds = max(1, min(int(max_scrolls), 100))
    except (TypeError, ValueError):
        rounds = 30
    try:
        pause = max(200, min(int(pause_ms), 4000))
    except (TypeError, ValueError):
        pause = 700
    budget = min(rounds * pause // 1000 + 45, 300)
    return await call_vue_method('scrollAndFind',
                                 [match, action, rounds, pause, attribute], timeout=budget)


_PULL_POLLUTED_PREFIX = ("Error executing", "Failed networkWatch", "networkWatch err:",
                         "浏览器操作超时", '{"jsonrpc"', "[Unknown Tool]", "Success")


def _pull_polluted(body):
    """S256：pull 失败时 call_vue_method 会回错误文案/超时提示——这类文本绝不能当成
    响应体落盘（agent 曾因此拿到『Vue 包装返回』伪文件）。含截断标记的半截 JSON 同理。"""
    if not isinstance(body, str) or not body:
        return True
    s = body.lstrip()
    return (s.startswith(_PULL_POLLUTED_PREFIX)
            or "[S106 truncated" in s[-96:]
            or s.startswith("Operation completed (Type:"))


async def network_watch(mode="start", pattern="", include_body=False):
    """S253: 内置网络观察器——start 挂 fetch/XHR 钩子（页面导航后需重挂）→ 操作页面 →
    read 增量收割 {url,status[,body 预览≤2KB]}（pattern 子串过滤）；stop 清空并解除。
    S254: include_body=True 时全量响应体留在页面侧，read 中超长正文自动落盘为
    uploaded_files 文件并回 body_url——完整 JSON 可用 load_files/终端 grep 读，不再 2KB 截断。
    S257: 落盘条目另附 body_path（本地绝对路径，read_file_range_tool_local 直读、免 token）；
    read 总返回硬性压在 S184 工具输出限额（20KB）之下——超限则收割清单整体落盘回路径，
    避免被 S184 截断成 .agent/tool_output 相对路径 marker 反而弄丢引用。"""
    if str(mode or "").lower() not in ("start", "read", "stop"):
        return "[Error] network_watch: mode 需 start|read|stop"
    m = str(mode).lower()
    res = await call_vue_method('networkWatch', [m, str(pattern or ""), bool(include_body), 0],
                                timeout=30)
    if m == "read" and isinstance(res, str) and res.strip().startswith("{"):
        try:
            import hashlib as _hl
            import os as _os
            d = json.loads(res)
            items = d.get("items") if isinstance(d, dict) else None
            overs = [it for it in (items or [])
                     if isinstance(it, dict) and int(it.get("blen") or 0) > 2048][:4]
            origin = str(d.get("origin") or "").strip()
            saved = failed = 0
            for it in overs:
                try:
                    body = await call_vue_method(
                        'networkWatch', ["pull", "", False, int(it.get("gi") or -1)], timeout=45)
                    if _pull_polluted(body):
                        it["b_err"] = ("全文拉取失败（渲染进程忙/被截断，非响应体内容），预览 b 仍有效；"
                                       "稍后重读 read 再取 body_url")
                        failed += 1
                        continue
                    _os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
                    fn = "net_" + _hl.md5(body.encode("utf-8", "ignore")).hexdigest()[:16] + ".json"
                    fp = _os.path.join(UPLOAD_FILES_DIR, fn)
                    with open(fp, "w", encoding="utf-8") as f:
                        f.write(body)
                    it["body_path"] = fp
                    # 127.0.0.1 写死：本机工具调用方，HOST 配成 0.0.0.0/局域网 IP 时反而不可用
                    it["body_url"] = f"http://127.0.0.1:{get_port()}/uploaded_files/{fn}"
                    if isinstance(it.get("b"), str):
                        it["b"] = it["b"][:200]  # 全文已在盘上，预览占位即可（S257 返回瘦身）
                    it["b_note"] = (f"完整正文 {it.get('blen')} 字节已存 body_path"
                                    "（read_file_range_tool_local/grep 直读，免鉴权）；"
                                    "body_url 为同文件 HTTP 形式")
                    saved += 1
                except Exception:  # noqa: BLE001
                    it["b_err"] = "全文拉取异常，预览 b 仍有效；可稍后重试 read"
                    failed += 1
            extra = ""
            if saved:
                extra += (f"；{saved} 条超长响应已落盘（各项 body_path/body_url），本地读路径最方便，"
                          "不必再手搓 fetch 钩子")
            if failed:
                extra += f"；{failed} 条全文拉取失败（b_err 说明），稍后可再 read 重试"
            if origin:
                extra += f"；数据抓取自 {origin}——正文里的相对路径资源（如 /emotions/xx.gif）需拼该域名"
            if extra:
                d["note"] = (str(d.get("note") or "") + extra).lstrip("；")
            payload = json.dumps(d, ensure_ascii=False)
            if len(payload.encode("utf-8", "ignore")) > 17000 and isinstance(items, list) and items:
                # S184 限额 20000B——超线会被"output truncated+.agent 相对路径"接管，
                # 连 body_path 一起丢（S257 事故根因）。改为收割清单整体落盘+紧凑摘要。
                try:
                    _os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
                    fn2 = ("net_read_" + _hl.md5(payload.encode("utf-8", "ignore")).hexdigest()[:16]
                           + ".json")
                    fp2 = _os.path.join(UPLOAD_FILES_DIR, fn2)
                    with open(fp2, "w", encoding="utf-8") as f:
                        f.write(payload)
                    brief = []
                    for it in items[:8]:
                        if isinstance(it, dict):
                            brief.append({k: str(it.get(k))[:120] for k in ("u", "s", "blen")
                                          if it.get(k) is not None})
                    d2 = {"total": d.get("total"), "new_items": d.get("new_items"),
                          "returned": 0, "items": brief,
                          "note": (f"本次收割 {len(items)} 条超返回限额，完整清单（含各条 "
                                   f"b 预览与 body_path/body_url）已存 {fp2}"
                                   "——用 read_file_range_tool_local 或 search_files_tool_local"
                                   "（path 传该绝对路径）读；想直接拿数据可加大 pattern 缩小增量再 read")}
                    if origin:
                        d2["note"] += f"；数据源 {origin}（相对路径资源拼该域名）"
                    res = json.dumps(d2, ensure_ascii=False)
                except Exception:  # noqa: BLE001
                    res = payload
            else:
                res = payload
        except Exception:  # noqa: BLE001
            pass
    return res


async def wait_for(text=None, selector=None, js=None, timeout=1000):
    """S246: 等待页面条件——text(文本出现)/selector(CSS 命中)/js(谓词表达式 truthy) 三选一。"""
    picked = [v for v in (text, selector, js) if v]
    if len(picked) != 1:
        return "[Error] wait_for: 请且仅传 text / selector / js 三者之一。"
    mode = "text" if text else ("selector" if selector else "js")
    expr = text or selector or js
    return await call_vue_method('webviewWaitFor', [expr, int(timeout), mode])

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

async def web_render(original_url, wait_text=None, timeout=45, mobile=False, use_proxy=False, focus=""):
    """用内置浏览器在离屏隐藏 webview 渲染动态(含JavaScript)页面，本地转 Markdown 回传，无云。

    仅 Electron 桌面版且启用内置浏览器时有效；可访问本机/内网地址（异于云端 markdown_new）。
    慢站超时前会尽量回传已加载到的部分内容(标注 partial)；重站可加大 timeout 或用 wait_text 等关键文本。
    mobile=True 用移动端 UA + 手机视口渲染（针对移动端 H5/公众号/贴吧/知乎等只给移动端内容的站点）。
    默认直连（不受系统全局代理影响）；use_proxy=True 走应用内代理（需先在设置配置）。
    """
    url = (original_url or "").strip()
    if not url:
        return "[Error] web_render: 缺少 url。"
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    err = await _proxy_egress_precheck(use_proxy)
    if err:
        return err
    if not await get_targets():
        return ("[Error] 内置浏览器通道不可用：仅 Electron 桌面版且已启用“内置浏览器”时有效。"
                "可改用 markdown_new / simple_fetch 等抓取工具。")
    t = int(timeout or 45)
    t = max(5, min(t, 60))
    opts = {"waitText": wait_text or "", "timeout": t, "mobile": bool(mobile),
            "useProxy": bool(use_proxy)}
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
            hint = ("超时未加载完成：站可能很慢或被墙。内置浏览器默认直连——"
                    "若目标需 VPN 出口可设 use_proxy=true（需先在 设置→系统→代理 配置）；"
                    "也可加大 timeout、提供 wait_text，或改用可直连的镜像/来源。")
        elif "no-content" in e:
            hint = "已连接但未抓到正文：可能需登录或被反爬，可加 wait_text 指定正文关键句后重试。"
        elif "wait-text-timeout" in e:
            hint = "等待的 wait_text 未出现：文本可能不对或被延迟，校正 wait_text 或加大 timeout；若连占位内容都没抓到，多为 SPA 数据请求被拒/未发出。"
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
    reason = str(data.get("reason") or "")
    # S248: Python 侧兜底——Vue 漏判的骨架屏短文本也拒绝宣告完整
    if not partial and not reason and len(md.replace(" ", "").replace("\n", "")) < 300 and _STALL_PAT.search(md):
        partial, reason = True, "async_load_stalled"
    src = f"Source: {final_url} (partial)" if partial else f"Source: {final_url}"
    head = f"# {title}\n{src}\n\n" if title else f"{src}\n\n"
    if partial:
        if reason == "wait_text_not_seen":
            head += "> 注意：wait_text 未出现，以下为超时前抓到的内容，大概率仍是占位/未加载完。请看尾部 [net-diag] 判断数据请求是被拒还是未发出。\n\n"
        else:
            head += "> 注意：页面疑似异步未加载完（骨架屏/占位），以下为已抓内容，非完整正文。可加大 timeout、改用内置浏览器标签+take_snapshot，并看尾部 [net-diag]。\n\n"
    wall = bool(_WALL_PAT.search(md[:6000]))
    captcha = bool(_CAPTCHA_PAT.search(md[:6000]))
    focus_s = str(focus or "").strip()
    if focus_s and not captcha:
        from py.text_focus import focus_blocks
        blocks, total = focus_blocks(md, focus_s, 6)
        if total:
            return head + blocks + _page_meta(wall, partial, reason, data.get("net"),
                                              data.get("ua"), data.get("cookieLen"), False)
        head += f"> 注意：focus '{focus_s}' 未在正文中命中（以下为全文）；可换关键词，或注意上方 partial/wall 状态。\n\n"
    return head + md + _page_meta(wall, partial, reason, data.get("net"), data.get("ua"),
                                   data.get("cookieLen"), captcha)


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


_WALL_PAT = re.compile(r"(扫码登录|请先登录|登录后查看|登录后可见|登录查看全部|登录查看更多"
                       r"|please log\s?in|sign\s?in to (view|continue))", re.I)


def _wall_hint(wall: bool, captcha: bool = False) -> str:
    if captcha:
        return "\n\n[page-meta] captcha_detected=true" + _CAPTCHA_HINT
    if not wall:
        return "\n\n[page-meta] login_wall_detected=false（以上应为完整正文）"
    return ("\n\n[page-meta] login_wall_detected=true"
            "——检测到登录墙信号：正文可能被软墙截断，「看不到更多」≠「抓完了」；"
            "考虑在内置浏览器标签登录（与 web_render/本工具共享登录态）后重试。")


# S249: 验证码/安全验证页信号（文本级兜底；guest 侧还有组件级检测）
_CAPTCHA_PAT = re.compile(r"(安全验证|拖动滑块|滑动验证|完成验证|点击按钮开始验证|输入验证码后|请完成下方验证"
                          r"|bfe_punish|verifycode|bdverify)")
_CAPTCHA_HINT = (" —— 检测到验证码/安全验证页：需人工处理。请提示用户在内置浏览器标签中手动完成验证"
                 "（移动端视口裁剪与坐标已修复，可直接点击），暂停交互、勿用 evaluate_script 硬解，通过后再重试。")


# S248：骨架屏/异步未加载完关键词（md 文本级兜底，配合 Vue 侧 isStalled）
_STALL_PAT = re.compile(r"(玩命加载|正在加载|加载中|页面加载中|请稍候|loading\.{0,3}|Loding)", re.I)


def _net_diag(net) -> str:
    """S248: SPA 数据请求诊断行——总数常附，仅在有 4xx/5xx/失败时列明细（体积受控）。"""
    try:
        rows = [r for r in (net or []) if isinstance(r, dict)]
    except Exception:  # noqa: BLE001
        rows = []
    if not rows:
        return ""
    line = f"\n\n[net-diag] reqs={len(rows)} (dom-ready 后捕获)"
    bad = []
    for r in rows:
        try:
            st = int(r.get("s") or 0)
        except (TypeError, ValueError):
            st = 0
        if st >= 400 or st == -1:
            bad.append(r)
    if bad:
        uniq = {}
        for r in bad:
            key = f"{str(r.get('u'))[:110]} ({'failed' if r.get('s') == -1 else r.get('s')})"
            uniq[key] = uniq.get(key, 0) + 1
        line += "; failures: " + "; ".join(f"{k}×{v}" if v > 1 else k for k, v in list(uniq.items())[:8])
        line += " —— 4xx/被拒=风控或鉴权问题(考虑登录态/mobile/换源)；failed=连接层被断"
    return line[:1500]


def _page_meta(wall: bool, partial: bool = False, reason: str = "", net=None, ua="", cookie_len=None,
               captcha: bool = False) -> str:
    """S248: web_render 结构化尾行——只有真完整才宣告完整；附 net 诊断与 ctx 自证行。S249: captcha 信号。"""
    if captcha:
        out = "\n\n[page-meta] captcha_detected=true" + _CAPTCHA_HINT
        out += _net_diag(net)
        if ua:
            cl = cookie_len if isinstance(cookie_len, int) else 0
            out += f"\n[ctx] ua={str(ua)[:60]} cookie_len={cl}"
        return out
    parts = ["login_wall_detected=" + ("true" if wall else "false")]
    if partial or reason:
        parts.append("partial=true reason=" + (reason or "timeout"))
    out = "\n\n[page-meta] " + " ".join(parts)
    if wall:
        out += ("——检测到登录墙信号：正文可能被软墙截断，「看不到更多」≠「抓完了」；"
                "考虑在内置浏览器标签登录（与 web_render/本工具共享登录态）后重试。")
    elif partial or reason:
        if reason == "wait_text_not_seen":
            out += "（wait_text 未出现，以上大概率仍是占位/未加载完，非完整正文；看 [net-diag] 定位数据请求成败）"
        else:
            out += "（疑似骨架屏/异步未加载完，非完整正文；加大 timeout 或改用内置浏览器标签+take_snapshot，并看 [net-diag]）"
    else:
        out += "（以上应为完整正文）"
    out += _net_diag(net)
    if ua:
        cl = cookie_len if isinstance(cookie_len, int) else 0
        out += f"\n[ctx] ua={str(ua)[:60]} cookie_len={cl}（cookie_len>0 且 ua 与请求参数一致=分区/UA 生效）"
    return out


async def get_page_markdown():
    """S246: meta 化——附 url/title 与登录墙信号，让 agent 明确"内容没了"还是"抓完了"。"""
    res = await call_vue_method('getPageHtml', [])
    s = res if isinstance(res, str) else json.dumps(res or {})
    if s.startswith("Error"):
        return s
    html, url, title, wall = s, "", "", False
    try:
        d = json.loads(s)
    except Exception:  # noqa: BLE001
        d = None
    if isinstance(d, dict) and "html" in d:  # 新版结构化返回；旧版纯 html 串走兜底
        html = d.get("html") or ""
        url = d.get("url") or ""
        title = (d.get("title") or "").strip()
        wall = bool(d.get("wallTxt")) or (int(d.get("wallN") or 0) > 0)
    md = html_to_md.html_to_markdown(html, max_chars=120000)
    if not wall:
        wall = bool(_WALL_PAT.search(md[:4000]))
    captcha = bool(_CAPTCHA_PAT.search(md[:6000]))
    if not md.strip():
        return "[Empty] 当前页无可抽取正文（可能需登录或纯 SPA 未渲染出内容）。" + _wall_hint(wall, captcha)
    head = (f"# {title}\n" if title else "") + (f"Source: {url}\n\n" if url else "")
    return head + md + _wall_hint(wall, captcha)


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
            "description": ("Get a list of pages open in the browser. Each page has a STABLE `id` (survives other tabs "
                            "opening/closing) and an unstable positional `index` — prefer passing the id as `tab_id` to "
                            "select_page/close_page/navigate_page when addressing a specific tab."),
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "new_page",
            "description": "Creates a new page in the browser tab bar. Network egress is chosen at creation: direct by default, or the app proxy with use_proxy=true. The new tab becomes active; call list_pages to get its stable `id` for reliable tab_id addressing later.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to load"},
                    "timeout": {"type": "integer"},
                    "background": {"type": "boolean", "description": "true=后台打开新标签，不抢占用户可见面板（默认 false）。"},
                    "mobile": {"type": "boolean", "description": "true=用移动端 UA + 手机视口打开（针对只给移动端内容/有App墙的站点）。默认 false。"},
                    "use_proxy": {"type": "boolean", "description": "true=本标签走应用内代理（设置→系统→代理 填的地址）；默认 false=直连——对国内站/本机内网地址正确，且不受系统全局代理(翻墙软件改系统代理时 Electron 行为异常)影响。仅目标确需 VPN 出口（如 Google、X）时设 true；设置里未配置可用代理时会直接报错。出口在创建时定死，想换用 close_page + new_page(use_proxy) 重建。"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_page",
            "description": "Closes the page by tab_id (stable, from list_pages — preferred) or pageIdx (positional, shifts as tabs open/close).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pageIdx": {"type": "integer", "description": "Index of the page to close"},
                    "tab_id": {"type": "integer", "description": "Stable tab id from list_pages (takes precedence over pageIdx)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "select_page",
            "description": "Switch tab to a page by tab_id (stable, from list_pages — preferred) or pageIdx (positional, shifts as tabs open/close).",
            "parameters": {
                "type": "object",
                "properties": {
                    "pageIdx": {"type": "integer"},
                    "bringToFront": {"type": "boolean"},
                    "tab_id": {"type": "integer", "description": "Stable tab id from list_pages (takes precedence over pageIdx)"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "navigate_page",
            "description": "Navigates a page — the ACTIVE tab by default, or a specific tab via tab_id (stable id from list_pages; it is switched to first, then navigated — avoids wrong-tab bugs caused by pageIdx shifting when tabs open/close). By default it WAITS for the page to finish loading (up to `timeout` seconds, returns early when done) and the result ends with '(loaded)' or '(still loading)' — so you can usually take_snapshot right after without a separate wait. Pass timeout=0 to return immediately (old fire-and-forget behavior). Set mobile=true/false to switch the tab between mobile (phone UA + viewport) and desktop rendering before navigating. The tab's network egress (direct vs app proxy) is fixed at creation via new_page(use_proxy); navigation keeps the current egress.",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["url", "back", "forward", "reload"]},
                    "url": {"type": "string"},
                    "ignoreCache": {"type": "boolean"},
                    "timeout": {"type": "integer", "description": "等待页面加载完成的秒数（0-30，默认 8）。加载完成会提前返回；超时返回 (still loading)，可再 wait_for/take_snapshot。0=不等待立即返回。"},
                    "mobile": {"type": "boolean", "description": "true=以移动端模式导航（手机UA+手机视口，绕过App墙/拿移动端内容）；false=恢复桌面；省略=不改变当前模式。"},
                    "tab_id": {"type": "integer", "description": "稳定 tab id（list_pages 的 id）：先切到该标签再导航，跨轮安全；省略=操作活动标签"}
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
            "description": "Get the accessibility tree of the current page to find UIDs for interaction. Besides interactive elements it also lists content images/canvas with UIDs (alt/size/loaded/offscreen and their source `url=` — pass those urls to view_images to actually SEE the images first-hand), so you can target them with take_screenshot(uid) or remove_element(uid). Image `url=` resolves lazy-loading placeholders: real addresses from `_src`/`data-src`/`data-actualsrc` attrs win over the placeholder `src`; S259: in-page-only sources (blob:/data:) deliberately show '[已渲染但无外部URL：用 take_screenshot(uid) 查看]' instead of a URL — feed such uids to take_screenshot (pixel capture, no URL needed) and do NOT hand blob:/data: links to view_images, they are unreachable outside the page. If the page is still loading it waits up to ~3s; if still not done it returns a possibly-PARTIAL snapshot ending with '(note: page still loading...)'. Tip: call right after navigate_page, which already waits for load by default. UID_EXPIRED / 'Element not found' after an interaction means the page DOM rebuilt and old UIDs died — just re-take_snapshot. If the snapshot ends with '[page-meta] captcha_detected=true' the page is a CAPTCHA/security-check: STOP automating it, ask the user to complete the check manually in the built-in browser tab (mouse clicks work there now), then resume — do not try to solve it via evaluate_script. SPA virtual-list sites (tieba/weibo feeds) often have NO hrefs on cards (click-only routing, cards unmount off-screen): use scroll_and_find(match=title, action='click') instead of scraping links from static DOM, and network_watch to grab list-API JSON if rendering won't cooperate; do NOT hammer site search APIs (they trigger risk-control CAPTCHAs).",
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
            "description": ("Wait for a page condition. Pass EXACTLY ONE of: text (substring appears in body), "
                            "selector (CSS selector matches an element — for 'wait for DOM structure'), or "
                            "js (JS predicate expression polled every 250ms until truthy — e.g. "
                            "\"document.querySelectorAll('.post').length>3\" or \"document.readyState==='complete'\"; "
                            "approximate network-idle via a readyState+contentStability predicate in js)."),
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "Text to wait for (mutually exclusive with selector/js)."},
                    "selector": {"type": "string", "description": "CSS selector to wait for (mutually exclusive)."},
                    "js": {"type": "string", "description": "JS predicate expression, waits until truthy (mutually exclusive)."},
                    "timeout": {"type": "integer", "description": "Timeout in milliseconds (default 1000).","minimum": 100,"default": 1000,"maximum": 30000}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "scroll_and_find",
            "description": ("S253: 滚动搜索原语——针对 SPA 虚拟滚动列表（贴吧吧列表、微博/信息流等：卡片滚出视口即卸载、"
                            "常无真实 href、点击才路由），自动逐屏向下滚动等新卡片挂载，命中即停。"
                            "这是此类站点『从列表进入某帖』的正确姿势：一次调用替代手搓 滚动+MutationObserver+XHR钩子+翻页探测 的几十次往返。"
                            "贴吧示例：scroll_and_find(match='让CMG把控教育', action='click') → 返回 url_after 即帖子地址，随后 web_render/get_page_markdown 读楼。"
                            "S254 人机等价：滚动用真滚轮输入事件(CDP isTrusted，浏览器命中测试自动路由到页面真正可滚的内层容器，"
                            "window.scrollBy 滚不动的 uniapp/虚拟列表页也能滚)、点击用真鼠标事件——返回 scroller_mode 说明所用通道"
                            "(wheel=真滚轮/container=内层容器/window)。"
                            "action=click 真点击命中卡片并等 SPA 路由返回新 URL，URL 不变会自动改点卡内标题/链接子目标再试；"
                            "action=extract 抠卡片 href 或 attribute 指定属性；action=none 仅报告命中。"
                            "未命中会返回滚动深度——可换 match 措辞/加大 max_scrolls，或改 network_watch 抓列表接口 JSON。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "match": {"type": "string", "description": "CSS 选择器（querySelector 命中即用）或目标可见文本（匹配最小含文本小块）。贴吧找帖直接填帖子标题片段。"},
                    "action": {"type": "string", "enum": ["none", "click", "extract"], "description": "click=合成点击并等新路由URL（虚拟列表进帖首选）；extract=抠href/attribute；none=仅报告。默认 none。"},
                    "max_scrolls": {"type": "integer", "description": "最多滚动轮数（1-100，默认30）。"},
                    "pause_ms": {"type": "integer", "description": "每轮滚动后等待挂载的毫秒数（200-4000，默认700）。慢站调大。"},
                    "attribute": {"type": "string", "description": "action=extract 时要抠的属性名（如 data-url），省略则抠 href。"}
                },
                "required": ["match"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "network_watch",
            "description": ("S253: 内置网络观察器（替代手搓 XHR/fetch 钩子）。start=给当前标签页挂 fetch/XHR 钩子（幂等；"
                            "S258: start 过一次之后每次导航 dom-ready 自动重挂，无需再手动 start；"
                            "导航进行中已发出的请求收不到——要全量就 start 后 reload 再操作）→ 然后 navigate/滚动/点击让页面自己发请求 → "
                            "read=增量收割 {url,status[,b=body预览2KB]}（pattern 按 URL 子串过滤，如 'newpostlist'；每次只返回上次 read 之后的新条目）。"
                            "适合『页面渲染不出但数据在接口里』的场景：抓列表/详情接口 JSON 直接拿 tid/数据。"
                            "S254/S257: include_body=true 时响应体全量保留，read 中 blen>2048 的条目自动落盘并附 body_path"
                            "（本地绝对路径——read_file_range_tool_local/grep 直读，免 token，首选）+body_url+blen，"
                            "收割总量超返回限额时完整清单自动整体落盘回路径，永不被截断；无需再手搓钩子。"
                            "stop=清空并停用。"),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["start", "read", "stop"], "description": "start 挂钩 / read 增量收割 / stop 清空停用。"},
                    "pattern": {"type": "string", "description": "read 时按 URL 子串过滤（如 'newpostlist'），省略返回全部新条目。"},
                    "include_body": {"type": "boolean", "description": "start 时是否记录响应体（全量保留；read 回 2KB 预览，超长自动落盘给 body_url）。默认 false。抓数据用 true。"}
                },
                "required": ["mode"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "take_screenshot",
            "description": "Take a screenshot of the current page (or a specific element). Captures rendered pixels, so static images, dynamically rendered images and canvas are all visible. FIRST-HAND vision (一手视觉): the result is shown back to you visually, so you can look at it directly without any secondhand VLM paraphrase. Prefer this and view_images over secondhand_* vision tools unless a text paraphrase is explicitly required.",
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
                "可访问本机或内网地址。SPA 骨架屏（加载中占位）会被自动识别并继续等待数据加载，不会把占位符当正文返回；"
                "若页面需滚动加载或异步渲染，可用 wait_text 指定等待出现的文本（超时也会带回已抓内容并标 reason=wait_text_not_seen）。"
                "慢站超时前会尽量返回已加载到的部分内容(标注 partial + reason)。"
                "输出尾部附 [net-diag]（dom-ready 后页面 XHR/fetch 请求成败，4xx=数据被风控拒）与 [ctx]（实际 UA/cookie 长度自证），"
                "SPA 拿到骨架屏时先看 net-diag 定位是请求被拒还是未发出，再决定换 mobile/登录/换源。"
                "若站点只向移动端吐内容或弹「打开App/扫码登录」墙，设 mobile=true 用手机UA+视口渲染。"
                "与内置浏览器 agent 标签共享登录态（同一持久分区，cookie 通用）：需要登录的站点可先用"
                " new_page/navigate_page 在标签里完成登录，本工具随即可见登录后的内容。"
                "默认直连访问（不受系统全局代理影响）；目标需 VPN 出口（如 Google、X）时设 use_proxy=true 走应用内代理。"
                "只要页面里的特定信息时传 focus=关键词：命中则返回 ±6 行聚焦块（带 @全文x%/行号 定位）替代整页正文。"
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
                    "use_proxy": {
                        "type": "boolean",
                        "description": "可选：true=本次渲染走应用内代理（设置→系统→代理 填的地址）；默认 false=直连——对国内站/本机内网地址正确，且不受系统全局代理(翻墙软件改系统代理时 Electron 行为异常)影响。仅目标确需 VPN 出口（如 Google、X）时设 true；设置里未配置可用代理时会直接报错。",
                    },
                    "focus": {
                        "type": "string",
                        "description": "可选：聚焦关键词（字面匹配）。命中时返回 ±6 行命中块（带 @全文x%/行号 定位）替代整页正文，适合大页查特定信息；未命中自动回退全文并提示。",
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
            "description": ("把当前活动标签页就地清洗并转换为 Markdown 文本返回（本地，无云）。适合读取已在浏览器打开的页面正文。"
                            "内容图以 ![](url) 保留（可把 url 交给 view_images 一手查看）；输出尾部附 [page-meta] "
                            "登录墙信号行，据此判断是抓完了还是被软墙截断。"),
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