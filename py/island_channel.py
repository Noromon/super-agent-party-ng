# -*- coding: utf-8 -*-
"""S222: 灵动岛 HUD 行为频道——把旁观发言等主动消息经 notification_center 投递到
本机 HUD（hud-capsule.js 胶囊/气泡，bot 分类默认显示）与通知中心留痕。

与 IM 平台 handler 契约同形 handler(chat_id, BehaviorItem)；island 为本地伪平台，
恒可用、无连接态。普通 behaviorList 事件因 island 无 platform_targets（空目标）
天然不达 HUD——旁观发言经 watcher 直调 handler("", item) 恰好投递（S71 直调语义）。
文本与 IM 同形：action.prompt → 本机 /v1 主链生成（角色人设随之生效）→ strip 空
回复吞掉（im_empty_guard）。唯一有意识分歧：生成失败回退直发观察事实文本（送达
优先），IM 侧失败即弃。
"""
import logging

from py import llm_gate

_GENERATE_TIMEOUT = 90


def _prompt_of(item):
    return (getattr(getattr(item, "action", None), "prompt", "") or "").strip()


def fact_text(item):
    """回退文本：旁观事实原文优先；非旁观直投（如日记选 island）退 prompt 截断。"""
    fact = (getattr(item, "screen_fact", "") or "").strip()
    if fact:
        return f"【屏幕旁观】{fact}"
    prompt = _prompt_of(item)
    return ("【主动消息】" + prompt[:200]) if prompt else ""


@llm_gate.gated
async def _generate(item) -> str:
    """与 bot 侧行为生成同形：进程内自调 /v1 主链（persona/工具过滤随
    behavior_trigger+tools_override），非自建模型连接。"""
    from openai import AsyncOpenAI
    from py.get_setting import get_port, load_settings
    settings = await load_settings()
    model = settings.get("model") or "default"
    client = AsyncOpenAI(api_key="super-secret-key",
                         base_url=f"http://127.0.0.1:{get_port()}/v1",
                         timeout=_GENERATE_TIMEOUT)
    resp = await client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": f"[system]: {_prompt_of(item)}"}],
        stream=False,
        extra_body={"is_app_bot": True, "platform": "island",
                    "behavior_trigger": True, **item.tools_override()})
    return (resp.choices[0].message.content or "").strip()


async def island_behavior_handler(chat_id, item):
    """behavior handler 契约实现；chat_id 忽略（HUD 无对端概念，广播本机）。

    空回复=模型判定不值得打扰 → 吞掉（与 IM 同形，不发回退）；
    生成失败=基础设施异常 → 才回退直发观察事实（送达优先）。
    """
    if item is None:
        return
    from py import notification_center
    from py.im_empty_guard import log_empty_reply
    gen_failed = False
    text = ""
    try:
        text = await _generate(item)
    except Exception as e:
        gen_failed = True
        logging.getLogger("app").warning(f"[IslandHUD] 生成失败: {e}")
    if not text:
        if not gen_failed:
            log_empty_reply("island-behavior", "hud")
            return
        text = fact_text(item)
    if not text:
        return
    notification_center.emit("bot", text[:500],
                             extra={"source": "screen_speak" if (
                                 getattr(item, "screen_fact", "") or "").strip()
                                 else "behavior", "platform": "island"})


def register_island_channel():
    """server 启动时注册（幂等）。与 bot 平台的 register_handler 同一注册表。"""
    from py.behavior_engine import global_behavior_engine
    global_behavior_engine.register_handler("island", island_behavior_handler)
