# -*- coding: utf-8 -*-
"""File management and visual-asset endpoints (file read/delete/load,
VRM model / VRMA motion / Gauss scene libraries) moved verbatim
out of server.py in the R1 router migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""
import sys as _sys
import glob
import os
import re
import uuid
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from pathlib import Path
from py import auth as sap_auth
from py.get_setting import DEFAULT_VRM_DIR, EXT_DIR, TOOL_TEMP_DIR, UPLOAD_FILES_DIR, USER_DATA_DIR, load_settings
from py.load_files import get_file_content
from pydantic import BaseModel
from typing import List
from fastapi import APIRouter

class FileNames(BaseModel):
    fileNames: List[str]


# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/load_file")
async def load_file_endpoint(request: Request, files: List[UploadFile] = File(None)):
    fastapi_base_url = str(request.base_url)
    file_links = []
    textFiles = []
    imageFiles = []
    vedioFiles = []
    
    # 辅助函数：根据后缀名判断类型
    def get_file_type(ext):
        ext = ext.lower().lstrip('.')
        if ext in _srv.ALLOWED_IMAGE_EXTENSIONS:
            return 'image'
        if ext in _srv.ALLOWED_VIDEO_EXTENSIONS:
            return 'video'
        return 'file'

    content_type = request.headers.get('Content-Type', '')
    try:
        if 'multipart/form-data' in content_type:
            for file in files:
                file_extension = os.path.splitext(file.filename)[1]
                unique_filename = f"{uuid.uuid4()}{file_extension}"
                destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)
                
                with open(destination, "wb") as buffer:
                    content = await file.read()
                    buffer.write(content)
                
                # ✨ 修改点：根据后缀决定 type
                current_type = get_file_type(file_extension)
                
                file_link = {
                    "path": f"{fastapi_base_url}uploaded_files/{unique_filename}",
                    "name": file.filename,
                    "type": current_type  # 返回给前端
                }
                file_links.append(file_link)
                
                # 兼容原有的分类列表
                file_meta = {"unique_filename": unique_filename, "original_filename": file.filename}
                ext_clean = file_extension[1:].lower()
                if ext_clean in _srv.ALLOWED_EXTENSIONS:
                    textFiles.append(file_meta)
                elif ext_clean in _srv.ALLOWED_IMAGE_EXTENSIONS:
                    imageFiles.append(file_meta)
                elif ext_clean in _srv.ALLOWED_VIDEO_EXTENSIONS:
                    vedioFiles.append(file_meta)

        elif 'application/json' in content_type:
            data = await request.json()
            _allowed_roots = [UPLOAD_FILES_DIR, TOOL_TEMP_DIR, USER_DATA_DIR]
            _cc = (await load_settings()).get("CLISettings", {}).get("cc_path")
            if _cc:
                _allowed_roots.append(_cc)
            for file_info in data.get("files", []):
                file_path = file_info.get("path")
                if not sap_auth.path_under(file_path, _allowed_roots):
                    return JSONResponse(status_code=403,
                                        content={"success": False, "detail": "path not in allowed roots"})
                file_name = file_info.get("name", os.path.basename(file_path))
                file_extension = os.path.splitext(file_name)[1]
                
                unique_filename = f"{uuid.uuid4()}{file_extension}"
                destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)
                
                with open(file_path, "rb") as src, open(destination, "wb") as dst:
                    dst.write(src.read())
                
                # ✨ 修改点：根据后缀决定 type
                current_type = get_file_type(file_extension)
                
                file_link = {
                    "path": f"{fastapi_base_url}uploaded_files/{unique_filename}",
                    "name": file_name,
                    "type": current_type
                }
                file_links.append(file_link)
                
                file_meta = {"unique_filename": unique_filename, "original_filename": file_name}
                ext_clean = file_extension[1:].lower()
                if ext_clean in _srv.ALLOWED_EXTENSIONS:
                    textFiles.append(file_meta)
                elif ext_clean in _srv.ALLOWED_IMAGE_EXTENSIONS:
                    imageFiles.append(file_meta)
                elif ext_clean in _srv.ALLOWED_VIDEO_EXTENSIONS:
                    vedioFiles.append(file_meta)

        return JSONResponse(content={"success": True, "fileLinks": file_links, "textFiles": textFiles, "imageFiles": imageFiles, "vedioFiles": vedioFiles})
    
    except Exception as e:
        _srv.logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/delete_file")
async def delete_file_endpoint(request: Request):
    data = await request.json()
    file_name = data.get("fileName")
    file_path = os.path.join(UPLOAD_FILES_DIR, file_name)
    if not sap_auth.path_under(file_path, [UPLOAD_FILES_DIR]):
        raise HTTPException(status_code=403, detail="path outside uploads dir")
    try:
        if os.path.isfile(file_path):
            os.remove(file_path)
            return JSONResponse(content={"success": True})
        else:
            return JSONResponse(content={"success": False, "message": "File not found"})
    except Exception as e:
        return JSONResponse(content={"success": False, "message": str(e)})


@router.delete("/delete_files")
async def delete_files_endpoint(req: FileNames):
    success_files = []
    errors = []
    for name in req.fileNames:
        path = os.path.join(UPLOAD_FILES_DIR, name)
        if not sap_auth.path_under(path, [UPLOAD_FILES_DIR]):
            errors.append(f"{name}: path outside uploads dir")
            continue
        try:
            if os.path.isfile(path):
                os.remove(path)
                success_files.append(name)
            else:
                errors.append(f"{name} not found")
        except Exception as e:
            errors.append(f"{name}: {str(e)}")

    return JSONResponse(content={
        "success": len(success_files) > 0,   # 只要有成功就算成功
        "successFiles": success_files,
        "errors": errors
    })


@router.post("/upload_vrm_model")
async def upload_vrm_model(
    request: Request,
    file: UploadFile = File(...),
    display_name: str = Form(...)
):
    fastapi_base_url = str(request.base_url)
    
    # 检查文件扩展名
    file_extension = file.filename.split('.')[-1].lower()
    if file_extension not in _srv.ALLOWED_VRM_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"不支持的文件类型: {file_extension}，只支持.vrm文件"}
        )
    
    # 生成唯一文件名
    unique_filename = f"{uuid.uuid4()}.{file_extension}"
    destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)
    
    try:
        # 保存文件
        with open(destination, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
        
        # 构建响应
        file_link = f"{fastapi_base_url}uploaded_files/{unique_filename}"
        
        return JSONResponse(content={
            "success": True,
            "message": "VRM模型上传成功",
            "file": {
                "path": file_link,
                "display_name": display_name,
                "original_name": file.filename,
                "unique_filename": unique_filename
            }
        })
    
    except Exception as e:
        _srv.logger.error(f"VRM模型上传失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"文件保存失败: {str(e)}"}
        )


@router.get("/get_default_vrm_models")
async def get_default_vrm_models(request: Request):
    try:
        fastapi_base_url = str(request.base_url)
        models = []
        
        # 确保目录存在
        if not os.path.exists(DEFAULT_VRM_DIR):
            os.makedirs(DEFAULT_VRM_DIR, exist_ok=True)
            return JSONResponse(content={
                "success": True,
                "models": []
            })
        
        # 扫描默认VRM目录中的所有.vrm文件
        vrm_files = glob.glob(os.path.join(DEFAULT_VRM_DIR, "*.vrm"))
        
        for vrm_file in vrm_files:
            file_name = os.path.basename(vrm_file)
            # 使用文件名（不含扩展名）作为显示名称
            display_name = os.path.splitext(file_name)[0]
            
            # 构建文件访问URL
            file_url = f"{fastapi_base_url}vrm/{file_name}"
            
            models.append({
                "id": os.path.splitext(file_name)[0].lower(),  # 使用文件名作为ID
                "name": display_name,
                "path": file_url,
                "type": "default"
            })
        
        # 按名称排序
        models.sort(key=lambda x: x['name'])
        return JSONResponse(content={
            "success": True,
            "models": models
        })
        
    except Exception as e:
        _srv.logger.error(f"获取默认VRM模型失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"获取默认模型失败: {str(e)}"}
        )


@router.delete("/delete_vrm_model/{filename}")
async def delete_vrm_model(filename: str):
    try:
        # 确保只能删除上传目录中的文件，不能删除默认模型
        file_path = os.path.join(UPLOAD_FILES_DIR, filename)
        
        # 安全检查：确保文件名是UUID格式，防止路径遍历攻击
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.vrm$", filename):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid filename"}
            )
        
        # 额外检查：确保文件路径在上传目录中，防止删除默认模型
        if not file_path.startswith(os.path.abspath(UPLOAD_FILES_DIR)):
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "Cannot delete default models"}
            )
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return JSONResponse(content={
                "success": True,
                "message": "VRM模型文件已删除"
            })
        else:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "文件不存在"}
            )
            
    except Exception as e:
        _srv.logger.error(f"删除VRM模型失败: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除失败: {str(e)}"}
        )


@router.get("/get_default_vrma_motions")
async def get_default_vrma_motions(request: Request):
    try:
        motions = _srv.scan_motion_files(_srv.animation_dir, _srv.ALLOWED_VRMA_EXTENSIONS)

        # 把磁盘路径转成 URL
        for m in motions:
            file_name = os.path.basename(m["path"])
            m["path"] = str(request.base_url) + f"vrm/animations/{file_name}"

        return {"success": True, "motions": motions}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"获取默认动作失败: {str(e)}"}
        )


@router.get("/get_user_vrma_motions")
async def get_user_vrma_motions(request: Request):
    try:
        # C-fix: scan_motion_files needs the extension set (the default-library
        # sibling passes it; this call site had been crashing with 500 since
        # the signature gained allowed_ext)
        motions = _srv.scan_motion_files(UPLOAD_FILES_DIR, _srv.ALLOWED_VRMA_EXTENSIONS)

        # 把磁盘路径转成 URL
        for m in motions:
            file_name = os.path.basename(m["path"])
            m["path"] = str(request.base_url) + f"uploaded_files/{file_name}"

        return {"success": True, "motions": motions}

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"获取用户动作失败: {str(e)}"}
        )


@router.post("/upload_vrma_motion")
async def upload_vrma_motion(
    request: Request,
    file: UploadFile = File(...),
    display_name: str = Form(...)
):
    # 检查扩展名
    file_extension = Path(file.filename).suffix.lower().lstrip(".")
    if file_extension not in _srv.ALLOWED_VRMA_EXTENSIONS:
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": f"不支持的文件类型: {file_extension}"}
        )

    # 生成唯一文件名
    unique_filename = f"{uuid.uuid4()}.vrma"
    destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)

    try:
        # 保存文件
        os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
        with open(destination, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

        # 构建返回数据
        file_url = _srv.make_file_url(request, f"uploaded_files/{unique_filename}")

        return JSONResponse(content={
            "success": True,
            "message": "动作上传成功",
            "file": {
                "unique_filename": unique_filename,
                "display_name": display_name,
                "path": file_url
            }
        })

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"保存文件失败: {str(e)}"}
        )


@router.delete("/delete_vrma_motion/{filename}")
async def delete_vrma_motion(filename: str):
    try:
        # 只允许删除 UPLOAD_FILES_DIR 中的文件
        if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.vrma$", filename):
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Invalid filename"}
            )

        file_path = os.path.join(UPLOAD_FILES_DIR, filename)
        abs_upload = os.path.abspath(UPLOAD_FILES_DIR)
        abs_file = os.path.abspath(file_path)

        if not abs_file.startswith(abs_upload):
            return JSONResponse(
                status_code=403,
                content={"success": False, "message": "禁止删除系统文件"}
            )

        if os.path.exists(file_path):
            os.remove(file_path)
            return {"success": True, "message": "动作文件已删除"}
        else:
            return JSONResponse(
                status_code=404,
                content={"success": False, "message": "文件不存在"}
            )

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"删除失败: {str(e)}"}
        )


@router.post("/upload_gauss_scene")
async def upload_gauss_scene(
    request: Request,
    file: UploadFile = File(...),
    display_name: str = Form(...)
):
    ext = Path(file.filename).suffix.lower().lstrip(".")
    if ext not in _srv.ALLOWED_GAUSS:
        return JSONResponse(status_code=400, content={
            "success": False,
            "message": f"不支持的文件类型: {ext}"
        })
    unique = f"{uuid.uuid4()}.{ext}"
    destination = os.path.join(UPLOAD_FILES_DIR, unique)
    try:
        os.makedirs(UPLOAD_FILES_DIR, exist_ok=True)
        with open(destination, "wb") as f:
            f.write(await file.read())
        url = str(request.base_url) + f"uploaded_files/{unique}"
        return JSONResponse(content={
            "success": True,
            "file": {
                "unique_filename": unique,
                "display_name": display_name,
                "path": url
            }
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/get_default_gauss_scenes")
async def get_default_gauss_scenes(request: Request):
    try:
        os.makedirs(_srv.GAUSS_DIR, exist_ok=True)
        scenes = []
        for f in os.listdir(_srv.GAUSS_DIR):
            ext = Path(f).suffix.lower().lstrip(".")
            if ext in _srv.ALLOWED_GAUSS:
                scenes.append({
                    "id":   Path(f).stem,
                    "name": Path(f).stem,
                    "path": str(request.base_url) + f"vrm/scene/{f}",
                    "type": "default"
                })
        scenes.sort(key=lambda x: x["name"])
        return {"success": True, "scenes": scenes}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/get_user_gauss_scenes")
async def get_user_gauss_scenes(request: Request):
    try:
        scenes = []
        for f in os.listdir(UPLOAD_FILES_DIR):
            ext = Path(f).suffix.lower().lstrip(".")
            if ext in _srv.ALLOWED_GAUSS:
                scenes.append({
                    "id":   Path(f).stem,
                    "name": Path(f).stem,
                    "path": str(request.base_url) + f"uploaded_files/{f}",
                    "type": "user"
                })
        scenes.sort(key=lambda x: x["name"])
        return {"success": True, "scenes": scenes}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.delete("/delete_gauss_scene/{filename}")
async def delete_gauss_scene(filename: str):
    if not re.match(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.(ply|spz|splat|ksplat|sog)$", filename):
        return JSONResponse(status_code=400, content={"success": False, "message": "Invalid filename"})
    file_path = os.path.join(UPLOAD_FILES_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        return {"success": True, "message": "场景已删除"}
    return JSONResponse(status_code=404, content={"success": False, "message": "文件不存在"})


@router.get("/get_file_content")
async def get_file_content_endpoint(file_url: str):
    file_path = os.path.join(UPLOAD_FILES_DIR, file_url)
    if not sap_auth.path_under(file_path, [UPLOAD_FILES_DIR]):
        raise HTTPException(status_code=403, detail="path outside uploads dir")
    content = await get_file_content(file_path)
    return JSONResponse(content={"content": content})


@router.get("/api/get_userfile")
async def get_userfile():
    try:
        userfile = USER_DATA_DIR
        return {"message": "Userfile loaded successfully", "userfile": userfile, "success": True}
    except Exception as e:
        return {"message": str(e), "success": False}


@router.get("/api/get_extfile")
async def get_extfile():
    try:
        extfile = EXT_DIR
        return {"message": "Extfile loaded successfully", "extfile": extfile, "success": True}
    except Exception as e:
        return {"message": str(e), "success": False}

