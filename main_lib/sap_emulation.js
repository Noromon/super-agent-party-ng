// S305：S277/S278/S279 浏览器策略/仿真域自 main.js 逐字搬移（Electron 主进程模块）。
// 纯移动：函数与状态体未动。_policyLog/_sapMobileDbg/_sapInputDbg/_sapDlgDbg 经
// 导出共享同一 Map/Set 实例（全代码只有增删、无重绑定），main.js 事件处理器
// 继续原位读写同一对象，行为逐点等价。
const fs = require('fs')
const path = require('path')
const { webContents } = require('electron')

// 自动决策记账（按 webContents 环形≤20 条；S278 browser_policy_report 取走回报给 agent）
const _policyLog = new Map();
function _policyNote(wcId, kind, note) {
  try {
    if (!wcId) return;
    let a = _policyLog.get(wcId);
    if (!a) { a = []; _policyLog.set(wcId, a); }
    a.push({ ts: Math.round(Date.now() / 1000), kind: String(kind), note: String(note).slice(0, 300) });
    if (a.length > 20) a.splice(0, a.length - 20);
  } catch (_) {}
}
const _sapSafeName = (n) => (String(n || 'download').replace(/[\\/:*?"<>|\u0000-\u001f]+/g, '_').replace(/^\.+/, '') || 'download').slice(0, 180);
function _sapUniquePath(dir, name) {
  const base = _sapSafeName(name);
  let p = path.join(dir, base);
  const dot = base.lastIndexOf('.');
  for (let i = 1; fs.existsSync(p) && i < 1000; i++) {
    p = dot > 0 ? path.join(dir, base.slice(0, dot) + ' (' + i + ')' + base.slice(dot)) : path.join(dir, base + ' (' + i + ')');
  }
  return p;
}
// 调试器记账：_sapMobileDbg=移动端仿真来源；_sapInputDbg=wheel/click 临时 attach（S263 分离）。
// S277 提升到模块级：复位助手与 detach 监听需要跨 whenReady/事件访问。
const _sapMobileDbg = new Set();
const _sapInputDbg = new Set();
// detach 时 Chromium 会隐式清掉全部 CDP 覆盖——只需同步记账；每 wc 只挂一次监听。
function sapWatchDetach(wc) {
  if (!wc || wc._sapDetachWatched) return;
  try {
    wc._sapDetachWatched = true;
    wc.debugger.on('detach', () => { _sapMobileDbg.delete(wc.id); _sapInputDbg.delete(wc.id); });
  } catch (_) {}
}
// S277：无条件仿真复位（触摸/emit/视口/UA 覆盖全清）。S263 教训：复位绝不能依赖
// "当时恰好 attach 且 set 命中"——调试器被 wheel/click 顶替 attach、模态框期间复位失败
// 都会让触摸仿真永久残留（光标变触摸点、首击被吞）。未 attach 且记账无命中时无覆盖残留，
// 直接跳过避免无谓 attach；opts.force=应急通道（reset_page_state 工具）无视记账强制清。
async function sapResetEmulation(wc, wcId, opts) {
  opts = opts || {};
  if (!wc || wc.isDestroyed()) return { ok: false, err: 'no-webcontents' };
  let wasAttached = false;
  try { wasAttached = wc.debugger.isAttached(); } catch (_) {}
  const known = _sapMobileDbg.has(wcId) || _sapInputDbg.has(wcId);
  if (!opts.force && !wasAttached && !known) return { ok: true, skipped: true };
  let attachedHere = false;
  if (!wasAttached) {
    try { wc.debugger.attach('1.3'); attachedHere = true; sapWatchDetach(wc); } catch (_) { return { ok: false, err: 'devtools-busy' }; }
  }
  try {
    try { await wc.debugger.sendCommand('Emulation.setEmitTouchEventsForMouse', { enabled: false }); } catch (_) {}
    try { await wc.debugger.sendCommand('Emulation.setTouchEmulationEnabled', { enabled: false, maxTouchPoints: 0 }); } catch (_) {}
    try { await wc.debugger.sendCommand('Emulation.clearDeviceMetricsOverride'); } catch (_) {}
    try { await wc.debugger.sendCommand('Emulation.clearUserAgentOverride'); } catch (_) {}
    if (opts.defaultUA) { try { wc.setUserAgent(''); } catch (_) {} }
    if (attachedHere || _sapMobileDbg.has(wcId) || (opts.detachInput && _sapInputDbg.has(wcId))) {
      try { await wc.debugger.detach(); } catch (_) {}
    }
    _sapMobileDbg.delete(wcId);
    _sapInputDbg.delete(wcId);
    return { ok: true, detached: attachedHere || undefined };
  } catch (e) {
    return { ok: false, err: String((e && e.message) || e).slice(0, 140) };
  }
}
// S321：宿主窗口触摸模式清扫——窗口触摸态挂在 NativeWindowKit 层，旧版 guest 开过的
// 触摸仿真在 guest 销毁后仍粘住（关掉全部标签也「点击要双击/光标是触摸点」）。对宿主
// webContents 只清触摸两项（不动 UA/视口），全程静默容错；启动自愈与 reset_page_state
// 的 host 通道共用。
async function sapHostTouchClear(wc) {
  if (!wc || wc.isDestroyed()) return { ok: false, err: 'no-webcontents' };
  let attachedHere = false;
  try {
    if (!wc.debugger.isAttached()) { wc.debugger.attach('1.3'); attachedHere = true; }
  } catch (_) { return { ok: false, err: 'devtools-busy' }; }
  try {
    try { await wc.debugger.sendCommand('Emulation.setEmitTouchEventsForMouse', { enabled: false }); } catch (_) {}
    try { await wc.debugger.sendCommand('Emulation.setTouchEmulationEnabled', { enabled: false, maxTouchPoints: 0 }); } catch (_) {}
    return { ok: true };
  } catch (e) {
    return { ok: false, err: String((e && e.message) || e).slice(0, 140) };
  } finally {
    if (attachedHere) { try { await wc.debugger.detach(); } catch (_) {} }
  }
}
// ---- S278：JS 弹窗策略执行（CDP Page 域主管；attach 失败退 Electron 事件兜底=只关不确认）----
// 主管原因：Electron 的 javascript-dialog-opening 只能 cancel（关），无法"确认"；accept 语义
// 必须 CDP Page.handleJavaScriptDialog。代价：watch 期间 guest 调试器被占用（DevTools 互斥），
// 策略改为"询问"或总开关关时自动 Page.disable+detach 释放。
const _sapDlgDbg = new Map(); // wcId -> { attachedHere }
async function sapEnsureDialogWatch(wc) {
  if (!wc || wc.isDestroyed()) return;
  const id = wc.id;
  if (_sapDlgDbg.has(id)) return;
  try {
    const rec = { attachedHere: false };
    if (!wc.debugger.isAttached()) {
      wc.debugger.attach('1.3');
      rec.attachedHere = true;
      sapWatchDetach(wc);
    }
    _sapDlgDbg.set(id, rec);
    if (!wc._sapDlgMsg) {
      wc._sapDlgMsg = true;
      wc.debugger.on('message', (event, method, params) => {
        if (method !== 'Page.javascriptDialogOpening') return;
        const pol = global.browserPolicy || {};
        if (pol.enabled === false || pol.jsDialog === 'ask') return;
        const accept = pol.jsDialog === 'accept';
        const type = String((params && params.type) || '');
        try { wc.debugger.sendCommand('Page.handleJavaScriptDialog', { accept, promptText: '' }).catch(() => {}); } catch (_) {}
        _policyNote(id, 'jsdialog', (accept ? 'auto-confirmed ' : 'auto-closed ') + type + ': ' + String((params && params.message) || '').slice(0, 80));
      });
    }
    await wc.debugger.sendCommand('Page.enable');
  } catch (_) { _sapDlgDbg.delete(id); }
}
function sapDropDialogWatch(wc) {
  if (!wc || wc.isDestroyed()) return;
  const rec = _sapDlgDbg.get(wc.id);
  if (!rec) return;
  _sapDlgDbg.delete(wc.id);
  try { wc.debugger.sendCommand('Page.disable').catch(() => {}); } catch (_) {}
  if (rec.attachedHere) {
    // 若 wheel/click/mobile 还记账着这份 attach，则只关 Page 域不 detach
    if (!_sapMobileDbg.has(wc.id) && !_sapInputDbg.has(wc.id)) {
      try { wc.debugger.detach(); } catch (_) {}
    }
  }
}
function sapReconcileDialogWatch() {
  const pol = global.browserPolicy || {};
  const want = pol.enabled !== false && pol.jsDialog !== 'ask';
  try {
    webContents.getAllWebContents().forEach((wc) => {
      try {
        if (!wc || wc.isDestroyed() || !wc.getType || wc.getType() !== 'webview') return;
        if (want) { if (!_sapDlgDbg.has(wc.id)) sapEnsureDialogWatch(wc); }
        else if (_sapDlgDbg.has(wc.id)) sapDropDialogWatch(wc);
      } catch (_) {}
    });
  } catch (_) {}
}

module.exports = { _policyLog, _policyNote, _sapUniquePath, _sapMobileDbg,
               _sapInputDbg, _sapDlgDbg, sapWatchDetach, sapResetEmulation, sapHostTouchClear,
               sapEnsureDialogWatch, sapDropDialogWatch, sapReconcileDialogWatch }
