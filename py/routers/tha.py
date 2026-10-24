# -*- coding: utf-8 -*-
"""S91(THA)：桌面宠物后端路由（上游 server.py THA 域终态迁 fork routers）。

端点：GET/POST /tha_config、POST /tha_emotion（外部集成/OBS）、模型
上传/列表/删除、WS /ws/tha（30fps JPEG 帧流：emotion/motion/motionClear/
mouth/mouse 指令）。HTTP 鉴权走全局中间件（非 exempt 路径自动覆盖），WS 先过
sap_auth.ws_auth_ok（fork 惯例，上游全局中间件不含 WS）。
"""
import asyncio
import json
import logging
import os
import sys
import time

from fastapi import APIRouter, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from py import auth as sap_auth
from py.get_setting import (DEFAULT_THA_DIR, THA_USER_MODELS_DIR, load_settings,
                            save_settings)
from py.voice import tts_manager

router = APIRouter()


@router.get("/tha_config")
async def tha_config():
    settings = await load_settings()
    return {"THAConfig": settings.get("THAConfig", {})}


@router.post("/tha_config")
async def set_tha_config(request: Request):
    """从 THA 页面前端更新模型选择。"""
    try:
        payload = await request.json()
        settings = await load_settings()
        tha = settings.get("THAConfig", {})
        if "selectedModelId" in payload:
            tha["selectedModelId"] = payload["selectedModelId"]
            settings["THAConfig"] = tha
            await save_settings(settings)
        return {"success": True}
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": str(e)})


@router.post("/tha_emotion")
async def tha_emotion(request: Request):
    """向所有已连接 THA 挂件广播表情/动作（调试与外部集成用）。

    支持三种格式：
      {"emotion": "happy"}                          单表情
      {"expressions": ["happy:0.3", "surprised:0.5"]} 权重字符串列表
      {"emotions": {"happy": 0.3, "surprised": 0.5}}  权重字典
    """
    try:
        payload = await request.json()
        if "emotions" in payload:
            emotions = payload["emotions"]
            if not isinstance(emotions, dict) or not all(
                    isinstance(v, (int, float)) for v in emotions.values()):
                return JSONResponse(status_code=400, content={
                    "success": False, "message": "emotions 必须是 {表情名: 数值权重} 字典"})
            expressions = [f"{k}:{v}" for k, v in emotions.items()]
        elif "expressions" in payload:
            if not isinstance(payload["expressions"], list):
                return JSONResponse(status_code=400, content={
                    "success": False, "message": "expressions 必须是字符串列表"})
            expressions = payload["expressions"]
        elif "emotion" in payload:
            if not isinstance(payload["emotion"], str):
                return JSONResponse(status_code=400, content={
                    "success": False, "message": "emotion 必须是字符串"})
            expressions = [payload["emotion"]]
        else:
            return JSONResponse(status_code=400, content={
                "success": False, "message": "需要 emotion / expressions / emotions 之一"})
        await tts_manager.broadcast_expressions_to_tha(expressions)
        return {"success": True, "expressions": expressions}
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": str(e)})


@router.post("/upload_tha_model")
async def upload_tha_model(
    request: Request,
    file: UploadFile = File(...),
    display_name: str = Form(...)
):
    from py.tha_engine import THAModelManager

    file_extension = str(file.filename or "").split('.')[-1].lower()
    if file_extension not in ('onnx', 'zip'):
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "只支持 .onnx 或 .zip (CoreML) 格式的THA模型文件"}
        )

    try:
        data = await file.read()
        manager = THAModelManager(DEFAULT_THA_DIR, THA_USER_MODELS_DIR)
        if file_extension == 'onnx':
            success, msg, info = manager.install_onnx(data, display_name)
        else:
            success, msg, info = manager.install_mlpackage(data, display_name)

        if success:
            return JSONResponse(content={"success": True, "message": msg, "model": info})
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    except Exception as e:
        logging.error(f"上传THA模型失败: {str(e)}")
        return JSONResponse(status_code=500,
                            content={"success": False, "message": f"上传失败: {str(e)}"})


@router.get("/get_default_tha_models")
async def get_default_tha_models(request: Request):
    from py.tha_engine import THAModelManager
    try:
        manager = THAModelManager(DEFAULT_THA_DIR, THA_USER_MODELS_DIR)
        models = manager.scan_default_models()
        return JSONResponse(content={"success": True, "models": models})
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": f"获取默认模型失败: {str(e)}"})


@router.get("/get_user_tha_models")
async def get_user_tha_models(request: Request):
    from py.tha_engine import THAModelManager
    try:
        manager = THAModelManager(DEFAULT_THA_DIR, THA_USER_MODELS_DIR)
        models = manager.scan_user_models()
        return JSONResponse(content={"success": True, "models": models})
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": f"获取用户模型失败: {str(e)}"})


