# -*- coding: utf-8 -*-
"""S120(R1c): 内容安全 guard（上游 guard.py 移植）+ fork 挂点存在性。"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# site-packages 里存在名为 py 的模块会遮蔽仓库 py/ 包，guard.py 零内部依赖→按文件直载
_spec = importlib.util.spec_from_file_location("sap_guard", ROOT / "py" / "guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)


def test_template_switch_defaults_off():
    tpl = json.loads((ROOT / "config" / "settings_template.json").read_text(encoding="utf-8"))
    assert tpl["systemSettings"]["contentSafety"] is False


def test_guard_hit_and_exemptions(tmp_path, monkeypatch):
    words = tmp_path / "safety_words.json"
    words.write_text(json.dumps({
        "zh": ["敏感词测试", "短"],          # 单字 CJK 应被 min_cjk_chars 豁免
        "en": ["badword", "bad.example.com"],  # ASCII 走 \b；URL 词走子串
    }), encoding="utf-8")
    monkeypatch.setattr(guard, "SAFETY_WORDS_FILE", str(words))
    guard.load_safety_words()
    try:
        ok, m = guard.check_content_safety_sync("这里有一个敏感词测试混进文本")
        assert not ok and "敏感词测试" in m
        ok, _ = guard.check_content_safety_sync("单字 短 不应该触发")
        assert ok
        ok, _ = guard.check_content_safety_sync("a badword inside")
        assert not ok
        ok, _ = guard.check_content_safety_sync("superbadwordy no boundary hit")
        assert ok  # ASCII 词边界匹配，不误伤长串
        ok, _ = guard.check_content_safety_sync("visit bad.example.com now")
        assert not ok  # URL 词=子串匹配
    finally:
        monkeypatch.setattr(guard, "SAFETY_WORDS_FILE", str(ROOT / "config" / "safety_words.json"))
        guard.load_safety_words()  # 还原（fork 无词表=禁用态）


def test_missing_wordlist_disables_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "SAFETY_WORDS_FILE", str(tmp_path / "absent.json"))
    guard.load_safety_words()
    ok, _ = guard.check_content_safety_sync("任何内容都放行")
    assert ok


def test_server_wired_hooks_present():
    src = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "from py.guard import load_safety_words, check_content_safety" in src
    assert src.count("check_content_safety(") >= 6  # 流式 helper+入站×2+ws 三处
    assert "_sanitize_conversations_safety" in src
    assert 'get("contentSafety"' in src
