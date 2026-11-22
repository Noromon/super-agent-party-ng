/* S166: 游戏 HUD 胶囊层（灵动岛 overlay 顶层独立模块，零依赖，不与 island-app 交互）
 * 观战线：消费 notification_center 的 {type:'notification'} ws 广播。
 * 配置：localStorage 'sapHudCfg'（与主窗口同源共享，设置卡写入后 storage 事件热应用）。 */
(function () {
  'use strict';

  var CFG_KEY = 'sapHudCfg';
  // S272：pop=消息送达弹出气泡开关（取代 approvalExpand 特殊化）；
  // holdMs=每条气泡送达后保留时长（到时淡出）；stackMax=同屏最大条数（超限立即撤最老的）。
  var DEFAULTS = {
    enabled: true,        // HUD 总开关（关=不渲染本层）
    capsule: true,        // 胶囊模式：折叠圆点+角标；关=完整气泡
    position: 'se',       // nw|ne|sw|se|n|s
    dim: false,           // 空闲深隐（S167：默认关，深隐后仅剩 10% 圆点几乎不可见，改为可选）
    idleMs: 5000,         // 空闲判定
    opacity: 0.9,         // 活跃不透明度
    dimOpacity: 0.1,      // 空闲不透明度
    expandDur: 6000,      // （S272 起弃用，保留兼容旧配置）
    approvalExpand: true, // （S272 起弃用：pop 统一接管弹出）
    pop: true,            // 消息送达弹出气泡（胶囊模式下也弹）
    holdMs: 8000,         // 每条气泡保留时长（淡出前）
    stackMax: 3,          // 同屏最大条数，超限撤最老（不等保留到期）
    badge: true,          // S274：数字角标显示与否（关=胶囊纯净，审批脉冲仍在）
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
    if (typeof cfg.holdMs !== 'number' || cfg.holdMs < 2000) cfg.holdMs = 8000;
    if (cfg.holdMs > 120000) cfg.holdMs = 120000;
    if (typeof cfg.stackMax !== 'number' || cfg.stackMax < 1) cfg.stackMax = 3;
    if (cfg.stackMax > 8) cfg.stackMax = 8;
    cfg.stackMax = Math.round(cfg.stackMax);
    return cfg;
  }

  var cfg = loadCfg();
  var layer = null, capsule = null, badge = null, stack = null;
  var unread = 0, idleTimer = null, ws = null, wsRetry = null, wsOpening = false;
  var panel = null, overCapsule = false; // S274：历史面板与鼠标持握状态
  // S282：持握状态机——三源(panel/domOver/pollOver)并联，250ms 迟滞释放。
  // 穿透窗下 mouseenter/click 可能整体失灵（本次事故根因），故不赌任何单一事件：
  // DOM mousemove+elementFromPoint 为主，OS 光标轮询兜底，两路都断也不影响彼此。
  var ISLAND_HOST = typeof location !== 'undefined' && String(location.pathname || '').indexOf('island') >= 0;
  var holdActive = false, domOver = false, pollOver = false, pollTrusted = false;
  var holdReleaseT = null, pollTimer = null;
  // S285：可观测性——rev 用于诊断台/演示气泡证实实际运行的代码版本；pollTicks 证明轮询活着
  var HUD_REV = 'S291';
  var pollTicks = 0, dbgLogged = false;
  // S289：物理点击通道——高 DPI 机 Blink 内部鼠标坐标错位时 DOM 点击命中整体失效，
  // 持握期间拉取后端全局左键态，配合 OS 光标真值合成点击（原生点击可达时自动让位）。
  var lastLbtn = false, lbtnDownTs = 0, msFail = 0, msMuteUntil = 0;
  var lastNativeClickTs = 0, nativeEnterTs = 0, lastEv = null, lastHudEvLog = 0;
  var lastPollP = null, panelCloseEl = null;
  // S286：高 DPI（如 125%）下 OS 光标返回物理像素，与 CSS 坐标错位一个 dpr 倍——
  // 所有命中判定先按原值测，越出视口时再除以 devicePixelRatio 复测（自校准，不猜单位）。
  function dpr() { var d = window.devicePixelRatio || 1; return d > 0 ? d : 1; }
  function inVp(x, y) { return x >= 0 && y >= 0 && x < (window.innerWidth || Infinity) && y < (window.innerHeight || Infinity); }
  // S273：已处理通知 id 环形去重——就算未来再出现任何双投递路径，也只渲染一次
  var seenIds = [], seenSet = {};
  // S287：气泡溢出改入 FIFO 队列（不再撤展示中的旧条），槽位空出自动补位；上限 50 丢最老
  var popQueue = [], POP_QMAX = 50;
  function isDup(id) {
    if (!id) return false;
    if (seenSet[id]) return true;
    seenSet[id] = 1; seenIds.push(id);
    while (seenIds.length > 64) { delete seenSet[seenIds.shift()]; }
    return false;
  }

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
    stack = el('div', 'sap-hud-stack hud-pos-' + cfg.position);
    layer.appendChild(capsule); layer.appendChild(stack);
    // S274：胶囊可点击展开历史面板——岛窗整体点击穿透，仅胶囊/面板吃鼠标；
    // S282：持握改由状态机裁决（mouseenter 仅作加速器，不再独任解锁职责）。
    capsule.addEventListener('mouseenter', function () { nativeEnterTs = Date.now(); overCapsule = true; domOver = true; updateHold(); });
    capsule.addEventListener('mouseleave', function () { overCapsule = false; if (!panel) { domOver = false; } updateHold(); });
    capsule.addEventListener('click', function () { lastNativeClickTs = Date.now(); togglePanel(); });
    // S289：捕获层只记账不打印（O(1)），[HudEv] 裁决 Blink 事件送达形态时用
    document.addEventListener('mousemove', function (e) {
      if (!e) return;
      var t = e.target;
      lastEv = { x: e.clientX, y: e.clientY, t: Date.now(), tgt: (t && (t.className || t.tagName)) || '' };
    }, true);
    // S291：面板外原生点击=一点即收（健康机通道；故障机原生不达时由物理路由同语义兜底）
    document.addEventListener('click', function (e) {
      if (!panel) return;
      var n = e && e.target;
      while (n) { if (n === panel || n === capsule) break; n = n.parentNode; }
      if (n === panel || n === capsule) return; // 面板内（含×）/胶囊交给各自处理器
      closePanel();
    }, true);
    (document.body || document.documentElement).appendChild(layer);
    document.addEventListener('mousemove', onDocMove);
    startPoll();
    applyCfg();
    wake();
  }

  function mergeCfg(u) {
    // S170：ipc 主通道推送的配置合并（主进程持久化值优先于本地兜底）
    if (!u || typeof u !== 'object') return;
    for (var k in u) {
      if (!(k in DEFAULTS)) continue;
      if (k === 'show' && u.show && typeof u.show === 'object') cfg.show = Object.assign({}, cfg.show, u.show);
      else if (k === 'position') { if (POS.indexOf(u.position) >= 0) cfg.position = u.position; }
      else if (typeof u[k] === typeof DEFAULTS[k]) cfg[k] = u[k];
    }
    if (typeof cfg.holdMs !== 'number' || cfg.holdMs < 2000) cfg.holdMs = 8000;
    if (cfg.holdMs > 120000) cfg.holdMs = 120000;
    if (typeof cfg.stackMax !== 'number' || cfg.stackMax < 1) cfg.stackMax = 3;
    if (cfg.stackMax > 8) cfg.stackMax = 8;
    cfg.stackMax = Math.round(cfg.stackMax);
    if (cfg.enabled && !layer) build();
    applyCfg();
    wake();
  }

  function applyCfg() {
    if (!layer) return;
    if (!cfg.enabled) { closePanel(); stopPoll(); layer.classList.add('hud-hidden'); teardownWS(); return; }
    layer.classList.remove('hud-hidden');
    layer.style.opacity = String(cfg.opacity);
    layer.classList.remove('hud-dim');
    capsule.className = 'sap-hud-capsule hud-pos-' + cfg.position
      + (unread > 0 ? ' hud-has-unread' : '') + (cfg.badge ? '' : ' hud-no-badge');
    capsule.style.display = cfg.capsule ? '' : 'none';
    stack.className = 'sap-hud-stack hud-pos-' + cfg.position + (cfg.capsule ? '' : ' hud-solo');
    trimStack(); // 远程把 stackMax 调小时即时收敛
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
    applyCfg();
    wake();
  }

  function toast(text) {
    var t = el('div', 'sap-hud-toast', text);
    layer.appendChild(t);
    requestAnimationFrame(function () { t.classList.add('hud-show'); });
    setTimeout(function () { t.classList.remove('hud-show'); setTimeout(function () { t.remove(); }, 400); }, 1800);
  }

  // ---- S272：消息气泡栈 ----
  // 最新条目紧邻胶囊点、旧条目向外排（n* 方位向下排=最新在上，s* 方位向上排=最新在下，
  // 由 hud-s-down / hud-s-up 的 flex-direction 决定）；每条保留 holdMs 后淡出；
  // 同屏条数超 stackMax 时最老一条立即提前撤下（不等保留到期）。
  function detachBubble(node, reason) {
    if (!node || node.__gone) return;
    node.__gone = true;
    if (node.__t) clearTimeout(node.__t);
    node.classList.remove('hud-show');
    setTimeout(function () { if (node.parentNode) node.parentNode.removeChild(node); }, 450);
    try { console.info('[HudPop] detach ' + (reason || '?') + ' age=' + (node.__birth ? Math.round((Date.now() - node.__birth) / 100) / 10 : -1) + 's'); } catch (e) {}
    pumpQueue(); // S287：live 计数已排除 __gone，槽位即时释放即补位
  }

  // S287：保留时长是承诺——溢出不再撤下展示中的气泡，改由队列等位补发
  function pumpQueue() {
    while (popQueue.length && stack) {
      var live = 0;
      for (var i = 0; i < stack.children.length; i++) if (!stack.children[i].__gone) live++;
      if (live >= cfg.stackMax) break;
      renderBubble(popQueue.shift());
    }
  }

  function trimStack() {
    if (!stack) return;
    // DOM 顺序即时间序（appendChild 新入）——最老恒为首个"未消亡"节点；
    // 淡出中的节点（__gone）450ms 后才真正移出 DOM，计数须排除，否则本循环永不收敛
    // S287：本函数现仅服务于「远程调小 stackMax」的收敛；推送溢出走队列不进这里
    var guard = 0;
    while (guard++ < 16) {
      var live = 0, oldest = null, i;
      for (i = 0; i < stack.children.length; i++) {
        var ch = stack.children[i];
        if (ch.__gone) continue;
        live++;
        if (!oldest) oldest = ch;
      }
      if (live <= cfg.stackMax || !oldest) break;
      detachBubble(oldest, 'trim');
    }
  }

  function renderBubble(item) {
    if (!stack) return;
    var icon = item.icon, text = item.text;
    var b = el('div', 'sap-hud-bubble' + (icon === ICONS.approval ? ' hud-approval' : '') + ' hud-corner-' + cfg.position);
    var i = el('i', 'hud-icon fa ' + icon);
    var t = el('div', 'hud-text', '');
    t.textContent = text;
    b.appendChild(i); b.appendChild(t);
    stack.appendChild(b);
    b.__birth = Date.now(); // S287：日志显示真实展示时长
    requestAnimationFrame(function () { b.classList.add('hud-show'); });
    trimStack();
    var hold = item.hold || cfg.holdMs;
    b.__t = setTimeout(function () { detachBubble(b, 'timeout'); }, hold);
    try {
      var n = 0;
      for (var q2 = 0; q2 < stack.children.length; q2++) if (!stack.children[q2].__gone) n++;
      console.info('[HudPop] push hold=' + (hold / 1000) + 's live=' + n + '/' + cfg.stackMax);
    } catch (e) {}
  }

  function pushBubble(icon, text, holdOverride, force) {
    if (!stack) return;
    var live = 0;
    for (var i2 = 0; i2 < stack.children.length; i2++) if (!stack.children[i2].__gone) live++;
    if (!force && live >= cfg.stackMax) {
      popQueue.push({ icon: icon, text: text, hold: holdOverride });
      while (popQueue.length > POP_QMAX) popQueue.shift();
      try { console.info('[HudPop] queue live=' + live + '/' + cfg.stackMax + ' q=' + popQueue.length); } catch (e) {}
      return;
    }
    renderBubble({ icon: icon, text: text, hold: holdOverride });
  }

  function onNotify(rec) {
    if (!cfg.enabled || !layer) return;
    if (isDup(rec && rec.id)) return; // S273：同一记录只消费一次（双投递兜底）
    var cat = rec.category || 'system';
    if (!cfg.show[cat]) return;
    var text = (rec.msg || '').slice(0, 200);
    var icon = ICONS[cat] || ICONS.system;
    wake();
    if (cfg.capsule) {
      unread += 1;
      badge.textContent = unread > 99 ? '99+' : String(unread);
      capsule.classList.add('hud-has-unread');
      capsule.classList.toggle('hud-alert', cat === 'approval' || rec.level === 'error');
    }
    // S272：弹出不再区分胶囊/完整模式，也不给审批开特例——由 pop 统一开关
    if (cfg.pop) pushBubble(icon, text);
  }

  function clearUnread() {
    unread = 0;
    if (badge) { badge.textContent = '0'; }
    if (capsule) { capsule.classList.remove('hud-has-unread', 'hud-alert'); }
  }

  // ---- S274：历史消息面板；S282：鼠标持握状态机 + 光标轮询兜底 ----
  function hudHoldMouse(on) {
    if (!ISLAND_HOST) return; // 主窗(index.html 同源加载)整窗天然吃鼠标，绝不允许碰穿透 API
    window.__sapHudHoldMouse = !!on;
    try { console.info('[HudHold] ' + (on ? 'ON' : 'OFF') + ' dom=' + domOver + ' poll=' + pollOver + ' panel=' + !!panel); } catch (e) {}
    var api = window.electronAPI || {};
    if (!api.setIgnoreMouseEvents) return;
    try {
      if (on) api.setIgnoreMouseEvents(false);
      else api.setIgnoreMouseEvents(true, { forward: true });
    } catch (e) {}
  }

  function hudHoldWanted() { return !!panel || domOver || pollOver; }

  function updateHold() {
    if (hudHoldWanted()) {
      if (holdReleaseT) { clearTimeout(holdReleaseT); holdReleaseT = null; }
      if (!holdActive) { holdActive = true; hudHoldMouse(true); }
      return;
    }
    if (holdActive && !holdReleaseT) {
      holdReleaseT = setTimeout(function () {
        holdReleaseT = null;
        if (!hudHoldWanted() && holdActive) { holdActive = false; hudHoldMouse(false); }
      }, 250); // 迟滞：指针沿边缘抖动时不反复开关穿透
    }
  }

  function hitHud(hit) {
    var n = hit;
    while (n) {
      if (n === capsule || (panel && n === panel)) return true;
      n = n.parentNode;
    }
    return false;
  }

  function onDocMove(e) {
    if (!capsule || !e) return;
    var over = false;
    try {
      if (document.elementFromPoint) {
        var x = e.clientX, y = e.clientY;
        over = hitHud(document.elementFromPoint(x, y));
        // S286：穿透转发事件的坐标在高 DPI 下可能带物理像素值，越界时除以 dpr 复判
        if (!over && !inVp(x, y)) over = hitHud(document.elementFromPoint(x / dpr(), y / dpr()));
      }
    } catch (er) {}
    if (over !== domOver) { domOver = over; overCapsule = over || !!panel; updateHold(); }
  }

  function inRect(x, y, r, pad) {
    if (!r || typeof r.left !== 'number') return false;
    pad = pad || 0;
    return x >= r.left - pad && x <= r.right + pad && y >= r.top - pad && y <= r.bottom + pad;
  }

  function hitPoint(x, y) {
    try {
      if (inRect(x, y, capsule.getBoundingClientRect && capsule.getBoundingClientRect(), 8)) return true;
      return !!panel && inRect(x, y, panel.getBoundingClientRect && panel.getBoundingClientRect(), 8);
    } catch (e) { return false; }
  }

  function startPoll() {
    if (pollTimer || !ISLAND_HOST) return;
    // OS 光标真相同路：即便合成事件整体失灵（本次事故形态），也能解锁首击。
    pollTimer = setInterval(function () {
      pollTicks++;
      var api = window.electronAPI || {};
      if (!api.getCursorScreenPoint || typeof window.screenX !== 'number') return;
      Promise.resolve(api.getCursorScreenPoint()).then(function (p) {
        if (!capsule || !p || typeof p.x !== 'number') return;
        var hit = false;
        try {
          var x = p.x - window.screenX, y = p.y - window.screenY;
          hit = hitPoint(x, y);
          if (!hit && !inVp(x, y)) hit = hitPoint(x / dpr(), y / dpr()); // S286：物理像素→CSS 自校准
          if (!dbgLogged && Math.abs(x - (window.innerWidth || 0)) < 400 && Math.abs(y - (window.innerHeight || 0)) < 400) {
            dbgLogged = true; // S286：角落首访留一行原始坐标底账（现场对质坐标系问题用）
            console.info('[HudDbg] raw=' + p.x + ',' + p.y + ' local=' + Math.round(x) + ',' + Math.round(y) +
              ' dpr=' + dpr() + ' inner=' + window.innerWidth + 'x' + window.innerHeight + ' scr=' + window.screenX + ',' + window.screenY);
          }
        } catch (e) {}
        if (hit) pollTrusted = true; // 换算命中=本窗坐标映射可信（含 S286 缩放候选）
        if (hit !== pollOver) { pollOver = hit; updateHold(); }
        if (!hit && pollTrusted && !panel && domOver) { domOver = false; updateHold(); } // 可信后 OS 真相可纠正 DOM 态
        // S289：OS 光标在圈上=手型光标兜底（Blink 视口外查询回退根元素样式）；
        // 持握但无原生 enter → [HudEv] 记录事件送达形态（错位送达 vs 裁剪丢弃）留证
        lastPollP = { x: x, y: y };
        try { document.documentElement.style.cursor = hit ? 'pointer' : ''; } catch (e4) {}
        if (hit && holdActive && lastEv && (Date.now() - nativeEnterTs > 2000) && (Date.now() - lastHudEvLog > 2000)) {
          lastHudEvLog = Date.now();
          console.info('[HudEv] no-native-enter lastEv=' + lastEv.x + ',' + lastEv.y +
            ' tgt=' + String(lastEv.tgt).slice(0, 40) + ' dpr=' + dpr() + ' inner=' + window.innerWidth + 'x' + window.innerHeight);
        }
      }).catch(function () {});
      if (holdActive) pollMouseState(); else { lastLbtn = false; lbtnDownTs = 0; }
    }, 150);
  }

  // ---- S289：物理点击通道（后端全局左键态 + OS 光标真值命中判定） ----
  function pollMouseState() {
    if (Date.now() < msMuteUntil) return;
    Promise.resolve(fetch('/api/mouse-state', { credentials: 'same-origin' })).then(function (r) {
      if (!r || !r.ok) throw new Error('http');
      return r.json();
    }).then(function (j) {
      msFail = 0;
      var down = !!(j && j.lbtn);
      var press = !!(j && j.lpress); // S291：系统级按下边沿——采样间隔内的快击也不丢
      if (press && !down) {
        lbtnDownTs = 0;              // 已松开：释放沿不再对同一次按键补发
        routePhysicalClick(80);      // 快击直达路由（80ms 仅作原生事件落账窗）
      } else if (down && !lastLbtn) {
        lbtnDownTs = Date.now();
      } else if (!down && lastLbtn && lbtnDownTs) {
        var held = Date.now() - lbtnDownTs;
        lbtnDownTs = 0;
        if (held <= 1500) routePhysicalClick(); // 长按/拖拽不算 HUD 点击
      }
      lastLbtn = down;
    }).catch(function () {
      msFail++;
      if (msFail >= 5) { msFail = 0; msMuteUntil = Date.now() + 5000; } // 旧后端无端点=静默重试
    });
  }

  function routePhysicalClick(settleMs) {
    setTimeout(function () {
      // 让位判据：原生 click 通道可达时（正常 DPI 机器）Blink 早已完成命中，勿双触发
      if (Date.now() - lastNativeClickTs < 450 || !holdActive || !lastPollP) return;
      var p = lastPollP, d = dpr();
      var inBoth = function (el) {
        if (!el || !el.getBoundingClientRect) return false;
        var r = el.getBoundingClientRect();
        return inRect(p.x, p.y, r, 10) || inRect(p.x / d, p.y / d, r, 10);
      };
      if (inBoth(capsule)) { togglePanel(); return; }
      if (!panel) return; // 面板不在场：外部点击本就不属于 HUD，无状态可改
      if (inBoth(panelCloseEl)) { closePanel(); return; }
      if (!inBoth(panel)) closePanel(); // S291：面板外点击=一点即收（该点击被透明层吞掉=全屏 overlay 固有）
    }, settleMs || 120);
  }

  function stopPoll() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    pollOver = false; pollTrusted = false; lastLbtn = false; lbtnDownTs = 0; lastPollP = null;
  }

  function fmtTime(ts) {
    try {
      var d = new Date(ts * 1000), p = function (x) { return (x < 10 ? '0' : '') + x; };
      return p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes());
    } catch (e) { return ''; }
  }

  function closePanel() {
    if (!panel) return;
    var p = panel; panel = null; panelCloseEl = null;
    p.classList.remove('hud-show');
    setTimeout(function () { if (p.parentNode) p.parentNode.removeChild(p); }, 300);
    // S282：关面板后由 mousemove/轮询重新裁决在位性；250ms 迟滞内可无感点回胶囊
    domOver = false; overCapsule = false; updateHold();
  }

  function togglePanel() {
    if (panel) { closePanel(); return; }
    panel = el('div', 'sap-hud-panel hud-pos-' + cfg.position + (cfg.capsule ? '' : ' hud-solo'));
    var head = el('div', 'hud-p-head');
    var hi = el('i', 'fa fa-clock-rotate-left');
    var ht = el('span', '', '历史消息');
    var sp = el('span', 'hud-p-spacer');
    var cl = el('span', 'hud-p-close', '×');
    cl.addEventListener('click', function (ev) { if (ev && ev.stopPropagation) ev.stopPropagation(); lastNativeClickTs = Date.now(); closePanel(); });
    head.appendChild(hi); head.appendChild(ht); head.appendChild(sp); cl && head.appendChild(cl);
    panelCloseEl = cl; // S289：物理通道需要关闭按钮矩形做命中判定
    var list = el('div', 'hud-p-list', '<div class="hud-p-empty">加载中…</div>');
    panel.appendChild(head); panel.appendChild(list);
    panel.addEventListener('mouseenter', function () { domOver = true; updateHold(); });
    // S282：面板在场=状态机硬持握（mouseleave 不再需要续持）
    layer.appendChild(panel);
    updateHold();
    requestAnimationFrame(function () { panel && panel.classList.add('hud-show'); });
    loadPanelList(list);
  }

  async function loadPanelList(list) {
    var myPanel = panel;
    try {
      var r = await fetch('/api/notifications?limit=50', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      var d = await r.json();
      if (!panel || panel !== myPanel) return; // 期间被关掉/重开
      var items = (d && Array.isArray(d.items)) ? d.items : [];
      list.innerHTML = '';
      if (!items.length) {
        list.appendChild(el('div', 'hud-p-empty', '暂无历史消息'));
        return;
      }
      items.forEach(function (it) {
        var row = el('div', 'hud-p-item' + (it.level === 'error' ? ' hud-p-err' : ''));
        row.appendChild(el('i', 'hud-icon fa ' + (ICONS[it.category] || ICONS.system)));
        var wrap = el('div', 'hud-p-body');
        var tx = el('div', 'hud-p-text', '');
        tx.textContent = String(it.msg || '').slice(0, 300);
        wrap.appendChild(tx);
        wrap.appendChild(el('div', 'hud-p-time', fmtTime(it.ts)));
        row.appendChild(wrap);
        list.appendChild(row);
      });
      var ids = items.map(function (it) { return it.id; }).filter(Boolean);
      if (ids.length) {
        fetch('/api/notifications/read', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'same-origin',
          body: JSON.stringify({ ids: ids }),
        }).catch(function () {});
      }
      clearUnread(); // 打开面板=用户已见，本地计数清零（服务端也已 mark_read）
    } catch (e) {
      if (!panel || panel !== myPanel) return;
      list.innerHTML = '';
      list.appendChild(el('div', 'hud-p-empty', '加载失败：' + String((e && e.message) || e)));
    }
  }

  function ensureWS() {
    if (ws || wsOpening || !cfg.enabled) return;
    // S273：__SAP_READY 未 resolve 前 ws 恒 null——旧版守卫形同虚设：
    // build 与 getHudCfg→mergeCfg 各排一个 open，token 到手双双建连，
    // 孤儿 socket 的 onmessage 仍指向 onNotify → 每条通知弹两次（重复气泡根因）。
    wsOpening = true;
    var open = function () {
      wsOpening = false;
      if (ws) return;
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
        if (ws !== this) { try { this.close(); } catch (e2) {} return; } // 陈旧 socket 自灭，别碰现行连接
        ws = null;
        if (cfg.enabled && !wsRetry) wsRetry = setTimeout(function () { wsRetry = null; ensureWS(); }, 5000);
      };
      ws.onerror = function () { try { ws.close(); } catch (e) {} };
    };
    if (window.__SAP_READY && window.__SAP_READY.then) {
      window.__SAP_READY.then(open, open); // token 获取失败也照常直连（旧行为）
    } else { open(); }
  }

  function teardownWS() {
    if (wsRetry) { clearTimeout(wsRetry); wsRetry = null; }
    if (ws) { try { ws.onclose = null; ws.close(); } catch (e) {} ws = null; }
  }

  window.addEventListener('storage', function (e) {
    if (e.key === CFG_KEY) { cfg = loadCfg(); applyCfg(); }
  });

  function showDemo() {
    if (!layer) { cfg.enabled = true; build(); }
    wake();
    pushBubble(ICONS.system, 'HUD 演示气泡：新通知会像这样弹出（保留期满淡出；同屏满了新消息自动排队补位）', 8000, true);
    toast('HUD rev ' + HUD_REV); // S285：toast 直接暴露岛页实际运行版本（旧缓存一眼识破）
  }

  var KEYMAP = { 'sap-hud-enabled': 'enabled', 'sap-hud-capsule': 'capsule', 'sap-hud-dim': 'dim', 'sap-hud-pop': 'pop', 'sap-hud-badge': 'badge' };

  // S272：数值型控件（保留秒数 / 同屏最大条数）单独钳制读写
  var NUMCFG = {
    'sap-hud-hold': { key: 'holdMs', min: 2, max: 120, def: 8 },      // 秒 ↔ holdMs
    'sap-hud-stack': { key: 'stackMax', min: 1, max: 8, def: 3 }
  };
  function numToCfg(id, raw) {
    var spec = NUMCFG[id]; var v = parseInt(raw, 10);
    if (isNaN(v)) v = spec.def;
    v = Math.max(spec.min, Math.min(spec.max, v));
    return spec.key === 'holdMs' ? v * 1000 : v;
  }
  function cfgToNum(id, from) {
    var spec = NUMCFG[id];
    var v = spec.key === 'holdMs' ? Math.round((from[spec.key] || spec.def * 1000) / 1000) : from[spec.key];
    return Math.max(spec.min, Math.min(spec.max, v || spec.def));
  }

  function bindSettings() {
    // 主窗口（chat.html）系统设置页：草稿模式 + 显式保存；保存后岛页经 storage 事件热应用
    var draft = loadCfg();
    var dirty = false;
    function $id(x) { return document.getElementById(x); }
    function status(txt, ok) {
      var s = $id('sap-hud-status');
      if (!s) return;
      s.textContent = txt;
      s.style.color = ok ? '#5bbf6b' : 'rgba(255,255,255,.55)';
    }
    function paint() {
      $id('sap-hud-enabled').checked = !!draft.enabled;
      $id('sap-hud-capsule').checked = !!draft.capsule;
      $id('sap-hud-dim').checked = !!draft.dim;
      if ($id('sap-hud-pop')) $id('sap-hud-pop').checked = !!draft.pop;
      if ($id('sap-hud-badge')) $id('sap-hud-badge').checked = draft.badge !== false;
      if ($id('sap-hud-hold')) $id('sap-hud-hold').value = cfgToNum('sap-hud-hold', draft);
      if ($id('sap-hud-stack')) $id('sap-hud-stack').value = cfgToNum('sap-hud-stack', draft);
      $id('sap-hud-pos').value = draft.position;
      Array.prototype.forEach.call(document.querySelectorAll('.sap-hud-cat'), function (n) {
        n.checked = !!(draft.show && draft.show[n.getAttribute('data-cat')]);
      });
    }
    function fill() {
      if (!$id('sap-hud-enabled')) return;
      if (dirty) return; // 有未保存草稿时不用存储值覆盖编辑
      draft = loadCfg();
      paint();
    }
    document.addEventListener('change', function (e) {
      var t = e.target;
      if (!t || !t.id || t.id.indexOf('sap-hud-') !== 0) return;
      if (t.id === 'sap-hud-save' || t.id === 'sap-hud-open' || t.id === 'sap-hud-reset') return;
      if (t.id === 'sap-hud-pos') { draft.position = t.value; }
      else if (t.classList.contains('sap-hud-cat')) { draft.show[t.getAttribute('data-cat')] = !!t.checked; }
      else if (NUMCFG[t.id]) { draft[NUMCFG[t.id].key] = numToCfg(t.id, t.value); }
      else if (KEYMAP[t.id]) { draft[KEYMAP[t.id]] = !!t.checked; }
      else { return; }
      dirty = true;
      status('有未保存的更改，点击「保存设置」生效');
    });
    document.addEventListener('click', function (e) {
      var t = e.target;
      while (t && t.id !== 'sap-hud-save' && t.id !== 'sap-hud-open' && t.id !== 'sap-hud-reset' && t.id !== 'sap-hud-diag') { t = t.parentElement; }
      if (!t) return;
      if (t.id === 'sap-hud-save') {
        try {
          localStorage.setItem(CFG_KEY, JSON.stringify(draft));
          if (window.electronAPI && window.electronAPI.publishHudCfg) window.electronAPI.publishHudCfg(draft);
          dirty = false;
          status('已保存 ✓（灵动岛侧即时生效）', true);
          setTimeout(function () { if (!dirty) status(''); }, 2500);
        } catch (e2) { status('保存失败：' + e2); }
      } else if (t.id === 'sap-hud-reset') {
        draft = (function () { var c = {}; for (var k in DEFAULTS) c[k] = DEFAULTS[k]; c.show = Object.assign({}, DEFAULTS.show); return c; })();
        dirty = true;
        paint();
        status('已恢复默认值（未保存），点击「保存设置」生效');
      } else if (t.id === 'sap-hud-open') {
        var api = window.electronAPI || {};
        if (api && api.openIslandWindow) {
          // S170：岛已开则只发演示，绝不重建（重建连点曾造出泄漏窗口群）
          var demoDelayed = function () { if (api.showHudDemo) setTimeout(function () { api.showHudDemo(); }, 800); };
          if (api.getIslandWindowState) {
            Promise.resolve(api.getIslandWindowState()).then(function (open) {
              if (open) { if (api.showHudDemo) api.showHudDemo(); }
              else { api.openIslandWindow(); demoDelayed(); }
            });
          } else { api.openIslandWindow(); demoDelayed(); }
        } else {
          status('预览需在桌面端主窗口中使用');
        }
      } else if (t.id === 'sap-hud-diag') {
        // S285：拉取岛窗 HUD 状态快照（旧缓存页会回显 HUD_REV_ABSENT=直接裁决代码版本问题）
        var dapi = window.electronAPI || {};
        var out = $id('sap-hud-diag-out');
        if (!dapi.hudDiag) {
          if (out) { out.style.display = 'block'; out.textContent = 'electronAPI.hudDiag 缺失（需重启主程序更新 preload）'; }
          return;
        }
        if (out) { out.style.display = 'block'; out.textContent = '诊断中…'; }
        Promise.resolve(dapi.hudDiag()).then(function (r) {
          if (out) out.textContent = JSON.stringify(r, null, 1);
        }).catch(function (err) { if (out) out.textContent = '诊断失败：' + err; });
      }
    });
    // 持续回填：Vue v-if 每次切回都会重建卡片 DOM，一次性 observer 会导致控件回到默认态（S167 根因）
    var fillTimer = null;
    function scheduleFill() {
      if (fillTimer) return;
      fillTimer = setTimeout(function () { fillTimer = null; fill(); }, 120);
    }
    new MutationObserver(scheduleFill).observe(document.body, { childList: true, subtree: true });
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', fill); } else { fill(); }
  }

  function init() {
    var isIsland = location.pathname.indexOf('island') >= 0;
    if (!isIsland) { bindSettings(); return; }
    // S285：诊断快照（主窗「胶囊诊断」按钮经主进程 executeJavaScript 调用）
    window.__hudDiag = function () {
      var r = null;
      try {
        if (capsule && capsule.getBoundingClientRect) {
          var rr = capsule.getBoundingClientRect();
          r = { l: rr.left, t: rr.top, w: rr.width, h: rr.height };
        }
      } catch (e) {}
      return {
        rev: HUD_REV, host: ISLAND_HOST, layer: !!layer,
        hidden: !!(layer && layer.classList.contains('hud-hidden')),
        enabled: cfg.enabled, capsuleMode: cfg.capsule, position: cfg.position,
        holdActive: holdActive, domOver: domOver, pollOver: pollOver, pollTicks: pollTicks,
        rect: r, screenXY: [window.screenX, window.screenY],
        dpr: window.devicePixelRatio || 1, inner: [window.innerWidth, window.innerHeight],
        apiSet: !!(window.electronAPI && window.electronAPI.setIgnoreMouseEvents),
        apiCursor: !!(window.electronAPI && window.electronAPI.getCursorScreenPoint),
        unread: unread, panelOpen: !!panel
      };
    };
    // S286：主进程看门狗轻量几何探针（高频轮询专用，避免整份诊断序列化）
    window.__hudDiagLite = function () {
      try {
        var r = capsule && capsule.getBoundingClientRect ? capsule.getBoundingClientRect() : null;
        if (!r) return null;
        return { rect: { l: r.left, t: r.top, w: r.width, h: r.height }, inner: [window.innerWidth, window.innerHeight], pos: cfg.position };
      } catch (e) { return null; }
    };
    if (!window.electron || !window.electron.ipcRenderer || typeof window.electron.ipcRenderer.on !== 'function') {
      // 无 preload 环境（纯浏览器）：降级为快捷键切换
      window.addEventListener('keydown', function (e) {
        if (e.altKey && e.shiftKey && (e.code === 'KeyH')) toggleCapsule();
      });
    } else {
      window.electron.ipcRenderer.on('hud-toggle-capsule', toggleCapsule);
      window.electron.ipcRenderer.on('hud-demo', showDemo);
      window.electron.ipcRenderer.on('hud-cfg', function (c) { mergeCfg(c); });
      // S274：Esc 关闭历史面板（面板打开时岛窗已被点击获焦，keydown 可达）
      document.addEventListener('keydown', function (e) {
        if (e && (e.key === 'Escape' || e.keyCode === 27) && panel) closePanel();
      });
      if (window.electronAPI && window.electronAPI.getHudCfg) {
        Promise.resolve(window.electronAPI.getHudCfg()).then(function (c) { if (c) mergeCfg(c); });
      }
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', function () { if (cfg.enabled) build(); });
    } else if (cfg.enabled) { build(); }
  }

  init();
})();
