# -*- coding: utf-8 -*-
"""S139(R6/灵动岛)：灵动岛后端路由（上游 server.py 灵动岛域终态迁 fork routers）。

HTTP：GET/POST /api/heatmap(+increment)、GET /api/weather、/api/ip-city、
/api/geocode、/cur_language（island-app.js 消费）。
WS 卸载：_ws_island() 处理 island_* 8 类消息（enable/disable/music_control/
track_set/poll_music/request_clipboard/write_clipboard/request_tasks，体=上游
server.py 12699-12811 逐字），server /ws 循环仅一条 startswith 分派（S71 惯例）。
notify_island_reply_done()：AI 回复完成后热力图+1 并广播 island_ai_reply_done
（上游 5842-5850 语义：非 sub_agent、异常吞掉）。
媒体执行在 py/dynamic_island.py（三平台自适应）；LLM 工具由 island-app.js 经
register_node_extension_mcp(ext_id=dynamic_island) 自注册，本模块仅桥媒体/剪贴板/待办。
"""
import asyncio
import json
import logging
import os
import platform
import re
import socket
import subprocess
import threading
from datetime import datetime

import aiohttp
from fastapi import APIRouter, WebSocket

from py import proxy_util
from py.dynamic_island import (get_island_tools, island_disable,
                               island_enable as dynamic_island_enable,
                               island_music_next, island_music_pause,
                               island_music_play, island_music_prev,
                               island_music_set_volume, island_track_set,
                               is_island_enabled)
from py.dynamic_island import poll_music_state
from py.get_setting import USER_DATA_DIR, load_settings
from py.ws_manager import ws_manager

router = APIRouter()
_logger = logging.getLogger("app")

# S283（取代 S140 出口策略）：外联接进 SAP 代理体系。S140 只试「直连(trust_env)→
# SAP_PROXY」两路，无视 设置→代理（S85 proxy_util），socks5 又按 S87 规范不入 env，
# 导致开了代理的用户天气/geo 全 timeout。现尝试序：粘滞 → 配置出口
# active_proxy(manual/旧库/system 注册表探测) → 直连(trust_env) → SAP_PROXY →
# direct4(强制 IPv4，治浏览器 Happy-Eyeballs 能开而 python 卡 AAAA 黑洞)。
# socks 型经 aiohttp_socks ProxyConnector 显式接线；settings 缓存 20s；逐路日志；
# 全败清粘滞（出口可能已断，下轮重估）。
_PROXY_TIMEOUT = 8
_settings_cache = {"data": None, "ts": 0.0}
_proxy_state = {"sticky": None}  # ("proxy", url) | ("direct",) | ("direct4",) | None


async def _settings_cached():
    import time
    now = time.time()
    if _settings_cache["data"] is None or now - _settings_cache["ts"] > 20:
        try:
            _settings_cache["data"] = await load_settings()
            _settings_cache["ts"] = now
        except Exception:
            pass  # 拉取失败继续沿用旧缓存，外联不因设置层抖动而停摆
    return _settings_cache["data"] or {}


def _plan_attempts(settings, sticky=None):
    """尝试序（去重保序）：粘滞 → 配置代理 → 直连 → SAP_PROXY → 强制 IPv4 直连。"""
    cands = []
    if sticky:
        cands.append(sticky if isinstance(sticky, tuple) else ("proxy", sticky))
    px = proxy_util.active_proxy(settings)
    if px:
        cands.append(("proxy", px))
    cands.append(("direct",))
    env_raw = os.environ.get("SAP_PROXY")
    if env_raw:
        env_px = proxy_util.normalize_proxy_url(env_raw, warn=False)
        if env_px:
            cands.append(("proxy", env_px))
    cands.append(("direct4",))
    out, seen = [], set()
    for s in cands:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _make_session(strat):
    """(session, proxy_kwarg)——socks 走 ProxyConnector，http 代理走 kw，direct4 限 AF_INET。"""
    kind = strat[0]
    if kind == "proxy" and strat[1].split("://", 1)[0].startswith("socks"):
        from aiohttp_socks import ProxyConnector
        # 装机版 aiohttp_socks 仅认 socks4/socks5；h/a 远端解析变体按协议语义等价降档
        purl = re.sub(r"^socks([45])[ah]://", r"socks\1://", strat[1], count=1)
        return aiohttp.ClientSession(connector=ProxyConnector.from_url(purl),
                                     trust_env=False), None
    if kind == "proxy":
        return aiohttp.ClientSession(trust_env=False), strat[1]
    if kind == "direct4":
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(family=socket.AF_INET), trust_env=False), None
    return aiohttp.ClientSession(trust_env=True), None


