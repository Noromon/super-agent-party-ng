# -*- coding: utf-8 -*-
"""S296：工具调用绕圈熔断器——贴吧探索事故（40 分钟、几十次近重复调用、零拦截）的直接对症。

滑窗签名计数：签名 = 工具名 + 归一化参数（小写、数字折叠为 0、percent 转义串折叠为 ¤、
空白收敛、总长截断）。percent 折叠让手敲 CJK 编码的错体互相收敛——"每次 URL 都稍微
不一样但全都错"的那类绕圈会判为同类，这正是事故主形态。

同签名在窗口内达到 repeat 次 → 产一次性提示（每签名只炸一次；后续再炸换升级文案），
由服务端以 name=system_note 元频道消息注入下一轮（不进前端时间线/mem0，同 S166 惯例）。
无参观测/轮询类工具豁免（重复是合法形态，签名无区分度反成误报源）。

纯逻辑模块，无 IO：服务端只做 observe→注入；可单测。
"""
import json
import re

EXEMPT = frozenset({
    # 合法轮询/无参观测类：重复调用是正常形态
    "wait_for", "check_redirect", "network_watch",
    "list_pages", "take_snapshot", "get_page_markdown", "take_screenshot",
    "browser_policy_report", "get_task_status", "query_task_progress",
})

_PCT = re.compile(r"(?:%[0-9a-fA-F]{2})+")
_NUM = re.compile(r"\d+")
_WS = re.compile(r"\s+")

_HINT1 = ("[系统·绕圈检测] 最近 {w} 次调用里 {name} 已用近似相同的参数调了 {n} 次"
          "（参数仅有数字/编码/空白差异）——重复同一形态大概率是死循环。"
          "立刻改用根本不同的路径（换工具、换数据源、站内搜索表单代替猜 URL、"
          "或先落盘已有成果），或向用户明确说明遇到的障碍；继续磨同一个形状没有意义。")
_HINT2 = ("[系统·绕圈检测·第{k}次] {name} 又近似相同参数重复了 {n} 次。最后提醒："
          "除非策略已发生实质变化，唯一正确动作是收尾——向用户交代你已尝试什么、"
          "卡点在哪、需要其做什么（如手动通过验证码）。")


def signature(name, args_dict):
    """稳定近重复签名：percent 串→¤（折叠手敲编码变体）、数字→0、空白收敛、截 200。"""
    try:
        raw = json.dumps(args_dict or {}, sort_keys=True, ensure_ascii=False)
    except Exception:
        raw = str(args_dict)
    raw = _PCT.sub("\u00a4", raw)
    raw = _NUM.sub("0", raw)
    raw = _WS.sub(" ", raw).strip().lower()
    return (str(name) + "|" + raw)[:200]


class SpiralWatch:
    def __init__(self, window=12, repeat=5):
        self.window = max(repeat + 1, int(window))
        self.repeat = max(3, int(repeat))
        self.recent = []
        self.tripped = set()
        self.trips = 0

    def observe(self, name, args_dict):
        """记录一次调用；应触发时返回提示文本（每签名一次），否则 None。"""
        if name in EXEMPT:
            return None
        sig = signature(name, args_dict)
        self.recent.append(sig)
        if len(self.recent) > self.window:
            self.recent.pop(0)
        n = self.recent.count(sig)
        if n < self.repeat or sig in self.tripped:
            return None
        self.tripped.add(sig)
        self.trips += 1
        tool = str(name)
        if self.trips == 1:
            return _HINT1.format(w=self.window, name=tool, n=n)
        return _HINT2.format(k=self.trips, name=tool, n=n)
