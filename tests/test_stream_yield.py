# S101：流读取泵让位 + 工具结果显示预计算（stucked-log 38.5s read.then 洪峰根治）
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_s101_yield_pins():
    src = _read("static/js/stream_client.js")
    assert "const yieldToPump" in src
    assert src.count("framesSinceYield >= 4") == 2  # SSE 与 NDJSON 两个迭代器（S105: 24→4+200ms 双闸）
    assert src.count("Date.now() - batchT0 > 200") == 2
    # 写入点全部改走 _setResultDisplay，且旧模板 live-replace 已摘除
    tb = _read("static/js/methods/11_tool_blocks.js")
    assert "_setResultDisplay(block, content)" in tb
    for tpl in ("page_chat_main", "page_home", "page_ai-browser"):
        t = _read(f"static/templates/{tpl}.html")
        assert "block.displayContent ?? block.content" in t, tpl
        assert "block.content.replace(/\\\\n" not in t, tpl
    rs = _read("static/js/methods/13_resume_stream.js")
    assert rs.count("this._setResultDisplay(") >= 2
    cs = _read("static/js/methods/10_chat_stream.js")
    assert cs.count("this._setResultDisplay(") >= 2


def test_s101_yield_runtime(tmp_path):
    # node 真跑：单次 read 返回 600 帧巨型 chunk，必须至少让位 floor(600/4) 次
    src = _read("static/js/stream_client.js")
    harness = tmp_path / "yield_harness.js"
    harness.write_text(
        "let yieldCalls = 0;\n"
        "const realTimeout = setTimeout;\n"
        "globalThis.setTimeout = (fn, ms, ...a) => { if (ms === 0) yieldCalls++; return realTimeout(fn, ms, ...a); };\n"
        + src +
        "\n"
        "const N = 600;\n"
        "let payload = '';\n"
        "for (let i = 0; i < N; i++) payload += 'data: {\"i\":' + i + '}\\n\\n';\n"
        "payload += 'data: [DONE]\\n\\n';\n"
        "const bytes = new TextEncoder().encode(payload);\n"
        "let sent = false;\n"
        "const response = { body: { getReader: () => ({ read: async () => sent ? { done: true } : (sent = true, { done: false, value: bytes }) }) } };\n"
        "let frames = 0;\n"
        "iterateSse(response, (p) => { frames += 1; }).then((r) => {\n"
        "  if (frames !== N) throw new Error('frame loss: ' + frames);\n"
        "  if (!r.serverDone) throw new Error('no done handling path exercised');\n"
        "  const min = Math.floor(N / 4);\n"
        "  if (yieldCalls < min) throw new Error('yields=' + yieldCalls + ' < ' + min);\n"
        "  console.log('YIELD_OK frames=' + frames + ' yields=' + yieldCalls);\n"
        "}).catch((e) => { console.error('FAIL', e.message); process.exit(1); });\n",
        encoding="utf-8",
    )
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=60)
    assert "YIELD_OK" in out.stdout, (out.stdout, out.stderr)
