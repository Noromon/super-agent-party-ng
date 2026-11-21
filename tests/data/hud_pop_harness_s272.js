// S272 行为驱动校验：pop 弹出/holdMs 淡出/stackMax 淘汰最老（假 DOM，无需浏览器）
'use strict';
const fs = require('fs');
const store = {};
function mkNode() {
  const n = {
    children: [], parentNode: null, _cl: new Set(), _attrs: {}, style: {},
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
    addEventListener() {},
    get firstElementChild() { return n.children[0] || null; },
    get lastElementChild() { return n.children[n.children.length - 1] || null; },
  };
  return n;
}
const body = mkNode();
global.document = { body, createElement: () => mkNode(), addEventListener() {}, readyState: 'complete' };
global.window = { addEventListener() {}, electron: undefined, electronAPI: undefined, __SAP_TOKEN: '' };
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

  console.log(fail ? 'S272-HARNESS failed=' + fail : 'S272-HARNESS all passed');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.log('HARNESS_ERR ' + ((e && e.stack) || e)); process.exit(3); });
