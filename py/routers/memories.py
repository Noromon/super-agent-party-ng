# -*- coding: utf-8 -*-
"""Memory CRUD, kb/mcp lifecycle and group-memory endpoints moved
verbatim out of server.py in the R1 router migration (audit 09
item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""

import logging
import sys as _sys
import threading

from py import app_state
from py.memory_store import fmt_iso8605_to_local
import asyncio
import json
import os
import shutil
from fastapi import BackgroundTasks, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from py import llm_gate
from py.get_setting import MEMORY_CACHE_DIR, load_settings, save_settings
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter

class ClearGroupMemoryRequest(BaseModel):
    group_id: Union[str, int, float]


class GroupMemoryExtractRequest(BaseModel):
    group_id: Union[str, int, float]
    conversation_id: Union[str, int, float]
    user_message_id: Optional[Union[str, int, float]] = None
    assistant_message_id: Optional[Union[str, int, float]] = None
    user_message: str
    assistant_message: str


class MemoryAddBody(BaseModel):
    new_text: str = ""    # S77: 上游终态主字段
    content: str = ""     # fork C-5 旧前端别名，兼容一版


class TextUpdate(BaseModel):
    new_text: str


# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

logger = logging.getLogger("app")

router = APIRouter()

@router.post("/api/group-memory/extract")
async def extract_group_memory_endpoint(req: GroupMemoryExtractRequest):
    req.group_id = _srv._normalize_entity_id(req.group_id)
    req.conversation_id = _srv._normalize_entity_id(req.conversation_id)
    req.user_message_id = _srv._normalize_entity_id(req.user_message_id) or None
    req.assistant_message_id = _srv._normalize_entity_id(req.assistant_message_id) or None

    group_map = await _srv._load_group_map()
    group = group_map.get(req.group_id)
    if not group or not (group.get("memoryConfig") or {}).get("enabled"):
        return {"success": True, "memories": 0}

    current_settings = await load_settings()
    client_class = _srv.get_client_class(current_settings, current_settings.get('selectedProvider'))
    memory_client = client_class(
        api_key=current_settings.get('api_key'),
        base_url=current_settings.get('base_url') or "https://api.openai.com/v1",
    )
    memories = await _srv._extract_group_memories(memory_client, current_settings, req.model_dump())
    await _srv._upsert_group_memories(
        req.group_id,
        req.conversation_id,
        req.assistant_message_id or req.user_message_id or req.conversation_id,
        memories,
    )
    return {"success": True, "memories": len(memories)}


@router.post("/api/group-memory/clear-group")
async def clear_group_memory_endpoint(req: ClearGroupMemoryRequest):
    req.group_id = _srv._normalize_entity_id(req.group_id)
    await _srv._invalidate_group_memories_by_group(req.group_id)
    return {"success": True}


@router.post("/api/group-memory/clear-all")
async def clear_all_group_memory_endpoint():
    await _srv._invalidate_all_group_memories()
    return {"success": True}


@router.post("/create_mcp")
async def create_mcp_endpoint(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    mcp_id = data.get("mcpId")
    
    if not mcp_id:
        raise HTTPException(status_code=400, detail="Missing mcpId")
    
    # 将任务添加到后台队列
    background_tasks.add_task(_srv.process_mcp, mcp_id)
    
    return {"success": True, "message": "MCP服务器初始化已开始"}


@router.get("/mcp_status/{mcp_id}")
async def get_mcp_status(mcp_id: str):
    status = app_state.mcp_status.get(mcp_id, "not_found")
    if status == "ready":
        # 保证 _tools 里都是可序列化的 dict / list / 基本类型
        tools = await app_state.mcp_client_list[mcp_id].get_openai_functions(disable_tools=[])
        tools = json.dumps(app_state.mcp_client_list[mcp_id]._tools_list)
        return {"mcp_id": mcp_id, "status": status, "tools": tools}
    return {"mcp_id": mcp_id, "status": status, "tools": []}


@router.delete("/remove_mcp")
async def remove_mcp_server(request: Request):
    try:
        data = await request.json()
        server_name = data.get("serverName", "")

        if not server_name:
            raise HTTPException(status_code=400, detail="No server names provided")

        # 移除指定的MCP服务器
        current_settings = await load_settings()
        if server_name in current_settings['mcpServers']:
            del current_settings['mcpServers'][server_name]
            await save_settings(current_settings)
            _srv.settings = current_settings

            # 从mcp_client_list中移除
            if server_name in app_state.mcp_client_list:
                app_state.mcp_client_list[server_name].disabled = True
                await app_state.mcp_client_list[server_name].close()
                del app_state.mcp_client_list[server_name]
                logging.getLogger("app").info(f"关闭MCP服务器: {server_name}")

            return JSONResponse({"success": True, "removed": server_name})
        else:
            raise HTTPException(status_code=404, detail="Server not found")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON format")
    except Exception as e:
        logger.error(f"移除MCP服务器失败: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/remove_memory")
async def remove_memory_endpoint(request: Request):
    data = await request.json()
    memory_id = data.get("memoryId")
    if memory_id:
        try:
            # 删除MEMORY_CACHE_DIR目录下的memory_id文件夹
            memory_dir = os.path.join(MEMORY_CACHE_DIR, memory_id)
            shutil.rmtree(memory_dir)
            return JSONResponse({"success": True, "message": "Memory removed"})
        except Exception as e:
            return JSONResponse({"success": False, "message": str(e)})
    else:
        return JSONResponse({"success": False, "message": "No memoryId provided"})


@router.post("/create_kb")
async def create_kb_endpoint(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    kb_id = data.get("kbId")
    
    if not kb_id:
        raise HTTPException(status_code=400, detail="Missing kbId")
    
    # 将任务添加到后台队列
    background_tasks.add_task(_srv.process_kb, kb_id)
    
    return {"success": True, "message": "知识库处理已开始，请稍后查询状态"}


@router.delete("/remove_kb")
async def remove_kb_endpoint(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    kb_id = data.get("kbId")

    if not kb_id:
        raise HTTPException(status_code=400, detail="Missing kbId")
    try:
        background_tasks.add_task(_srv.remove_kb, kb_id)
    except Exception as e:
        return {"success": False, "message": str(e)}
    return {"success": True, "message": "知识库已删除"}


@router.get("/kb_status/{kb_id}")
async def get_kb_status(kb_id):
    status = app_state.kb_status.get(kb_id, "not_found")
    logging.getLogger("app").info (f"kb_status: {kb_id} - {status}")
    return {"kb_id": kb_id, "status": status}


# ---------- S77: 记忆 CRUD（上游 91c038eb 终态：全走 mem0 API + uuid 定位） ----------
# 锁语义=同进程 CRUD 串行（1c33bc74），锁在 worker 线程内持有，不阻塞事件循环。
_m0_crud_lock = threading.Lock()


async def _memory_cfg_or_404(memory_id: str):
    cur_settings = await load_settings()
    cur_memory = next((m for m in (cur_settings.get("memories") or [])
                       if isinstance(m, dict) and m.get("id") == memory_id), None)
    if cur_memory is None:
        raise HTTPException(status_code=404, detail="memory config not found")
    if not cur_memory.get("providerId"):
        raise HTTPException(status_code=400,
                            detail="memory has no embedding provider configured")
    return cur_memory, cur_settings


def _m0_session(memory_id, cur_memory, cur_settings):
    # dims 护栏 + pkl 迁移都在 llm_gate.get_mem0_instance 单点内完成
    return llm_gate.get_mem0_instance(memory_id, cur_memory, cur_settings)


@router.get("/memory/{memory_id}")
async def read_memory(memory_id: str) -> List[Dict[str, Any]]:
    cur_memory, cur_settings = await _memory_cfg_or_404(memory_id)
    try:
        def _op():
            with _m0_crud_lock:
                m0 = _m0_session(memory_id, cur_memory, cur_settings)
                return m0.get_all(user_id=memory_id, limit=10000)
        results = await asyncio.to_thread(_op)
        # mem0 v1.1+ 返回 {"results": [...]}，旧版直接返回 list
        items = results.get("results", []) if isinstance(results, dict) else (results or [])
        flat = []
        for item in items:
            flat.append({
                "idx": len(flat),
                "uuid": item.get("id", ""),
                "text": item.get("memory", ""),
                "created_at": fmt_iso8605_to_local(item.get("created_at", "")),
                "timetamp": fmt_iso8605_to_local(item.get("updated_at")
                                                 or item.get("created_at", "")),
            })
        return flat
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[memory] GET /memory/{memory_id} 失败")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/{memory_id}")
async def add_memory_text(memory_id: str, body: MemoryAddBody = Body(...)) -> dict:
    text = (body.new_text or body.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="new_text required")
    cur_memory, cur_settings = await _memory_cfg_or_404(memory_id)
    try:
        def _op():
            with _m0_crud_lock:
                m0 = _m0_session(memory_id, cur_memory, cur_settings)
                # infer=False=原文入库不走 LLM 抽取
                return m0.add(text, user_id=memory_id, infer=False)
        await asyncio.to_thread(_op)
        return {"message": "added"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[memory] POST /memory/{memory_id} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"add failed: {e}")


@router.put("/memory/{memory_id}/{uuid}")
async def update_text(memory_id: str, uuid: str,
                      body: TextUpdate = Body(...)) -> dict:
    cur_memory, cur_settings = await _memory_cfg_or_404(memory_id)
    try:
        def _op():
            with _m0_crud_lock:
                m0 = _m0_session(memory_id, cur_memory, cur_settings)
                return m0.update(memory_id=uuid, data=body.new_text)
        await asyncio.to_thread(_op)
        return {"message": "updated", "uuid": uuid}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[memory] PUT /memory/{memory_id}/{uuid} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"update failed: {e}")


@router.delete("/memory/{memory_id}/{uuid}")
async def delete_text(memory_id: str, uuid: str) -> dict:
    cur_memory, cur_settings = await _memory_cfg_or_404(memory_id)
    try:
        def _op():
            with _m0_crud_lock:
                m0 = _m0_session(memory_id, cur_memory, cur_settings)
                return m0.delete(memory_id=uuid)
        await asyncio.to_thread(_op)
        return {"message": "deleted", "uuid": uuid}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[memory] DELETE /memory/{memory_id}/{uuid} 失败: {e}")
        raise HTTPException(status_code=500, detail=f"delete failed: {e}")

