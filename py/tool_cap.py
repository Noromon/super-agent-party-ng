# -*- coding: utf-8 -*-
"""S233：工具循环轮数上限的运行时热值。

上限原先在请求开始时快照（settings.max_tool_iterations，默认 100），任务执行
中途改设置无效。本模块持有进程级热值，由 save_settings 热同步，工具循环在
每个轮边界读取——调小/调大上限或开合「破限」开关都在在途任务的下一轮边界
（通常秒级）生效。

破限（unlimited）= 本轮任务工具轮数不设上限；恢复限制后，若已累计轮数超过
现上限，循环在下一轮边界自然走既有 LoopCap 收尾提示（阶段性总结），无需
本模块特判。

读取优先级：systemSettings.maxToolIterations → 旧顶层 max_tool_iterations → 100。
"""

DEFAULT_LIMIT = 100
_UNLIMITED_CAP = 10 ** 12

unlimited = False
limit = DEFAULT_LIMIT


def _clamp_limit(raw) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(100000, n))


def apply_setting(settings):
    """save_settings / 启动时同步热值。settings 为完整设置 dict。"""
    global unlimited, limit
    settings = settings or {}
    sys_cfg = settings.get("systemSettings", {}) or {}
    raw = sys_cfg.get("maxToolIterations")
    if raw is None:
        raw = settings.get("max_tool_iterations")
    limit = _clamp_limit(DEFAULT_LIMIT if raw is None else raw)
    unlimited = bool(sys_cfg.get("toolCapUnlimited", False))


def effective_limit() -> int:
    """工具循环每轮边界读取：破限时为天文数字（既有比较逻辑零特判）。"""
    return _UNLIMITED_CAP if unlimited else limit
