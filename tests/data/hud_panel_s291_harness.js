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
const until = async (fn, ms, step = 80) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) { if (fn()) return true; await sleep(step); }
  return false;
};
const last = (calls, ig) => { for (let i = calls.length - 1; i >= 0; i--) if (calls[i].ig === ig) return calls[i]; return null; };

(async () => {
  global.location = { protocol: 'http:', host: 'x.invalid', pathname: '/island.html' };
  const env = freshEnv();
  let pressFlag = false; // 读到即消耗（同 GetAsyncKeyState 低位语义）
  let downFlag = false;  // S294：按住态（高位语义，拖动场景用）
  let wheelDelta = 0;    // S294：滚轮增量（drain 语义：拉取即清零）
  global.fetch = async (url) => {
    if (String(url).indexOf('mouse-state') >= 0) {
      const p = pressFlag; pressFlag = false;
      return { ok: true, status: 200, json: async () => ({ lbtn: downFlag, lpress: p }) };
    }
    if (String(url).indexOf('wheel-state') >= 0) {
      const w = wheelDelta; wheelDelta = 0;
      return { ok: true, status: 200, json: async () => ({ delta: w }) };
    }
    return { ok: true, status: 200, json: async () => ({ items: [] }) };
  };
  new Function(src)();
  await sleep(60);
  const capsule = env.body.children[0].children[0];
  const layer = env.body.children[0];
  capsule.getBoundingClientRect = () => ({ left: 1506, top: 786, right: 1524, bottom: 804 });
  const shownPanel = () => layer.children.find(c => c._cl.has('sap-hud-panel') && c._cl.has('hud-show'));

  // —— S293：持握空窗期累积的陈旧 lpress 不得在武装时幽灵开面板（首击必死回归锁）——
  env.cursor = { x: 700, y: 400 };
  pressFlag = true; // 用户落位前在别处点过左键：无采样期边沿持续累积
  await sleep(420);
  ok(!shownPanel() && last(env.calls, false) === null, 'S293: 空窗期不消费：陈旧边沿滞留、无持握无面板');
  env.cursor = { x: 1890, y: 990 }; // 悬停落到圈上（还没点）
  await sleep(550);
  ok(!shownPanel(), 'S293: 武装即冲刷→陈旧边沿被清,悬停本身不幽灵开面板');
  ok(last(env.calls, false) !== null, 'S293: 持握已正常武装（物理像素光标）');
  pressFlag = true; // 落位后的第一次真实点击
  await sleep(420);
  ok(!!shownPanel(), 'S293: 悬停后首次真实点击即时生效（快击路径无恙）');

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

  // —— S292：通道存活时幻影 click（错位命中 target=body）让位物理通道；
  //    复现并锁死「点胶囊关闭却关了又开」的双重行动序列 ——
  const outside = mkNode(); // 游离节点=不在面板/胶囊链上（幻影事件的典型 target）
  env.cursor = { x: 1890, y: 990 }; // 光标回到胶囊上（真实用户动作）
  await sleep(180);                 // 等新位置进入 lastPollP 记账
  pressFlag = true; // 胶囊上按下（面板此刻开着）
  await sleep(10);  // 现实时序：幻影 click 先于下一次键态采样到达
  (global.document._ev.click || []).forEach(fn => fn({ target: outside }));
  await sleep(450);
  ok(!shownPanel(), 'S292: 幻影click+物理路由点胶囊 → 仅关闭一次（关了又开=回归）');
  (global.document._ev.click || []).forEach(fn => fn({ target: outside }));
  await sleep(120);
  ok(!shownPanel(), 'S292: 通道存活期间幻影 click 持续静默（面板保持关闭）');
  // 面板开+幻影外部 click 不得抢关（物理通道全权期）
  pressFlag = true;
  await sleep(400);
  ok(!!shownPanel(), 'S292: 前置：物理再按下开面板');
  (global.document._ev.click || []).forEach(fn => fn({ target: outside }));
  await sleep(150);
  ok(!!shownPanel(), 'S292: 通道存活幻影外部 click → 捕获层让位（面板不被抢关）');

  // ===== S294：列表滚轮 + 物理拖动平移（OS 真值通道） =====
  env.cursor = { x: 700, y: 400 }; pressFlag = true; await sleep(450); // 面板外按下收起
  ok(!shownPanel(), 'S294: 前置——面板已收起');
  wheelDelta = -600; // 开面板之前在桌面滚过的陈旧增量
  env.cursor = { x: 1890, y: 990 }; await sleep(300);
  pressFlag = true; await sleep(420);
  const panel4 = shownPanel();
  ok(!!panel4, 'S294: 前置——面板已打开');
  const listEl = panel4.children[1];
  listEl.getBoundingClientRect = () => ({ left: 1176, top: 290, right: 1496, bottom: 790 });
  await sleep(400); // 让滚轮轮询多拍通过
  ok(!listEl.scrollTop, 'S294: 开面冲刷——陈旧滚轮增量不闪跳列表');
  env.cursor = { x: 1700, y: 700 }; await sleep(700); // 光标稳定进入 lastPollP（负载余量）
  wheelDelta = -240;
  ok(await until(() => (listEl.scrollTop || 0) >= 180, 2500),
    'S294: 光标在列表上滚轮下滚 → scrollTop+180（OS 真值滚轮）');
  // 物理拖动：列表内按住上移 200 物理px → +160 CSS px；随后释放不得误关面板
  downFlag = true; await sleep(450);                       // 按下沿落账=起拖
  env.cursor = { x: 1700, y: 500 }; await sleep(750);      // 位移跨拍采样
  downFlag = false;
  ok(await until(() => (listEl.scrollTop || 0) >= 340, 2500), 'S294: 物理拖动平移列表（+160）');
  await sleep(400);
  ok(!!shownPanel(), 'S294: 拖动释放不误关面板（点击路由被抑制）');
  wheelDelta = 0;

  // —— S292：通道断（旧后端/掉线）→ 捕获层原生语义兜底接管 ——
  global.fetch = async (url) => {
    if (String(url).indexOf('mouse-state') >= 0) return { ok: false, status: 503 };
    return { ok: true, status: 200, json: async () => ({ items: [] }) };
  };
  await sleep(3200); // 3s 存活窗过期
  if (shownPanel()) { ((capsule._ev.click) || []).forEach(fn => fn({})); await sleep(350); } // 归零到关闭态
  ((capsule._ev.click) || []).forEach(fn => fn({}));
  await sleep(30);
  ok(!!shownPanel(), 'S292: 通道断场景前置：面板已打开');
  (global.document._ev.click || []).forEach(fn => fn({ target: outside }));
  await sleep(150);
  ok(!shownPanel(), 'S292: 通道断 → 捕获层恢复掌控，外部点击一点即收（旧后端不回归）');

  console.log(fail ? 'S291-HARNESS failed=' + fail : 'S291-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
