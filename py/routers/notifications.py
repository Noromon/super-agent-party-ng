# -*- coding: utf-8 -*-
"""S151: 通知中心端点——列表/已读/清空 + IM 挂起审批的双向批复。"""
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

router = APIRouter()


class ReadReq(BaseModel):
    ids: Optional[List[str]] = None  # None=全部标记已读


class ImDecisionReq(BaseModel):
    approval_id: str
    decision: str  # approve | always | deny
    note: str = ""


@router.get("/api/notifications")
async def notifications_list(category: str = "", unread_only: bool = False,
                             limit: int = 100):
    from py import notification_center
    return {"items": notification_center.list_items(category, unread_only, limit)}


@router.post("/api/notifications/read")
async def notifications_read(req: ReadReq):
    from py import notification_center
    return {"updated": notification_center.mark_read(req.ids)}


@router.post("/api/notifications/clear")
async def notifications_clear():
    from py import notification_center
    return {"cleared": notification_center.clear_all()}


@router.post("/api/notifications/im_decision")
async def notifications_im_decision(req: ImDecisionReq):
    """IM 来源挂起审批在 Web 面板批复（本机主人免 approver 名录门禁）。"""
    from py import approval_im
    ok, msg = await approval_im.resolve_by_id_web(req.approval_id, req.decision, req.note)
    if not ok:
        return JSONResponse(status_code=400, content={"success": False, "message": msg})
    return {"success": True, "message": msg}
