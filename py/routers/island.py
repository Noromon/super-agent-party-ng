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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://ip-api.com/json/", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("status") == "success":
                        _ip_city_cache = {
                            "city": data.get("city", ""),
                            "regionName": data.get("regionName", ""),
                            "country": data.get("country", ""),
                            "lat": data.get("lat"),
                            "lon": data.get("lon"),
                        }
                        return _ip_city_cache
    except Exception as e:
        _logger.warning(f"[IP City] Failed to fetch: {e}")
    return {"city": "", "regionName": "", "country": "", "lat": None, "lon": None}


@router.get("/api/weather")
async def proxy_weather(lat: float, lon: float, daily: str = None, forecast_days: int = None):
    try:
        params = {"latitude": lat, "longitude": lon, "current_weather": "true"}
        if daily:
            params["daily"] = daily
        if forecast_days:
            params["forecast_days"] = str(forecast_days)
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.open-meteo.com/v1/forecast",
                params=params,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        _logger.warning(f"[Weather Proxy] Failed: {e}")
    return {"error": "weather_fetch_failed"}


@router.get("/api/geocode")
async def proxy_geocode(city: str, lang: str = "zh"):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": lang},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        _logger.warning(f"[Geocode Proxy] Failed: {e}")
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
