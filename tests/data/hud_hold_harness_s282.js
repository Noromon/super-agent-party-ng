// S282 行为校验：持握状态机双保险（DOM 命中驱动 / OS 光标轮询兜底 / 主窗门闩）
'use strict';
const fs = require('fs');
const store = {};
function mkNode() {
  const n = {
    children: [], parentNode: null, _cl: new Set(), _attrs: {}, style: {}, _ev: {},
    textContent: '', innerHTML: '',
    classList: {
      add(...c) { c.forEach(x => n._cl.add(x)); },
      remove(...c) { c.forEach(x => n._cl.delete(x)); },
      toggle(c, f) { if (f === undefined) f = !n._cl.has(c); f ? n._cl.add(c) : n._cl.delete(c); },
      contains(c) { return n._cl.has(c); },
    },
    get className() { return [...n._cl].join(' '); },
    set className(v) { n._cl = new Set(String(v).split(/\s+/).filter(Boolean)); },
    setAttribute(k, v) { n._attrs[k] = v; },
    getAttribute(k) { return n._attrs[k] ?? null; },
    appendChild(c) { c.parentNode = n; n.children.push(c); return c; },
    removeChild(c) { n.children = n.children.filter(x => x !== c); c.parentNode = null; return c; },
    remove() { if (n.parentNode) n.parentNode.removeChild(n); },
    querySelector(sel) {
      const cls = String(sel || '').replace(/^\./, '');
      const walk = (n) => { for (const c of n.children) { if (c._cl.has(cls)) return c; const r = walk(c); if (r) return r; } return null; };
      return walk(n);
    },
    addEventListener(t, fn) { (n._ev[t] = n._ev[t] || []).push(fn); },
  };
  return n;
}
function freshEnv() {
  const body = mkNode();
  const calls = [];
  const env = { body, calls };
  global.document = {
    body, createElement: () => mkNode(), _ev: {}, readyState: 'complete',
    addEventListener(t, fn) { (global.document._ev[t] = global.document._ev[t] || []).push(fn); },
    elementFromPoint: (x, y) => (env.efpAt ? env.efpAt(x, y) : (env.efp || null)),
    getElementById: () => null,
  };
  global.window = { _ev: {}, addEventListener(t, fn) { (global.window._ev[t] = global.window._ev[t] || []).push(fn); }, electron: undefined, __SAP_TOKEN: '' };
  global.window.electronAPI = {
    getHudCfg: () => Promise.resolve(null), publishHudCfg: () => {},
    setIgnoreMouseEvents: (ig, opt) => calls.push({ ig: !!ig, fwd: !!(opt && opt.forward) }),
    getCursorScreenPoint: async () => env.cursor || null,
  };
  global.window.screenX = 0; global.window.screenY = 0;
  global.window.innerWidth = 1536; global.window.innerHeight = 864; global.window.devicePixelRatio = 1;
  global.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
  global.WebSocket = function () { this.close = () => {}; };
  global.MutationObserver = function () { this.observe = () => {}; this.disconnect = () => {}; };
  global.fetch = async () => ({ ok: true, status: 200, json: async () => ({}) });
  global.requestAnimationFrame = (fn) => { setTimeout(fn, 0); return 0; };
  return env;
}
const src = fs.readFileSync(process.argv[2] || 'static/js/hud-capsule.js', 'utf8');
let fail = 0;
const ok = (cond, label) => { console.log((cond ? 'PASS ' : 'FAIL ') + label); if (!cond) fail++; };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const last = (calls, ig) => { for (let i = calls.length - 1; i >= 0; i--) if (calls[i].ig === ig) return calls[i]; return null; };

