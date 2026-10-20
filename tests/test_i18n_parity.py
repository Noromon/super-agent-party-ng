# -*- coding: utf-8 -*-
"""批 0-② i18n 对账门禁（R2-11，接替 test_frontend_pins 的 dataGuard* 微滴钉）。

三层钉：
  1) zh/en 键集零差集（双向 parity，防新增语言单侧键）。
  2) t() 实现必须带 en-US 兜底（缺键不再裸显 key）。
  3) 模板/JS 引用的 t('key') 必须存在于语言包——存量缺键进基线白名单
     （修键=显示文案变更，属行为变更不随门禁做），只拦新增。
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ZH = REPO / "static" / "js" / "locales" / "zh-CN.js"
EN = REPO / "static" / "js" / "locales" / "en-US.js"
TEMPLATE_FILES = [
    REPO / "static" / "index.html",
    REPO / "static" / "chat.html",
    REPO / "static" / "js" / "vue_methods.js",
    REPO / "static" / "js" / "renderer.js",
    REPO / "static" / "js" / "vue_data.js",
]

_KEY_RE = re.compile(r"""^\s*['"]([A-Za-z0-9_.]+)['"]\s*:""", re.M)
_T_CALL_RE = re.compile(r"""(?:^|[^\w$.])(?:this\.)?t\(\s*['"]([A-Za-z0-9_.]+)['"]\s*[,)]""", re.M)

# 基线（批 0-② 定档）：这些引用键在语言包中不存在，UI 现状=直接显示 key。
# 补键会改变显示文案=行为变更，须走单独批次评审；此处仅防新增缺键引用。
KNOWN_MISSING_KEYS = {
    "ComfyUI", "URL", "Voice", "audioConversionFailed", "audioProcessingStarted",
    "backToDefaultView", "cancelSuccess", "copySuccess", "copy_failed", "denying",
    "editLLMTool", "editText", "executing", "failed_to_reload_live_config",
    "failed_to_start_live", "failed_to_stop_live", "fillAllFields", "fillRequired",
    "installDocker", "intask", "invalidConfig",
    "live_config_reloaded_successfully", "live_started_successfully",
    "live_stopped_successfully", "method", "micPermissionDenied", "microphoneError",
    "networkError", "noBlockSelected", "noResultsFound", "noTextToConvert",
    "openFolder", "pleaseCompleteForm", "pleaseConfigWorkspace", "readDirError",
    "refreshFailed", "removeFromGlobal", "removeFromProject", "resume",
    "selectVoice", "space", "success", "sync", "syncToGlobal",
    "transcriptionFailed", "tts_started", "updateFailed", "uploadFailed",
    "webSpeechNotSupported",
}


def _load_keys(path):
    return set(_KEY_RE.findall(path.read_text(encoding="utf-8")))


def _used_keys():
    used = set()
    for f in TEMPLATE_FILES:
        used |= set(_T_CALL_RE.findall(f.read_text(encoding="utf-8")))
    return used


def test_locale_keysets_identical():
    zh, en = _load_keys(ZH), _load_keys(EN)
    only_zh = sorted(zh - en)
    only_en = sorted(en - zh)
    assert not only_zh and not only_en, (
        f"i18n 语言包键漂移：仅 zh 有={only_zh} 仅 en 有={only_en}")


def test_no_typo_key_regressions():
    # 批 0-② 修复的拼写/大小写错位键不得回潮
    zh, en = _load_keys(ZH), _load_keys(EN)
    for bad in ("nvalidMCPConfig", "CurrentFieldOfView", "Personality"):
        assert bad not in zh and bad not in en, f"错位键回潮: {bad}"
    for good in ("invalidMCPConfig", "currentFieldOfView", "personality"):
        assert good in zh and good in en, f"修正键缺失: {good}"


def test_t_function_has_en_fallback():
    src = (REPO / "static" / "js" / "vue_methods.js").read_text(encoding="utf-8")
    m = re.search(r"\n    t\(key\) \{\n(.*?)\n    \},", src, re.S)
    assert m, "未找到 methods.t() 实现（结构变动请同步本钉）"
    body = m.group(1)
    assert "'en-US'" in body or '"en-US"' in body, "t() 缺少 en-US 兜底"
    assert "|| key" in body, "t() 缺少 key 原名最终兜底"


def test_referenced_keys_have_no_new_gaps():
    zh, en = _load_keys(ZH), _load_keys(EN)
    missing = {k for k in _used_keys() if k not in zh or k not in en}
    new_gaps = sorted(missing - KNOWN_MISSING_KEYS)
    assert not new_gaps, (
        f"新增引用键不在语言包（先双语补键再引用）: {new_gaps}")
    gone = sorted(KNOWN_MISSING_KEYS - missing)
    assert not gone, (
        f"基线缺键已补齐，请同步收缩 KNOWN_MISSING_KEYS: {gone}")
