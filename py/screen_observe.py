# -*- coding: utf-8 -*-
"""S226 旁观判断 VLM 的路由与请求体解析（纯函数，零网络零 LLM）。

仅服务于窥屏"观察/判断"调用（screen_watcher._vlm）；发言仍走主模型链不动。与
unifiedModel、共享 vision 角色、聊天图片理解、desktopVision 完全解耦——这里只决定
"用哪个端点做观察 + 这次观察额外下发哪些引擎参数"。

观察配置位于 settings['screenWatchSettings']['observe']：
- mode: auto(默认,现状) | main(主模型) | vlm(独立 vision 角色) | custom(独立端点)
- custom: {model, baseUrl, apiKey}
- activePreset / presets[{name, bodyJson}] / extraParamsJson —— 思考与引擎适配参数，
  任意 mode 皆可叠加。预设 body 以 JSON 字符串存（便于前端 textarea 直接编辑），
  合并次序：activePreset.bodyJson → extraParamsJson（后者深度合并、同名覆盖、自由兜底）。
"""
import json
import logging


def _observe(settings):
    return ((settings or {}).get("screenWatchSettings") or {}).get("observe") or {}


def resolve_observe_cfg(settings: dict) -> dict:
    """观察调用的端点配置（与 vision 角色同形：api_key/base_url/model/enabled）。

    main/custom 视为按需启用（端点填了才可用）；vlm 沿用 vision.enabled；
    auto 完全委托 vision_model_cfg（＝现状，零行为回归）。非破坏——不回写 settings。
    """
    settings = settings or {}
    mode = (_observe(settings).get("mode") or "auto").lower()
    if mode == "main":
        return {"enabled": bool(settings.get("base_url")),
                "api_key": settings.get("api_key"),
                "base_url": settings.get("base_url"),
                "model": settings.get("model"),
                "selectedProvider": settings.get("selectedProvider")}
    if mode == "vlm":
        return dict(settings.get("vision") or {})
    if mode == "custom":
        c = _observe(settings).get("custom") or {}
        return {"enabled": bool(c.get("baseUrl") and c.get("model")),
                "api_key": c.get("apiKey"),
                "base_url": c.get("baseUrl"),
                "model": c.get("model")}
    from py.get_setting import vision_model_cfg  # 延迟导入避免环依赖
    return dict(vision_model_cfg(settings))


def _deep_merge(base: dict, over: dict) -> dict:
    """就地深度合并：dict 递归、其余整体覆盖；over 优先。"""
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def build_observe_extra_body(settings: dict) -> dict:
    """观察调用要下发的 extra_body（思考/引擎参数）。activePreset 预设 → extraParamsJson
    自由 JSON，逐层深度合并（自由兜底、同名覆盖、嵌套如 chat_template_kwargs 不被吞）。
    任一段非法 JSON → 告警并忽略该段，绝不炸观察主链路。返回 {} 表示不注入（＝现状）。"""
    ob = _observe(settings)
    out = {}
    active = ob.get("activePreset") or ""
    if active:
        for p in ob.get("presets") or []:
            if isinstance(p, dict) and p.get("name") == active:
                body = _load_json_obj(p.get("bodyJson"), f"预设「{p.get('name')}」")
                if body:
                    _deep_merge(out, body)
                break
    free = _load_json_obj(ob.get("extraParamsJson"), "自定义参数")
    if free:
        _deep_merge(out, free)
    return out


def _load_json_obj(raw, what):
    """把字符串解析成 dict；空/非对象/坏 JSON 都安全返回 {}（坏 JSON 告警）。"""
    s = (raw or "").strip()
    if not s:
        return {}
    try:
        obj = json.loads(s)
    except Exception as e:
        logging.getLogger("app").warning(
            f"[ScreenWatch] observe {what} 解析失败，已忽略: {e}")
        return {}
    if not isinstance(obj, dict):
        logging.getLogger("app").warning(
            f"[ScreenWatch] observe {what} 不是 JSON 对象，已忽略")
        return {}
    return obj
