# -*- coding: utf-8 -*-
"""ComfyUI workflow management and sticker-pack creation endpoints moved
verbatim out of server.py in the R1 router migration (audit 09
item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve
at request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""
import logging
import json
import os
import uuid
from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from py import auth as sap_auth
from py.get_setting import UPLOAD_FILES_DIR
from typing import List
from fastapi import APIRouter

# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
logger = logging.getLogger("app")

router = APIRouter()

@router.post("/create_sticker_pack")
async def create_sticker_pack(
    request: Request,
    files: List[UploadFile] = File(..., description="表情文件列表"),
    pack_name: str = Form(..., description="表情包名称"),
    descriptions: List[str] = Form(..., description="表情描述列表")
):
    """
    创建新表情包
    - files: 上传的图片文件列表
    - pack_name: 表情包名称
    - descriptions: 每个表情的描述列表
    """
    fastapi_base_url = str(request.base_url)
    imageFiles = []
    stickers_data = []
    
    try:
        # 验证输入数据
        if not pack_name:
            raise HTTPException(status_code=400, detail="表情包名称不能为空")
        if len(files) == 0:
            raise HTTPException(status_code=400, detail="至少需要上传一个表情")
        if len(descriptions) != len(files):
            raise HTTPException(
                status_code=400, 
                detail=f"描述数量({len(descriptions)})与文件数量({len(files)})不匹配"
            )

        # 处理上传的表情文件
        for idx, file in enumerate(files):
            # 获取文件扩展名
            file_extension = os.path.splitext(file.filename)[1].lower()
            
            # 验证文件类型
            if file_extension not in ['.png', '.jpg', '.jpeg', '.gif', '.webp']:
                raise HTTPException(
                    status_code=400, 
                    detail=f"不支持的文件类型: {file_extension}"
                )
            
            # 生成唯一文件名
            unique_filename = f"{uuid.uuid4()}{file_extension}"
            destination = os.path.join(UPLOAD_FILES_DIR, unique_filename)

            # 保存文件
            with open(destination, "wb") as buffer:
                content = await file.read()
                buffer.write(content)

            # 构建返回数据
            imageFiles.append({
                "unique_filename": unique_filename,
                "original_filename": file.filename,
            })
            
            # 获取对应的描述（处理可能的索引越界）
            description = descriptions[idx] if idx < len(descriptions) else ""

            # 构建表情数据
            stickers_data.append({
                "unique_filename": unique_filename,
                "original_filename": file.filename,
                "url": f"{fastapi_base_url}uploaded_files/{unique_filename}",
                "description": description
            })

        # 创建表情包ID（可替换为数据库存储逻辑）
        sticker_pack_id = str(uuid.uuid4())
        
        return JSONResponse(content={
            "success": True,
            "id": sticker_pack_id,
            "name": pack_name,
            "stickers": stickers_data,
            "imageFiles": imageFiles,
            "cover": stickers_data[0]["url"] if stickers_data else None
        })
    
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"创建表情包时出错: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"服务器错误: {str(e)}")


@router.post("/add_workflow")
async def add_workflow(file: UploadFile = File(...), workflow_data: str = Form(...)):
    # 检查文件类型是否为 JSON
    if file.content_type != "application/json":
        raise HTTPException(
            status_code=400,
            detail="Only JSON files are allowed."
        )

    # 生成唯一文件名，uuid.uuid4()，没有连词符
    unique_filename = str(uuid.uuid4()).replace('-', '')

    # 拼接文件路径
    file_path = os.path.join(UPLOAD_FILES_DIR, unique_filename + ".json")

    # 保存文件
    try:
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save file: {str(e)}"
        )

    # 解析 workflow_data
    workflow_data_dict = json.loads(workflow_data)

    # 返回文件信息
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": "File uploaded successfully",
            "file": {
                "unique_filename": unique_filename,
                "original_filename": file.filename,
                "url": f"/uploaded_files/{unique_filename}",
                "enabled": True,
                "text_input": workflow_data_dict.get("textInput"),
                "text_input_2": workflow_data_dict.get("textInput2"),
                "image_input": workflow_data_dict.get("imageInput"),
                "image_input_2": workflow_data_dict.get("imageInput2"),
                "seed_input": workflow_data_dict.get("seedInput"),
                "seed_input2": workflow_data_dict.get("seedInput2"),
                "description": workflow_data_dict.get("description")
            }
        }
    )


@router.delete("/delete_workflow/{filename}")
async def delete_workflow(filename: str):
    file_path = os.path.join(UPLOAD_FILES_DIR, filename + ".json")
    if not sap_auth.path_under(file_path, [UPLOAD_FILES_DIR]):
        raise HTTPException(status_code=403, detail="path outside uploads dir")
    # 检查文件是否存在
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    # 删除文件
    try:
        os.remove(file_path)
        return JSONResponse(
            status_code=200,
            content={"success": True, "message": "File deleted successfully"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete file: {str(e)}"
        )

