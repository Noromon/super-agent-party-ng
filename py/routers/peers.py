# -*- coding: utf-8 -*-
"""S145：/api/peers-seen —— UI「已见未登记」对端列表。"""
from fastapi import APIRouter

from py import peer_identity

router = APIRouter()


@router.get("/api/peers-seen")
async def peers_seen():
    return peer_identity.get_seen()
