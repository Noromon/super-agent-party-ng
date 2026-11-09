# -*- coding: utf-8 -*-
"""S206 每模型推理参数覆盖：provider 卡片 params → 角色有效值合并。

数据：settings.modelProviders[i].params = {temperature?, top_p?, max_tokens?,
reasoning_effort?, contextWindow?, extra_params?}，字段缺省/null/空串=继承角色默认。
语义（用户定稿）：卡片参数作用于所有选中该卡片的角色；extra_params 模型级整体替换
角色级列表；优先级 请求级 > 模型卡片级 > 角色默认（请求级由调用方处理）。
"""
from __future__ import annotations

_PARAM_KEYS = ("temperature", "top_p", "max_tokens", "reasoning_effort")


def provider_overrides(settings, selected_provider_id) -> dict:
    """按 selectedProvider id 取卡片覆盖，仅返回非空字段；无效/缺失 → {}。"""
    if not selected_provider_id or not isinstance(settings, dict):
        return {}
    params = None
    for p in settings.get("modelProviders") or []:
        try:
            if isinstance(p, dict) and p.get("id") == selected_provider_id:
                params = p.get("params")
                break
        except AttributeError:
            continue
    if not isinstance(params, dict):
        return {}
    out = {}
    for k in _PARAM_KEYS + ("contextWindow",):
        v = params.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, str) and v.strip().lower() == "auto" and k == "contextWindow":
            out[k] = "auto"
            continue
        if k == "reasoning_effort":
            if isinstance(v, str) and v.strip():
                out[k] = v.strip()
            continue
        try:
            float(v)
        except (TypeError, ValueError):
            continue
        out[k] = v
    ep = params.get("extra_params")
    if isinstance(ep, list):
        out["extra_params"] = [e for e in ep if isinstance(e, dict)]
    return out


def effective_main_params(settings) -> dict:
    """主角色有效参数：角色默认 + 卡片覆盖。"""
    settings = settings or {}
    eff = {
        "temperature": settings.get("temperature", 1),
        "top_p": settings.get("top_p", 1),
        "max_tokens": settings.get("max_tokens"),
        "reasoning_effort": settings.get("reasoning_effort"),
        "extra_params": list(settings.get("extra_params") or []),
    }
    ov = provider_overrides(settings, settings.get("selectedProvider"))
    for k in _PARAM_KEYS:
        if ov.get(k) is not None:
            eff[k] = ov[k]
    if "extra_params" in ov:
        eff["extra_params"] = list(ov["extra_params"])  # 浅拷贝：调用方会原地 remove
    return eff


def effective_role_params(settings, role_cfg) -> dict:
    """通用角色（fast/reasoner/vision…）：角色默认 + 卡片覆盖。"""
    settings = settings or {}
    role_cfg = role_cfg if isinstance(role_cfg, dict) else {}
    eff = {k: v for k, v in role_cfg.items() if k in _PARAM_KEYS}
    ov = provider_overrides(settings, role_cfg.get("selectedProvider"))
    for k in _PARAM_KEYS:
        if ov.get(k) is not None:
            eff[k] = ov[k]
    return eff
