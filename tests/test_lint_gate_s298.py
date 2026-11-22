# -*- coding: utf-8 -*-
"""S298：eslint no-undef 全域门禁恢复真值（外审 BL-01 关门钉）。

RA-37 判词实证：flat 配置初版起 tha.js 就被 script sourceType 罩出 Parsing
error，而 CI 只 lint diff 文件 + 该文件 S91 后零改动 = 从未被 lint 过。首跑
即出两案：PIXI 白名单缺口（5 处 no-undef）与 isHidden 未声明真缺陷（同文件
在用的是 isModelHiddenByHover）；main.js 侧 S239 在 attachFreezeProbe 外调用
probe 内局部的 evidenceAppend，ReferenceError 被调用点 try 吞掉——三案同根：
门禁失明期无人可见。本钉=全量 eslint 必须 0 error（warning 不设限）。
"""
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_no_undef_fixes_in_place():
    main_js = (ROOT / "main.js").read_text(encoding="utf-8")
    # evidenceAppend 上提模块级：定义必须先于 attachFreezeProbe
    assert main_js.index("const evidenceAppend = ") < main_js.index("function attachFreezeProbe(")
    assert "evidenceAppend('[AgentProxy] setProxy direct" in main_js
    tha = (ROOT / "static" / "js" / "tha.js").read_text(encoding="utf-8-sig")
    # 未声明 isHidden 已根除（剥注释行防自吞），门控改用文件内真实状态位
    body = "\n".join(l for l in tha.splitlines() if not l.strip().startswith("//"))
    assert "isHidden" not in body.replace("isModelHiddenByHover", "")
    assert "if (!isModelHiddenByHover) return;" in tha


def test_eslint_zero_errors():
    r = subprocess.run(
        ["npx", "eslint", "static/js", "main.js", "start.js"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=600, shell=True,
    )
    assert r.returncode == 0, (r.stdout or "")[-2500:]


def test_tha_module_override_present():
    cfg = (ROOT / "eslint.config.js").read_text(encoding="utf-8")
    assert 'files: ["static/js/tha.js"]' in cfg
    assert 'sourceType: "module"' in cfg
