# -*- coding: utf-8 -*-
"""S136(SoulX)：SoulX FlashHead 真人伴侣后端路由（上游 server.py SoulX 域终态迁 fork routers）。

端点：GET/POST /soulx_config（窗口页选择参考图）、POST /upload_soulx_image
（PIL RGB→PNG）、GET /get_soulx_images（默认目录+用户目录合并）、
DELETE /delete_soulx_image/{id}（默认形象不可删）、WS /ws/soulx（窗口页
animationComplete 转发主窗口）。HTTP 鉴权走全局中间件，WS 先过
sap_auth.ws_auth_ok（fork 惯例，上游全局中间件不含 WS）。
"""
import io
import json
import logging
import os
import re
import uuid

from fastapi import APIRouter, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from PIL import Image

from py import auth as sap_auth
from py.get_setting import (DEFAULT_SOULX_IMAGES_DIR, SOULX_IMAGES_DIR,
                            load_settings, save_settings)
from py.voice import tts_manager

router = APIRouter()


@router.get("/soulx_config")
async def soulx_config():
    settings = await load_settings()
    return {"SoulxConfig": settings.get("SoulxConfig", {})}


@router.post("/soulx_config")
async def set_soulx_config(request: Request):
    """从 SoulX 页面前端更新参考图选择。"""
    try:
        payload = await request.json()
        settings = await load_settings()
        soulx = settings.get("SoulxConfig", {})
        if "selectedImageId" in payload:
            soulx["selectedImageId"] = payload["selectedImageId"]
            settings["SoulxConfig"] = soulx
            await save_settings(settings)
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": str(e)})


def _soulx_image_id_from_name(display_name: str) -> str:
    """生成安全的图片 id（同时作为文件名和 FlashHead 的 person_name）。"""
    safe = re.sub(r'[\\/:*?"<>|.\s]+', '_', display_name).strip('_')[:50]
    if not safe:
        safe = f"img_{uuid.uuid4().hex[:8]}"
    candidate = safe
    idx = 2
    while os.path.exists(os.path.join(SOULX_IMAGES_DIR, f"{candidate}.png")):
        candidate = f"{safe}_{idx}"
        idx += 1
    return candidate


@router.post("/upload_soulx_image")
async def upload_soulx_image(
    request: Request,
    file: UploadFile = File(...),
    display_name: str = Form(...)
):
    try:
        data = await file.read()
        img = Image.open(io.BytesIO(data)).convert("RGB")
        image_id = _soulx_image_id_from_name(
            display_name.strip() or (file.filename or "").rsplit('.', 1)[0])
        os.makedirs(SOULX_IMAGES_DIR, exist_ok=True)
        img.save(os.path.join(SOULX_IMAGES_DIR, f"{image_id}.png"), format="PNG")
        return JSONResponse(content={
            "success": True,
            "image": {
                "id": image_id,
                "name": display_name.strip() or image_id,
                "url": f"/uploaded_files/soulx_images/{image_id}.png"
            }
        })
    except Exception as e:
        logging.error(f"上传SoulX参考图失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"上传失败: {str(e)}"}
        )


@router.get("/get_soulx_images")
async def get_soulx_images(request: Request):
    try:
        images = []
        seen = set()
        # 默认形象（不可删除，不可被同名覆盖），排在前面
        if os.path.isdir(DEFAULT_SOULX_IMAGES_DIR):
            for fname in sorted(os.listdir(DEFAULT_SOULX_IMAGES_DIR)):
                if fname.lower().endswith('.png'):
                    stem = fname[:-4]
                    seen.add(stem)
                    images.append({
                        "id": stem,
                        "name": stem,
                        "url": f"/default_soulx_images/{fname}",
                        "default": True
                    })
        # 用户上传的形象
        if os.path.isdir(SOULX_IMAGES_DIR):
            for fname in sorted(os.listdir(SOULX_IMAGES_DIR)):
                if fname.lower().endswith('.png'):
                    stem = fname[:-4]
                    if stem in seen:
                        continue
                    images.append({
                        "id": stem,
                        "name": stem,
                        "url": f"/uploaded_files/soulx_images/{fname}"
                    })
        return JSONResponse(content={
            "success": True,
            "images": images,
            "dir": os.path.abspath(SOULX_IMAGES_DIR)
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"获取参考图列表失败: {str(e)}"}
        )


@router.delete("/delete_soulx_image/{image_id}")
async def delete_soulx_image(image_id: str):
    try:
        if not re.fullmatch(r'[\w\-]+', image_id):
            return JSONResponse(status_code=400,
                                content={"success": False, "message": "非法的图片id"})
        # 禁止删除默认形象
        default_path = os.path.join(DEFAULT_SOULX_IMAGES_DIR, f"{image_id}.png")
        if os.path.exists(default_path):
            return JSONResponse(status_code=403,
                                content={"success": False, "message": "默认形象不可删除"})
        path = os.path.join(SOULX_IMAGES_DIR, f"{image_id}.png")
        if not os.path.exists(path):
            return JSONResponse(status_code=404,
                                content={"success": False, "message": "图片不存在"})
        os.remove(path)
        settings = await load_settings()
        soulx = settings.get("SoulxConfig", {})
        if soulx.get("selectedImageId") == image_id:
            soulx["selectedImageId"] = ""
            settings["SoulxConfig"] = soulx
            await save_settings(settings)
        return JSONResponse(content={"success": True, "message": "参考图已删除"})
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除失败: {str(e)}"}
        )


@router.websocket("/ws/soulx")
async def soulx_websocket_endpoint(websocket: WebSocket):
    """SoulX FlashHead 窗口 WebSocket：接收主窗口发来的 TTS 音频和指令。"""
    if not sap_auth.ws_auth_ok(websocket):
        logging.info("[SoulX WS] handshake rejected: auth failed (missing/invalid sap_token)")
        await websocket.close(code=4401)
        return
    await tts_manager.connect_soulx(websocket)
    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                data = json.loads(msg["text"])
                if data.get('type') == 'animationComplete':
                    await tts_manager.send_to_main(msg["text"])
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        logging.error(f"WS error in SoulX: {e}")
    finally:
        tts_manager.disconnect_soulx(websocket)
