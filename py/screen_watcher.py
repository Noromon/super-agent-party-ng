# -*- coding: utf-8 -*-
"""S215 旁观者内核：亚实时屏幕视觉观察 → 结构化事件 → jsonl。

总规划（用户已批）：采集→视觉理解→情景记忆(S216)→对话注入(S217)→主动发言(S218)。
本期内核约束：默认关闭；aHash 场景门控——画面未变不调 VLM（成本命门）；前台窗口
标题命中隐私黑名单直接跳帧（密码管理器等，敏感画面不进 VLM）；视觉严格用
settings['vision'] 卡，不回退主卡（主卡常为纯文本）；pyautogui/PIL 可选导入
（Docker/无头自动禁用，沿用 computer_use_tool 语义）；截图只看，绝不碰键鼠。
循环未启用时空转（仿 diary_engine），保存设置经 update_config 热更新。
"""
import asyncio
import base64
import ctypes
import datetime
import io
import json
import logging
import os
import time
from typing import Optional

from py import llm_gate
from py import screen_memory
from py import screen_speak
from py.get_setting import SCREEN_WATCH_DIR, load_settings
from py.llm_recovery import acreate

GUI_AVAILABLE = False
try:
    import pyautogui
    from PIL import Image
    GUI_AVAILABLE = True
except Exception as _e:  # 无头环境不 crash，观察功能自动不可用
    logging.getLogger("app").info(f"⚠️ [ScreenWatcher] 屏幕采集不可用 (缺 pyautogui/PIL): {_e}")

DEFAULT_PRIVACY_KEYWORDS = ("1password", "keepass", "lastpass", "bitwarden",
                            "dashlane", "密码管理器", "凭据管理")
_VLM_PROMPT = (
    "这是用户桌面的当前屏幕截图。分析前景窗口内容，严格只输出 JSON（不要代码围栏、"
    '不要任何其他文字）：{"summary": "用中文一句话描述前景内容与关键信息(80字内)", '
    '"activity": "在 coding|browsing|chatting|meeting|gaming|idle|other 中选一个", '
    '"importance": 1到5的整数（5=用户可能需关注，如报错弹窗/任务完成/异常；'
    "1=常规无信息量）}"
)