(async () => {
  // ===== 段 0：主窗（index.html）根本不建 HUD 层 + 穿透 API 零调用 =====
  global.location = { protocol: 'http:', host: 'x.invalid', pathname: '/index.html' };
  let env = freshEnv();
  new Function(src)();
  await sleep(60);
  ok(env.body.children.find(c => c.id === 'sap-hud-layer') === undefined, 'S282: 主窗实例不建 HUD 层（init 早退）');
  ok(env.calls.length === 0 && global.window.__sapHudHoldMouse === undefined, 'S282: 主窗实例零穿透 API 调用（门闩）');

  // ===== 段 1：岛窗 DOM 驱动 =====
  global.location = { protocol: 'http:', host: 'x.invalid', pathname: '/island.html' };
  env = freshEnv();
  new Function(src)();
  await sleep(60);
  const capsule = env.body.children[0].children[0];
  const badge = capsule.children[0];
  capsule.getBoundingClientRect = () => ({ left: 100, top: 100, right: 118, bottom: 118 });
  env.cursor = { x: 5, y: 5 };
  env.efp = badge;
  (global.document._ev.mousemove || []).forEach(fn => fn({ clientX: 109, clientY: 109 }));
  ok(last(env.calls, false) !== null, 'S282: mousemove 命中胶囊 → 立即解除穿透');
  ok(typeof global.window.__hudDiag === 'function', 'S285: 岛宿主已暴露 __hudDiag');
  {
    const d = global.window.__hudDiag();
    ok(/^S28\d$/.test(d.rev) && d.host === true && d.layer === true && d.apiSet === true, 'S28x: 诊断快照 rev/host/layer/api 正常: ' + d.rev);
    ok(typeof global.window.__hudDiagLite === 'function' && d.dpr === 1, 'S286: __hudDiagLite 已暴露且 dpr 上报');
  }
  env.efp = null;
  (global.document._ev.mousemove || []).forEach(fn => fn({ clientX: 300, clientY: 300 }));
  ok(last(env.calls, false) !== null && last(env.calls, true) === null, 'S282: 离开走迟滞，250ms 内不立刻恢复穿透');
  await sleep(320);
  const off = last(env.calls, true);
  ok(off && off.fwd === true, 'S282: 迟滞到期恢复 forward 穿透');

  // ===== 段 2：DOM 事件全盲 → OS 光标轮询兜底（本次事故形态）=====
  env = freshEnv();
  new Function(src)();
  await sleep(60);
  const capsule2 = env.body.children[0].children[0];
  capsule2.getBoundingClientRect = () => ({ left: 100, top: 100, right: 118, bottom: 118 });
  env.efp = null;              // elementFromPoint 全盲
  env.cursor = { x: 109, y: 109 }; // 光标在胶囊矩形内
  await sleep(400);            // 轮询 150ms × 若干轮
  ok(last(env.calls, false) !== null, 'S282: DOM 全盲时轮询命中矩形 → 解除穿透（可点击）');
  env.cursor = { x: 400, y: 400 };
  await sleep(400 + 320);
  const off2 = last(env.calls, true);
  ok(off2 && off2.fwd === true, 'S282: 光标离开 → 恢复穿透');

  // ===== 段 3：125% DPI 自校准（S286 现场事故：OS 光标物理像素 vs CSS 坐标）=====
  env = freshEnv();
  global.window.devicePixelRatio = 1.25;
  global.window.innerWidth = 1536; global.window.innerHeight = 816;
  new Function(src)();
  await sleep(60);
  const capsule3 = env.body.children[0].children[0];
  capsule3.getBoundingClientRect = () => ({ left: 1506, top: 786, right: 1524, bottom: 804 });
  env.efp = null;
  env.cursor = { x: 1890, y: 990 }; // 物理像素：正好在圈上（CSS 视角 = 1512,792）
  await sleep(400);
  ok(last(env.calls, false) !== null, 'S286: 125% 物理像素光标 → /dpr 候选命中矩形 → 解除穿透');
  const nUn = env.calls.filter(c => c.ig === false).length;
  env.cursor = { x: 1200, y: 630 }; // 视口内、远离胶囊（1.25 倍后恰好 1500,787.5——不得误伤）
  await sleep(400);
  ok(env.calls.filter(c => c.ig === false).length === nUn, 'S286: 视口内 miss 不试缩放候选（无误伤）');
  await sleep(320 + 200);
  ok(last(env.calls, true) !== null, 'S286: 离开后恢复穿透');
  env.cursor = { x: 9000, y: 9000 }; // 轮询彻底失明，只剩 DOM 事件通道
  env.efpAt = (x, y) => (x >= 1498 && x <= 1532 && y >= 778 && y <= 812 ? capsule3 : null);
  const nUn2 = env.calls.filter(c => c.ig === false).length;
  (global.document._ev.mousemove || []).forEach(fn => fn({ clientX: 1890, clientY: 990 }));
  ok(env.calls.filter(c => c.ig === false).length > nUn2, 'S286: 越界事件坐标 /dpr 复判 → mousemove 救援生效');

  console.log(fail ? 'S282-HARNESS failed=' + fail : 'S282-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
