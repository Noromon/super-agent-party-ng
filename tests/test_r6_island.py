# -*- coding: utf-8 -*-
"""S139(R6)：灵动岛移植钉桩（资产哈希、M2 token 补丁、后端接线、Electron 桥）。"""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 上游 origin/main@3eb32bb2 终态哈希（dynamic_island.py / island.css 逐字节）
SHA_DYNAMIC_ISLAND = "0728ca9a843925e8e210a6c217bf272dd07fea482f2249598787964cb1647c46"
SHA_ISLAND_CSS = "ede0b79dce0675e1c0b81b97a80b1fe8f65e049959c6f792a21dbdb135a4d5de"
# fork 补丁后资产哈希（上游 + S139 M2 token 补丁 + S141 纯图标刷新徽章，白名单改动）
SHA_ISLAND_APP = "4445e7df71f3899ac9ab8efec1ad619881cb373016ea596f2f96a808341ea450"
SHA_ISLAND_HTML = "93fab8cd4993f67aa674316165ac9bd748540cc14a6c396cf629c849c6ed506b"


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace").read()


def _sha(*p):
    return hashlib.sha256(open(os.path.join(ROOT, *p), "rb").read()).hexdigest()


class TestIslandAssetsS139:
    def test_dynamic_island_verbatim(self):
        assert _sha("py", "dynamic_island.py") == SHA_DYNAMIC_ISLAND
        assert os.path.getsize(os.path.join(ROOT, "py", "dynamic_island.py")) == 19287

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
        assert "build=S144" in _read("static", "js", "renderer.js")


class TestIslandProxyFallbackS140:
    """S140：本机 DNS 挂起/IPv6 黑洞环境下，外联走 直连(trust_env)→本机代理 回退。"""

    def test_router_has_fallback_helper(self):
        s = _read("py", "routers", "island.py")
        assert "_external_get_json" in s
        assert "trust_env=True" in s
        assert "SAP_PROXY" in s and "127.0.0.1:1080" in s and "127.0.0.1:7890" in s
        # 三个外联端点统一走回退出口
        for url in ("http://ip-api.com/json/", "api.open-meteo.com/v1/forecast",
                    "geocoding-api.open-meteo.com/v1/search"):
            assert url in s
        assert "total=5" not in s  # 上游 5s 超时全部移除

    def test_attempt_order_direct_then_proxy(self, monkeypatch):
        import importlib

        m = importlib.import_module("py.routers.island")
        monkeypatch.delenv("SAP_PROXY", raising=False)
        m._proxy_state["sticky"] = None
        order = m._attempt_order()
        assert order[0] is None and "http://127.0.0.1:7890" in order and "http://127.0.0.1:1080" in order
        # 粘滞：代理成功后优先该代理，直连降为次选
        m._proxy_state["sticky"] = "http://127.0.0.1:7890"
        order = m._attempt_order()
        assert order[0] == "http://127.0.0.1:7890" and order[1] is None
        # SAP_PROXY 显式指定时只用它（不外探默认口）
        monkeypatch.setenv("SAP_PROXY", "http://127.0.0.1:9999")
        m._proxy_state["sticky"] = None
        order = m._attempt_order()
        assert order == [None, "http://127.0.0.1:9999"]
        m._proxy_state["sticky"] = None

    def test_proxy_exit_disables_ip_city(self):
        # 代理出口下 IP 定位=代理城市，禁用兜底（前端保留默认/手选城市）
        s = _read("py", "routers", "island.py")
        i = s.find('async def get_ip_city')
        block = s[i:i + 900]
        j_sticky = block.find('_proxy_state.get("sticky")')
        j_ext = block.find("_external_get_json")
        assert j_sticky != -1 and j_sticky < j_ext
