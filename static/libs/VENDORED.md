# Vendored third-party libraries

All files in this directory are third-party works redistributed under their
respective licenses. License texts live in [`licenses/`](licenses/).
Where a version is marked "~" the minified build did not embed an exact
version string; the entry reflects the best identification from file headers
and upstream release history.

| File / directory | Upstream project | Version | License | License file |
|---|---|---|---|---|
| `vue.global.prod.js` | [vuejs/core](https://github.com/vuejs/core) | 3.5.22 | MIT | `licenses/vue.txt` |
| `element-plus.js` / `element-plus.css` | [element-plus](https://github.com/element-plus/element-plus) | ~2.9.x | MIT | `licenses/element-plus.txt` |
| `element-plus-icons.js` | [@element-plus/icons-vue](https://github.com/element-plus/element-plus-icons) | ~2.3 | MIT | `licenses/element-plus-icons-vue.txt` |
| `mermaid.min.js` | [mermaid-js/mermaid](https://github.com/mermaidjs/mermaid) | ~11.x | MIT | `licenses/mermaid.txt` |
| `three/` | [mrdoob/three.js](https://github.com/mrdoob/three.js) | r178 | MIT | `licenses/three.txt` |
| `@pixiv/three-vrm/`, `@pixiv/three-vrm-animation/` | [pixiv/three-vrm](https://github.com/pixiv/three-vrm) | ~3.4 | MIT | `licenses/pixiv-three-vrm.txt`, `licenses/pixiv-three-vrm-animation.txt` |
| `katex.min.js` / `katex.min.css` | [KaTeX/KaTeX](https://github.com/KaTeX/KaTeX) | 0.16.9 | MIT | `licenses/katex.txt` |
| `fonts/KaTeX_*` | [KaTeX fonts](https://github.com/KaTeX/KaTeX) | 0.16.9 | SIL OFL 1.1 | `licenses/SIL-OFL-1.1.txt` |
| `markdown-it.min.js` | [markdown-it](https://github.com/markdown-it/markdown-it) | 14.1.0 | MIT | `licenses/markdown-it.txt` |
| `markdown-it-container.min.js` | markdown-it-container | ~4 | MIT | `licenses/markdown-it-container.txt` |
| `markdown-it-footnote.min.js` | markdown-it-footnote | ~4 | MIT | `licenses/markdown-it-footnote.txt` |
| `markdown-it-task-lists.min.js` | markdown-it-task-lists | 2.1.1 | MIT | `licenses/markdown-it-task-lists.txt` |
| `texmath.min.js` | [goessner/markdown-it-texmath](https://github.com/goessner/markdown-it-texmath) | 1.0.0 | MIT | `licenses/markdown-it-texmath.txt` |
| `tex-svg.js` | [MathJax](https://github.com/mathjax/MathJax) | ~3.2 | Apache-2.0 | `licenses/mathjax.txt` |
| `highlight.min.js` | [highlight.js](https://github.com/highlightjs/highlight.js) | 11.7.0 | BSD-3-Clause | `licenses/highlight.js.txt` |
| `html2canvas.min.js` | [html2canvas](https://github.com/niklasvh/html2canvas) | 1.4.1 | MIT | `licenses/html2canvas.txt` |
| `exceljs.min.js` | [exceljs](https://github.com/exceljs/exceljs) | ~4.4 | MIT | `licenses/exceljs.txt` |
| `clipboard.min.js` | [clipboard.js](https://github.com/zenorocha/clipboard.js) | 2.0.8 | MIT | `licenses/clipboard.txt` |
| `qrcode.min.js` | [qrcodejs](https://github.com/soldair/node-qrcode) | 1.5.1 | MIT | `licenses/qrcode.txt` |
| `driver.js` / `driver.css` | [kamranahmedse/driver.js](https://github.com/kamranahmedse/driver.js) | ~1.3 | MIT | `licenses/driver.js.txt` |
| `morphdom-umd.min.js` | [patm1988/MorphDOM](https://github.com/patm1988/MorphDOM) | ~2.7 | MIT | `licenses/morphdom.txt` |
| `uuid.min.js` | [uuid](https://github.com/uuidjs/uuid) | ~11 | MIT | `licenses/uuid.txt` |
| `ort.js` | [onnxruntime-web](https://github.com/microsoft/onnxruntime) | ~1.20 | MIT | `licenses/onnxruntime-web.txt` |
| `bundle.min.js` | [@ricky0123/vad-web](https://github.com/ricky0123/vad-web) (silero-vad bundle) | ~0.0.x | ISC (code) / MIT (Silero model) | `licenses/vad-web.txt`, `licenses/silero-vad-model.txt` |
| `vad.worklet.bundle.min.js` | @ricky0123/vad-web worklet | ~0.0.x | ISC | `licenses/vad-web.txt` |
| `pixi/pixi.min.js` | [pixijs/pixijs](https://github.com/pixijs/pixijs) | ~8 | MIT | `licenses/pixi.js.txt` |
| `@sparkjsdev/spark/` | [sparkjsdev/spark](https://github.com/sparkjsdev/spark) | ~2.x | MIT | `licenses/sparkjsdev-spark.txt` |
| `anime4k-sr.bundle.js` | Anime4K-style WebGPU super-resolution (exports `CNNx2VL`); no attribution embedded in the minified bundle | unknown | **unverified — provenance TODO** | — |

Notes:

- `tex-svg.js` (MathJax, Apache-2.0) additionally requires notice of
  modifications; this project uses the unmodified upstream build.
- The `anime4k-sr.bundle.js` entry has an unverified provenance. If you know
  its upstream, please open an issue so attribution can be completed.
- KaTeX code is MIT; its fonts (in `fonts/`) are SIL OFL 1.1. The bundled
  OFL file is the standard license text; per-font copyright notices are
  maintained upstream.
