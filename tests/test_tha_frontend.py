# S91(THA) B2：前端+桌壳结构 pins（纯文本断言，不起服务）
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_main_js_tha_ipc():
    src = _read("main.js")
    assert "ipcMain.handle('start-tha-window'" in src
    assert "ipcMain.handle('stop-tha-window'" in src
    assert "tha.html" in src
    assert "thaWindows" in src


def test_preload_tha_api():
    src = _read("static/js/preload.js")
    assert "startTHAWindow" in src
    assert "stopTHAWindow" in src


def test_vue_data_tha_state():
    src = _read("static/js/data/30_tiles_vrm.js")
    assert "THAConfig:" in src
    assert "srMode" in src
    assert "enabledFineControl" in src
    assert "showThaModelDialog" in src
    assert "newThaModel" in src
    assert src.count('"thaButton"') == 3
    src2 = _read("static/js/data/40_tts_voice.js")
    assert "isTHAStarting: false" in src2


def test_deploy_tiles_tha_pet():
    src = _read("static/js/data/50_bots_translate.js")
    assert "THA_pet" in src
    assert "THAPet" in src


def test_tha_domain_methods_registered():
    src = _read("static/js/methods/43_tha_domain.js")
    for m in ("startTHA", "startTHAweb", "stopTHA", "uploadTHAModel",
              "deleteTHAModel", "loadTHAModels", "copyTHAEndpoint"):
        assert m in src, m
    for host in ("static/index.html", "static/chat.html"):
        assert "js/methods/43_tha_domain.js" in _read(host), host
    assert "this.loadTHAModels()" in _read("static/js/methods/14_ws_client.js")


def test_schema_and_template_tha():
    assert "['THAConfig', 'THAConfig']" in _read("static/js/settings_schema.js")
    tpl = json.loads(_read("config/settings_template.json"))
    tha = tpl["THAConfig"]
    for k in ("enabledEmotions", "enabledFineControl", "srMode",
              "selectedModelId", "windowWidth", "windowHeight"):
        assert k in tha, k

    n = 0
    for key in ("largeMoreButtonDict", "smallMoreButtonDict"):
        n += sum(1 for item in tpl.get(key, []) if isinstance(item, dict) and item.get("name") == "thaButton")
    assert n == 2


def test_panel_and_topbar_buttons():
    panel = _read("static/templates/page_deploy-bot.html")
    assert "subMenu === 'THA_pet'" in panel
    assert "startTHAweb" in panel
    assert "copyTHAEndpoint" in panel
    assert "/tha.html" in panel
    for tpl in ("page_home", "page_chat_main", "page_ai-browser"):
        src = _read(f"static/templates/{tpl}.html")
        assert "@click=\"startTHA\"" in src, tpl
        assert "thaButton" in src, tpl
        assert "isTHAStarting" in src, tpl
    assert "startTHA" in _read("static/templates/page_dashboard.html")


def test_tha_static_assets():
    assert (ROOT / "static/tha.html").exists()
    assert (ROOT / "static/js/tha.js").exists()
    assert (ROOT / "static/libs/pixi/pixi.min.js").exists()
    assert (ROOT / "static/libs/anime4k-sr.bundle.js").exists()
    assert (ROOT / "scripts/anime4k-entry.js").exists()
    assert "js/tha.js" in _read("static/tha.html")


_THA_KEYS = [
    "thaDesktopPet", "enabledFineControl", "srMode", "srOff", "thaAPI",
    "thaApiEndpoint", "thaAPIInstructions", "tha_table_pet_config",
    "start_tha_table_pet", "start_tha_table_pet_web", "stop_tha_table_pet",
    "thaNotice1", "dropTHAZipFile", "THAPet", "thaModel", "thaButton",
    "tha_distill_model", "tha_distill_desc",
]


def test_locale_tha_keys_present():
    for loc in ("static/js/locales/zh-CN.js", "static/js/locales/en-US.js"):
        src = _read(loc)
        for k in _THA_KEYS:
            assert re.search(rf"'{k}':\s*'", src) or re.search(rf'"{k}":\s*"', src), f"{loc} missing {k}"


def test_tha_prompt_wiring():
    src = _read("server.py")
    assert "_append_tha_prompt" in src
    assert "THAConfig" in src
