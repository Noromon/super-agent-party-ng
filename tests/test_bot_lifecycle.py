# -*- coding: utf-8 -*-
"""批 0-① bot manager 生命周期冒烟骨架（R2-9 BaseBotManager 的前置防护网）。

覆盖 9 个 manager 的统一契约：
  初始 status → start 就绪 → 双开拒绝 → 行为热更（如有）→ stop 线程收敛 → stop 幂等。
  另加启动失败传播测试：SDK 抛错时 start_bot 必须抛异常并复位状态。

Fake 策略：monkeypatch 各 manager 模块内的 SDK/client 符号，零网络、零真实凭据。
漂移钉：已知契约缺口用 xfail 标记（strict），R2-9 手术完成后 XPASS 会强制摘除标记。

运行约定：pytest 进程必须带 SAP_DATA_DIR=空临时目录（项目测试惯例），
bot 线程内 load_settings() 读空配置即跳过行为同步，不触碰真实用户数据。
"""
import asyncio
import importlib
import sys
import threading
import time
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
# Package-mode import of repo py/* (a third-party `py` shim can hijack `import py`).
if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
    del sys.modules["py"]

import py.behavior_engine as behavior_engine_pkg


# ---------------------------------------------------------------- 基础设施

class FakeEngine:
    """替身行为引擎：is_running 恒 True，避免各 manager 真起引擎任务。"""
    is_running = True

    def update_config(self, *a, **k):
        pass

    def register_handler(self, *a, **k):
        pass

    def report_activity(self, *a, **k):
        pass

    def stop(self):
        pass

    async def start(self):
        # 立即完成：dingtalk 的 gather(engine.start(), client.start())
        # 依赖 client 停止即收敛；长驻引擎任务是真实引擎行为，不在本测试范围。
        await asyncio.sleep(0)


def wait_until(pred, timeout=15.0, interval=0.05):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if pred():
            return True
        time.sleep(interval)
    return False


def _bag(**kw):
    return types.SimpleNamespace(**kw)


class _Bag:
    """属性袋：允许 manager 对 fake client 任意 setattr 赋值属性。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _raiser(cls_name="sdk"):
    class _Raiser:
        def __init__(self, *a, **k):
            raise RuntimeError(f"boom-{cls_name}")

    return _Raiser


# ---------------------------------------------------------------- 各 bot spec

def _apply_engine(monkeypatch, mod, eng):
    monkeypatch.setattr(behavior_engine_pkg, "global_behavior_engine", eng)
    if hasattr(mod, "global_behavior_engine"):
        monkeypatch.setattr(mod, "global_behavior_engine", eng)


# ---- feishu ----

class _FeishuWs:
    _conn = None

    def __init__(self, *a, **k):
        pass

    async def _connect(self):
        pass

    async def _ping_loop(self):
        await asyncio.sleep(3600)

    async def _disconnect(self):
        pass


class _LarkBuilder:
    def __getattr__(self, name):
        return lambda *a, **k: self

    def build(self):
        return _Bag()


def _feishu_patches(monkeypatch, mod, eng, fail):
    client = _raiser("FeishuClient") if fail else (lambda *a, **k: _Bag(
        _is_ready=True, sync_handle_message=lambda *a, **k: None))
    monkeypatch.setattr(mod, "FeishuClient", client)
    monkeypatch.setitem(sys.modules, "lark_oapi", _bag(
        Client=_bag(builder=lambda: _LarkBuilder()),
        LogLevel=_bag(INFO=10),
        EventDispatcherHandler=_bag(builder=lambda *a, **k: _LarkBuilder()),
        ws=_bag(Client=_FeishuWs),
    ))
    _apply_engine(monkeypatch, mod, eng)


# ---- qq ----

class _QQClient:
    is_running = False
    _shutdown_requested = False

    def __init__(self, *a, **k):
        pass

    async def start(self, appid=None, secret=None):
        self.is_running = True
        if self._ready_callback:
            self._ready_callback()
        while not self._shutdown_requested:
            await asyncio.sleep(0.1)

    async def close(self):
        self._shutdown_requested = True


def _qq_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "MyClient",
                        _raiser("MyClient") if fail else _QQClient)
    _apply_engine(monkeypatch, mod, eng)


# ---- wechat ----

class _WxBot:
    def __init__(self, *a, **k):
        self._stop = False

    def on_message(self, fn):
        return fn

    async def run(self):
        while not self._stop:
            await asyncio.sleep(0.1)

    def stop(self):
        self._stop = True


def _wechat_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "WeChatBot",
                        _raiser("WeChatBot") if fail else _WxBot)
    _apply_engine(monkeypatch, mod, eng)


# ---- discord ----

class _DiscordClient:
    def __init__(self, config, manager=None):
        self.manager = manager
        self.config = config

    async def start(self, token):
        m = self.manager
        m.is_running = True
        m._ready_complete.set()
        while not m._shutdown_event.is_set():
            await asyncio.sleep(0.1)

    async def close(self):
        pass


def _discord_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "DiscordClient",
                        _raiser("DiscordClient") if fail else _DiscordClient)
    _apply_engine(monkeypatch, mod, eng)


# ---- slack ----

class _SlackWeb:
    def __init__(self, token=None):
        pass

    async def auth_test(self):
        return {"user_id": "U_TEST"}


class _SlackSocket:
    def __init__(self, app_token=None, web_client=None):
        self.socket_mode_request_listeners = []

    async def connect(self):
        pass

    async def close(self):
        pass


def _slack_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "AsyncWebClient",
                        _raiser("AsyncWebClient") if fail else _SlackWeb)
    monkeypatch.setattr(mod, "SocketModeClient", _SlackSocket)
    _apply_engine(monkeypatch, mod, eng)


# ---- dingtalk ----

_DT_LAST = []  # 最后创建的 fake stream client（供 stop 竞态守卫）


class _DTCredential:
    def __init__(self, *a, **k):
        pass


class _DTClient:
    def __init__(self, credential):
        self._stop = False
        _DT_LAST.clear()
        _DT_LAST.append(self)

    def register_callback_handler(self, topic, handler):
        pass

    async def start(self):
        while not self._stop:
            await asyncio.sleep(0.1)

    def stop(self):
        self._stop = True


def _dingtalk_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "dingtalk_stream", _bag(
        Credential=_DTCredential,
        DingTalkStreamClient=_DTClient,
    ))
    logic = _raiser("DingtalkClientLogic") if fail else (lambda cfg: _Bag(config=cfg))
    monkeypatch.setattr(mod, "DingtalkClientLogic", logic)
    _apply_engine(monkeypatch, mod, eng)


# ---- telegram ----

class _TGClient:
    _is_ready = False
    _shutdown_requested = False
    _manager_ref = None
    _ready_callback = None

    def __init__(self, *a, **k):
        pass

    async def run(self):
        self._is_ready = True
        if self._manager_ref:
            m = self._manager_ref()
            if m:
                m._ready_complete.set()
                m.is_running = True
        while not self._shutdown_requested:
            await asyncio.sleep(0.1)


def _telegram_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "TelegramClient",
                        _raiser("TelegramClient") if fail else _TGClient)
    _apply_engine(monkeypatch, mod, eng)


# ---- wecom ----

class _WecomClient:
    ws_client = None

    def register_events(self):
        pass


class _WecomWS:
    def __init__(self, options):
        pass

    async def connect(self):
        pass

    def disconnect(self):
        pass


def _wecom_patches(monkeypatch, mod, eng, fail):
    monkeypatch.setattr(mod, "WeComClient",
                        _raiser("WeComClient") if fail else _WecomClient)
    monkeypatch.setattr(mod, "WSClient", _WecomWS)
    monkeypatch.setattr(mod, "WSClientOptions", lambda **k: _Bag())
    _apply_engine(monkeypatch, mod, eng)


# ---- xmpp ----

class _XmppClient:
    _is_ready = False
    _shutdown_requested = False
    _manager_ref = None

    def __init__(self, *a, **k):
        pass

    async def run(self):
        self._is_ready = True
        if self._manager_ref:
            m = self._manager_ref()
            if m:
                m._ready_complete.set()
                m.is_running = True
        while not self._shutdown_requested:
            await asyncio.sleep(0.1)


def _xmpp_patches(monkeypatch, mod, eng, fail):
    import py.xmpp_client as xmpp_client_mod
    monkeypatch.setattr(xmpp_client_mod, "XmppClient",
                        _raiser("XmppClient") if fail else _XmppClient)
    _apply_engine(monkeypatch, mod, eng)


BOTS = [
    {
        "id": "feishu", "mod": "py.feishu_bot_manager",
        "mgr": "FeishuBotManager", "cfg": "FeishuBotConfig",
        "data": dict(FeishuAgent="super-model", memoryLimit=10, appid="ai",
                     secret="sec", separators=["。"], reasoningVisible=False,
                     quickRestart=True, enableTTS=False, wakeWord=""),
        "patches": _feishu_patches,
    },
    {
        "id": "qq", "mod": "py.qq_bot_manager",
        "mgr": "QQBotManager", "cfg": "QQBotConfig",
        "data": dict(QQAgent="super-model", memoryLimit=10, appid="ai",
                     secret="sec", separators=["。"], reasoningVisible=False,
                     quickRestart=True, is_sandbox=False),
        "patches": _qq_patches,
    },
    {
        "id": "wechat", "mod": "py.wechat_bot_manager",
        "mgr": "WeChatBotManager", "cfg": "WeChatBotConfig",
        "data": {},
        "patches": _wechat_patches,
    },
    {
        "id": "discord", "mod": "py.discord_bot_manager",
        "mgr": "DiscordBotManager", "cfg": "DiscordBotConfig",
        "data": dict(token="tk", wakeWord=""),
        "patches": _discord_patches,
        "slow_failure": True,  # 失败路径无 ready 释放，需等满 30s 就绪超时
    },
    {
        "id": "slack", "mod": "py.slack_bot_manager",
        "mgr": "SlackBotManager", "cfg": "SlackBotConfig",
        "data": dict(bot_token="xoxb-t", app_token="xapp-t"),
        "patches": _slack_patches,
    },
    {
        "id": "dingtalk", "mod": "py.dingtalk_bot_manager",
        "mgr": "DingtalkBotManager", "cfg": "DingtalkBotConfig",
        "data": dict(DingtalkAgent="super-model", memoryLimit=10, appKey="ak",
                     appSecret="as", separators=["。"], reasoningVisible=False,
                     quickRestart=True, enableTTS=False, wakeWord=""),
        "patches": _dingtalk_patches,
        "client_settle": True,  # stop 前需等线程内 fake client 就位
    },
    {
        "id": "telegram", "mod": "py.telegram_bot_manager",
        "mgr": "TelegramBotManager", "cfg": "TelegramBotConfig",
        "data": dict(TelegramAgent="super-model", memoryLimit=10,
                     separators=["。"], reasoningVisible=False, quickRestart=True,
                     enableTTS=False, bot_token="tg-t", wakeWord=""),
        "patches": _telegram_patches,
    },
    {
        "id": "wecom", "mod": "py.wecom_bot_manager",
        "mgr": "WeComBotManager", "cfg": "WeComBotConfig",
        "data": dict(WeComAgent="super-model", memoryLimit=10, bot_id="bi",
                     secret="sec", reasoningVisible=False, quickRestart=True,
                     enableTTS=False, wakeWord=""),
        "patches": _wecom_patches,
    },
    {
        "id": "xmpp", "mod": "py.xmpp_bot_manager",
        "mgr": "XmppBotManager", "cfg": "XmppBotConfig",
        "data": dict(XmppAgent="super-model", bot_username="u",
                     bot_password="p"),
        "patches": _xmpp_patches,
    },
]

BOT_IDS = [b["id"] for b in BOTS]


def _make(monkeypatch, spec, fail=False):
    mod = importlib.import_module(spec["mod"])
    eng = FakeEngine()
    spec["patches"](monkeypatch, mod, eng, fail)
    mgr = getattr(mod, spec["mgr"])()
    cfg_cls = getattr(mod, spec["cfg"])
    cfg = cfg_cls(**spec["data"])
    cfg2 = cfg_cls(**dict(spec["data"], wakeWord="唤醒词2")
                   if "wakeWord" in spec["data"] else spec["data"])
    return mgr, cfg, cfg2


# ---------------------------------------------------------------- 测试

@pytest.mark.parametrize("bot_id", BOT_IDS)
def test_lifecycle_roundtrip(bot_id, monkeypatch):
    """初始态 → start 就绪 → 双开拒绝 → 热更 → stop 收敛 → stop 幂等。"""
    spec = next(b for b in BOTS if b["id"] == bot_id)
    mgr, cfg, cfg2 = _make(monkeypatch, spec)

    # 1) 初始状态契约
    st = mgr.get_status()
    assert isinstance(st, dict) and "is_running" in st
    assert st["is_running"] is False

    # 2) 启动并就绪
    mgr.start_bot(cfg)
    assert wait_until(lambda: mgr.is_running is True, timeout=20), \
        f"{bot_id}: start_bot 后未就绪 startup_error={getattr(mgr, '_startup_error', None)}"

    # 3) 运行中状态契约
    st = mgr.get_status()
    assert st["is_running"] is True
    assert getattr(mgr, "_startup_error", None) in (None, "")

    # 4) 双开拒绝（契约：运行中再次 start 必抛）
    with pytest.raises(Exception):
        mgr.start_bot(cfg)

    # 5) 行为热更（契约：应人人有；qq 缺失=R2-9 漂移钉）
    if spec.get("no_hot_update"):
        assert not hasattr(mgr, "update_behavior_config")
        pytest.xfail(f"R2-9 漂移钉：{bot_id} 缺 update_behavior_config（契约应人人有，"
                     f"基类化后补上会让本钉转红，强制摘除）")
    if spec.get("client_settle"):  # dingtalk: 线程内 bot_logic 异步赋值，先等就位
        assert wait_until(lambda: bool(_DT_LAST), timeout=20), f"{bot_id}: fake client 未创建"
    mgr.update_behavior_config(cfg2)
    assert mgr.config is cfg2

    # 6) 停止并等待线程收敛
    mgr.stop_bot()
    thread = getattr(mgr, "bot_thread", None)
    if thread is not None:
        assert wait_until(lambda: not thread.is_alive(), timeout=20), \
            f"{bot_id}: stop_bot 后线程未收敛"
    assert wait_until(lambda: mgr.is_running is False, timeout=10)


@pytest.mark.parametrize("bot_id", BOT_IDS)
def test_start_failure_propagates(bot_id, monkeypatch):
    """SDK 构造抛错 → start_bot 必须抛异常并复位（slack/dingtalk 有漂移钉）。

    漂移钉反转逻辑：drift bot「未抛错」=记录现状绿；一旦抛错=漂移已修复，
    本测试转红强制摘除 failure_drift 标记（等效 strict xfail）。
    """
    spec = next(b for b in BOTS if b["id"] == bot_id)
    mgr, cfg, _ = _make(monkeypatch, spec, fail=True)
    raised = False
    try:
        mgr.start_bot(cfg)
    except Exception:
        raised = True
    drift = spec.get("failure_drift")
    if drift:
        if raised:
            pytest.fail(f"漂移已修复（启动错误已能传播），请摘除 failure_drift 钉：{drift}")
        try:  # 清理可能已起的后台线程
            mgr.stop_bot()
        except Exception:
            pass
    else:
        assert raised, f"{bot_id}: SDK 启动错误未传播到 start_bot"
        assert mgr.is_running is False
        try:
            mgr.stop_bot()  # 清理残留线程
        except Exception:
            pass


@pytest.mark.parametrize("bot_id", BOT_IDS)
def test_stop_idempotent(bot_id, monkeypatch):
    """未启动/已停止状态下 stop_bot 幂等不崩。"""
    spec = next(b for b in BOTS if b["id"] == bot_id)
    mgr, _, _ = _make(monkeypatch, spec)
    mgr.stop_bot()
    mgr.stop_bot()


# ---------------------------------------------------------------- S154 僵尸线程恢复


class _HangingClient:
    """run() 全挂起（只响应取消，不轮询停止标志）：模拟 slixmpp 失联重连态。"""
    _is_ready = False
    _shutdown_requested = False
    _manager_ref = None

    def __init__(self, *a, **k):
        pass

    async def run(self):
        self._is_ready = True
        if self._manager_ref:
            m = self._manager_ref()
            if m:
                m._ready_complete.set()
                m.is_running = True
        await asyncio.Event().wait()


def _xmpp_mgr(monkeypatch, client_cls):
    import py.xmpp_bot_manager as mod
    import py.xmpp_client as xmpp_client_mod
    eng = FakeEngine()
    _apply_engine(monkeypatch, mod, eng)
    monkeypatch.setattr(xmpp_client_mod, "XmppClient", client_cls)
    mgr = mod.XmppBotManager()
    cfg = mod.XmppBotConfig(XmppAgent="super-model", bot_username="u", bot_password="p")
    return mgr, cfg


def test_cooperative_stop_kills_hanging_thread(monkeypatch):
    """client 只响应取消的极端形态：loop 内 watcher 必须在有界时间内收敛线程。"""
    mgr, cfg = _xmpp_mgr(monkeypatch, _HangingClient)
    mgr.start_bot(cfg)
    assert wait_until(lambda: mgr.is_running is True, timeout=20)
    mgr.stop_bot()
    thread = mgr.bot_thread
    assert wait_until(lambda: not thread.is_alive(), timeout=20), \
        "S154 协作停止未能收敛全挂起 client 线程"
    assert mgr.is_running is False


def test_zombie_selfheal_restart(monkeypatch):
    """僵尸态（线程存活+未运行）start 必须自救：清掉旧线程并完成完整启动。"""
    mgr, cfg = _xmpp_mgr(monkeypatch, _XmppClient)
    zombie = threading.Thread(target=lambda: time.sleep(2), daemon=True)
    zombie.start()
    mgr.bot_thread = zombie  # 模拟清理失败残留：线程活着但 bot 未在运行
    mgr.start_bot(cfg)
    assert wait_until(lambda: mgr.is_running is True, timeout=20), \
        f"僵尸自救后启动失败 startup_error={mgr._startup_error}"
    assert not zombie.is_alive()
    mgr.stop_bot()


def test_start_guard_running_message(monkeypatch):
    """运行中重复 start：文案必须是「已在运行」（旧实现被线程存活守卫吞成「清理中」）。"""
    mgr, cfg = _xmpp_mgr(monkeypatch, _XmppClient)
    mgr.start_bot(cfg)
    try:
        with pytest.raises(Exception) as ei:
            mgr.start_bot(cfg)
        assert "已在运行" in str(ei.value)
    finally:
        mgr.stop_bot()


def test_start_guard_zombie_cleanup_failure_raises():
    """真僵尸（join 超时且硬清理无效）→ 明确「未能自我清理」错误，不再无限「稍后再试」。"""
    mgr, cfg = _xmpp_mgr_no_patch()
    zombie = threading.Thread(target=lambda: time.sleep(30), daemon=True)
    zombie.start()
    mgr.bot_thread = zombie
    mgr.STOP_JOIN_TIMEOUT = 0.2
    with pytest.raises(Exception) as ei:
        mgr.start_bot(cfg)
    assert "自我清理" in str(ei.value)
    zombie.join(timeout=1)


def _xmpp_mgr_no_patch():
    import py.xmpp_bot_manager as mod
    return mod.XmppBotManager(), mod.XmppBotConfig(
        XmppAgent="super-model", bot_username="u", bot_password="p")
