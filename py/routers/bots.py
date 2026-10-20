# -*- coding: utf-8 -*-
"""IM bot control endpoints (start / stop / reload / status for the
nine bot platforms plus the xmpp certificate flow) moved verbatim
out of server.py in the R1 router migration (audit 09 item 6).  Process state defined by server is reached through
the module object bound below (`_srv`); server runs as __main__ when
launched directly, so we bind the OBJECT once and attributes resolve at
request time (lifespan rebinds stay visible).  server imports this
module, never the other way around.  Legacy exemptions: see pyproject
per-file-ignores.
"""
import sys as _sys
import asyncio
from fastapi.responses import JSONResponse
from fastapi import APIRouter

# bind the server module OBJECT once (see docstring); attributes
# resolve per request so lifespan rebinds stay visible
_srv = _sys.modules.get('server') or _sys.modules['__main__']

router = APIRouter()

@router.post("/start_qq_bot")
async def start_qq_bot(config_data: dict):
    try:
        from py.qq_bot_manager import QQBotConfig
        config = QQBotConfig(**config_data)
        _srv.BotContainer.get_qq().start_bot(config)
        return {"success": True, "message": "QQ机器人已成功启动", "environment": "thread-based"}
    except Exception as e:
        _srv.logger.error(f"启动QQ机器人失败: {e}")
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_qq_bot")
async def stop_qq_bot():
    try:
        if _srv.BotContainer._qq:
            _srv.BotContainer.get_qq().stop_bot()
        return {"success": True, "message": "QQ机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/qq_bot_status")
async def qq_bot_status():
    if _srv.BotContainer._qq is None:
        return {"is_running": False, "status": "stopped"}
    status = _srv.BotContainer.get_qq().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.post("/reload_qq_bot")
async def reload_qq_bot(config_data: dict):
    try:
        from py.qq_bot_manager import QQBotConfig
        config = QQBotConfig(**config_data)
        manager = _srv.BotContainer.get_qq()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "QQ机器人已重新加载", "config_changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_wechat_bot")
async def start_wechat_bot(config_data: dict):
    try:
        from py.wechat_bot_manager import WeChatBotConfig
        config = WeChatBotConfig(**config_data)
        _srv.BotContainer.get_wechat().start_bot(config)
        return {"success": True, "message": "微信机器人已启动，请查看终端输出扫码登录", "environment": "thread-based"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_wechat_bot")
async def stop_wechat_bot():
    try:
        if _srv.BotContainer._wechat:
            _srv.BotContainer.get_wechat().stop_bot()
        return {"success": True, "message": "微信机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/wechat_bot_status")
async def wechat_bot_status():
    if _srv.BotContainer._wechat is None:
        return {"is_running": False}
    status = _srv.BotContainer.get_wechat().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.post("/reload_wechat_bot")
async def reload_wechat_bot(config_data: dict):
    try:
        from py.wechat_bot_manager import WeChatBotConfig
        config = WeChatBotConfig(**config_data)
        manager = _srv.BotContainer.get_wechat()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "微信机器人已重新加载"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_feishu_bot")
async def start_feishu_bot(config_data: dict):
    try:
        from py.feishu_bot_manager import FeishuBotConfig
        config = FeishuBotConfig(**config_data)
        _srv.BotContainer.get_feishu().start_bot(config)
        return {"success": True, "message": "飞书机器人已成功启动", "environment": "thread-based"}
    except Exception as e:
        _srv.logger.error(f"启动飞书机器人失败: {e}")
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_feishu_bot")
async def stop_feishu_bot():
    try:
        if _srv.BotContainer._feishu:
            _srv.BotContainer.get_feishu().stop_bot()
        return {"success": True, "message": "飞书机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/feishu_bot_status")
async def feishu_bot_status():
    if _srv.BotContainer._feishu is None:
        return {"is_running": False}
    status = _srv.BotContainer.get_feishu().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.post("/reload_feishu_bot")
async def reload_feishu_bot(config_data: dict):
    try:
        from py.feishu_bot_manager import FeishuBotConfig
        config = FeishuBotConfig(**config_data)
        manager = _srv.BotContainer.get_feishu()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "飞书机器人已重新加载", "config_changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_dingtalk_bot")
