# -*- coding: utf-8 -*-
"""Bot conversation management and conversation compact/delete
endpoints moved verbatim out of server.py in the R1 router
migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.
"""

import logging
import sys as _sys
from fastapi import Request
from fastapi.responses import JSONResponse
from py.get_setting import load_covs, load_settings, save_covs
from pydantic import BaseModel
from typing import Union
from fastapi import APIRouter

class DeleteConversationRequest(BaseModel):
    conversation_id: Union[str, int, float]
    delete_memory: bool = False


# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/api/compact")
async def compact_conversation_endpoint(request: Request):
    """手动上下文压缩（/compact 指令）：任意任务模式生成摘要，前端负责替换落账。"""
    settings = await load_settings()
    body = await request.json()
    messages = body.get("messages") or []
    focus = (body.get("focus") or "").strip() or None
    conversation_id = body.get("conversation_id")
    if not messages:
        return JSONResponse(status_code=400, content={"ok": False, "reason": "empty messages"})
    try:
        from py.context_manager import compact_messages, detect_task_mode, get_context_settings
        c_class = _srv.get_client_class(settings, settings['selectedProvider'])
        compact_client = _srv.client if _srv.client is not None else c_class(
            api_key=settings['api_key'],
            base_url=settings['base_url'] or "https://api.openai.com/v1")
        r_cli = None
        r_model = None
        if settings.get('reasoner', {}).get('enabled'):
            r_class = _srv.get_client_class(settings, settings['reasoner']['selectedProvider'])
            r_cli = _srv.reasoner_client if _srv.reasoner_client is not None else r_class(
                api_key=settings['reasoner']['api_key'],
                base_url=settings['reasoner']['base_url'] or "https://api.openai.com/v1")
            r_model = settings['reasoner']['model']
        cm = get_context_settings(settings)
        task_mode = detect_task_mode(messages)
        if not cm["enabled"]:
            cm = dict(cm, enabled=True)  # 手动指令无视自动开关
        res = await compact_messages(compact_client, settings['model'], messages, task_mode=task_mode,
                                     focus=focus, keep_recent_dialog=cm["keep_recent_dialog"],
                                     extra_params=None, reasoner_client=r_cli, reasoner_model=r_model)
        if not res:
            return {"ok": False, "reason": "not-worth-compacting"}
        req_stub = _srv.ChatRequest(messages=messages, conversation_id=conversation_id)
        _srv._write_context_state(settings, req_stub, res)
        return {"ok": True, "summary": res["summary"], "task_mode": res["task_mode"],
                "compacted_count": res["compacted_count"]}
    except Exception as e:
        logging.getLogger("app").info(f"[Compact] /api/compact 失败: {e}")
        return JSONResponse(status_code=500, content={"ok": False, "reason": str(e)})


@router.post("/api/conversations/delete")
async def delete_conversation_endpoint(req: DeleteConversationRequest):
    req.conversation_id = _srv._normalize_entity_id(req.conversation_id)
    covs = await load_covs()
    conversations = covs.get("conversations", []) or []
    covs["conversations"] = [conv for conv in conversations if conv.get("id") != req.conversation_id]
    await save_covs(covs)
    if req.delete_memory:
        await _srv._invalidate_group_memories_by_chat(req.conversation_id)
    return {"success": True}


@router.get("/bot_conversations")
async def bot_conversations():
    from py.get_setting import list_bot_convs
    try:
        items = await list_bot_convs()
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})
    live = set()
    if _srv.BotContainer._xmpp is not None and getattr(_srv.BotContainer._xmpp, "bot_client", None):
        live = {"bot:xmpp:%s" % k for k in (_srv.BotContainer._xmpp.bot_client.memoryList or {})}
    for it in items:
        it.update(_srv._bot_conv_meta(it["conv_id"]))
        it["live"] = it["conv_id"] in live
    return {"success": True, "conversations": items}


@router.get("/bot_conversation")
async def bot_conversation(id: str):
    from py.get_setting import load_bot_conv, redact_messages_for_view
    if not str(id).startswith("bot:"):
        return JSONResponse(status_code=400, content={"success": False, "message": "id 需以 bot: 开头"})
    msgs = await load_bot_conv(id)
    if msgs is None:
        return JSONResponse(status_code=404, content={"success": False, "message": "会话不存在"})
    return {"success": True, "conv_id": id, **_srv._bot_conv_meta(id),
            "messages": redact_messages_for_view(msgs)}


@router.delete("/bot_conversation")
async def delete_bot_conversation(id: str):
    from py.get_setting import delete_bot_conv
    try:
        await delete_bot_conv(id)
        return {"success": True}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/bot_conversation/clear")
async def clear_bot_conversation(data: dict):
    from py.get_setting import save_bot_conv
    conv_id = str(data.get("id", ""))
    try:
        await save_bot_conv(conv_id, [])
        if _srv.BotContainer._xmpp is not None and getattr(_srv.BotContainer._xmpp, "bot_client", None):
            jid = _srv._bot_conv_meta(conv_id)["peer"] if conv_id.startswith("bot:xmpp:") else ""
            if jid and jid in _srv.BotContainer._xmpp.bot_client.memoryList:
                _srv.BotContainer._xmpp.bot_client.memoryList[jid] = []
        return {"success": True}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/bot_conversation/new")
async def new_bot_conversation(data: dict):
    """Archive the active conversation; next inbound message starts fresh."""
    from py.get_setting import archive_bot_conv
    conv_id = str(data.get("id", ""))
    try:
        archive_id = await archive_bot_conv(conv_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})
    if _srv.BotContainer._xmpp is not None and getattr(_srv.BotContainer._xmpp, "bot_client", None):
        jid = _srv._bot_conv_meta(conv_id)["peer"] if conv_id.startswith("bot:xmpp:") else ""
        if jid and jid in _srv.BotContainer._xmpp.bot_client.memoryList:
            _srv.BotContainer._xmpp.bot_client.memoryList[jid] = []
    return {"success": True, "archive_id": archive_id}


@router.post("/bot_conversation/activate")
async def activate_bot_conversation(data: dict):
    """Swap an archived conversation into the active slot (demoting the
    current active one into the archive) — next message continues it."""
    from py.get_setting import swap_bot_conv, load_bot_conv
    archive_id, active_id = str(data.get("id", "")), str(data.get("into", ""))
    try:
        await swap_bot_conv(archive_id, active_id)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})
    if _srv.BotContainer._xmpp is not None and getattr(_srv.BotContainer._xmpp, "bot_client", None):
        jid = _srv._bot_conv_meta(active_id)["peer"] if active_id.startswith("bot:xmpp:") else ""
        if jid:
            _srv.BotContainer._xmpp.bot_client.memoryList[jid] = await load_bot_conv(active_id) or []
    return {"success": True}

