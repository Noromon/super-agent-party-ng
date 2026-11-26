# -*- coding: utf-8 -*-
"""S326 语义钉：locale 键必须放 window.lang_XX 顶层（t() 平铺查找）。

S324 教训：t() 实现为 translations[lang][key]，只查顶层；把键插进
properties:{} 等嵌套子对象 = 运行时渲染字面量/空白，而"字符串存在性"
grep 测试全绿也拦不住。本文件做真正的解析语义验证。
"""
import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_ZH = _ROOT / "static" / "js" / "locales" / "zh-CN.js"
_EN = _ROOT / "static" / "js" / "locales" / "en-US.js"
_BASELINE = _ROOT / "tests" / "data" / "locale_top_violations_baseline.json"

_S324_KEYS = {
    "allowAiStartExtension", "allowAiStartExtensionTip",
    "permManageTitle", "permManageTip", "permToolsTitle", "permDirsTitle",
    "permNoItems", "permGrant", "permRevoke", "permToolDesc",
}


def _top_level_keys(path):
    keys, depth, started = set(), 0, False
    for line in path.read_text(encoding="utf-8").splitlines():
        code = re.sub(r"//.*$", "", line)
        if not started:
            if re.search(r"window\.lang_\w+\s*=\s*\{", code):
                started, depth = True, 1
            continue
        m = re.match(r"\s+'([A-Za-z0-9_]+)'\s*:", code) if depth == 1 else None
        if m:
            keys.add(m.group(1))
        depth += code.count("{") - code.count("}")
        if depth <= 0:
            break
    assert started and depth <= 0, f"brace walk failed: {path}"
    return keys


def _perm_tool_desc_pairs(path):
    text = path.read_text(encoding="utf-8")
    m = re.search(r"'permToolDesc'\s*:\s*\{(.*?)\n(\s*)\},", text, re.S)
    assert m, "permToolDesc block not found"
    return dict(re.findall(r"'([A-Za-z0-9_]+)'\s*:\s*'([^']+)'", m.group(1)))


class TestS324KeysTopLevel:
    def test_zh_top_level(self):
        assert _S324_KEYS <= _top_level_keys(_ZH), \
            "S324/S325 keys missing from zh top level (t() is flat lookup!)"

    def test_en_top_level(self):
        assert _S324_KEYS <= _top_level_keys(_EN), \
            "S324/S325 keys missing from en top level (t() is flat lookup!)"

    def test_perm_desc_values_nonempty(self):
        for path in (_ZH, _EN):
            pairs = _perm_tool_desc_pairs(path)
            assert pairs and all(v.strip() for v in pairs.values()), path


class TestPermDescCoversSensitive:
    def test_covers_sensitive_tools(self):
        from py.tool_registry import SENSITIVE_TOOLS
        for path in (_ZH, _EN):
            pairs = _perm_tool_desc_pairs(path)
            missing = sorted(t for t in SENSITIVE_TOOLS if t not in pairs)
            assert not missing, f"{path.name}: SENSITIVE tool without desc: {missing}"


class TestNoNewViolations:
    def test_baseline(self):
        zh, en = _top_level_keys(_ZH), _top_level_keys(_EN)
        pat = re.compile(r"[^A-Za-z0-9_]t\('([A-Za-z0-9_]+)'\)")
        used = set()
        for f in (_ROOT / "static" / "templates").glob("*.html"):
            used |= set(pat.findall(f.read_text(encoding="utf-8")))
        viol = sorted(k for k in used if k not in zh and k not in en)
        baseline = set(json.loads(_BASELINE.read_text(encoding="utf-8")))
        new = sorted(set(viol) - baseline)
        assert not new, (
            "template t('key') not resolvable at lang top level (renders raw "
            f"literal!). New offenders: {new}. Fix: move key to top of "
            "window.lang_zhCN/en-US (NOT into nested blocks)."
        )
        removed = sorted(baseline - set(viol))
        assert not removed, (
            f"violations healed ({removed}) — regenerate baseline json"
        )