async def start_dingtalk_bot(config_data: dict):
    try:
        from py.dingtalk_bot_manager import DingtalkBotConfig
        config = DingtalkBotConfig(**config_data)
        _srv.BotContainer.get_dingtalk().start_bot(config)
        return {"success": True, "message": "钉钉机器人已成功启动"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/stop_dingtalk_bot")
async def stop_dingtalk_bot():
    try:
        if _srv.BotContainer._dingtalk:
            _srv.BotContainer.get_dingtalk().stop_bot()
        return {"success": True, "message": "钉钉机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/dingtalk_bot_status")
async def dingtalk_bot_status():
    if _srv.BotContainer._dingtalk is None:
        return {"is_running": False}
    return _srv.BotContainer.get_dingtalk().get_status()


@router.post("/reload_dingtalk_bot")
async def reload_dingtalk_bot(config_data: dict):
    try:
        from py.dingtalk_bot_manager import DingtalkBotConfig
        config = DingtalkBotConfig(**config_data)
        manager = _srv.BotContainer.get_dingtalk()
        manager.stop_bot()
        import time as sync_time # 这里的 time 是为了配合你原代码中的 time.sleep
        sync_time.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "钉钉机器人配置已重载"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/start_discord_bot")
async def start_discord_bot(config_data: dict):
    try:
        from py.discord_bot_manager import DiscordBotConfig
        config = DiscordBotConfig(**config_data)
        _srv.BotContainer.get_discord().start_bot(config)
        return {"success": True, "message": "Discord 机器人已启动"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/stop_discord_bot")
async def stop_discord_bot():
    if _srv.BotContainer._discord:
        _srv.BotContainer.get_discord().stop_bot()
    return {"success": True, "message": "Discord 机器人已停止"}


@router.get("/discord_bot_status")
async def discord_bot_status():
    if _srv.BotContainer._discord is None:
        return {"is_running": False}
    return _srv.BotContainer.get_discord().get_status()


@router.post("/reload_discord_bot")
async def reload_discord_bot(config_data: dict):
    try:
        from py.discord_bot_manager import DiscordBotConfig
        config = DiscordBotConfig(**config_data)
        manager = _srv.BotContainer.get_discord()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "Discord 机器人已重载"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_slack_bot")
async def start_slack_bot(config_data: dict):
    try:
        from py.slack_bot_manager import SlackBotConfig
        config = SlackBotConfig(**config_data)
        _srv.BotContainer.get_slack().start_bot(config)
        return {"success": True, "message": "Slack 机器人已启动"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": str(e)})


@router.post("/stop_slack_bot")
async def stop_slack_bot():
    if _srv.BotContainer._slack:
        _srv.BotContainer.get_slack().stop_bot()
    return {"success": True, "message": "Slack 机器人已停止"}


@router.get("/slack_bot_status")
async def slack_bot_status():
    if _srv.BotContainer._slack is None:
        return {"is_running": False}
    return _srv.BotContainer.get_slack().get_status()


@router.post("/reload_slack_bot")
async def reload_slack_bot(config_data: dict):
    try:
        from py.slack_bot_manager import SlackBotConfig
        config = SlackBotConfig(**config_data)
        manager = _srv.BotContainer.get_slack()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "Slack 机器人已重载"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_telegram_bot")
async def start_telegram_bot(config_data: dict):
    try:
        from py.telegram_bot_manager import TelegramBotConfig
        config = TelegramBotConfig(**config_data)
        _srv.BotContainer.get_telegram().start_bot(config)
        return {"success": True, "message": "Telegram 机器人已成功启动", "environment": "thread-based"}
    except Exception as e:
        _srv.logger.error(f"启动 Telegram 机器人失败: {e}")
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_telegram_bot")
async def stop_telegram_bot():
    try:
        if _srv.BotContainer._telegram:
            _srv.BotContainer.get_telegram().stop_bot()
        return {"success": True, "message": "Telegram 机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/telegram_bot_status")
async def telegram_bot_status():
    if _srv.BotContainer._telegram is None:
        return {"is_running": False}
    status = _srv.BotContainer.get_telegram().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.post("/reload_telegram_bot")
async def reload_telegram_bot(config_data: dict):
    try:
        from py.telegram_bot_manager import TelegramBotConfig
        config = TelegramBotConfig(**config_data)
        manager = _srv.BotContainer.get_telegram()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "Telegram 机器人已重新加载", "config_changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_xmpp_bot")
async def start_xmpp_bot(config_data: dict):
    try:
        from py.xmpp_bot_manager import XmppBotConfig
        config = XmppBotConfig(**config_data)
        _srv.BotContainer.get_xmpp().start_bot(config)
        return {"success": True, "message": "XMPP 机器人已成功启动", "environment": "thread-based"}
    except Exception as e:
        _srv.logger.error(f"启动 XMPP 机器人失败: {e}")
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_xmpp_bot")
async def stop_xmpp_bot():
    try:
        if _srv.BotContainer._xmpp:
            _srv.BotContainer.get_xmpp().stop_bot()
        return {"success": True, "message": "XMPP 机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/xmpp_bot_status")
async def xmpp_bot_status():
    from py import xmpp_trust
    if _srv.BotContainer._xmpp is None:
        return {"is_running": False, "pending_certs": xmpp_trust.PENDING.list()}
    status = _srv.BotContainer.get_xmpp().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.get("/xmpp_cert_pending")
async def xmpp_cert_pending():
    from py import xmpp_trust
    items = []
    for it in xmpp_trust.PENDING.list():
        it.pop("pem", None)  # 指纹与摘要足够审阅，不整段外发 PEM
        items.append(it)
    return {"pending": items}


@router.post("/xmpp_cert_decision")
async def xmpp_cert_decision(data: dict):
    from py import xmpp_trust
    key = str(data.get("key", ""))
    decision = str(data.get("decision", ""))
    if not key or decision not in ("reject", "once", "always"):
        return JSONResponse(status_code=400, content={"success": False, "message": "需要 key 与 decision(reject|once|always)"})
    handled = xmpp_trust.decide(key, decision)
    if not handled:
        return JSONResponse(status_code=404, content={"success": False, "message": "无对应待审证书"})
    return {"success": True, "decision": decision}


@router.post("/reload_xmpp_bot")
async def reload_xmpp_bot(config_data: dict):
    try:
        from py.xmpp_bot_manager import XmppBotConfig
        config = XmppBotConfig(**config_data)
        manager = _srv.BotContainer.get_xmpp()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "XMPP 机器人已重新加载", "config_changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.post("/start_wecom_bot")
async def start_wecom_bot(config_data: dict):
    try:
        from py.wecom_bot_manager import WeComBotConfig
        config = WeComBotConfig(**config_data)
        _srv.BotContainer.get_wecom().start_bot(config)
        return {"success": True, "message": "企业微信机器人已成功启动", "environment": "thread-based"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"success": False, "message": f"启动失败: {str(e)}", "error_type": "startup_error"})


@router.post("/stop_wecom_bot")
async def stop_wecom_bot():
    try:
        if hasattr(_srv.BotContainer, '_wecom') and _srv.BotContainer._wecom:
            _srv.BotContainer.get_wecom().stop_bot()
        return {"success": True, "message": "企业微信机器人已停止"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})


@router.get("/wecom_bot_status")
async def wecom_bot_status():
    if not hasattr(_srv.BotContainer, '_wecom') or _srv.BotContainer._wecom is None:
        return {"is_running": False}
    status = _srv.BotContainer.get_wecom().get_status()
    if status.get("startup_error") and not status.get("is_running"):
        status["error_message"] = f"启动失败: {status['startup_error']}"
    return status


@router.post("/reload_wecom_bot")
async def reload_wecom_bot(config_data: dict):
    try:
        from py.wecom_bot_manager import WeComBotConfig
        config = WeComBotConfig(**config_data)
        manager = _srv.BotContainer.get_wecom()
        manager.stop_bot()
        await asyncio.sleep(1)
        manager.start_bot(config)
        return {"success": True, "message": "企业微信机器人已重新加载", "config_changed": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "message": str(e)})

