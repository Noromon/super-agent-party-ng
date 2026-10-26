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
import json
import logging
import os
import platform
import subprocess
from datetime import datetime

import aiohttp
from fastapi import APIRouter, WebSocket

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

# S140：部分网络环境下 aiohttp 直连 open-meteo/ip-api 不稳，且 aiohttp 不读系统
# 代理配置。外联统一走 _external_get_json：直连（trust_env 尊重标准代理环境变量，
# 含设置中已应用的代理）→ 显式代理回退（SAP_PROXY 指定），成功后粘滞。
_PROXY_TIMEOUT = 8
_FALLBACK_PROXIES = ()  # 无内置默认代理；需显式回退时经 SAP_PROXY 配置
_proxy_state = {"sticky": None}


def _attempt_order():
    env = os.environ.get("SAP_PROXY")
    fallbacks = [env] if env else list(_FALLBACK_PROXIES)
    sticky = _proxy_state.get("sticky")
    if sticky:
        return [sticky, None] + [p for p in fallbacks if p != sticky]
    return [None] + fallbacks


def _note_success(proxy):
    if _proxy_state.get("sticky") != proxy:
        _proxy_state["sticky"] = proxy
        _logger.info(f"[IslandProxy] 外联出口切换：{'direct' if not proxy else proxy}")


async def _external_get_json(url: str, params: dict = None):
    """GET 外联 JSON：按 _attempt_order 逐路尝试；成功返回解析 JSON，全败返回 None。"""
    last_err = None
    for proxy in _attempt_order():
        try:
            async with aiohttp.ClientSession(trust_env=True) as session:
                kw = {"timeout": aiohttp.ClientTimeout(total=_PROXY_TIMEOUT)}
                if proxy:
                    kw["proxy"] = proxy
                async with session.get(url, params=params, **kw) as resp:
                    if resp.status == 200:
                        _note_success(proxy)
                        return await resp.json()
                    last_err = f"HTTP {resp.status}"
        except Exception as e:
            last_err = type(e).__name__
    _logger.warning(f"[IslandProxy] 全路径失败 {url}: {last_err}")
    return None

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
    # S140：走统一代理回退出口（原实现 5s 直连无回退）。出口为本机代理时 IP 定位=
    # 代理出口城市（非用户位置），禁用该兜底，让前端保留默认城市/用户手选城市。
    if _proxy_state.get("sticky"):
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
