/* S166: 游戏 HUD 胶囊层（灵动岛 overlay 顶层独立模块，零依赖，不与 island-app 交互）
 * 观战线：消费 notification_center 的 {type:'notification'} ws 广播。
 * 配置：localStorage 'sapHudCfg'（与主窗口同源共享，设置卡写入后 storage 事件热应用）。 */
(function () {
  'use strict';

  var CFG_KEY = 'sapHudCfg';
  var DEFAULTS = {
    enabled: true,        // HUD 总开关（关=不渲染本层）
    capsule: true,        // 胶囊模式：折叠圆点+角标；关=完整气泡
    position: 'se',       // nw|ne|sw|se|n|s
    dim: true,            // 空闲深隐
    idleMs: 5000,         // 空闲判定
    opacity: 0.9,         // 活跃不透明度
    dimOpacity: 0.1,      // 空闲不透明度
    expandDur: 6000,      // 非胶囊气泡驻留
    approvalExpand: true, // 胶囊模式下审批类仍展开
    show: { approval: true, generation: true, bot: true, error: true, system: false }
  };
  var ICONS = { approval: 'fa-triangle-exclamation', generation: 'fa-wand-magic-sparkles', bot: 'fa-comment-dots', error: 'fa-circle-exclamation', system: 'fa-bell' };
  var POS = ['nw', 'ne', 'sw', 'se', 'n', 's'];

  function loadCfg() {
    var cfg = {};
    for (var k in DEFAULTS) { cfg[k] = DEFAULTS[k]; }
    try {
      var raw = localStorage.getItem(CFG_KEY);
      if (raw) {
        var u = JSON.parse(raw) || {};
        for (var k2 in u) {
          if (k2 in DEFAULTS) {
            if (k2 === 'show' && u.show && typeof u.show === 'object') { cfg.show = Object.assign({}, DEFAULTS.show, u.show); }
            else if (k2 === 'position') { if (POS.indexOf(u.position) >= 0) cfg.position = u.position; }
            else if (typeof u[k2] === typeof DEFAULTS[k2]) cfg[k2] = u[k2];
          }
        }
      }
    } catch (e) {}
    if (typeof cfg.idleMs !== 'number' || cfg.idleMs < 1000) cfg.idleMs = 5000;
    if (typeof cfg.expandDur !== 'number' || cfg.expandDur < 1000) cfg.expandDur = 6000;
    return cfg;
  }

  var cfg = loadCfg();
  var layer = null, capsule = null, badge = null, bubble = null, bubbleText = null, bubbleIcon = null;
  var unread = 0, idleTimer = null, expandTimer = null, ws = null, wsRetry = null;

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function build() {
    layer = el('div'); layer.id = 'sap-hud-layer';
    capsule = el('div', 'sap-hud-capsule hud-pos-' + cfg.position);
    capsule.appendChild(el('span', 'hud-badge', '0'));
    badge = capsule.querySelector('.hud-badge');
    bubble = el('div', 'sap-hud-bubble hud-pos-' + cfg.position);
    bubbleIcon = el('i', 'hud-icon fa ' + ICONS.system);
    bubbleText = el('div', 'hud-text', '');
    bubble.appendChild(bubbleIcon); bubble.appendChild(bubbleText);
    layer.appendChild(capsule); layer.appendChild(bubble);
    (document.body || document.documentElement).appendChild(layer);
    applyCfg();
    wake();
  }

  function applyCfg() {
    if (!layer) return;
    if (!cfg.enabled) { layer.classList.add('hud-hidden'); teardownWS(); return; }
    layer.classList.remove('hud-hidden');
    layer.style.opacity = String(cfg.opacity);
    layer.classList.remove('hud-dim');
    capsule.className = 'sap-hud-capsule hud-pos-' + cfg.position + (unread > 0 ? ' hud-has-unread' : '');
    capsule.style.display = cfg.capsule ? '' : 'none';
    bubble.className = 'sap-hud-bubble hud-pos-' + cfg.position;
    startIdle(); ensureWS();
  }

  function wake() {
    if (!layer || !cfg.enabled) return;
    layer.style.opacity = String(cfg.opacity);
    layer.classList.remove('hud-dim');
    startIdle();
  }

  function startIdle() {
    if (idleTimer) clearTimeout(idleTimer);
    if (!cfg.dim) return;
    idleTimer = setTimeout(function () {
      if (layer && cfg.enabled && cfg.dim) {
        layer.classList.add('hud-dim');
        layer.style.opacity = String(cfg.dimOpacity);
      }
    }, cfg.idleMs);
  }

  function toggleCapsule() {
    cfg.capsule = !cfg.capsule;
    try { localStorage.setItem(CFG_KEY, JSON.stringify(cfg)); } catch (e) {}
    toast(cfg.capsule ? 'HUD 胶囊模式' : 'HUD 完整模式');
    if (!cfg.capsule && bubble && bubbleText.textContent) expandBubble(lastIcon, lastText, cfg.expandDur);
    wake();
  }
  var lastIcon = ICONS.system, lastText = '';

  function toast(text) {
    var t = el('div', 'sap-hud-toast', text);
    layer.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('hud-show'); });
    setTimeout(function () { t.classList.remove('hud-show'); setTimeout(function () { t.remove(); }, 400); }, 1800);
  }

  function expandBubble(icon, text, dur) {
    bubbleIcon.className = 'hud-icon fa ' + icon;
    bubbleText.textContent = text;
    bubble.classList.toggle('hud-approval', icon === ICONS.approval);
    bubble.classList.add('hud-show');
    if (expandTimer) clearTimeout(expandTimer);
    expandTimer = setTimeout(function () { bubble.classList.remove('hud-show'); }, dur);
  }

  function onNotify(rec) {
    if (!cfg.enabled || !layer) return;
    var cat = rec.category || 'system';
    if (!cfg.show[cat]) return;
    var text = (rec.msg || '').slice(0, 200);
    var icon = ICONS[cat] || ICONS.system;
    lastIcon = icon; lastText = text;
    wake();
    if (cfg.capsule) {
      unread += 1;
      badge.textContent = unread > 99 ? '99+' : String(unread);
      capsule.classList.add('hud-has-unread');
      capsule.classList.toggle('hud-alert', cat === 'approval' || rec.level === 'error');
      if (cat === 'approval' && cfg.approvalExpand) expandBubble(icon, text, cfg.expandDur);
    } else {
      expandBubble(icon, text, cfg.expandDur);
    }
  }

  function clearUnread() {
    unread = 0;
    if (badge) { badge.textContent = '0'; }
    if (capsule) { capsule.classList.remove('hud-has-unread', 'hud-alert'); }
  }

  function ensureWS() {
    if (ws || !cfg.enabled) return;
    var open = function () {
      var wsUrl = (location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + location.host + '/ws';
      var tok = window.__SAP_TOKEN || '';
      try { ws = new WebSocket(tok ? wsUrl + '?sap_token=' + encodeURIComponent(tok) : wsUrl); } catch (e) { return; }
      ws.onmessage = function (e) {
        try {
          var d = JSON.parse(e.data);
          if (d && d.type === 'notification' && d.data) onNotify(d.data);
        } catch (err) {}
      };
      ws.onclose = function () {
        ws = null;
        if (cfg.enabled && !wsRetry) wsRetry = setTimeout(function () { wsRetry = null; ensureWS(); }, 5000);
      };
      ws.onerror = function () { try { ws.close(); } catch (e) {} };
    };
    if (window.__SAP_READY && window.__SAP_READY.then) { window.__SAP_READY.then(open); } else { open(); }
  }

  function teardownWS() {
    if (wsRetry) { clearTimeout(wsRetry); wsRetry = null; }
    if (ws) { try { ws.onclose = null; ws.close(); } catch (e) {} ws = null; }
  }

  window.addEventListener('storage', function (e) {
    if (e.key === CFG_KEY) { cfg = loadCfg(); applyCfg(); }
  });

  function bindSettings() {
    // 主窗口（chat.html）系统设置页：卡片控件 ↔ localStorage 双向，岛页经 storage 事件热应用
    function $id(x) { return document.getElementById(x); }
    function fill() {
      var c = loadCfg();
      if (!$id('sap-hud-enabled')) return;
      $id('sap-hud-enabled').checked = !!c.enabled;
      $id('sap-hud-capsule').checked = !!c.capsule;
      $id('sap-hud-dim').checked = !!c.dim;
      $id('sap-hud-pos').value = c.position;
      Array.prototype.forEach.call(document.querySelectorAll('.sap-hud-cat'), function (n) {
        n.checked = !!(c.show && c.show[n.getAttribute('data-cat')]);
      });
    }
    document.addEventListener('change', function (e) {
      var t = e.target;
      if (!t || !t.id || t.id.indexOf('sap-hud-') !== 0) return;
      var c = loadCfg();
      if (t.id === 'sap-hud-pos') { c.position = t.value; }
      else if (t.classList.contains('sap-hud-cat')) { c.show[t.getAttribute('data-cat')] = !!t.checked; }
      else if (t.id === 'sap-hud-enabled') { c.enabled = !!t.checked; }
      else if (t.id === 'sap-hud-capsule') { c.capsule = !!t.checked; }
      else if (t.id === 'sap-hud-dim') { c.dim = !!t.checked; }
      else { return; }
      try { localStorage.setItem(CFG_KEY, JSON.stringify(c)); } catch (e2) {}
    });
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', fill); } else { fill(); }
    var mo = new MutationObserver(function () { if ($id('sap-hud-enabled')) { fill(); mo.disconnect(); } });
    mo.observe(document.body, { childList: true, subtree: true });
  }

  function init() {
    var isIsland = location.pathname.indexOf('island') >= 0;
    if (!isIsland) { bindSettings(); return; }
    if (!window.electron || !window.electron.ipcRenderer || typeof window.electron.ipcRenderer.on !== 'function') {
      // 无 preload 环境（纯浏览器）：降级为快捷键切换
      window.addEventListener('keydown', function (e) {
        if (e.altKey && e.shiftKey && (e.code === 'KeyH')) toggleCapsule();
      });
    } else {
      window.electron.ipcRenderer.on('hud-toggle-capsule', toggleCapsule);
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { if (cfg.enabled) build(); });
    } else if (cfg.enabled) { build(); }
  }

  init();
})();
