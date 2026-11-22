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
    elementFromPoint: () => env.efp || null,
    getElementById: () => null,
  };
  global.window = { _ev: {}, addEventListener(t, fn) { (global.window._ev[t] = global.window._ev[t] || []).push(fn); }, electron: undefined, __SAP_TOKEN: '' };
  global.window.electronAPI = {
    getHudCfg: () => Promise.resolve(null), publishHudCfg: () => {},
    setIgnoreMouseEvents: (ig, opt) => calls.push({ ig: !!ig, fwd: !!(opt && opt.forward) }),
    getCursorScreenPoint: async () => env.cursor || null,
  };
  global.window.screenX = 0; global.window.screenY = 0;
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

  console.log(fail ? 'S282-HARNESS failed=' + fail : 'S282-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
