# -*- coding: utf-8 -*-
"""S81（A8 KaTeX）接线 pin：libs/引入/插件/旧 MathJax 全退役。"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_katex_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402


def _read(rel):
    return io.open(_ROOT / rel, encoding="utf-8-sig").read()


def test_katex_libs_present():
    for name in ("static/libs/katex.min.css", "static/libs/katex.min.js",
                 "static/libs/texmath.min.js"):
        p = _ROOT / name
        assert p.exists() and p.stat().st_size > 1000, name


def test_html_wiring_and_mathjax_retired():
    for page in ("static/index.html", "static/chat.html"):
        html = _read(page)
        assert 'href="libs/katex.min.css"' in html, page
        assert 'src="libs/katex.min.js"' in html, page
        assert 'src="libs/texmath.min.js"' in html, page
        assert 'tex-svg' not in html, page
        assert 'window.MathJax' not in html, page
        assert 'MJX-CONTAINER' not in html, page
        # katex 必须在 vue/renderer 之前、markdown-it 之后加载
        assert (html.index('libs/markdown-it.min.js')
                < html.index('libs/katex.min.js')
                < html.index('libs/texmath.min.js')), page


def test_md_texmath_plugin():
    vm = _read("static/js/vue_methods.js")
    assert "md.use(window.texmath" in vm
    assert "engine: window.katex" in vm
    assert "output: 'html'" in vm


def test_mathjax_full_retirement_js():
    for f in ("static/js/methods/08_message_render.js",
              "static/js/methods/10_chat_stream.js",
              "static/js/methods/64_conversation_groups.js",
              "static/js/renderer.js"):
        src = _read(f)
        assert "window.MathJax" not in src, f
        assert "queueMathJax" not in src, f
    m8 = _read("static/js/methods/08_message_render.js")
    assert "LATEX_PLACEHOLDER" not in m8          # 占位保护退役，$ 直交 texmath
    vm = _read("static/js/vue_methods.js")
    assert "LATEX_PLACEHOLDER_PREFIX" not in vm
    data = _read("static/js/data/60_cards_options.js")
    assert "mathJaxQueue" not in data and "isMathJaxRunning" not in data


def test_b4_strip_survives_katex():
    m8 = _read("static/js/methods/08_message_render.js")
    assert "safeAttrs" in m8                       # B4 on* 剥离仍在前（S81 未回退）


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