def _tag_of(strat):
    return (f"proxy:{proxy_util.mask_proxy_url(strat[1])}"
            if strat[0] == "proxy" else strat[0])


async def _attempt_get(strat, url: str, params: dict = None):
    """单路 GET：返回 (payload|None, err|None)。S284：错误附 str() 摘要（排障可见根因）。"""
    tag = _tag_of(strat)
    try:
        session, proxy_kw = _make_session(strat)
        async with session:
            kw = {"timeout": aiohttp.ClientTimeout(total=_PROXY_TIMEOUT)}
            if proxy_kw:
                kw["proxy"] = proxy_kw
            async with session.get(url, params=params, **kw) as resp:
                if resp.status == 200:
                    return await resp.json(), None
                return None, f"{tag}=HTTP{resp.status}"
    except Exception as e:
        detail = str(e).replace("\n", " ")[:120]
        return None, (f"{tag}={type(e).__name__}({detail})" if detail
                      else f"{tag}={type(e).__name__}")


def _note_sticky(strat, tag):
    if _proxy_state.get("sticky") != strat:
        _proxy_state["sticky"] = strat
        _logger.info(f"[IslandProxy] 外联出口切换：{tag}")


async def _serial_get_json(url, params, cands):
    """S283 串行链：逐路尝试（粘滞优先），全败清粘滞。"""
    errs = []
    for strat in cands:
        payload, err = await _attempt_get(strat, url, params)
        if err is None:
            _note_sticky(strat, _tag_of(strat))
            return payload
        errs.append(err)
    _proxy_state["sticky"] = None
    _logger.warning(f"[IslandProxy] 全路径失败 {url}: " + " | ".join(errs))
    return None


async def _race_get_json(url, params, cands):
    """S284 并发竞速：全路同发、先 200 者胜败者取消；首轮全败 500ms 后二竞速
    （实证网络时通时断，浏览器即靠并发+重试幸存）。胜路粘滞，全败清粘滞。"""
    errs = []
    for round_no in (1, 2):
        errs = []
        tasks = {asyncio.ensure_future(_attempt_get(s, url, params)): s for s in cands}
        pending = set(tasks)
        winner = None
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending, timeout=_PROXY_TIMEOUT + 2, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    errs.append("race=wait-timeout")
                    break
                hit = False
                for t in done:
                    try:
                        payload, err = t.result()
                    except Exception as e:
                        errs.append(f"task={type(e).__name__}")
                        continue
                    if err is None:
                        winner = (tasks[t], payload)
                        hit = True
                        break
                    errs.append(err)
                if hit:
                    break
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
            await asyncio.gather(*tasks.keys(), return_exceptions=True)
        if winner:
            strat, payload = winner
            _note_sticky(strat, _tag_of(strat))
            return payload
        if round_no == 1:
            await asyncio.sleep(0.5)
    _proxy_state["sticky"] = None
    _logger.warning(f"[IslandProxy] 竞速两轮全败 {url}: " + " | ".join(errs))
    return None


async def _external_get_json(url: str, params: dict = None):
    """GET 外联 JSON。S284：systemSettings.islandFetchRace（缺省 True）=并发竞速；
    显式 False 回退 S283 串行逐路。成功返回解析 JSON，全败返回 None。"""
    settings = await _settings_cached()
    ss = settings.get("systemSettings") or {}
    if ss.get("islandFetchRace") is False:
        return await _serial_get_json(url, params,
                                      _plan_attempts(settings, _proxy_state.get("sticky")))
    return await _race_get_json(url, params, _plan_attempts(settings))

# 上游 server.py 逐字（12231-12316 域）
_ip_city_cache = None

HEATMAP_FILE = os.path.join(USER_DATA_DIR, "island_heatmap.json")


