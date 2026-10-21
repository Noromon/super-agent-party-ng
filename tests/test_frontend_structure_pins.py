# -*- coding: utf-8 -*-
"""批 3 前端结构钉（F0 安全网）。

看护 vue_methods/vue_data 顶层键名集合、index/chat 的 script 加载顺序、
console.log 计数与 styles.css 行数——F2 域切/F3 页面分片过程中
键名与页面名不得增删改（装配等价的保险）。
基线再生成：.venv\\Scripts\\python.exe scripts/gen_frontend_baseline.py
（确有方法/数据键增删时评审后重跑并在提交信息中说明）。
"""
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_STATIC = _ROOT / "static"
_BASELINE = _ROOT / "tests" / "data" / "frontend_keys_baseline.json"

sys.path.insert(0, str(_ROOT / "scripts"))
from gen_frontend_baseline import collect  # noqa: E402

DATA = json.loads(_BASELINE.read_text(encoding="utf-8"))


class TestScriptOrder:
    @pytest.mark.parametrize("page", ["index.html", "chat.html"])
    def test_order_matches_baseline(self, page):
        cur = collect()["script_order"][page]
        assert cur == DATA["script_order"][page], (
            f"{page} 的 <script src> 序列变化。若是有意调整顺序/拆分文件，"
            "评审后重跑 scripts/gen_frontend_baseline.py 更新基线。")


class TestVueKeys:
    def test_methods_key_set_stable(self):
        cur = set(collect()["vue_methods_keys"])
        base = set(DATA["vue_methods_keys"])
        assert cur == base, (
            f"vue_methods 键名增删: -{sorted(base - cur)} +{sorted(cur - base)}")

    def test_data_key_set_stable(self):
        cur = set(collect()["vue_data_keys"])
        base = set(DATA["vue_data_keys"])
        assert cur == base, (
            f"vue_data 键名增删: -{sorted(base - cur)} +{sorted(cur - base)}")

    def test_no_new_duplicate_keys(self):
        # 存量重复键 41 个（last-wins 语义），禁止继续增加
        dups = set(collect()["_dup_methods"])
        assert dups <= set(DATA["_dup_methods"]), (
            f"新增重复键: {sorted(dups - set(DATA['_dup_methods']))}")


class TestConsoleRatchet:
    def test_total_do_not_grow(self):
        cur = collect()
        assert cur["console_log_total"] <= DATA["console_log_total"], (
            f"console.log 总数 {DATA['console_log_total']} → "
            f"{cur['console_log_total']}：只降不升；清理后重跑生成器下调基线。")

    def test_styles_css_do_not_grow(self):
        cur = collect()["styles_css_lines"]
        assert cur <= DATA["styles_css_lines"], (
            f"styles.css {DATA['styles_css_lines']} → {cur} 行：存量样式不动，"
            "新样式必须写入新的 css/ 文件（CSS 防恶化裁决）。")


class TestTemplatesDirHygiene:
    def test_pages_are_html_only_assets(self):
        tpl = _STATIC / "templates"
        if not tpl.exists():
            pytest.skip("F3 之前 templates/ 不存在")
        for f in tpl.iterdir():
            assert f.name.startswith("page_") and f.suffix == ".html", f.name
