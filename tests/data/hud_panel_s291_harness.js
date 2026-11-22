// S291 行为校验（独立进程运行：避免 hud_hold_harness 早前段存活实例抢消费
// mouse-state 边沿标志）。覆盖：lpress 快击边沿不丢 / 面板外一点即收 /
// 原生 click 450ms 让位 / 面板内按下不误收。
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
    removeChild(c) { n.children = n.children.filter(x => c !== x); c.parentNode = null; return c; },
    remove() { if (n.parentNode) n.parentNode.removeChild(n); },
    querySelector(sel) {
      const cls = String(sel || '').replace(/^\./, '');
      const walk = (m) => { for (const c of m.children) { if (c._cl.has(cls)) return c; const r = walk(c); if (r) return r; } return null; };
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
  global.window.innerWidth = 1536; global.window.innerHeight = 816; global.window.devicePixelRatio = 1.25;
  global.document.documentElement = mkNode();
  global.localStorage = { getItem: (k) => store[k] ?? null, setItem: (k, v) => { store[k] = String(v); } };
  global.WebSocket = function () { this.close = () => {}; };
  global.MutationObserver = function () { this.observe = () => {}; this.disconnect = () => {}; };
  global.requestAnimationFrame = (fn) => { setTimeout(fn, 0); return 0; };
  return env;
}
const src = fs.readFileSync(process.argv[2] || 'static/js/hud-capsule.js', 'utf8');
let fail = 0;
const ok = (cond, label) => { console.log((cond ? 'PASS ' : 'FAIL ') + label); if (!cond) fail++; };
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const last = (calls, ig) => { for (let i = calls.length - 1; i >= 0; i--) if (calls[i].ig === ig) return calls[i]; return null; };

(async () => {
  global.location = { protocol: 'http:', host: 'x.invalid', pathname: '/island.html' };
  const env = freshEnv();
  let pressFlag = false; // 读到即消耗（同 GetAsyncKeyState 低位语义）
  global.fetch = async (url) => {
    if (String(url).indexOf('mouse-state') >= 0) {
      const p = pressFlag; pressFlag = false;
      return { ok: true, status: 200, json: async () => ({ lbtn: false, lpress: p }) };
    }
    return { ok: true, status: 200, json: async () => ({ items: [] }) };
  };
  new Function(src)();
  await sleep(60);
  const capsule = env.body.children[0].children[0];
  const layer = env.body.children[0];
  capsule.getBoundingClientRect = () => ({ left: 1506, top: 786, right: 1524, bottom: 804 });
  env.cursor = { x: 1890, y: 990 }; // 125% 机物理像素：正落在圈上（CSS 1512,792）
  await sleep(450);
  ok(last(env.calls, false) !== null, 'S291: 前置持握已建立（物理像素光标）');
  const shownPanel = () => layer.children.find(c => c._cl.has('sap-hud-panel') && c._cl.has('hud-show'));

  // —— lpress 快击：按下+松开完整周期落在采样间隙，仅边沿标志可见 ——
  pressFlag = true;
  await sleep(400);
  ok(!!shownPanel(), 'S291: lpress 边沿不丢——采样间快击也展开面板');

  // —— 面板外按下 → 一点即收 ——
  env.cursor = { x: 700, y: 400 };
  pressFlag = true;
  await sleep(450);
  ok(!shownPanel(), 'S291: 面板外物理按下 → 一点即收');

  // —— 原生 click 450ms 内物理让位（刚由原生打开的面板不被物理外部判抢关）——
  ((capsule._ev.click) || []).forEach(fn => fn({}));
  await sleep(30);
  ok(!!shownPanel(), 'S291: 原生点击展开面板');
  env.cursor = { x: 700, y: 400 };
  pressFlag = true;
  await sleep(400);
  ok(!!shownPanel(), 'S291: 原生点击后 450ms 内外部物理按下让位（面板未被抢关）');

  // —— 面板内按下不误收 ——
  const panel = shownPanel();
  panel.getBoundingClientRect = () => ({ left: 1176, top: 250, right: 1496, bottom: 790 });
  env.cursor = { x: 1450, y: 500 }; // 原值命中面板；缩放候选(1160,400)在面板外
  pressFlag = true;
  await sleep(400);
  ok(layer.children.includes(panel) && !panel.__gone, 'S291: 面板内按下不触发外部收起');

  console.log(fail ? 'S291-HARNESS failed=' + fail : 'S291-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
