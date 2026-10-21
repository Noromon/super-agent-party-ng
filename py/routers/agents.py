# -*- coding: utf-8 -*-
"""Agent-party and A2A endpoints (agent list/remove, a2a init) moved
verbatim out of server.py in the R1 router migration (audit 09
item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve
at request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""
import json
import os
import shutil
from fastapi import Request, status
from fastapi.responses import JSONResponse
from py.get_setting import AGENT_DIR, load_settings
from fastapi import APIRouter

# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible

router = APIRouter()

@router.get("/v1/agents",operation_id="get_agents")
async def get_agents():
    """
    获取模型列表
    """
    try:
        # 重新加载最新设置
        current_settings = await load_settings()
        agents = current_settings['agents']
        # 构造符合 OpenAI 格式的 Model 对象
        model_data = [
            {
                "name": agent["name"],
                "description": agent["system_prompt"],
            }
            for agent in agents.values()  
        ]
        # 添加默认的 'super-model'
        model_data.append(
            {
                "name": 'super-model',
                "description": "Super-Agent-Party default agent",
            }
        )
        return model_data
        
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


@router.delete("/remove_agent")
async def remove_agent_endpoint(request: Request):
    data = await request.json()
    agent_id = data.get("agentId")
    if agent_id:
        try:
            # 删除AGENT_CACHE_DIR目录下的agent_id文件夹
            agent_dir = os.path.join(AGENT_DIR, f"{agent_id}.json")
            shutil.rmtree(agent_dir)
            return JSONResponse({"success": True, "message": "Agent removed"})
        except Exception as e:
            return JSONResponse({"success": False, "message": str(e)})
    else:
        return JSONResponse({"success": False, "message": "No agentId provided"})


@router.post("/a2a")
async def initialize_a2a(request: Request):
    from python_a2a import A2AClient
    data = await request.json()
    try:
        client = A2AClient(data['url'])
        agent_card = client.agent_card.to_json()
        agent_card = json.loads(agent_card)
        return JSONResponse({
            **agent_card,
            "status": "ready",
            "enabled": True
        })
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )

