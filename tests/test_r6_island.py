# -*- coding: utf-8 -*-
"""S139(R6)：灵动岛移植钉桩（资产哈希、M2 token 补丁、后端接线、Electron 桥）。"""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# dynamic_island.py：上游 origin/main@3eb32bb2 逐字节 + fork 补丁（S153：print→logging，白名单改动）
SHA_DYNAMIC_ISLAND = "a0a52cc8168b877219458341b64aaf4f3a335182c44aa9c45140538eee4426ed"
SHA_ISLAND_CSS = "ede0b79dce0675e1c0b81b97a80b1fe8f65e049959c6f792a21dbdb135a4d5de"
# fork 补丁后资产哈希（上游 + S139 M2 token 补丁 + S141 纯图标刷新徽章 + S274 HUD 鼠标持握守卫，白名单改动）
SHA_ISLAND_APP = "724415e20f4b5bdbab0066161441220c3faed322d098e8d2add4c4a7182509c4"
SHA_ISLAND_HTML = "3c302635b2653f9ea0a3a5da499111cc8b6de71d44f9df3e6ba8ced7bf8a4956"


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace").read()


def _sha(*p):
    return hashlib.sha256(open(os.path.join(ROOT, *p), "rb").read()).hexdigest()


class TestIslandAssetsS139:
    def test_dynamic_island_verbatim(self):
        assert _sha("py", "dynamic_island.py") == SHA_DYNAMIC_ISLAND
        assert os.path.getsize(os.path.join(ROOT, "py", "dynamic_island.py")) == 19697

    def test_island_css_verbatim(self):
        assert _sha("static", "css", "island.css") == SHA_ISLAND_CSS

    def test_island_app_patched_hash(self):
        assert _sha("static", "js", "island-app.js") == SHA_ISLAND_APP

    def test_island_app_m2_patches(self):
        s = _read("static", "js", "island-app.js")
        assert "sap_token" in s and "__SAP_TOKEN" in s and "__SAP_READY" in s
        # fork 补丁必须恰好 2 处（上游 2027 行 + 补丁行）
        assert s.count("__SAP_TOKEN") == 1
        assert s.count("__SAP_READY") == 2
        # 上游能力面不回归
        assert "register_node_extension_mcp" in s and "dynamic_island" in s
        for tool in ("island_music_play", "island_pomodoro_start", "island_task_create",
                     "island_weather_get_current", "island_translate", "island_clipboard_list"):
            assert tool in s

    def test_island_html_bootstrap(self):
        assert _sha("static", "island.html") == SHA_ISLAND_HTML
        h = _read("static", "island.html")
        assert "session_token" in h
        assert h.find("__SAP_READY") < h.find('js/island-app.js')
        assert "css/island.css" in h

    def test_weather_manual_refresh_s140(self):
        # S140 引入、S141 重设计：天气图标右上角纯图标徽章（无文字，刷新中 fa-spin）
        h = _read("static", "island.html")
        assert "weather-refresh-btn" in h and "refreshWeather" in h
        i = h.find("weather-refresh-btn")
        badge = h[i - 400:i + 600]
        assert "position:absolute" in badge and "fa-spin" in badge
        assert "{{ t('weatherRefresh') }}" not in h  # 纯图标：文字已移除，仅 :title 保留
        assert h.count("t('weatherRefresh')") == 1
        a = _read("static", "js", "island-app.js")
        assert "refreshWeather()" in a
        assert a.count("weatherRefresh") == 2  # zh 字典 + en 字典（模板引用在 island.html）
        assert _sha("static", "css", "island.css") == SHA_ISLAND_CSS

    def test_weather_city_manual_pin_s142(self):
        # S142：手选城市持久化（manual 标记 + IP 定位早退）+ 退出钮退回自动
        a = _read("static", "js", "island-app.js")
        assert a.count("island_weather_city_manual") == 4  # 早退读 + 手选/工具写 + resetCityAuto 清
        assert "resetCityAuto()" in a
        assert a.count("weatherAutoCity") == 2  # zh + en 字典
        h = _read("static", "island.html")
        assert "weather-auto-btn" in h and "resetCityAuto" in h
        assert "fa-location-crosshairs" in h


class TestIslandBackendS139:
    def test_router_endpoints(self):
        s = _read("py", "routers", "island.py")
        for ep in ('/api/heatmap"', '/api/heatmap/increment', '/api/weather', '/api/ip-city', '/api/geocode', '/cur_language'):
            assert ep in s
        assert "island_ai_reply_done" in s and "notify_island_reply_done" in s
        for h in ("island_enable", "island_disable", "island_music_control", "island_track_set",
                  "island_poll_music", "island_request_clipboard", "island_write_clipboard", "island_request_tasks"):
            assert '"%s"' % h in s

    def test_server_wiring(self):
        s = _read("server.py")
        assert "app.include_router(island_router)" in s
        assert 'elif msg_type.startswith("island_"):' in s
        assert "await _ws_island(websocket, msg_type, data)" in s
        # 流尾钩子：DONE 之后、finalize 之前（上游 5842-5850 语义位）
        b = s.find("await notify_island_reply_done(request.is_sub_agent)")
        assert b != -1
        window = s[b - 200:b + 250]
        assert 'yield "data: [DONE]' in window and "_stream_finalize_jobs" in window

    def test_deps_and_spec(self):
        p = _read("pyproject.toml")
        for dep in ("winrt-windows-media-control>=3.2.1 ; sys_platform == 'win32'",
                    "pycaw>=20240210 ; sys_platform == 'win32'",
                    "jeepney>=0.8.0 ; sys_platform == 'linux'"):
            assert dep in p
        assert '"py/dynamic_island.py" = ["E401", "F401", "F541", "F811"]' in p
        sp = _read("server.spec")
        assert "collect_submodules('winrt')" in sp and "collect_submodules('pycaw')" in sp


class TestIslandElectronS139:
    def test_main_window_ipc(self):
        g = _read("main.js")
        for ch in ("open-island-window", "close-island-window", "get-island-window-state",
                   "clipboard-read", "clipboard-write", "clipboard-read-image", "clipboard-read-file-paths"):
            assert "ipcMain.handle('%s'" % ch in g
        assert "let dynamicIslandWindow = null" in g
        assert "island.html" in g
        assert "setIgnoreMouseEvents(true, { forward: true })" in g
        assert "dynamicIslandWindow.webContents.send('language-changed')" in g

    def test_island_window_no_websecurity_off(self):
        # S137 教训：island 窗口 webPreferences 不得含 webSecurity:false（历史窗口 2 处不在本钉范围）
        g = _read("main.js")
        block = g[g.find("open-island-window"):g.find("close-island-window")]
        assert "webSecurity: false" not in block

    def test_preload_bridges(self):
        p = _read("static", "js", "preload.js")
        for api in ("openIslandWindow", "closeIslandWindow", "getIslandWindowState",
                    "onIslandWindowClosed", "onLanguageChanged", "clipboardRead",
                    "clipboardWrite", "clipboardReadImage", "clipboardReadFilePaths"):
            assert api in p


class TestIslandUiS139:
    def test_button_and_registration(self):
        h = _read("static", "index.html")
        assert 'id="dynamic-island-btn"' in h
        assert "toggleDynamicIsland" in h and "fa-jar" in h
        assert "46_island_domain.js" in h
        assert "dynamicIslandClose" in h

    def test_methods_data_i18n(self):
        m = _read("static", "js", "methods", "46_island_domain.js")
        assert "toggleDynamicIsland()" in m and "onIslandWindowClosed" in m
        d = _read("static", "js", "data", "50_bots_translate.js")
        assert "isDynamicIsland: false" in d
        for loc, val in (("zh-CN", "灵动岛"), ("en-US", "Dynamic Island")):
            z = _read("static", "js", "locales", "%s.js" % loc)
            assert val in z and "dynamicIslandClose" in z

    def test_stamp_s139(self):
        assert "build=S301" in _read("static", "js", "renderer.js")


class TestIslandProxyFallbackS283:
    """S283（取代 S140 出口）：外联接 SAP 代理体系（active_proxy/socks/IPv4/逐路日志）。"""

    @staticmethod
    def _module():
        import importlib
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
            del sys.modules["py"]  # site-packages py.py 影子
        return importlib.import_module("py.routers.island")

    def test_router_has_fallback_helper(self):
        s = _read("py", "routers", "island.py")
        assert "_external_get_json" in s
        assert "trust_env=True" in s
        assert "SAP_PROXY" in s and "_FALLBACK_PROXIES" not in s
        # S283：接 S85 代理解析 + socks 显式接线 + direct4 治 AAAA 黑洞 + 脱敏日志
        for anchor in ("proxy_util.active_proxy", "aiohttp_socks",
                       "socket.AF_INET", "mask_proxy_url"):
            assert anchor in s, anchor
        # 三个外联端点统一走回退出口
        for url in ("http://ip-api.com/json/", "api.open-meteo.com/v1/forecast",
                    "geocoding-api.open-meteo.com/v1/search"):
            assert url in s
        assert "total=5" not in s  # 上游 5s 超时全部移除

    def test_plan_attempts_order(self, monkeypatch):
        m = self._module()
        monkeypatch.delenv("SAP_PROXY", raising=False)
        m._proxy_state["sticky"] = None
        # 未配代理：直连(trust_env)为主，direct4 兜底
        assert m._plan_attempts({}) == [("direct",), ("direct4",)]
        # manual 配置出口优先于直连
        ss = {"systemSettings": {"proxyMode": "manual", "proxy": "http://127.0.0.1:7890"}}
        assert m._plan_attempts(ss)[:2] == [("proxy", "http://127.0.0.1:7890"), ("direct",)]
        # 粘滞最前（tuple 形与旧库字符串形兼容）
        assert m._plan_attempts({}, ("proxy", "http://127.0.0.1:5555"))[0] == ("proxy", "http://127.0.0.1:5555")
        assert m._plan_attempts(ss, "http://127.0.0.1:5555")[0] == ("proxy", "http://127.0.0.1:5555")
        # SAP_PROXY 显式兜底入列且去重
        monkeypatch.setenv("SAP_PROXY", "http://127.0.0.1:9999")
        order = m._plan_attempts({})
        assert ("proxy", "http://127.0.0.1:9999") in order and order[-1] == ("direct4",)
        assert order.count(("proxy", "http://127.0.0.1:9999")) == 1
        monkeypatch.setenv("SAP_PROXY", "http://127.0.0.1:7890")
        assert m._plan_attempts(ss).count(("proxy", "http://127.0.0.1:7890")) == 1
        m._proxy_state["sticky"] = None

    def test_session_branches(self):
        import asyncio
        m = self._module()

        async def main():
            out = {}
            for key, strat in (("socks", ("proxy", "socks5h://127.0.0.1:7891")),
                               ("http", ("proxy", "http://127.0.0.1:7890")),
                               ("d4", ("direct4",)),
                               ("direct", ("direct",))):
                sess, kw = m._make_session(strat)
                out[key] = (kw, sess.connector is not None, sess.trust_env)  # 关前捕获
                await sess.close()
            return out

        loop = asyncio.new_event_loop()
        try:
            out = loop.run_until_complete(main())
        finally:
            loop.close()
        assert out["http"][0] == "http://127.0.0.1:7890"
        assert out["socks"][0] is None and out["socks"][1] is True  # ProxyConnector 已挂
        assert out["socks"][2] is False
        assert out["d4"][0] is None and out["d4"][2] is False
        assert out["direct"][2] is True

    def test_external_get_fallback_and_sticky(self, monkeypatch):
        import asyncio
        m = self._module()
        m._proxy_state["sticky"] = None

        class FakeResp:
            def __init__(self, status, payload):
                self.status = status
                self._p = payload

            async def json(self):
                return self._p

        class FakeCtx:
            def __init__(self, resp):
                self._resp = resp

            async def __aenter__(self):
                return self._resp

            async def __aexit__(self, *a):
                return False

        class FakeSession:
            def __init__(self, results, strat):
                self.results = results
                self.strat = strat

            def get(self, url, **kw):
                key = self.strat[0] if self.strat[0] in self.results else "any"
                status, payload = self.results[key]
                return FakeCtx(FakeResp(status, payload))

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        calls = []

        def routing_make(results):
            def f(strat):
                calls.append(strat)
                return (FakeSession(results, strat),
                        (strat[1] if strat[0] == "proxy" else None))
            return f

        async def go(results, settings=None):
            monkeypatch.setattr(m, "_make_session", routing_make(results))

            async def fake_settings():
                return settings or {}
            monkeypatch.setattr(m, "_settings_cached", fake_settings)
            return await m._external_get_json("https://example.invalid/x")

        loop = asyncio.new_event_loop()
        try:
            # 直连失败→manual 代理成功 → 粘滞=代理
            m._proxy_state["sticky"] = None
            ss = {"systemSettings": {"proxyMode": "manual", "proxy": "http://127.0.0.1:7890"}}
            r = loop.run_until_complete(go({"direct": (500, {}), "proxy": (200, {"v": 1})}, ss))
            assert r == {"v": 1}
            assert m._proxy_state["sticky"] == ("proxy", "http://127.0.0.1:7890")
            # 全败 → None 且清粘滞、direct/direct4 都试过
            calls.clear()
            r = loop.run_until_complete(go({"any": (599, {})}))
            assert r is None and m._proxy_state["sticky"] is None
            assert ("direct",) in calls and ("direct4",) in calls
            # 直连成功 → 粘滞=direct
            m._proxy_state["sticky"] = None
            r = loop.run_until_complete(go({"direct": (200, {"ok": 2})}))
            assert r == {"ok": 2} and m._proxy_state["sticky"] == ("direct",)
            m._proxy_state["sticky"] = None
        finally:
            loop.close()

    def test_proxy_exit_disables_ip_city(self):
        # 代理出口下 IP 定位=代理城市，禁用兜底（前端保留默认/手选城市）
        s = _read("py", "routers", "island.py")
        i = s.find('async def get_ip_city')
        block = s[i:i + 900]
        j_sticky = block.find('_proxy_state.get("sticky")')
        j_ext = block.find("_external_get_json")
        assert j_sticky != -1 and j_sticky < j_ext


class TestIslandRaceS284:
    """S284：并发竞速引擎+islandFetchRace 开关；串行引擎原样保留可回退。"""

    @staticmethod
    def _module():
        import importlib
        import sys
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        if "py" in sys.modules and not hasattr(sys.modules["py"], "__path__"):
            del sys.modules["py"]
        return importlib.import_module("py.routers.island")

    def test_engine_split_static(self):
        s = _read("py", "routers", "island.py")
        for anchor in ("async def _serial_get_json", "async def _race_get_json",
                       "islandFetchRace", "FIRST_COMPLETED", "await asyncio.sleep(0.5)",
                       "type(e).__name__}({detail})"):
            assert anchor in s, anchor

    def _wire(self, monkeypatch, m, attempt_fn, settings):
        async def fake_settings():
            return settings
        monkeypatch.setattr(m, "_attempt_get", attempt_fn)
        monkeypatch.setattr(m, "_settings_cached", fake_settings)

    def test_race_first_success_wins(self, monkeypatch):
        import asyncio
        import time
        m = self._module()
        m._proxy_state["sticky"] = None
        calls = []

        async def slow_direct(strat, url, params=None):
            calls.append(strat)
            if strat == ("direct",):
                await asyncio.sleep(1.0)
                return {"late": True}, None
            await asyncio.sleep(0.02)
            return {"fast": True}, None

        self._wire(monkeypatch, m, slow_direct, {"systemSettings": {}})
        loop = asyncio.new_event_loop()
        try:
            t0 = time.monotonic()
            r = loop.run_until_complete(m._external_get_json("https://example.invalid/x"))
            dt = time.monotonic() - t0
            assert r == {"fast": True} and dt < 0.6  # 慢路不拖累（串行必 >=1s）
            assert ("direct4",) in calls  # 全路都发了
        finally:
            loop.close()
        m._proxy_state["sticky"] = None

    def test_serial_when_toggle_off(self, monkeypatch):
        import asyncio
        import time
        m = self._module()
        m._proxy_state["sticky"] = None
        order = []

        async def slow_first(strat, url, params=None):
            order.append(strat)
            if strat == ("direct",):
                await asyncio.sleep(0.5)
                return {"serial": 1}, None
            return {"other": 1}, None

        self._wire(monkeypatch, m, slow_first, {"systemSettings": {"islandFetchRace": False}})
        loop = asyncio.new_event_loop()
        try:
            t0 = time.monotonic()
            r = loop.run_until_complete(m._external_get_json("https://example.invalid/x"))
            dt = time.monotonic() - t0
            # 串行=按序等首路成功，不并发抢先
            assert r == {"serial": 1} and dt >= 0.45
            assert order == [("direct",)]
        finally:
            loop.close()
        m._proxy_state["sticky"] = None

    def test_race_retries_round2(self, monkeypatch):
        import asyncio
        m = self._module()
        m._proxy_state["sticky"] = None
        seen = {}

        async def flaky(strat, url, params=None):
            n = seen.get(strat, 0) + 1
            seen[strat] = n
            await asyncio.sleep(0.01)
            if n == 1:
                return None, f"{strat[0]}=flaky"
            return {"round": n}, None

        self._wire(monkeypatch, m, flaky, {"systemSettings": {}})
        loop = asyncio.new_event_loop()
        try:
            r = loop.run_until_complete(m._external_get_json("https://example.invalid/x"))
            assert r == {"round": 2}  # 首轮全败→500ms 后二轮扳回
            assert all(v >= 2 for v in seen.values())
        finally:
            loop.close()
        m._proxy_state["sticky"] = None

    def test_attempt_err_detail(self, monkeypatch):
        import asyncio
        m = self._module()

        class Boom(Exception):
            pass

        def exploding_session(strat):
            raise Boom("socks handshake reset by peer")

        monkeypatch.setattr(m, "_make_session", exploding_session)
        loop = asyncio.new_event_loop()
        try:
            payload, err = loop.run_until_complete(m._attempt_get(("direct",), "https://x.invalid"))
            assert payload is None
            assert "Boom" in err and "handshake reset" in err  # 不再光报类型名
        finally:
            loop.close()