def foreground_window_title() -> str:
    """Windows 前台窗口标题（ctypes user32，零新依赖）；非 win32/失败返回 ""。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value or ""
    except Exception:
        return ""


def privacy_blocked(title: Optional[str], keywords) -> bool:
    """前台标题命中隐私黑名单（大小写不敏感子串）→ 该帧不进 VLM。"""
    t = (title or "").lower()
    return any(str(k).strip().lower() in t for k in (keywords or ()) if str(k).strip())


def compute_ahash(img) -> int:
    """8x8 均值哈希（PIL 灰度缩放，零新依赖），返回 64 位 int。"""
    gray = img.convert("L").resize((8, 8), Image.BILINEAR)
    px = list(gray.getdata())
    avg = sum(px) / len(px)
    h = 0
    for p in px:
        h = (h << 1) | (1 if p > avg else 0)
    return h


def mean_rgb(img):
    """8x8 RGB 通道均值。纯色帧 aHash 恒为 0（黑屏与蓝屏同哈希）——
    场景变化门控必须叠加本值差，纯色/大面积换色才不会漏检。"""
    px = list(img.convert("RGB").resize((8, 8), Image.BILINEAR).getdata())
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def rgb_shift(a, b) -> int:
    """两组 RGB 均值的最大通道绝对差（0-255）。"""
    return max(abs(x - y) for x, y in zip(a, b))


def scene_changed(prev_hash, prev_rgb, cur_hash, cur_rgb,
                  threshold: int, rgb_threshold: int) -> bool:
    """场景是否变化：aHash 汉明距离达标 或 RGB 均值大幅漂移（救纯色/大面积换色
    盲区——纯色帧 aHash 恒 0，仅靠汉明距离会把黑屏换蓝屏误判为"未变"）。"""
    if prev_hash is None or prev_rgb is None:
        return True
    return (hamming(prev_hash, cur_hash) >= threshold
            or rgb_shift(prev_rgb, cur_rgb) >= rgb_threshold)


def encode_jpeg_data_uri(img, max_width: int) -> str:
    """缩放到限宽 JPEG data URI：VLM 只喂压缩帧，控制 token 成本。"""
    if max_width and img.width > max_width:
        img = img.resize((max_width, max(1, int(img.height * max_width / img.width))),
                         Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def parse_vlm_json(text: Optional[str]) -> dict:
    """VLM 输出 → 事件字段。容错：剥围栏/首尾大括号提取；失败整段降为 summary。"""
    t = (text or "").strip()
    s, e = t.find("{"), t.rfind("}")
    if s != -1 and e > s:
        try:
            d = json.loads(t[s:e + 1])
            if isinstance(d, dict):
                imp = d.get("importance")
                return {"summary": str(d.get("summary") or "").strip()[:200],
                        "activity": str(d.get("activity") or "").strip()[:40],
                        "importance": imp if isinstance(imp, int) and 1 <= imp <= 5 else None}
        except Exception:
            pass
    return {"summary": t[:200], "activity": "", "importance": None}


class ScreenWatcher:
    """常驻观察循环：门控截图→vision 卡 VLM→事件 jsonl 追加。未启用零动作。"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._inited = False
        return cls._instance

    def __init__(self):
        if self._inited:
            return
        self._inited = True
        self.config = {}
        self.is_running = False
        self._stop_event = None
        self._observe_task = None
        self._last_capture = 0.0
        self._last_hash = None
        self._last_rgb = None
        self._cooldown_until = 0.0
        self._last_maintain = 0.0
        self._vlm_missing_warned = False

    def update_config(self, cfg):
        self.config = dict(cfg) if isinstance(cfg, dict) else {}
        self._vlm_missing_warned = False

    def _cfg_int(self, name, default):
        try:
            v = int(self.config.get(name, default) or default)
            return v if v > 0 else default
        except (TypeError, ValueError):
            return default

    def _interval(self):
        return max(2, self._cfg_int("intervalSeconds", 5))

    def _privacy_keywords(self):
        kws = self.config.get("privacyKeywords")
        return kws if isinstance(kws, list) else list(DEFAULT_PRIVACY_KEYWORDS)

    # ---------------- 生命周期（仿 diary_engine） ----------------

    async def start(self):
        self._stop_event = asyncio.Event()
        self.is_running = True
        logging.getLogger("app").info(
            f"[ScreenWatcher] 旁观引擎已启动 (GUI可用: {GUI_AVAILABLE}, 默认未启用)")
        try:
            while not self._stop_event.is_set():
                try:
                    await self._tick()
                except Exception as e:
                    logging.getLogger("app").error(f"[ScreenWatcher] tick 异常: {e}")
                await asyncio.sleep(1)
        finally:
            self.is_running = False
            logging.getLogger("app").info("[ScreenWatcher] 旁观引擎已退出")

    def stop(self):
        self.is_running = False
        if self._stop_event:
            self._stop_event.set()
        if self._observe_task and not self._observe_task.done():
            self._observe_task.cancel()

    # ---------------- 循环 ----------------

    async def _tick(self):
        # S216：记忆层维护（48h 明细清理/30 天摘要清理/昨日摘要）——不受 enabled
        # 支配：旁观停用后存量数据仍照常到期清理。每小时节流，失败仅告警。
        now = time.time()
        if now - self._last_maintain >= self._cfg_int("maintainSeconds", 3600):
            self._last_maintain = now
            try:
                await asyncio.to_thread(screen_memory.maintain, self.config)
            except Exception as e:
                logging.getLogger("app").warning(f"[ScreenWatcher] 记忆层维护异常: {e}")
        if not self.config.get("enabled", False) or not GUI_AVAILABLE:
            return
        if now < self._cooldown_until or now - self._last_capture < self._interval():
            return
        if self._observe_task is not None and not self._observe_task.done():
            return  # 单飞：一次观察未完不叠任务
        self._last_capture = now
        self._observe_task = asyncio.create_task(self._observe_once())

    async def _observe_once(self):
        try:
            settings = await load_settings()
            vision = (settings or {}).get("vision") or {}
            if not vision.get("enabled"):
                self._warn_vlm_missing()
                return
            title = self._title()
            if privacy_blocked(title, self._privacy_keywords()):
                logging.getLogger("app").debug(
                    f"[ScreenWatcher] 隐私黑名单跳帧: {title[:80]}")
                return
            shot = self._grab()
            h = compute_ahash(shot)
            cur_rgb = mean_rgb(shot)
            if not scene_changed(self._last_hash, self._last_rgb, h, cur_rgb,
                                 self._cfg_int("changeThreshold", 6),
                                 self._cfg_int("rgbShiftThreshold", 24)):
                return  # 场景未变：跳过 VLM——成本命门，画面不动零调用
            self._last_hash, self._last_rgb = h, cur_rgb
            data_uri = encode_jpeg_data_uri(shot, self._cfg_int("maxImageWidth", 768))
            t0 = time.time()
            parsed = parse_vlm_json(await self._vlm(vision, data_uri))
            self._cooldown_until = 0.0
            now = time.time()
            ev = {"ts": round(now, 1),
                  "iso": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                  "title": (title or "")[:120], "took_s": round(now - t0, 1), **parsed}
            await asyncio.to_thread(self._append_event, ev)
            await self._maybe_speak(ev)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            cd = self._cfg_int("vlmFailCooldownSeconds", 300)
            self._cooldown_until = time.time() + cd
            logging.getLogger("app").warning(
                f"[ScreenWatcher] 观察失败，冷却 {cd}s 再试: {e!r}")

    def _warn_vlm_missing(self):
        self._cooldown_until = time.time() + self._cfg_int("vlmFailCooldownSeconds", 300)
        if not self._vlm_missing_warned:
            self._vlm_missing_warned = True
            logging.getLogger("app").warning(
                "[ScreenWatcher] vision 角色未启用/未配置，旁观已退避"
                "（请在设置→视觉模型 配置后自动恢复）")

    def _append_event(self, ev):
        os.makedirs(SCREEN_WATCH_DIR, exist_ok=True)
        with open(os.path.join(SCREEN_WATCH_DIR, "screen_log.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(ev, ensure_ascii=False) + "\n")

    async def _maybe_speak(self, ev):
        """S218：高重要度事件主动发言——防骚扰闸门为 screen_speak 纯函数；发送
        复用 behavior 平台 handler 契约（空 chat_id=平台展开用户配置的行为目标，
        频道配置体验与行为系统一致）。发言失败绝不影响观察主链路。"""
        cfg = self.config.get("speak")
        if not isinstance(cfg, dict) or not cfg.get("enabled", False):
            return
        try:
            from py.behavior_engine import global_behavior_engine
            state = await asyncio.to_thread(screen_speak.load_state)
            ok, reason = screen_speak.should_speak(cfg, ev, state, time.time())
            if not ok:
                if screen_speak.is_busy_reason(reason):
                    logging.getLogger("app").info(f"[旁观发言] 本次不发: {reason}")
                return
            platforms = screen_speak.target_platforms(
                cfg, list(global_behavior_engine.handlers.keys()))
            if not platforms:
                logging.getLogger("app").warning(
                    "[旁观发言] 无可用平台 handler（对应 bot 未启用？）")
                return
            item = screen_speak.build_behavior_item(ev)
            for p in platforms:
                asyncio.create_task(global_behavior_engine.handlers[p]("", item))
            screen_speak.record_sent(state, time.time())
            await asyncio.to_thread(screen_speak.save_state, state)
            logging.getLogger("app").info(f"[旁观发言] 已投递行为通道: {platforms}")
        except Exception as e:
            logging.getLogger("app").warning(f"[旁观发言] 投递失败: {e}")

    # ---------------- 真机接缝（单测整体替换，零真机依赖） ----------------

    def _grab(self):
        return pyautogui.screenshot()

    def _title(self):
        return foreground_window_title()

    @llm_gate.gated
    async def _vlm(self, vision, data_uri):
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=vision.get("api_key"),
                             base_url=vision.get("base_url"),
                             timeout=self._cfg_int("vlmTimeoutSeconds", 60))
        extra = {}
        temp = vision.get("temperature")
        if isinstance(temp, (int, float)) and temp != 1:
            extra["temperature"] = temp
        resp = await acreate(
            lambda: client.chat.completions.create(
                model=vision.get("model"),
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": _VLM_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}}]}],
                **extra),
            attempts=1, base_delay=1.0, label="s215-screen-watcher")
        return resp.choices[0].message.content


global_screen_watcher = ScreenWatcher()
