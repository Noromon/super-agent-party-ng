# -*- coding: utf-8 -*-
"""S324：授权管理面板端点——查看/收回/重新授权工作区「总是允许」白名单。

「总是允许」来自审批弹窗的 Allow Always（approval_exec "always" →
.party/config.json），此前只能进不能出；本模块给用户完整的收回/再授权
能力。面板=授权主控制台：工具勾选双向（写=显式再授权，无需等下次弹批）。
"""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from py.get_setting import load_settings

router = APIRouter(prefix="/api/permissions", tags=["permissions"])


class ToolPermReq(BaseModel):
    name: str
    allowed: bool


class DirPermReq(BaseModel):
    dir: str
    allowed: bool


async def _cwd_or_400() -> str:
    s = await load_settings()
    cwd = (s.get("CLISettings") or {}).get("cc_path") or ""
    if not cwd:
        raise HTTPException(400, "未配置工作区（CLISettings.cc_path 为空），白名单无从存取")
    return cwd


@router.get("/allowlist")
async def get_allowlist():
    """当前工作区的白名单全景：已授权项 + 可授权候选（敏感工具池 ∪ 已授权）。"""
    from py.agent import get_project_config_data
    from py.tool_registry import SENSITIVE_TOOLS
    cwd = ""
    data = {"allowed_tools": [], "allowed_dirs": []}
    try:
        s = await load_settings()
        cwd = (s.get("CLISettings") or {}).get("cc_path") or ""
        if cwd:
            data = get_project_config_data(cwd)
    except Exception as e:
        raise HTTPException(500, f"读取授权配置失败: {e}")
    allowed = data["allowed_tools"]
    pool = list(dict.fromkeys(list(SENSITIVE_TOOLS) + [t for t in allowed if t not in SENSITIVE_TOOLS]))
    return {"cwd": cwd, "allowed_tools": allowed, "allowed_dirs": data["allowed_dirs"],
            "tools_pool": pool}


@router.post("/allowlist/tool")
async def set_tool_perm(req: ToolPermReq):
    from py.agent import add_tool_to_project_config, remove_tool_from_project_config
    name = str(req.name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "非法工具名")
    cwd = await _cwd_or_400()
    if req.allowed:
        add_tool_to_project_config(cwd, name)
    else:
        remove_tool_from_project_config(cwd, name)
    return {"name": name, "allowed": bool(req.allowed)}


@router.post("/allowlist/dir")
async def set_dir_perm(req: DirPermReq):
    from py.agent import add_dirs_to_project_config, remove_dir_from_project_config
    d = str(req.dir or "").strip()
    if not d or not os.path.isabs(d):
        raise HTTPException(400, "目录必须是绝对路径")
    cwd = await _cwd_or_400()
    if req.allowed:
        add_dirs_to_project_config(cwd, [d])
    else:
        remove_dir_from_project_config(cwd, d)
    return {"dir": d, "allowed": bool(req.allowed)}