def _load_heatmap() -> dict:
    try:
        with open(HEATMAP_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_heatmap(data: dict):
    os.makedirs(os.path.dirname(HEATMAP_FILE), exist_ok=True)
    with open(HEATMAP_FILE, "w") as f:
        json.dump(data, f)


def increment_heatmap():
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load_heatmap()
    data[today] = data.get(today, 0) + 1
    _save_heatmap(data)


async def notify_island_reply_done(is_sub_agent: bool):
    """上游 server.py 5842-5850：主流式回复 DONE 后热力图+1 并通知灵动岛。"""
    if is_sub_agent:
        return
    try:
        increment_heatmap()
        await ws_manager.broadcast({
            "type": "island_ai_reply_done",
            "data": {"text": "活干完啦，快来看看吧！"}
        })
    except Exception:
        pass


@router.get("/api/heatmap")
async def get_heatmap():
    return _load_heatmap()


@router.post("/api/heatmap/increment")
async def post_heatmap_increment():
    increment_heatmap()
    return {"ok": True}


@router.get("/api/ip-city")
async def get_ip_city():
    global _ip_city_cache
    if _ip_city_cache is not None:
        return _ip_city_cache
    # S283：代理出口粘滞时 IP 定位=代理出口城市（非用户位置），禁用该兜底，
    # 让前端保留默认城市/用户手选城市；direct/direct4 直连粘滞=真实出口，可定位。
    _sticky = _proxy_state.get("sticky")
    if isinstance(_sticky, tuple) and _sticky[0] == "proxy":
        return {"city": "", "regionName": "", "country": "", "lat": None, "lon": None}
    data = await _external_get_json("http://ip-api.com/json/")
    if data and data.get("status") == "success":
        _ip_city_cache = {
            "city": data.get("city", ""),
            "regionName": data.get("regionName", ""),
            "country": data.get("country", ""),
            "lat": data.get("lat"),
            "lon": data.get("lon"),
        }
        return _ip_city_cache
    return {"city": "", "regionName": "", "country": "", "lat": None, "lon": None}


@router.get("/api/weather")
async def proxy_weather(lat: float, lon: float, daily: str = None, forecast_days: int = None):
    params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
    if daily:
        params["daily"] = daily
    if forecast_days:
        params["forecast_days"] = str(forecast_days)
    data = await _external_get_json("https://api.open-meteo.com/v1/forecast", params=params)
    if data is not None:
        return data
    return {"error": "weather_fetch_failed"}


@router.get("/api/geocode")
async def proxy_geocode(city: str, lang: str = "zh"):
    data = await _external_get_json(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1, "language": lang},
    )
    if data is not None:
        return data
    return {"error": "geocode_failed"}


def _mouse_state():
    """S289：全局左键态。高位=当前按下；S291：低位=自上次调用以来按下过
    （系统级边沿标志，比采样周期还短的快速点击也不会漏；本端点是全机唯一
    消费者，无争用）。返回 (down, press)；非 Windows 恒 (False, False)。"""
    if platform.system() != "Windows":
        return False, False
    try:
        import ctypes
        v = ctypes.windll.user32.GetAsyncKeyState(0x01) & 0xFFFF
        return bool(v & 0x8000), bool(v & 0x0001)
    except Exception:
        return False, False


@router.get("/api/mouse-state")
async def get_mouse_state():
    down, press = _mouse_state()
    return {"lbtn": down, "lpress": press}


# ---- S294：全局滚轮真相通道（WH_MOUSE_LL 低级钩子，惰性安装，drain 语义）----
# 高 DPI 故障机 Blink 的 wheel 命中同样错位（与点击事故同根源），面板滚动改走
# OS 真值：钩子只累加增量，消费端（HUD 面板）拉取即清零；页面侧自带开面冲刷。
_wheel_lock = threading.Lock()
_wheel_delta = 0
_wheel_installed = False
_wheel_cb_ref = None  # 回调必须持强引用：GC 掉原生钩子指针=随机崩溃


def _wheel_install():
    """首次调用拉起钩子线程（daemon）；装败不重试（重试会反复起线程）。非 Windows 静默。"""
    global _wheel_installed, _wheel_cb_ref
    if _wheel_installed:
        return
    _wheel_installed = True
    if platform.system() != "Windows":
        return
    try:
        import ctypes
        import ctypes.wintypes as wt

        def _pump():
            global _wheel_delta
            user32 = ctypes.windll.user32
            proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, ctypes.c_int, wt.LPARAM)

            def _proc(nCode, wParam, lParam):
                global _wheel_delta
                if nCode == 0 and wParam == 0x020A:  # HC_ACTION + WM_MOUSEWHEEL
                    try:
                        # MSLLHOOKSTRUCT: {POINT pt; DWORD mouseData; ...} mouseData 高16位=带符号滚量
                        md = ctypes.cast(lParam, ctypes.POINTER(ctypes.c_uint32))[2]
                        d = (md >> 16) & 0xFFFF
                        if d >= 0x8000:
                            d -= 0x10000
                        with _wheel_lock:
                            _wheel_delta += d
                    except Exception:
                        pass
                return user32.CallNextHookEx(None, nCode, wParam, lParam)

            cb = proto(_proc)
            _wheel_cb_ref = cb
            h = user32.SetWindowsHookExW(14, cb, ctypes.windll.kernel32.GetModuleHandleW(None), 0)
            if not h:
                return
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))

        threading.Thread(target=_pump, daemon=True, name="wheel-hook").start()
    except Exception:
        pass


