// S272 行为驱动校验：pop 弹出/holdMs 淡出/stackMax 淘汰最老（假 DOM，无需浏览器）
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
      const walk = (n) => {
        for (const c of n.children) {
          if (c._cl.has(cls)) return c;
          const r = walk(c);
          if (r) return r;
        }
        return null;
      };
      return walk(n);
    },
    addEventListener(t, fn) { (n._ev[t] = n._ev[t] || []).push(fn); },
    get firstElementChild() { return n.children[0] || null; },
    get lastElementChild() { return n.children[n.children.length - 1] || null; },
  };
  return n;
}
const body = mkNode();
global.document = { body, createElement: () => mkNode(), addEventListener(t, fn) { (global.document._ev[t] = global.document._ev[t] || []).push(fn); }, _ev: {}, readyState: 'complete' };
global.window = { addEventListener(t, fn) { (global.window._ev[t] = global.window._ev[t] || []).push(fn); }, _ev: {}, electron: undefined, electronAPI: undefined, __SAP_TOKEN: '' };
global.localStorage = {
  getItem: (k) => store[k] ?? null,
  setItem: (k, v) => { store[k] = String(v); },
};
global.location = { protocol: 'http:', host: 'x.invalid', pathname: '/island.html' };
let lastWs = null;
let wsCount = 0;
const wsSockets = [];
global.WebSocket = function (u) {
  wsCount++; this.url = u; this.close = () => {};
  lastWs = this; wsSockets.push(this);
};
global.requestAnimationFrame = (fn) => { setTimeout(fn, 0); return 0; };

const src = fs.readFileSync(process.argv[2] || 'static/js/hud-capsule.js', 'utf8');
let fail = 0;
const ok = (cond, label) => { console.log((cond ? 'PASS ' : 'FAIL ') + label); if (!cond) fail++; };

