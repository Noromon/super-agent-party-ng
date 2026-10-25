# -*- coding: utf-8 -*-
"""S85-B：前端 _ingestToolProgress 防膨胀——incremental 追加 / 全量替换 / 64KB 封顶。"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_s85b_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")

_JS = r"""
const fs = require('fs');
const vm = {};
new Function('vue_methods', fs.readFileSync(process.argv[2], 'utf8'))(vm);

function makeStub() {
    const blocks = {};
    const o = {
        toolArgsAccumulator: {},
        blocks,
        truncateDisplayContent(s) { return s.length > 5000 ? s.slice(0, 5000) : s; },
        requestScrollToBottom() {},
        _markReasoningDone() {},
        _setResultDisplay(b, c) { b.content = c; b.displayContent = c; },
        _setToolArgs(b, a) { b.args = a; b.displayArgs = a; },
        streamBacklog() { return false; },
    };
    o.getBlock = (t, id, name) => {
        const k = t + ':' + id;
        if (!blocks[k]) blocks[k] = { type: t, id, name, args: '' };
        return blocks[k];
    };
    o.ingest = (p) => vm._ingestToolProgress.call(o, p, o.getBlock, []);
    return o;
}

// 1) 新协议 incremental：帧帧追加
let s = makeStub();
s.ingest({ id: 'c1', name: 'web', arguments: '{"q"', incremental: true });
s.ingest({ id: 'c1', name: 'web', arguments: ':1}', incremental: true });
if (s.toolArgsAccumulator.c1 !== '{"q":1}') throw 'incremental append broken: ' + s.toolArgsAccumulator.c1;

// 2) 旧全量协议：前缀延长 → 替换不重复
s = makeStub();
s.ingest({ id: 'c2', name: 'web', arguments: '{"a"' });
s.ingest({ id: 'c2', name: 'web', arguments: '{"a":1}' });
if (s.toolArgsAccumulator.c2 !== '{"a":1}') throw 'full-prefix replace broken';

// 3) 全量但前缀断裂（跨轮复用 id）→ 整体替换，绝不 append（旧版此处 O(n^2) 膨胀卡死）
s = makeStub();
s.ingest({ id: 'c3', name: 'web', arguments: '{"a":1}' });
s.ingest({ id: 'c3', name: 'web', arguments: '{"b":2}' });
if (s.toolArgsAccumulator.c3 !== '{"b":2}') throw 'broken-prefix must REPLACE: ' + s.toolArgsAccumulator.c3;

// 4) incremental 也封顶 64KB（复读风暴防护）
s = makeStub();
const big = 'x'.repeat(70000);
s.ingest({ id: 'c4', name: 'web', arguments: big, incremental: true });
if (s.toolArgsAccumulator.c4.length !== 65536) throw 'cap broken: ' + s.toolArgsAccumulator.c4.length;
s.ingest({ id: 'c4', name: 'web', arguments: big, incremental: true });
if (s.toolArgsAccumulator.c4.length !== 65536) throw 'cap not sticky';

// 5) block.args 走截断展示
s = makeStub();
s.ingest({ id: 'c5', name: 'web', arguments: '{"ok":true}', incremental: true });
if (s.blocks['tool_call:c5'].args !== '{"ok":true}') throw 'block args not synced';

// 6) 无 id 时按 name 复用栈上未决调用（原语义回归）
s = makeStub();
const stack = [{ id: 'reuse1', name: 'web', resolved: false }];
vm._ingestToolProgress.call(s, { name: 'web', arguments: '{"a":1}', incremental: true }, s.getBlock, stack);
if (!s.toolArgsAccumulator.reuse1) throw 'stack reuse broken';

console.log('OK');
"""


@requires_node
def test_ingest_tool_progress_hardening(tmp_path):
    js_path = tmp_path / "ingest_test.js"
    io.open(js_path, "w", encoding="utf-8").write(_JS)
    target = _ROOT / "static" / "js" / "methods" / "13_resume_stream.js"
    r = subprocess.run(
        ["node", str(js_path), str(target)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
    )
    assert r.returncode == 0, f"node failed rc={r.returncode}\n{r.stdout}\n{r.stderr}"
    assert "OK" in r.stdout, json.dumps({"out": r.stdout, "err": r.stderr})