@router.get("/api/wheel-state")
async def get_wheel_state():
    _wheel_install()
    global _wheel_delta
    with _wheel_lock:
        d, _wheel_delta = _wheel_delta, 0
    return {"delta": d}


@router.get("/cur_language")
async def cur_language():
    settings = await load_settings()
    target_language = settings["currentLanguage"]
    return {"language": target_language}


async def _ws_island(websocket: WebSocket, msg_type: str, data: dict):
    """island_* 消息卸载处理（体=上游 server.py ws 循环 12699-12811 逐字）。"""
    if msg_type == "island_enable":
        result = dynamic_island_enable()
        _logger.info(f"[DynamicIsland] 前端请求启用: {result}")
        await ws_manager.broadcast({
            "type": "island_state",
            "data": result
        })
        await ws_manager.broadcast({
            "type": "node_ext_mcp_registered",
            "data": {
                "ext_id": "dynamic_island",
                "tools": result.get("tools", [])
            }
        })

    elif msg_type == "island_disable":
        result = island_disable()
        _logger.info(f"[DynamicIsland] 前端请求禁用: {result}")
        await ws_manager.broadcast({
            "type": "island_state",
            "data": result
        })
        await ws_manager.broadcast({
            "type": "node_ext_mcp_unregistered",
            "data": {"ext_id": "dynamic_island"}
        })

    elif msg_type == "island_music_control":
        action = data.get("data", {}).get("action")
        if action == "play":
            result = island_music_play()
        elif action == "pause":
            result = island_music_pause()
        elif action == "next":
            result = island_music_next()
        elif action == "prev":
            result = island_music_prev()
        elif action == "volume":
            level = data.get("data", {}).get("level", 50)
            result = island_music_set_volume(int(level))
        else:
            result = "未知操作"
        await ws_manager.send_json({
            "type": "island_music_result",
            "data": {"action": action, "result": result}
        }, websocket)

    elif msg_type == "island_track_set":
        track_info = data.get("data", {})
        await island_track_set(ws_manager, track_info)

    elif msg_type == "island_poll_music":
        state = await poll_music_state()
        await ws_manager.send_json({
            "type": "island_music_state",
            "data": state
        }, websocket)

    elif msg_type == "island_request_clipboard":
        try:
            if platform.system() == 'Darwin':
                text = subprocess.check_output(['pbpaste'], text=True)
            elif platform.system() == 'Windows':
                text = subprocess.check_output(['powershell', '-Command', 'Get-Clipboard'], text=True)
            else:
                text = subprocess.check_output(['xclip', '-selection', 'clipboard', '-o'], text=True)
        except Exception:
            text = ''
        await ws_manager.send_json({
            "type": "island_clipboard_text",
            "data": text.strip() if text else ''
        }, websocket)

    elif msg_type == "island_write_clipboard":
        text = data.get("data", {}).get("text", "")
        try:
            p = subprocess.Popen(
                ['pbcopy'] if platform.system() == 'Darwin' else (
                    ['powershell', '-Command', 'Set-Clipboard -Value $input'] if platform.system() == 'Windows' else ['xclip', '-selection', 'clipboard']
                ),
                stdin=subprocess.PIPE,
                text=True
            )
            p.communicate(input=text)
        except Exception:
            pass
        await ws_manager.send_json({"type": "island_clipboard_write_result", "data": "ok"}, websocket)

    elif msg_type == "island_request_tasks":
        current_settings = await load_settings()
        workspace_dir = current_settings.get("CLISettings", {}).get("cc_path", "")
        tasks = []
        if workspace_dir:
            from py.task_center import get_task_center
            tc = await get_task_center(workspace_dir)
            raw = await tc.list_tasks()
            for t in raw:
                tasks.append({
                    "task_id": t.task_id,
                    "title": t.title,
                    "description": t.description,
                    "status": t.status.value if hasattr(t.status, 'value') else str(t.status),
                    "progress": t.progress,
                    "agent_type": t.agent_type,
                    "created_at": t.created_at,
                    "started_at": t.started_at,
                    "completed_at": t.completed_at
                })
        await ws_manager.send_json({
            "type": "island_task_list",
            "data": tasks
        }, websocket)


__all__ = ['router', '_ws_island', 'notify_island_reply_done', 'get_island_tools', 'is_island_enabled']
