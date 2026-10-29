# -*- coding: utf-8 -*-
"""S136：SoulX FlashHead（上游 A3）移植钉桩——后端路由、TTS 广播 fanout、
配置链、前端面板/入口、Electron 窗口、资产与打包。"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SOULX_KEYS = [
    "name", "enabled", "serverUrl", "condImage", "selectedImageId",
    "images", "transparentBg", "windowWidth", "windowHeight",
]

I18N_KEYS = [
    "SoulXFlashHead", "soulxServiceNotice", "soulxServerUrl",
    "soulxWindowWidth", "soulxWindowHeight", "soulxTransparentBg",
    "soulxRefImage", "soulxNoImage", "soulxSelectImage", "soulxUploadImage",
    "soulxDropImage", "soulxImageNamePlaceholder", "soulxUpload",
    "startSoulxPet", "startSoulxPetWeb", "stopSoulxPet",
    "summonRealPersonCompanion",
]

METHODS = [
    "startSoulx", "startSoulxweb", "stopSoulx", "loadSoulxImages",
    "migrateLegacySoulxImage", "uploadSoulxImage", "deleteSoulxImage",
    "handleSoulxImageFileDrop", "browseSoulxImageFile",
    "cancelSoulxImageUpload", "connectToSoulx",
]


def _read(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8", errors="replace").read()


class TestSoulxBackendS136:
    def test_router_endpoints(self):
        s = _read("py", "routers", "soulx.py")
        for route in ('"/soulx_config"', '"/upload_soulx_image"',
                      '"/get_soulx_images"', '"/delete_soulx_image/{image_id}"',
                      '"/ws/soulx"'):
            assert route in s
        # fork 加固：WS 先过 ws_auth_ok（上游全局中间件不含 WS）
        assert "ws_auth_ok" in s
        assert 'close(code=4401)' in s
        assert "_soulx_image_id_from_name" in s
        assert "默认形象不可删除" in s  # 默认图保护随上游

    def test_server_wiring(self):
        s = _read("server.py")
        assert "app.include_router(soulx_router)" in s
        assert 'app.mount("/default_soulx_images"' in s
        assert "DEFAULT_SOULX_IMAGES_DIR" in s

    def test_get_setting_dirs(self):
        g = _read("py", "get_setting.py")
        assert "DEFAULT_SOULX_IMAGES_DIR = os.path.join(base_path, 'default_soulx_images')" in g
        assert "SOULX_IMAGES_DIR = os.path.join(UPLOAD_FILES_DIR, 'soulx_images')" in g
        a = g.find("dirs_to_create")
        assert "SOULX_IMAGES_DIR" in g[a:g.find("]", a)]

    def test_voice_fanout(self):
        v = _read("py", "voice.py")
        assert "self.soulx_connections" in v
        assert "async def connect_soulx" in v
        assert "def disconnect_soulx" in v
        a = v.find("async def broadcast_to_vrm")
        block = v[a:v.find("async def broadcast_emotion_to_tha")]
        # 二进制→vrm+soulx；文本→vrm+soulx+overlay（上游语义）
        assert "send_bytes(message)" in block
        assert block.count("self.soulx_connections") == 2
        assert "send_text(message)" in block


class TestSoulxConfigChainS136:
    def test_template_keys(self):
        t = json.loads(_read("config", "settings_template.json"))
        cfg = t["SoulxConfig"]
        assert sorted(cfg.keys()) == sorted(SOULX_KEYS)
        assert cfg["serverUrl"] == "ws://127.0.0.1:8765"
        assert cfg["enabled"] is False  # GPU 服务后补即用：默认关（checkpoint 决议）

    def test_schema_registered(self):
        assert "['SoulxConfig', 'SoulxConfig']," in _read("static", "js", "settings_schema.js")

    def test_data_shards(self):
        d = _read("static", "js", "data", "30_tiles_vrm.js")
        for key in ("SoulxConfig", "showSoulxImageDialog", "newSoulxImage"):
            assert key in d
        assert d.count('"soulxButton"') == 3  # MoreButtonDict/large/small 三表
        assert "isSoulxStarting: false" in _read("static", "js", "data", "40_tts_voice.js")
        tiles = _read("static", "js", "data", "50_bots_translate.js")
        assert "{ id: 'Soulx_pet', title: 'SoulXFlashHead'" in tiles


class TestSoulxFrontendS136:
    def test_method_shard_registered(self):
        m = _read("static", "js", "methods", "45_soulx_domain.js")
        assert "Object.assign(vue_methods" in m
        for meth in METHODS:
            assert meth in m
        # fork 适配：面板磁贴 id
        assert "this.subMenu = 'Soulx_pet'" in m
        assert 'js/methods/45_soulx_domain.js' in _read("static", "index.html")
        assert "loadSoulxImages()" in _read("static", "js", "methods", "14_ws_client.js")

    def test_computed_on_root_app(self):
        r = _read("static", "js", "renderer.js")
        assert r.count("selectedSoulxImage()") == 1
        # 必须落在根 app computed（R2-1 注释之后），不能落进 A2UI 子组件
        assert r.find("selectedSoulxImage()") > r.find("A2UIRendererComponent")

    def test_panel_and_entries(self):
        h = _read("static", "templates", "page_deploy-bot.html")
        assert "v-show=\"subMenu === 'Soulx_pet'\"" in h
        for key in ("soulxServerUrl", "soulxTransparentBg", "showSoulxImageDialog"):
            assert key in h
        d = _read("static", "templates", "page_dashboard.html")
        assert "@click=\"startSoulx\"" in d and "summonRealPersonCompanion" in d
        for f in ("page_home.html", "page_chat_main.html", "page_ai-browser.html"):
            assert "'soulxButton'" in _read("static", "templates", f)

    def test_window_pages_and_ipc(self):
        g = _read("main.js")
        for ch in ("start-soulx-window", "stop-soulx-window"):
            assert ch in g
        assert "let soulxWindows = []" in g
        assert "/soulx.html" in g
        assert "autoplayPolicy: 'no-user-gesture-required'" in g
        p = _read("static", "js", "preload.js")
        assert "startSoulxWindow" in p and "stopSoulxWindow" in p

    def test_static_assets_verbatim(self):
        h = _read("static", "soulx.html")
        assert 'src="js/soulx.js"' in h
        j = _read("static", "js", "soulx.js")
        for ref in ("/ws/vrm", "/soulx_config", "/get_soulx_images"):
            assert ref in j
        png = os.path.join(ROOT, "default_soulx_images", "default.png")
        assert os.path.getsize(png) > 100000
        assert "('default_soulx_images', 'default_soulx_images')," in _read("server.spec")

    def test_i18n_parity(self):
        z = _read("static", "js", "locales", "zh-CN.js")
        e = _read("static", "js", "locales", "en-US.js")
        for key in I18N_KEYS:
            assert f"'{key}'" in z, key
            assert f"'{key}'" in e, key

    def test_stamp(self):
        assert "build=S170" in _read("static", "js", "renderer.js")
