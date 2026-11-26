# -*- coding: utf-8 -*-
"""S324：授权管理面板端点——查看/收回/重新授权「总是允许」白名单。

「总是允许」来自审批弹窗的 Allow Always（approval_exec "always"）。
S329 两级化：插件域工具（GLOBAL_APPROVAL_TOOLS，如拉起插件后台服务）
存全局层 settings.globalAllowedTools——与当前工作区无关，无 cwd 也可
查看/管理；系统高危类仍存工作区级 .party/config.json。面板=授权主
控制台：工具勾选双向（写=显式再授权，无需等下次弹批）。
"""
import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from py.get_setting import load_settings, save_settings

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
    """授权全景两级：全局层（插件域）+ 当前工作区层（高危工具/目录）。
    无 cwd 不再整体报错——全局区照常可读（S329：插件与 cwd 解耦）。"""
    from py.agent import get_project_config_data
    from py.tool_registry import GLOBAL_APPROVAL_TOOLS, SENSITIVE_TOOLS
    cwd = ""
    global_allowed = []
    data = {"allowed_tools": [], "allowed_dirs": []}
    try:
        s = await load_settings()
        cwd = (s.get("CLISettings") or {}).get("cc_path") or ""
        global_allowed = [t for t in (s.get("globalAllowedTools") or []) if t]
        if cwd:
            data = get_project_config_data(cwd)
    except Exception as e:
        raise HTTPException(500, f"读取授权配置失败: {e}")
    allowed = data["allowed_tools"]
    # 工作区池=敏感工具（剔除插件域）∪ 已授权项；插件域单独进全局区
    ws_pool = [t for t in SENSITIVE_TOOLS if t not in GLOBAL_APPROVAL_TOOLS]
    pool = list(dict.fromkeys(ws_pool + [t for t in allowed if t not in ws_pool]))
    g_pool = list(dict.fromkeys(list(GLOBAL_APPROVAL_TOOLS) +
                                [t for t in global_allowed if t not in GLOBAL_APPROVAL_TOOLS]))
    return {"cwd": cwd, "allowed_tools": allowed, "allowed_dirs": data["allowed_dirs"],
            "tools_pool": pool,
            "global_allowed_tools": global_allowed, "global_pool": g_pool}


@router.post("/allowlist/tool")
async def set_tool_perm(req: ToolPermReq):
    from py.agent import add_tool_to_project_config, remove_tool_from_project_config
    from py.tool_registry import GLOBAL_APPROVAL_TOOLS
    name = str(req.name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(400, "非法工具名")
    if name in GLOBAL_APPROVAL_TOOLS:
        # S329：插件域=全局层（无需 cwd）
        s = await load_settings()
        gl = [t for t in (s.get("globalAllowedTools") or []) if t]
        if req.allowed and name not in gl:
            gl.append(name)
        elif not req.allowed and name in gl:
            gl.remove(name)
        s["globalAllowedTools"] = gl
        await save_settings(s)
        return {"name": name, "allowed": bool(req.allowed), "scope": "global"}
    cwd = await _cwd_or_400()
    if req.allowed:
        add_tool_to_project_config(cwd, name)
    else:
        remove_tool_from_project_config(cwd, name)
    return {"name": name, "allowed": bool(req.allowed), "scope": "project"}


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
