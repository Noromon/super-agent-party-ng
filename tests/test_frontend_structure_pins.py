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

    def test_no_cross_file_key_overlap(self):
        # F2 分片：宿主与分片、分片与分片之间键名不得相交
        # （跨文件重复会让 winner 随加载顺序漂移，41 个存量 dup 仅允许存在于宿主内部）
        from gen_frontend_baseline import scan_assign_keys, scan_top_level_keys
        js = _ROOT / "static" / "js"
        groups = {
            "vue_methods.js": scan_top_level_keys(
                (js / "vue_methods.js").read_text(encoding="utf-8-sig"),
                r"(?:let|const|var)\s+vue_methods\s*=\s*\{"),
        }
        for f in sorted((js / "methods").glob("*.js")):
            groups[f.name] = scan_assign_keys(f.read_text(encoding="utf-8-sig"))
        names = list(groups)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                clash = set(groups[names[i]]) & set(groups[names[j]])
                assert not clash, f"{names[i]} ∩ {names[j]} = {sorted(clash)}"
        data_groups = {
            "vue_data.js": scan_top_level_keys(
                (js / "vue_data.js").read_text(encoding="utf-8-sig"),
                r"(?:let|const|var)\s+vue_data\s*=\s*\{"),
        }
        for f in sorted((js / "data").glob("*.js")):
            data_groups[f.name] = scan_assign_keys(
                f.read_text(encoding="utf-8-sig"), "vue_data")
        names = list(data_groups)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                clash = set(data_groups[names[i]]) & set(data_groups[names[j]])
                assert not clash, f"{names[i]} ∩ {names[j]} = {sorted(clash)}"


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
            if f.name == "MANIFEST.json":
                continue
            assert f.name.startswith("page_") and f.suffix == ".html", f.name
            body = f.read_text(encoding="utf-8")
            assert "<script" not in body.lower(), f"{f.name} 含可执行脚本"

    def test_manifest_pages_wired(self):
        tpl = _STATIC / "templates"
        mf = tpl / "MANIFEST.json"
        if not mf.exists():
            pytest.skip("尚无 MANIFEST")
        pages = json.loads(mf.read_text(encoding="utf-8"))["pages"]
        idx = (_STATIC / "index.html").read_text(encoding="utf-8")
        chat = (_STATIC / "chat.html").read_text(encoding="utf-8")
        for p in pages:
            assert (tpl / f"{p}.html").exists(), f"缺模板文件 {p}.html"
            host = chat if p.startswith("page_chat_") else idx
            assert f'data-tpl="{p}"' in host, f"{p} 锚点缺失"
            assert f'activeMenu' not in "".join(
                l for l in host.splitlines() if f'data-tpl="{p}"' in l)
            assert f'activeMenu' not in "".join(
                l for l in idx.splitlines() if f'data-tpl="{p}"' in l)
        for pg, body in (("index.html", idx), ("chat.html", chat)):
            assert '<script src="js/boot_templates.js"></script>' in body, pg
            assert body.index('<script src="js/boot_templates.js">') < \
                body.index('<script src="js/renderer.js">'), f"{pg}: loader 必须先于 renderer"