@router.delete("/delete_tha_model/{model_id}")
async def delete_tha_model(model_id: str):
    from py.tha_engine import THAModelManager, clear_engine_cache
    try:
        manager = THAModelManager(DEFAULT_THA_DIR, THA_USER_MODELS_DIR)
        if manager.delete_model(model_id):
            # fork 微改进（上游未清缓存）：删除后立即失效引擎缓存，
            # 避免新连接对已删路径重建会话
            clear_engine_cache()
            return JSONResponse(content={"success": True, "message": "THA模型已删除"})
        return JSONResponse(
            status_code=404,
            content={"success": False, "message": "模型不存在或无法删除默认模型"}
        )
    except Exception as e:
        return JSONResponse(status_code=500,
                            content={"success": False, "message": f"删除失败: {str(e)}"})


@router.websocket("/ws/tha")
async def tha_websocket_endpoint(websocket: WebSocket):
    """THA 桌面宠物 WebSocket：接收控制指令，返回 JPEG 帧。"""
    if not sap_auth.ws_auth_ok(websocket):
        logging.info("[THA WS] handshake rejected: auth failed (missing/invalid sap_token)")
        await websocket.close(code=4401)
        return

    from py.tha_engine import THAPoseGenerator, get_engine

    settings = await load_settings()
    tha_config = settings.get("THAConfig", {})
    selected_id = tha_config.get("selectedModelId", "Lyra")
    sr_mode = tha_config.get("srMode", "cnnx2vl")
    jpeg_quality = 90 if sr_mode != "off" else 50

    # 1. 查找模型路径（macOS: .mlpackage 优先，非 macOS: 仅 .onnx）
    is_mac = (sys.platform == 'darwin')

    def _find_model_in(scan_dir):
        try:
            for entry in os.listdir(scan_dir):
                entry_path = os.path.join(scan_dir, entry)
                if os.path.isdir(entry_path) and entry == selected_id:
                    if is_mac:
                        mlp = os.path.join(entry_path, "model.mlpackage")
                        if os.path.isdir(mlp):
                            return mlp
                    mp = os.path.join(entry_path, "model.onnx")
                    if os.path.exists(mp):
                        return mp
        except FileNotFoundError:
            pass
        return None

    model_path = _find_model_in(DEFAULT_THA_DIR)
    if not model_path:
        model_path = _find_model_in(THA_USER_MODELS_DIR)

    if not model_path:
        logging.error(f"[THA WS] Model not found: {selected_id}")
        await websocket.accept()
        await websocket.close()
        return

    logging.info(f"[THA WS] Client connected: model={selected_id} sr={sr_mode}")
    try:
        engine = get_engine(model_path)
        gen = THAPoseGenerator()
        logging.info(f"[THA WS] Engine ready: {model_path}")

        await tts_manager.connect_tha(websocket)
        websocket._tha_gen = gen

        # 2. 接收控制流
        async def recv_loop():
            try:
                while True:
                    msg = await websocket.receive_text()
                    data = json.loads(msg)
                    cmd_type = data.get("type", "")
                    if cmd_type == "emotion":
                        gen.set_emotion(data.get("emotion", "neutral"))
                    elif cmd_type == "motion":
                        gen.set_motion(data.get("motion", ""))
                    elif cmd_type == "motionClear":
                        gen.clear_motion()
                    elif cmd_type == "mouth":
                        gen.set_mouth(float(data.get("amplitude", 0)))
                    elif cmd_type == "mouse":
                        gen.set_mouse(float(data.get("x", 0)), float(data.get("y", 0)))
            except WebSocketDisconnect:
                return
            except Exception as e:
                logging.error(f"[THA WS] Instruction receive error: {e}")

        # 3. 渲染发送流（30fps，推理进 executor 避免卡事件循环）
        async def render_loop():
            target_fps = 30
            frame_interval = 1.0 / target_fps
            loop = asyncio.get_running_loop()

            try:
                while True:
                    start_time = time.perf_counter()

                    pose = gen.step()
                    jpeg = await loop.run_in_executor(None, engine.render, pose, jpeg_quality)

                    await websocket.send_bytes(jpeg)

                    elapsed = time.perf_counter() - start_time
                    await asyncio.sleep(max(0.0, frame_interval - elapsed))
            except WebSocketDisconnect:
                return
            except Exception as e:
                logging.error(f"[THA WS] Frame render error: {e}")

        recv_task = asyncio.create_task(recv_loop())
        render_task = asyncio.create_task(render_loop())

        done, pending = await asyncio.wait(
            [recv_task, render_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logging.error(f"[THA WS] Main loop runtime error: {e}")
    finally:
        tts_manager.disconnect_tha(websocket)
        logging.info("[THA WS] Client disconnected")