(async () => {
  new Function(src)();
  await new Promise(r => setTimeout(r, 30));
  const layer = body.children.find(c => c.id === 'sap-hud-layer');
  ok(!!layer, 'layer built');
  const stack = layer && layer.children.find(c => c._cl.has('sap-hud-stack'));
  ok(!!stack, 'stack container built（单气泡已替换为栈）');
  ok(lastWs, 'ws instance captured (ensureWS)');
  const send = (rec) => lastWs.onmessage({ data: JSON.stringify({ type: 'notification', data: rec }) });
  send({ category: 'bot', msg: 'msg-1' });
  send({ category: 'bot', msg: 'msg-2' });
  await new Promise(r => setTimeout(r, 20));
  ok(stack.children.length === 2, '两条送达各自入栈弹出（胶囊模式不再只加角标）');
  send({ category: 'bot', msg: 'msg-3' });
  send({ category: 'bot', msg: 'msg-4' });
  await new Promise(r => setTimeout(r, 20));
  const texts = stack.children.map(c => c.children[1] && c.children[1].textContent);
  ok(texts.includes('msg-2') && texts.includes('msg-3') && texts.includes('msg-4'), '最新三条在场: ' + JSON.stringify(texts));
  const oldest = stack.children.find(c => c.children[1] && c.children[1].textContent === 'msg-1');
  ok(oldest && oldest.__gone && !oldest._cl.has('hud-show'), '超限(stackMax=3)后最老一条被提前撤下（不等保留到期，正在淡出）');
  ok(texts.length === 4, '淡出中的节点仍短暂在场（450ms 过渡）: ' + texts.length);
  // 保留时长：默认 8000——5s 后显示中的仍是最新三条
  await new Promise(r => setTimeout(r, 5000));
  const alive = stack.children.filter(c => c._cl.has('hud-show'));
  ok(alive.length === 3, '保留期内最新三条不淡出（holdMs 默认 8000）: ' + alive.length);
  // 到点全清：msg-2 弹出时刻 ~t0+20ms，8000 保留 + 450 过渡
  await new Promise(r => setTimeout(r, 3800));
  const alive2 = stack.children.filter(c => c._cl.has('hud-show') && !c.__gone);
  ok(alive2.length === 0, '保留到期全部淡出清除: 剩 ' + alive2.length);

  // ===== S273：__SAP_READY 延迟期双 ensureWS 竞态 + 同 id 双投递去重（第二实例）=====
  let resolveReady;
  global.window.__SAP_READY = new Promise(res => { resolveReady = res; });
  global.window.electron = { ipcRenderer: { on: () => {} } };
  global.window.electronAPI = { getHudCfg: () => Promise.resolve({ enabled: true }) };
  const wsCountBefore = wsCount;
  new Function(fs.readFileSync(process.argv[2] || 'static/js/hud-capsule.js', 'utf8'))();
  await new Promise(r => setTimeout(r, 30)); // build(ensureWS#1) + getHudCfg→mergeCfg(ensureWS#2) 均已排队
  resolveReady();
  await new Promise(r => setTimeout(r, 60));
  ok(wsCount - wsCountBefore === 1, 'S273: ready 前双触发只建一条 WS（实建 ' + (wsCount - wsCountBefore) + ' 条）');
  const layer2 = body.children.filter(c => c.id === 'sap-hud-layer')[1];
  ok(!!layer2, 'S273: 第二实例层已建');
  const stack2 = layer2.children.find(c => c._cl.has('sap-hud-stack'));
  const ws2 = wsSockets[wsSockets.length - 1];
  const dup = { id: 'rec-dup-1', category: 'bot', msg: 'dup-msg' };
  ws2.onmessage({ data: JSON.stringify({ type: 'notification', data: dup }) });
  ws2.onmessage({ data: JSON.stringify({ type: 'notification', data: dup }) });
  await new Promise(r => setTimeout(r, 20));
  const dupCount = stack2.children.filter(c => c.children[1] && c.children[1].textContent === 'dup-msg').length;
  ok(dupCount === 1, 'S273: 同 id 双投递只弹一次（实弹 ' + dupCount + ' 次）');
  const badge2 = layer2.children[0].children[0];
  ok(badge2 && badge2.textContent === '1', 'S273: 角标也不双计（现 ' + (badge2 && badge2.textContent) + '）');

  // ===== S274：badge 开关 + 胶囊点击历史面板（第三实例）=====
  const fire = (n, t, evt) => ((n._ev && n._ev[t]) || []).forEach(fn => fn(evt || { stopPropagation() {} }));
  store['sapHudCfg'] = JSON.stringify({ enabled: true, capsule: true, badge: false });
  const fetchCalls = [];
  global.fetch = async (url, opt) => {
    fetchCalls.push({ url: String(url), opt: opt || {} });
    if (String(url).startsWith('/api/notifications?')) {
      return { ok: true, status: 200, json: async () => ({ items: [
        { id: 'a1', ts: 1795274824, category: 'bot', level: 'info', msg: 'hist-1' },
        { id: 'b2', ts: 1795274900, category: 'approval', level: 'warn', msg: 'hist-2' },
      ] }) };
    }
    return { ok: true, status: 200, json: async () => ({}) };
  };
  new Function(fs.readFileSync(process.argv[2] || 'static/js/hud-capsule.js', 'utf8'))();
  await new Promise(r => setTimeout(r, 30));
  const layer3 = body.children.filter(c => c.id === 'sap-hud-layer')[2];
  ok(!!layer3, 'S274: 第三实例层已建');
  const capsule3 = layer3.children[0];
  ok(capsule3._cl.has('hud-no-badge'), 'S274: badge 关闭 → 角标不渲染（hud-no-badge）');
  const ws3 = wsSockets[wsSockets.length - 1];
  ws3.onmessage({ data: JSON.stringify({ type: 'notification', data: { id: 'n-pre', category: 'bot', msg: 'pre-panel' } }) });
  await new Promise(r => setTimeout(r, 20));
  ok(capsule3.children[0].textContent === '1', 'S274: 角标关闭时计数仍在累计（仅不显示）');
  fire(capsule3, 'click');
  await new Promise(r => setTimeout(r, 50));
  const panel3 = layer3.children.find(c => c._cl.has('sap-hud-panel'));
  ok(!!panel3, 'S274: 点击胶囊展开历史面板');
  ok(global.window.__sapHudHoldMouse === true, 'S274: 面板打开期间持握鼠标（岛窗穿透已关）');
  ok(fetchCalls.some(c => c.url.startsWith('/api/notifications?limit=50')), 'S274: 面板数据走 GET /api/notifications');
  const list3 = panel3 && panel3.children.find(c => c._cl.has('hud-p-list'));
  ok(list3 && list3.children.length === 2, 'S274: 面板渲染历史条数=' + (list3 && list3.children.length));
  ok(fetchCalls.some(c => c.url === '/api/notifications/read' && c.opt.method === 'POST'), 'S274: 打开面板即标记已读');
  ok(capsule3.children[0].textContent === '0', 'S274: 打开面板清零本地角标');
  fire(capsule3, 'click');
  await new Promise(r => setTimeout(r, 20));
  ok(panel3 && !panel3._cl.has('hud-show'), 'S274: 再点胶囊收起面板');
  await new Promise(r => setTimeout(r, 320)); // S282: 释放走 250ms 迟滞，防边缘抖动反复开关穿透
  ok(global.window.__sapHudHoldMouse === false, 'S274: 关闭且不在胶囊上 → 恢复点击穿透（S282 迟滞内）');
  // Esc 兜底（document keydown）
  fire(capsule3, 'click');
  await new Promise(r => setTimeout(r, 20));
  (global.document._ev.keydown || []).forEach(fn => fn({ key: 'Escape' }));
  const panels3 = layer3.children.filter(c => c._cl.has('sap-hud-panel'));
  ok(panels3.length > 0 && panels3.every(p => !p._cl.has('hud-show')), 'S274: Esc 关闭面板');

  console.log(fail ? 'S272-HARNESS failed=' + fail : 'S272-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
