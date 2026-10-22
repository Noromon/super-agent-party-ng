# -*- coding: utf-8 -*-
"""S80（B6 弹幕成套）：队列方法行为测（node 子进程）+ 全家桶接线 pin。"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["SAP_DATA_DIR"] = tempfile.mkdtemp(prefix="sap_danmu_")

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

_DANMU = io.open(_ROOT / "static" / "js" / "methods" / "72_live_danmu.js",
                 encoding="utf-8-sig").read()
_TTS = io.open(_ROOT / "static" / "js" / "methods" / "40_voice_tts.js",
               encoding="utf-8-sig").read()

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")

_JS = r"""
const fs=require('fs');
const vm={};
new Function('vue_methods', fs.readFileSync(process.argv[1],'utf8'))(vm);
function stub(){const o={danmu:[],liveConfig:{danmakuQueueLimit:5},calls:[]};
  o.startDanmuProcessor=()=>o.calls.push('start');
  o.processDanmuQueue=()=>o.calls.push('proc');
  for(const k of ['trimDanmuQueue','removeDanmuItem','enqueueLiveRequest'])
    o[k]=(...a)=>vm[k].apply(o,a);
  return o;}
let st=stub();
st.danmu=[{content:'a'},{content:'b'},{content:'c'},{content:'d'},{content:'e'},{source:'director'}];
vm.trimDanmuQueue.call(st);
if(st.danmu.length!==6||!st.danmu.some(d=>d.source==='director'))throw 'trim lost director';
st.danmu=Array.from({length:8},(_,i)=>({content:''+i}));
vm.trimDanmuQueue.call(st);
if(st.danmu.length!==5)throw 'trim plain';
st=stub();st.danmu=[{content:'viewer'}];
vm.enqueueLiveRequest.call(st,{text:'old'});
vm.enqueueLiveRequest.call(st,{text:'new',silent:false});
const dirs=st.danmu.filter(d=>d.source==='director');
if(dirs.length!==1||dirs[0].content!=='new'||dirs[0].silent!==false)throw 'enqueue replace/silent';
vm.enqueueLiveRequest.call(st,{text:'   '});
if(st.danmu.filter(d=>d.source==='director').length!==1)throw 'empty no-op';
if(!st.calls.includes('start')||!st.calls.includes('proc'))throw 'kick timer+process';
const a={id:'a'},b={id:'b'};st.danmu=[a,b];
vm.removeDanmuItem.call(st,a);
if(st.danmu.length!==1||st.danmu[0]!==b)throw 'remove by ref';
vm.removeDanmuItem.call(st,null);
console.log('OK');
"""


@requires_node
def test_danmu_queue_methods_behavior():
    r = subprocess.run(["node", "-e", _JS, str(_ROOT / "static" / "js" / "methods" / "72_live_danmu.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout


# ---------------- 接线 / TTS 防卡死 pins ----------------

def test_live_enqueue_wiring():
    srv = io.open(_ROOT / "server.py", encoding="utf-8-sig").read()
    assert 'msg_type == "live_enqueue"' in srv
    ws = io.open(_ROOT / "static" / "js" / "methods" / "14_ws_client.js",
                 encoding="utf-8-sig").read()
    assert "data.type === 'live_enqueue'" in ws
    assert "this.enqueueLiveRequest(data.data)" in ws


def test_danmu_queue_hardening_pins():
    assert "this.danmu.pop()" not in _DANMU              # pop 全退役
    assert "this.removeDanmuItem(processing)" in _DANMU
    assert "!this.danmu.some((d) => d && d.source === 'director')" in _DANMU  # 导演豁免
    assert "oldestDanmu.source !== 'director' && this.lastProcessedContent" in _DANMU
    assert "if (!oldestDanmu.silent)" in _DANMU          # 导演请求不上 OBS 画面
    assert "this.trimDanmuQueue();" in _DANMU            # 观众入队也走裁剪单点
    assert "!this.hasActiveTTSPlayback()" in _DANMU      # 陈旧锁释放


def test_tts_placeholder_chain_pins():
    assert "_silent: true" in _TTS                       # 空文本占位
    assert _TTS.count("_failed: true") == 2              # 400 + 异常两条占位路径
    assert "Skipping failed TTS chunk" in _TTS
    assert "if (audioChunk && !audioChunk.url) {" in _TTS
    assert "this.currentAudio && typeof this.currentAudio.paused" in _TTS  # fork 字段适配
    i = _TTS.index("stopAllAudioPlayback() {")
    tail = _TTS[i:i + 1400]
    assert "this.TTSrunning = false;" in tail            # 8f06e799 停播即解锁
    assert _TTS.count("currentChunk = 0;") >= 4          # d35c9eaa 归位×2（存量×2）


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
