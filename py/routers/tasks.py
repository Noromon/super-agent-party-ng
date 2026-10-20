# -*- coding: utf-8 -*-
"""Background task and stream control endpoints (task create/list/
cancel/delete, stream cancel, chat resume) moved verbatim out of
server.py in the R1 router migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""
import sys as _sys
import asyncio
from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pathlib import Path
from py.get_setting import load_settings
from py.sub_agent import run_subtask_in_background
from py.task_center import get_task_center
from pydantic import BaseModel
from typing import Any, Dict, List, Optional
from fastapi import APIRouter

class StreamResumeRequest(BaseModel):
    stream_id: str
    from_index: int = 0


class TaskCreateRequest(BaseModel):
    title: str
    description: str
    agent_type: str = "default"
    task_type: str = "once"  # once, time, cycle
    platforms: List[str] = []
    trigger_config: Optional[Dict[str, Any]] = None


# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/v1/streams/cancel/{stream_id}")
async def cancel_stream_endpoint(stream_id: str):
    """用户点击停止生成时调用：标记取消并取消生产者任务。

    围栏语义：取消后 stream_generator 在每次工具调度与后续 LLM 轮次前
    检查 cancelled 并立即终止，不再产生任何工具副作用。
    """
    async with _srv._active_streams_lock:
        entry = _srv._active_streams.get(stream_id)
        if not entry:
            return JSONResponse(status_code=404, content={"cancelled": False, "stream_id": stream_id})
        entry["cancelled"] = True
        entry["done"] = True
    task = entry.get("task")
    if task and not task.done():
        task.cancel()
    # T-4: cancel 后必须排程清理（count 门槛保护活跃消费者；未清者由 TTL sweeper 兜底）
    asyncio.create_task(_srv._cleanup_stream(stream_id, delay=5.0))
    _srv.logger.info(f"Stream {stream_id} cancelled by user")
    return {"cancelled": True, "stream_id": stream_id}


@router.post("/v1/chat/resume")
async def resume_stream_endpoint(req: StreamResumeRequest):
    """
    断点续传端点：客户端 SSE 连接中断后，通过此端点恢复接收剩余的流内容。
    后端生产者仍在后台运行（如果尚未完成），此端点作为新的消费者从 buffer[from_index] 开始读取。
    """
    stream_id = req.stream_id
    from_index = req.from_index

    entry = _srv._active_streams.get(stream_id)
    if not entry:
        return JSONResponse(
            status_code=404,
            content={"error": "Stream not found or expired", "stream_id": stream_id}
        )
    if entry.get("cancelled"):
        return JSONResponse(
            status_code=410,
            content={"error": "Stream was cancelled by user", "stream_id": stream_id}
        )

    # 增加消费者计数
    entry["consumer_count"] = entry.get("consumer_count", 0) + 1

    async def _resume_consumer():
        try:
            async for chunk in _srv._stream_consumer_generator(stream_id, from_index):
                yield chunk
        finally:
            # T-4: 统一经 helper 释放（与消费者计数语义同源）
            _srv._release_consumer(stream_id)

    return StreamingResponse(
        _resume_consumer(),
        media_type="text/event-stream",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Stream-Id": stream_id,
        }
    )


@router.get("/v1/tasks/list")
async def list_tasks_endpoint():
    """获取当前工作区的所有任务"""
    current_settings = await load_settings()
    workspace_dir = current_settings.get("CLISettings", {}).get("cc_path")
    
    if not workspace_dir:
        return {"tasks": [], "error": "No workspace configured"}
        
    try:
        task_center = await get_task_center(workspace_dir)
        tasks = await task_center.list_tasks()
        return {"tasks": [t.model_dump() for t in tasks]}
    except Exception as e:
        return {"tasks": [], "error": str(e)}


@router.post("/v1/tasks/create")
async def create_task_endpoint(req: TaskCreateRequest):
    """手动创建任务：支持单次、定时、周期模式"""
    current_settings = await load_settings()
    workspace_dir = current_settings.get("CLISettings", {}).get("cc_path")
    
    if not workspace_dir:
        raise HTTPException(status_code=400, detail="工作区路径未配置")

    try:
        task_center = await get_task_center(workspace_dir)
        
        # 构造初始上下文
        context = {
            "task_type": req.task_type,
            "trigger_config": getattr(req, "trigger_config", {}), # 防止取不到报错
            "history": [],
            "ran_count": 0
        }
        
        # 1. 创建任务记录 (⭐ 关键修复：把 req.platforms 传进去)
        task = await task_center.create_task(
            title=req.title,
            description=req.description,
            agent_type=req.agent_type,
            parent_task_id="USER",
            context=context,
            platforms=req.platforms  # 👈👈👈 必须加这一行！
        )
        
        # 2. 读取共识（可选）
        consensus_content = None
        consensus_file = Path(workspace_dir) / ".agent" / "consensus.md"
        if consensus_file.exists():
            import aiofiles
            async with aiofiles.open(consensus_file, 'r', encoding='utf-8') as f:
                consensus_content = await f.read()

        # 3. 执行逻辑分发
        if req.task_type == "once":
            # 立即执行模式：直接丢进后台
            asyncio.create_task(
                run_subtask_in_background(
                    task_id=task.task_id,
                    workspace_dir=workspace_dir,
                    settings=current_settings,
                    consensus_content=consensus_content
                )
            )
            msg = "任务已启动"
        else:
            # 定时或周期模式：由 scheduler.py 负责，此处仅保存
            msg = f"计划任务已创建 (模式: {req.task_type})"
            
        return {"success": True, "message": msg, "task": task.model_dump()}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/v1/tasks/cancel/{task_id}")
async def cancel_task_endpoint(task_id: str):
    """取消任务"""
    current_settings = await load_settings()
    workspace_dir = current_settings.get("CLISettings", {}).get("cc_path")
    if not workspace_dir:
        raise HTTPException(status_code=400, detail="No workspace")
        
    task_center = await get_task_center(workspace_dir)
    success = await task_center.cancel_task(task_id)
    return {"success": success}


@router.delete("/v1/tasks/{task_id}")
async def delete_task_endpoint(task_id: str):
    """删除任务"""
    current_settings = await load_settings()
    workspace_dir = current_settings.get("CLISettings", {}).get("cc_path")
    if not workspace_dir:
        raise HTTPException(status_code=400, detail="No workspace")
        
    task_center = await get_task_center(workspace_dir)
    success = await task_center.delete_task(task_id)
    return {"success": success}

