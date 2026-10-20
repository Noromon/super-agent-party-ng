# -*- coding: utf-8 -*-
"""Status / discovery endpoints (backup list-now-verify, acpx status,
vrm_config, provider model listing) moved verbatim out of server.py
in the R1 router migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve
at request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""
import sys as _sys
import asyncio
import os
from fastapi import Body, HTTPException, status
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI
from py.acpx_tools import check_acpx_available
from py.get_setting import USER_DATA_DIR, load_settings
from pydantic import BaseModel
from fastapi import APIRouter

class ProviderModelRequest(BaseModel):
    url: str
    api_key: str


# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.get("/v1/models")
async def get_models():
    """
    获取模型列表
    """
    from openai.types import Model
    from openai.pagination import SyncPage
    try:
        # 重新加载最新设置
        current_settings = await load_settings()
        agents = current_settings['agents']
        # 构造符合 OpenAI 格式的 Model 对象
        model_data = [
            Model(
                id=agent["name"],  
                created=0,  
                object="model",
                owned_by="super-agent-party"  # 非空字符串
            )
            for agent in agents.values()  
        ]
        # 添加默认的 'super-model'
        model_data.append(
            Model(
                id='super-model',
                created=0,
                object="model",
                owned_by="super-agent-party"  # 非空字符串
            )
        )

        # 构造完整 SyncPage 响应
        response = SyncPage[Model](
            object="list",
            data=model_data,
            has_more=False  # 添加分页标记
        )
        # 直接返回模型字典，由 FastAPI 自动序列化为 JSON
        return response.model_dump()  
        
    except Exception as e:
        return JSONResponse(
            status_code=e.status_code,
            content={
                "error": {
                    "message": str(e),
                    "type": "api_error",
                }
            }
        )
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": {
                    "message": str(e),
                    "type": "server_error",
                    "code": 500
                }
            }
        )


@router.post("/v1/providers/models")
async def fetch_provider_models(request: ProviderModelRequest):
    try:
        # 使用传入的provider配置创建AsyncOpenAI客户端
        client = AsyncOpenAI(api_key=request.api_key, base_url=request.url)
        # 获取模型列表
        model_list = await client.models.list()
        # 提取模型ID并返回
        return JSONResponse(content={"data": [model.id for model in model_list.data]})
    except Exception as e:
        # 处理异常，返回错误信息
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vrm_config")
async def vrm_config():
    settings = await load_settings()
    return {"VRMConfig": settings.get("VRMConfig", {})}


@router.get("/api/backup/list")
async def backup_list() -> dict:
    from py.data_backup import list_snapshots
    snaps = await asyncio.to_thread(list_snapshots, USER_DATA_DIR)
    return {"snapshots": snaps}


@router.post("/api/backup/now")
async def backup_now() -> dict:
    from py.data_backup import snapshot_data_dir
    cur_settings = await load_settings()
    include = bool(((cur_settings.get("systemSettings") or {}).get("backupIncludeUploads")
                    or cur_settings.get("backupIncludeUploads") or False))
    return await asyncio.to_thread(snapshot_data_dir, USER_DATA_DIR, 5, include, 0.0)


@router.post("/api/backup/verify")
async def backup_verify(body: dict = Body(...)) -> dict:
    from py.data_backup import backups_root, verify_snapshot
    name = str((body or {}).get("name") or "")
    root = os.path.abspath(backups_root(USER_DATA_DIR))
    target = os.path.abspath(os.path.join(root, name))
    # 路径围栏：只允许 backups/ 直属子目录，拒绝穿越与绝对路径
    if not target.startswith(root + os.sep) or not os.path.isdir(target):
        raise HTTPException(status_code=400, detail="invalid snapshot name")
    return await asyncio.to_thread(verify_snapshot, target)


@router.get("/api/acpx/status")
async def acpx_status():
    """返回 ACPX 的安装状态和环境信息"""
    return check_acpx_available()

