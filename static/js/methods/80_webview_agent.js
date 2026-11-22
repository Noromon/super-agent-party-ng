// 批 3 F2：自 vue_methods.js 搬移的 js/methods/80_webview_agent.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
// S229：移动端 App 拉活/扫码登录/全屏遮罩选择器（定向、避免误伤正文），供离屏清洗与反广告注入共用。
const WALLS_SEL = '[class*=open-app],[class*=openapp],[class*=callapp],[class*=call-native],[class*=call_native],[class*=download-app],[class*=downloadapp],[class*=app-download],[class*=app-banner],[class*=appopen],[class*=OpenApp],[class*=AppDownload],[class*=AppBanner],[class*=login-mask],[class*=loginMask],[class*=LoginMask],[id*=loginbox],[class*=scan-login],[class*=scanlogin],[class*=qrcode-login],[class*=QRLogin],[class*=modal-backdrop],[class*=interstitial],[class*=downloadTop],[id*=downloadTop]';
// S230：软档反广告选择器上提为常量，_applyAdblock 与 getPageHtml（markdown 路径）共用。
const AD_SOFT_SEL = '#onetrust-consent-sdk,#onetrust-banner-sdk,#onetrust-popup,.qc-cmp2-container,#cmpwrapper,#cookie-banner,#cookieConsent,.cookie-consent,.cookie-banner,[id^="didomi-"],#didomi-host,#didomi-consent,.adns-popup,.adns-overlay,iframe[src*="doubleclick"],iframe[src*="googlesyndication"],iframe[src*="adservice"],iframe[src*="amazon-adsystem"],ins.adsbygoogle,.adsbygoogle,div[id^="google_ads_"],div[class*="ad-slot"],[aria-label="Advertisement"]';
// S277：CDP 输入 IPC 超时护栏。原生模态框（另存为/上传框）会禁用宿主窗口并使
// cdp-input-* 的 invoke 无限悬挂；不加守卫则滚动/点击第一通道卡死整条 promise 链
// （30s 后端超时），JS 回退通道永远轮不到。返回值恒为对象（超时/异常 → ok:false），
// 调用方按 falsy 走回退。window.__SAP_INPUT_TMO 可整体调低（行为测试用）。
function _inputTmo(p, ms) {
  let lim = Math.max(50, Number(ms) || 1500);
  try { const o = Number(window.__SAP_INPUT_TMO); if (o > 0) lim = Math.max(20, o); } catch (e) {}
  return new Promise((res) => {
    let done = false;
    const t = setTimeout(() => { if (!done) { done = true; res({ ok: false, err: 'input-timeout' }); } }, lim);
    Promise.resolve(p).then((r) => {
      if (!done) { done = true; clearTimeout(t); res(r && typeof r === 'object' ? r : { ok: false, err: 'input-null-resp' }); }
    }, (e) => {
      if (!done) { done = true; clearTimeout(t); res({ ok: false, err: String((e && e.message) || e) }); }
    });
  });
}

// S297：验证码域级熔断。贴吧事故里验证页被撞了几十次点击/填写——此前快照只给
// 提示语、全靠模型自觉。现改硬熔断：快照检出 captcha 即把该 host 拉入熔断名单，
// 交互方法（click/fill/fill_form/drag/hover/press_key）直接回拒；同 host 干净
// 快照自动解除。导航与只读不受影响——离开该域和用户过关都需要通道，不做自动重试。
const _captchaFrozen = new Set();
function _captchaHostOf(wv) {
    try { return new URL(wv.getURL ? (wv.getURL() || wv.src || '') : (wv.src || '')).hostname; } catch (e) { return ''; }
}
function _captchaGuard(wv) {
    const h = _captchaHostOf(wv);
    if (h && _captchaFrozen.has(h)) {
        return '[Error] captcha 域级熔断：' + h + ' 已检出验证码页，交互已熔断。'
            + '重复点击/填写只会撞同一堵墙——请提示用户在该内置浏览器标签手动完成验证，'
            + '之后任意一次 take_snapshot 见 captcha 消失即自动恢复，无需别的操作。';
    }
    return '';
}

Object.assign(vue_methods, {

    // S106: guest 端结果截断网关。MB 级页面内容原样回传宿主时，DOMWebSocket
    // host handler 实测 1s+ 长任务（LoAF 点名 DOMWebSocket.onmessage=1080ms）。
    _wvExec(wv, script, maxLen) {
      const lim = maxLen || 60000; // S230: 仅个别路径(如 getPageHtml)放宽回传上限；默认仍守 S106 长任务防护
      const cap = '(async()=>{const __r=await eval(' + JSON.stringify(script) + ');' +
        "if(typeof __r==='string'&&__r.length>" + lim + ")return __r.slice(0," + lim + ")+'\\n...[S106 truncated '+(__r.length-" + lim + ")+' chars]';" +
        "if(__r&&typeof __r==='object'){try{const __s=JSON.stringify(__r);if(__s.length>" + lim + ")return __s.slice(0," + lim + ")+'...[S106 truncated]';}catch(_e){}}" +
        'return __r;})()';
      return wv.executeJavaScript(cap);
    },
    getPagesInfo() {
        const info = this.browserTabs.map((tab, index) => ({
            index: index,
            id: tab.id,
            title: tab.title || 'Loading...',
            url: tab.url || '',
            active: tab.id === this.currentTabId
        }));
        return JSON.stringify(info);
    },

    closeTabByIndex(index) {
        const tabId = this.getTabIdByIndex(index);
        if (tabId) {
            this.closeTab(tabId);
            return "Closed tab index " + index;
        }
        return "Error: Tab index " + index + " not found";
    },

    switchTabByIndex(index) {
        const tabId = this.getTabIdByIndex(index);
        if (tabId) {
            this.switchTab(tabId);
            this.activeMenu = 'ai-browser';
            return "Selected tab index " + index;
        }
        return "Error: Tab index " + index + " not found";
    },

    // S230: timeout(秒)>0 时等待加载停止再返回，结果带 (loaded)/(still loading)；缺省/0=旧行为立即返回。
    async browserNavigate(type, url, ignoreCache, timeout) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        let waitSec = parseInt(timeout) || 0;
        waitSec = Math.max(0, Math.min(waitSec, 30));

        try {
            this.activeMenu = 'ai-browser'; // 切换到 AI Browser 菜单
            let base = '';
            switch (type) {
                case 'url':
                    if (!url) return "Error: URL is required";
                    this.navigateTo(url);
                    base = "Navigating to " + url;
                    break;
                case 'back':
                    if (wv.canGoBack()) {
                        wv.goBack();
                        base = "Navigated Back";
                        break;
                    }
                    return "Error: Cannot go back";
                case 'forward':
                    if (wv.canGoForward()) {
                        wv.goForward();
                        base = "Navigated Forward";
                        break;
                    }
                    return "Error: Cannot go forward";
                case 'reload':
                    if (ignoreCache) wv.reloadIgnoringCache();
                    else wv.reload();
                    base = "Reloaded";
                    break;
                default:
                    // 默认为 URL 导航
                    if (url) {
                        this.navigateTo(url);
                        base = "Navigated to " + url;
                        break;
                    }
                    return "Error: Unknown navigation type";
            }
            if (waitSec > 0) {
                const done = await this._waitLoadStop(wv, waitSec * 1000);
                base += done ? " (loaded)" : " (still loading)";
            }
            return base;
        } catch (e) {
            return "Navigation Exception: " + e.message;
        }
    },

    // S230: 轮询等待 webview 停止加载。true=已停止(或瞬时完成)；false=超时仍在加载。
    _waitLoadStop(wv, ms) {
        return new Promise((resolve) => {
            const start = Date.now();
            let sawLoading = false;
            const tick = () => {
                let loading = false;
                try { loading = wv.isLoading(); } catch (e) { resolve(true); return; }
                if (loading) sawLoading = true;
                if (!loading && sawLoading) { resolve(true); return; }
                if (!loading && !sawLoading && Date.now() - start > 400) { resolve(true); return; } // 缓存页/瞬时导航
                if (Date.now() - start > ms) { resolve(!loading); return; }
                setTimeout(tick, 250);
            };
            setTimeout(tick, 150);
        });
    },

    // --- 0. 拟人化延迟辅助函数 ---
    async _humanDelay() {
        // 随机延迟 100ms 到 1000ms (0.1s - 1s)
        const delay = Math.floor(Math.random() * 900) + 100;
        await new Promise(resolve => setTimeout(resolve, delay));
    },

    // --- 1. 伪装成 A11y 树的快照 (无延迟，读取操作越快越好) ---
    async getWebviewSnapshot(verbose = false) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        // S230: 加载中先短等 3s；仍未完不再硬报错，改为照常出(可能不完整的)快照并加尾注
        let loadNote = '';
        if (wv.isLoading()) {
            const done = await this._waitLoadStop(wv, 3000);
            if (!done) loadNote = '\n(note: page still loading — snapshot may be partial)';
        }

        const script = `
        (function() {
            try {
                if (!window._ai_uid_counter) window._ai_uid_counter = 1;
                const interactiveSelector = 'a, button, input, textarea, select, details, label, summary, [role="button"], [role="link"], [role="menuitem"], [role="tab"], [onclick]';
                
                function isVisible(el) {
                    const style = window.getComputedStyle(el);
                    return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0' && el.offsetWidth > 0;
                }

                function getSafeText(el) {
                    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
                    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') return el.value || el.getAttribute('placeholder') || '';
                    if (el.tagName === 'SELECT') return el.options[el.selectedIndex]?.text || '';
                    return el.innerText ? el.innerText.slice(0, 50).replace(/[\\r\\n]+/g, ' ').trim() : '';
                }

                function getRole(el) {
                    if (el.getAttribute('role')) return el.getAttribute('role');
                    return el.tagName.toLowerCase();
                }

                const elements = document.querySelectorAll(interactiveSelector);
                const lines = [];

                elements.forEach(el => {
                    if (!isVisible(el)) return;
                    let uid = el.getAttribute('data-ai-id');
                    if (!uid) {
                        uid = 'ai-' + window._ai_uid_counter++;
                        el.setAttribute('data-ai-id', uid);
                    }
                    const role = getRole(el);
                    const name = getSafeText(el);
                    const value = (el.value && el.value !== name) ? el.value : '';
                    
                    let line = \`[\${uid}] \${role}\`;
                    if (name) line += \` "\${name}"\`;
                    if (value) line += \` Value: "\${value}"\`;

                    lines.push(line);
                });

                // --- images (S228): 让 agent 知道哪里有图，赋 uid 供 take_screenshot/remove_element 定位 ---
                const imgLines = [];
                let skipped = 0, listed = 0;
                const imgEls = document.querySelectorAll('img,[role="img"],input[type="image"],canvas');
                imgEls.forEach(el => {
                    if (!isVisible(el)) return;
                    let rect = { width: 0, height: 0, top: 0, bottom: 0 };
                    try { rect = el.getBoundingClientRect(); } catch (e) {}
                    const rw = rect.width || 0, rh = rect.height || 0;
                    const isCanvas = (el.tagName === 'CANVAS');
                    const nw = isCanvas ? (el.width || rw) : (el.naturalWidth || rw);
                    const nh = isCanvas ? (el.height || rh) : (el.naturalHeight || rh);
                    if (rw < 24 || rh < 24 || nw <= 1 || nh <= 1) { skipped++; return; }
                    let iuid = el.getAttribute('data-ai-id');
                    if (!iuid) { iuid = 'ai-' + window._ai_uid_counter++; el.setAttribute('data-ai-id', iuid); }
                    if (listed >= 60) { skipped++; return; }
                    listed++;
                    const tag = el.tagName.toLowerCase();
                    const irole = el.getAttribute('role') || (tag === 'img' ? 'img' : tag);
                    let nm = String(el.getAttribute('alt') || el.getAttribute('aria-label') || '').slice(0, 60);
                    nm = nm.split(String.fromCharCode(10)).join(' ').split(String.fromCharCode(13)).join(' ').trim();
                    const loaded = isCanvas ? 'canvas' : ((el.complete && nw > 1) ? 'loaded' : 'pending');
                    const off = (rect.bottom < 0 || rect.top > window.innerHeight) ? ' [offscreen]' : '';
                    // S246: 带源 URL，agent 可直接喂 view_images 一手看图（零转述闭环）。
                    // S258: 懒加载站(贴吧等)未渲染时 src 只是占位符，真图地址在 _src/data-actualsrc 等属性。
                    // S262: 但已渲染页面 src 才是真图(_src 留旧缩略)——http src 优先，懒属性仅回退。
                        let iurl = '', ph = '';
                        if (!isCanvas) {
                            try {
                                // S262: 帖内页 JS 渲染后 src=真长图、_src 仍是旧缩略——src 已是 http 必取 src；
                                // 仅未渲染(src 缺失/data:/blob: 占位)才回退懒属性链（列表页懒加载场景）。
                                const cur = String(el.currentSrc || el.src || '');
                                if (/^https?:/i.test(cur)) iurl = cur;
                                if (!iurl) {
                                    const lz = ['_src', 'data-src', 'data-actualsrc', 'data-original', 'data-lazy-src', 'data-original-src'];
                                    for (let li = 0; li < lz.length; li++) {
                                        const v = el.getAttribute(lz[li]);
                                        if (v && /^(https?:)?\\/\\//i.test(String(v))) {
                                            try { iurl = new URL(String(v), location.href).href; } catch (e2) { iurl = String(v); }
                                            break;
                                        }
                                    }
                                }
                            // S259: blob:/data: 等页内源外部永远取不到（喂 view_images 必空手，
                            // 曾把 agent 引去试 canvas——污染死路）。不吐 URL 本体，直导像素路。
                            if (iurl && !/^https?:/i.test(iurl)) {
                                ph = ' [已渲染但无外部URL：用 take_screenshot(uid) 查看]'; iurl = '';
                            }
                            iurl = iurl.slice(0, 200);
                        } catch (e) {}
                    }
                    let iline = '[' + iuid + '] ' + irole + (nm ? ' "' + nm + '"' : '') + ' ' + Math.round(nw) + 'x' + Math.round(nh) + ' [' + loaded + ']' + off + ph + (iurl ? ' url=' + iurl : '');
                    imgLines.push(iline);
                });

                const out = [];
                if (lines.length) out.push(lines.join('\\n'));
                if (imgLines.length) {
                    out.push('--- images (' + imgLines.length + (skipped ? ', +' + skipped + ' more omitted' : '') + ') ---');
                    out.push(imgLines.join('\\n'));
                } else if (skipped) {
                    out.push('--- images: ' + skipped + ' small/hidden image(s) omitted ---');
                }
                if (out.length === 0) return "Page empty or no interactive elements found.";
                return out.join('\\n');
            } catch (e) {
                return "Snapshot Script Error: " + e.message;
            }
        })()
        `;
        
        // S249: 验证码/安全验证页信号——agent 应停下请人工在标签里过关，而不是硬解
        let captchaNote = '';
        try {
            const probe = "(function(){try{"
                + "var sel='#captcha,[class*=passMod],[id*=passMod],[class*=verify-code],[id*=verify],[class*=captcha],[id*=captcha],img[src*=verifycode]';"
                + "var vis=function(n){try{return !!n&&(n.offsetWidth>0||n.offsetHeight>0);}catch(e){return false;};};"
                + "var nodes=[];try{nodes=Array.prototype.slice.call(document.querySelectorAll(sel)).filter(vis);}catch(e){}"
                + "var t='';try{t=(document.body&&document.body.innerText||'').slice(0,3000);}catch(e){}"
                + "return nodes.length>0||/(安全验证|拖动滑块|滑动验证|完成验证|点击按钮开始验证|输入验证码后|请完成下方验证)/.test(t);"
                + "}catch(e){return false;}})()";
            const hit = await this._wvExec(wv, probe);
            const _ch = _captchaHostOf(wv);
            if (hit === true && _ch) _captchaFrozen.add(_ch);
            if (hit === true) captchaNote = '\n[page-meta] captcha_detected=true —— 检测到验证码/安全验证页：需人工处理，该域交互已熔断（click/fill/press_key 会直接被拒）。请提示用户在内置浏览器标签中手动完成验证（移动端视口裁剪与坐标已修复，可直接点击），勿用 evaluate_script 硬解，通过后再 take_snapshot（captcha 消失即解除熔断）。';
            else if (_ch && _captchaFrozen.has(_ch)) {
                _captchaFrozen.delete(_ch);
                captchaNote = '\n[page-meta] captcha_cleared=true —— ' + _ch + ' 验证码已消失，交互熔断已解除。';
            }
        } catch (e) {}

        try {
            const r = await this._wvExec(wv, script);
            return (typeof r === 'string') ? (r + captchaNote + loadNote) : r;
        } catch (e) {
            return "Vue Snapshot Error: " + e.message;
        }
    },

    // --- 2. 点击 (增加延迟) ---
    async webviewClick(uid, dblClick = false) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();
        const script = `
        (async function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            // S246: 快照 uid 全灭=页面重建，给结构化信号省一轮盲猜
            if (!el) return document.querySelectorAll('[data-ai-id]').length === 0
                ? "UID_EXPIRED: page DOM rebuilt — all snapshot UIDs invalid, call take_snapshot for a fresh set"
                : "Element not found: ${uid}";
            
            // 1. 滚动到可见 (平滑滚动更像人)
            el.scrollIntoView({behavior: "smooth", block: "center", inline: "center"});
            
            // 等待一小会儿让滚动完成
            await new Promise(r => setTimeout(r, 200));

            // 2. 计算随机坐标 (核心改进)
            const rect = el.getBoundingClientRect();
            // 不点边缘，只在中心 80% 区域内随机
            // Math.random() - 0.5 生成 -0.5 到 0.5 的数
            const randomX = (Math.random() - 0.5) * (rect.width * 0.8); 
            const randomY = (Math.random() - 0.5) * (rect.height * 0.8);
            
            // 加上 rect.left 等于视口绝对坐标，加上 rect.width/2 等于中心点
            // clientX/Y 是相对于视口的
            const clientX = rect.left + (rect.width / 2) + randomX;
            const clientY = rect.top + (rect.height / 2) + randomY;

            // 3. 构造事件对象 (带真实坐标)
            const opts = { 
                bubbles: true, 
                cancelable: true, 
                view: window, 
                buttons: 1,
                clientX: clientX,
                clientY: clientY,
                screenX: clientX + window.screenX, // 模拟屏幕坐标
                screenY: clientY + window.screenY
            };

            // 4. 触发完整的事件链
            el.dispatchEvent(new MouseEvent('mouseover', opts));
            el.dispatchEvent(new MouseEvent('mousedown', opts));
            // 鼠标按下和抬起之间极短的停顿
            await new Promise(r => setTimeout(r, Math.floor(Math.random() * 50) + 10)); 
            el.dispatchEvent(new MouseEvent('mouseup', opts));
            el.dispatchEvent(new MouseEvent('click', opts));
            
            if (${dblClick}) {
                el.dispatchEvent(new MouseEvent('dblclick', opts));
            }
            return "Clicked " + "${uid}";
        })()
        `;
        
        try {
            const result = await this._wvExec(wv, script);
            // 操作后的大延迟（模拟思考下一步）
            await this._humanDelay();
            return result;
        } catch (e) {
            return "Click Error: " + e.message;
        }
    },

    // --- 3. 输入 (增加延迟) ---
    async webviewFill(uid, value) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();
        // 注意：这里需要把 value 传给 JS，使用 JSON.stringify 确保安全
        const script = `
        (async function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return document.querySelectorAll('[data-ai-id]').length === 0
                ? "UID_EXPIRED: page DOM rebuilt — all snapshot UIDs invalid, call take_snapshot for a fresh set"
                : "Element not found: ${uid}";
            
            el.focus();
            
            const text = ${JSON.stringify(value)};
            
            // 获取原生 Setter (解决 React/Vue 无法监听 js 赋值的问题)
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
            
            // 清空现有内容 (如果需要追加模式，可以去掉这行)
            if (nativeInputValueSetter) {
                nativeInputValueSetter.call(el, '');
            } else {
                el.value = '';
            }
            el.dispatchEvent(new Event('input', { bubbles: true }));

            // ★ 核心：逐字输入循环
            for (let i = 0; i < text.length; i++) {
                const char = text[i];
                
                // 1. 模拟按键按下 (keydown)
                el.dispatchEvent(new KeyboardEvent('keydown', { key: char, bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keypress', { key: char, bubbles: true }));

                // 2. 更新值 (模拟输入进去的效果)
                const currentVal = el.value + char;
                if (nativeInputValueSetter && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) {
                    nativeInputValueSetter.call(el, currentVal);
                } else {
                    el.value = currentVal;
                }

                // 3. 触发 input 事件 (让框架知道值变了)
                el.dispatchEvent(new InputEvent('input', { data: char, inputType: 'insertText', bubbles: true }));
                
                // 4. 模拟按键抬起 (keyup)
                el.dispatchEvent(new KeyboardEvent('keyup', { key: char, bubbles: true }));

                // ★ 5. 随机打字延迟 (30ms - 150ms)
                // 模拟人打字忽快忽慢
                const delay = Math.floor(Math.random() * 120) + 30;
                await new Promise(r => setTimeout(r, delay));
            }

            // 完成后的 change 事件
            el.dispatchEvent(new Event('change', { bubbles: true }));
            
            // 稍微停顿后失焦
            await new Promise(r => setTimeout(r, 200));
            el.blur();

            return "Filled " + "${uid}";
        })()
        `;
        
        try {
            const result = await this._wvExec(wv, script);
            // 操作后的大延迟
            await this._humanDelay();
            return result;
        } catch (e) {
            return "Fill Error: " + e.message;
        }
    },

    // --- 4. 批量填表 (增加延迟) ---
    async webviewFillForm(elements) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();
        const dataStr = JSON.stringify(elements); 

        const script = `
        (function() {
            const items = ${dataStr};
            const log = [];
            items.forEach(item => {
                const el = document.querySelector('[data-ai-id="' + item.uid + '"]');
                if (el) {
                    el.focus();
                    el.value = item.value;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    log.push(item.uid);
                }
            });
            return "Filled elements: " + log.join(', ');
        })()
        `;
        
        const result = await this._wvExec(wv, script);
        
        // ★ 批量操作后等待
        await this._humanDelay();
        
        return result;
    },

    // --- 5. 拖拽 (增加延迟) ---
    async webviewDrag(fromUid, toUid) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();
        const script = `
        (function() {
            const src = document.querySelector('[data-ai-id="${fromUid}"]');
            const tgt = document.querySelector('[data-ai-id="${toUid}"]');
            if (!src || !tgt) return "Elements not found";

            const srcRect = src.getBoundingClientRect();
            const tgtRect = tgt.getBoundingClientRect();
            const clientX = srcRect.left + srcRect.width / 2;
            const clientY = srcRect.top + srcRect.height / 2;
            const targetX = tgtRect.left + tgtRect.width / 2;
            const targetY = tgtRect.top + tgtRect.height / 2;

            const emit = (type, x, y) => {
                const ev = new MouseEvent(type, { 
                    bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, buttons: 1 
                });
                (type === 'mouseup' ? tgt : src).dispatchEvent(ev);
            };

            emit('mousedown', clientX, clientY);
            emit('mousemove', clientX + 5, clientY + 5); 
            emit('mousemove', targetX, targetY);         
            emit('mouseup', targetX, targetY);           

            return "Dragged " + "${fromUid}" + " to " + "${toUid}";
        })()
        `;
        
        const result = await this._wvExec(wv, script);
        
        // ★ 拖拽动作幅度大，等待时间可以稍微长一点（这里复用随机等待）
        await this._humanDelay();
        
        return result;
    },

    // --- 6. 悬停 (增加延迟) ---
    async webviewHover(uid) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();
        const script = `
        (function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return document.querySelectorAll('[data-ai-id]').length === 0
                ? "UID_EXPIRED: page DOM rebuilt — all snapshot UIDs invalid, call take_snapshot for a fresh set"
                : "Element not found: ${uid}";
            el.scrollIntoView({block: "center"});
            el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
            el.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
            return "Hovered " + "${uid}";
        })()
        `;
        
        const result = await this._wvExec(wv, script);
        
        // ★ 悬停通常是为了看东西，稍微等一下合理
        await this._humanDelay();
        
        return result;
    },

    // --- 8. 处理弹窗 (无延迟) ---
    async webviewHandleDialog(action, promptText) {
        // ... (代码保持不变，弹窗处理通常是瞬时的) ...
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        wv.focus();
        const script = `
        (function() {
            window.__ai_dialog_action = "${action}"; 
            window.__ai_dialog_text = ${JSON.stringify(promptText || "")};
            window.alert = function() { return true; };
            window.confirm = function() { return window.__ai_dialog_action === 'accept'; };
            window.prompt = function() { return window.__ai_dialog_action === 'accept' ? window.__ai_dialog_text : null; };
            return "Dialog handlers patched";
        })()
        `;
        return await this._wvExec(wv, script);
    },

    // --- 9. 按键 (增加延迟) ---
    async webviewPressKey(keyCombo, uid) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const _cg = _captchaGuard(wv); if (_cg) return _cg;  // S297
        wv.focus();

        // 1. 获取元素坐标 (JS 只负责告诉我们它在哪)
        const rectScript = `
        (function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return null;
            
            // 滚动到屏幕中间
            el.scrollIntoView({behavior: "auto", block: "center", inline: "center"});
            
            // 获取相对于视口的精确坐标
            const rect = el.getBoundingClientRect();
            return {
                x: rect.left + (rect.width / 2),
                y: rect.top + (rect.height / 2)
            };
        })()
        `;

        try {
            const rect = await this._wvExec(wv, rectScript);
            if (!rect) return "Element not found or not rendered: " + uid + " (uid stale/hidden? call take_snapshot for a fresh set)";

            // ★ 关键修复：使用 sendInputEvent 发送真实的鼠标点击
            // 这会强制操作系统将焦点转移到该坐标下的输入框
            // 注意：x, y 是相对于 Webview 左上角的坐标
            
            // 1. 移动并按下鼠标
            wv.sendInputEvent({ 
                type: 'mouseDown', 
                x: rect.x, 
                y: rect.y, 
                button: 'left', 
                clickCount: 1 
            });
            
            // 2. 抬起鼠标 (完成点击)
            wv.sendInputEvent({ 
                type: 'mouseUp', 
                x: rect.x, 
                y: rect.y, 
                button: 'left', 
                clickCount: 1 
            });

            // 等待点击生效，输入框激活光标
            await new Promise(r => setTimeout(r, 400));

            // 3. 处理按键
            const parts = keyCombo.split('+').map(k => k.trim());
            let key = parts.pop(); 
            const modifiers = parts.map(m => m.toLowerCase());
            
            if (key.toLowerCase() === 'enter') key = 'Enter';

            // 4. 发送原生按键
            // 模拟按下
            wv.sendInputEvent({ type: 'keyDown', keyCode: key, modifiers });
            
            // ★ 补充 char 事件：Enter 键经常需要配套一个 char code 13 (\r)
            // 许多网页(特别是旧一点的或 React 封装的)依赖这个 char 事件来触发表单提交
            if (key === 'Enter') {
                wv.sendInputEvent({ type: 'char', keyCode: '\r', modifiers });
            } else if (key.length === 1) {
                wv.sendInputEvent({ type: 'char', keyCode: key, modifiers });
            }

            // 模拟按住停顿
            await new Promise(r => setTimeout(r, Math.floor(Math.random() * 50) + 30));

            // 模拟抬起
            wv.sendInputEvent({ type: 'keyUp', keyCode: key, modifiers });
            
            await this._humanDelay();
            
            return "Pressed (Native) " + keyCombo + " on " + uid;
        } catch (e) {
            return "PressKey Error: " + e.message;
        }
    },

    // --- 10. 等待文本 (无延迟，这是轮询操作) ---
    // S246: wait_for 扩展——mode='text'|'selector'|'js'（默认 text，向后兼容两参调用）。
    // selector: querySelector 命中即真；js: 谓词表达式每次轮询求值（truthy 通过，抛错=未就绪）。
    async webviewWaitFor(expr, timeout, mode = 'text') {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";

        const probe = mode === 'selector'
            ? "(function(){try{return !!document.querySelector(" + JSON.stringify(expr) + ")})()"
            : mode === 'js'
                ? "(function(){try{return !!(" + String(expr) + ")||false}catch(_e){return false}})()"
                : "document.body.innerText.includes(" + JSON.stringify(expr) + ")";
        const script = `
        (function() {
            return new Promise((resolve) => {
                const start = Date.now();
                const probe = ${probe};
                const label = ${JSON.stringify((mode === 'text' ? '' : mode + ':') + String(expr).slice(0, 80))};
                const check = () => {
                    let hit = false;
                    try { hit = probe; } catch (e) { hit = false; }
                    if (hit) {
                        resolve("Found: " + label);
                    } 
                    else if (Date.now() - start > ${timeout}) {
                        if (document.readyState === 'complete') {
                            resolve("Not found: " + label + " (page loaded)");
                        } else {
                            resolve("Timeout: " + label + " not matched (page still loading)");
                        }
                    } 
                    else {
                        setTimeout(check, 250);
                    }
                };
                check();
            });
        })()
        `;
        return await this._wvExec(wv, script);
    },

    // --- 11. 截图 (无延迟) ---
    async captureWebviewScreenshot(fullPage = false, uid = null) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        wv.focus();
        try {
            // 1. 元素区域：定位 + 滚动入视口 + 测量（无 click 副作用，S228）
            let region = null;
            if (uid) {
                const sel = (/^ai-\d+$/.test(uid)) ? '[data-ai-id="' + uid + '"]' : String(uid);
                const measure = "(function(){try{"
                    + "var el=document.querySelector(" + JSON.stringify(sel) + ");"
                    + "if(!el)return JSON.stringify({err:'notfound'});"
                    + "try{el.scrollIntoView({block:'center',inline:'center',behavior:'instant'});}catch(e){}"
                    + "var r=el.getBoundingClientRect();"
                    + "return JSON.stringify({x:r.left,y:r.top,w:r.width,h:r.height,iw:window.innerWidth,ih:window.innerHeight});"
                    + "}catch(e){return JSON.stringify({err:String((e&&e.message)||e)});}})()";
                const infoStr = await this._wvExec(wv, measure);
                let info = {}; try { info = JSON.parse(infoStr); } catch (e) {}
                if (info.err) return "Screenshot Error: element not found: " + uid + " (uid stale? call take_snapshot for a fresh set)";
                if (!(info.w > 0 && info.h > 0 && info.iw > 0 && info.ih > 0)) return "Screenshot Error: element has zero size: " + uid;
                region = info;
                await this._humanDelay();
            }

            // 2. 捕获视口像素（静态图/动态渲染 img/canvas 一视同仁；fullPage 暂为视口）
            const image = await wv.capturePage();
            const size = image.getSize();

            // 3. 裁剪区域 → 设备像素 rect（越界夹取；S235：先算好喂异步管线）
            let cropRect = { x: 0, y: 0, w: size.width, h: size.height };
            if (region) {
                const sx = size.width / region.iw, sy = size.height / region.ih;
                const cx = Math.max(0, Math.min(Math.round(region.x * sx), size.width - 1));
                const cy = Math.max(0, Math.min(Math.round(region.y * sy), size.height - 1));
                cropRect = {
                    x: cx, y: cy,
                    w: Math.max(1, Math.min(Math.round(region.w * sx), size.width - cx)),
                    h: Math.max(1, Math.min(Math.round(region.h * sy), size.height - cy)),
                };
            }

            // 4. S235：解码/裁剪/缩放/编码移出主线程——nativeImage crop/resize/toJPEG
            //    是同步位图处理，大帧每步阻塞主窗口渲染线程数百 ms（整屏冻结观感之一）；
            //    改 createImageBitmap + OffscreenCanvas.convertToBlob 后全异步。
            //    S238：跨 contextBridge 传 Uint8Array 不可靠（实测到达主进程变 0 字节 →
            //    0B 假图喂上游 400），统一改传 base64 字符串；空数据当场报错不发假 URL。
            let b64 = '';
            try {
                const pngBlob = new Blob([new Uint8Array(image.toPNG())], { type: 'image/png' });
                const tw = cropRect.w > 1280 ? 1280 : cropRect.w;
                const th = Math.max(1, Math.round(cropRect.h * (tw / cropRect.w)));
                const bmp = await createImageBitmap(pngBlob, cropRect.x, cropRect.y, cropRect.w, cropRect.h,
                    { resizeWidth: tw, resizeHeight: th, resizeQuality: 'high' });
                const canvas = new OffscreenCanvas(bmp.width, bmp.height);
                canvas.getContext('2d').drawImage(bmp, 0, 0);
                if (bmp.close) bmp.close();
                const jpeg = await canvas.convertToBlob({ type: 'image/jpeg', quality: 0.7 });
                const ab = await jpeg.arrayBuffer();
                if (!ab || ab.byteLength === 0) return "Screenshot Error: empty";
                const bytes = new Uint8Array(ab);
                let bin = '';
                for (let i = 0; i < bytes.length; i += 0x8000) {
                    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
                }
                b64 = btoa(bin);
            } catch (e) {
                // S235-fallback：异步管线不可用时兜底旧同步三连（crop→resize→toJPEG）
                let target = image;
                if (region) {
                    try { target = image.crop({ x: cropRect.x, y: cropRect.y, width: cropRect.w, height: cropRect.h }); } catch (e2) { target = image; }
                }
                if (target.getSize().width > 1280) target = target.resize({ width: 1280 });
                const jpegBuf = target.toJPEG(70);
                if (!jpegBuf || jpegBuf.length === 0) return "Screenshot Error: empty";
                b64 = jpegBuf.toString('base64');
            }

            // 5. 交主进程保存（S238：base64 字符串跨桥可靠；主进程解码并拒空）
            const filename = await window.electronAPI.saveScreenshotDirect(b64);

            // 6. 拼接 URL（preload 暴露后端 host/port）
            const host = window.electron.server.host || '127.0.0.1';
            const port = window.electron.server.port || 3456;
            return `http://${host}:${port}/uploaded_files/${filename}`;

        } catch (e) {
            return "Screenshot Error: " + e.message;
        }
    },

    // --- 12. 通用 JS 执行 (增加延迟) ---
    async executeInActiveWebview(codeStr, args = []) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        wv.focus();
        try {
            const script = `(${codeStr})(...${JSON.stringify(args || [])})`;
            const result = await this._wvExec(wv, script);
            
            // ★ 自定义脚本执行后也等待，防止 Agent 连续高频调用
            await this._humanDelay();

            if (result === undefined) return "undefined";
            if (result === null) return "null";
            if (typeof result === 'object') return JSON.stringify(result);
            return String(result);

        } catch (e) {
            return "JS Execution Error: " + e.message;
        }
    },

    // --- 12b. S227：反弹窗/广告注入（CSS 实时隐藏 + 立即移除匹配节点；force=激进档）---
    // 仅 DOM 层，无网络域名名单。onDomReady 在标签页每次加载后自动调用软档（受 adblock 设置控制）。
    _applyAdblock(wv, hard) {
        if (!wv) return Promise.resolve("Error: No active webview");
        const soft = AD_SOFT_SEL;
        const extra = ',[role="dialog"][aria-modal="true"],[class*="modal-backdrop"],[class*="interstitial"],[id*="paywall"],[class*="paywall"]' + ',' + WALLS_SEL;
        const css = hard ? (soft + extra) : soft;
        const script = '(function(){try{'
            + 'var css=' + JSON.stringify(css) + ';'
            + 'var el=document.getElementById("__sap_adblock__");if(!el){el=document.createElement("style");el.id="__sap_adblock__";(document.head||document.documentElement).appendChild(el);}'
            + 'el.textContent=css+"{display:none!important;width:0!important;height:0!important;}";'
            + 'var n=0;css.split(",").forEach(function(s){try{document.querySelectorAll(s.trim()).forEach(function(x){try{x.remove?x.remove():(x.parentNode&&x.parentNode.removeChild(x));n++;}catch(e){}})}catch(e){}});'
            + 'return "cleaned:"+n;}catch(e){return "clean err:"+e.message;}})()';
        return this._wvExec(wv, script);
    },

    cleanPage(force) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        return this._applyAdblock(wv, !!force);
    },

    // 拔除指定元素：target 可为快照 uid（ai-N）或任意 CSS 选择器
    removeElement(target) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const script = '(function(){try{'
            + 'var t=' + JSON.stringify(target || '') + ';if(!t)return "no target";'
            + 'var sel=t;if(/^ai-\\d+$/.test(t)){sel=\'[data-ai-id="\'+t+\'"]\';}'
            + 'var els=document.querySelectorAll(sel);var n=0;'
            + 'els.forEach(function(e){try{e.remove?e.remove():(e.parentNode&&e.parentNode.removeChild(e));n++;}catch(x){}});'
            + 'return "removed:"+n;}catch(e){return "remove err:"+e.message;}})()';
        return this._wvExec(wv, script);
    },

    stopLoading() {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        try { if (wv.stop) wv.stop(); return "stopped"; }
        catch (e) { return "stop err: " + e.message; }
    },

    // 急停 + 后退：从误跳转/弹窗逃生
    escapeBack() {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        try {
            if (wv.stop) wv.stop();
            if (wv.canGoBack()) { wv.goBack(); return "stopped and went back"; }
            return "stopped (no history to go back)";
        } catch (e) { return "escapeBack err: " + e.message; }
    },

    // 把当前活动页就地清洗后返回 HTML（供 get_page_markdown 转 Markdown）
    // S246: 返回 JSON {html,url,title,wallN,wallTxt}——url/title 供 meta 头；
    // wallN/wallTxt 为删除遮罩【之前】的登录墙信号计数（软墙检测的事实源）。
    // guest 回传串带 'S246W|n|t|' 前缀（单字符串走 _wvExec cap，截断也不丢头部）。
    async getPageHtml() {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        if (wv.isLoading()) return "Error: Page is loading...";
        const kill = "(function(){"
            + "var wallN=0,wallTxt=false;"
            + "try{var walls=" + JSON.stringify(WALLS_SEL) + ";walls.split(',').forEach(function(s){try{wallN+=document.querySelectorAll(s).length}catch(e){}});}catch(e){}"
            + "try{wallTxt=/(扫码登录|请先登录|登录后查看|登录后可见|登录查看全部|扫码下载.*查看更多|please log ?in|sign ?in to (view|continue))/i.test((document.body&&document.body.innerText||'').slice(0,8000));}catch(e){}"
            + "try{var sel=" + JSON.stringify(AD_SOFT_SEL + ',' + WALLS_SEL) + ";sel.split(',').forEach(function(s){try{document.querySelectorAll(s).forEach(function(n){try{n.remove()}catch(e){}})}catch(e){}});}catch(e){}"
            + "try{document.querySelectorAll('img[src^=\"data:\"]').forEach(function(n){try{n.remove()}catch(e){}});}catch(e){}"
            + "try{['script','style','noscript','template','svg','canvas','video','audio','iframe','nav','footer','header','aside'].forEach(function(t){document.querySelectorAll(t).forEach(function(n){try{n.remove()}catch(e){}})});}catch(e){}"
            + "try{return 'S246W|'+wallN+'|'+(wallTxt?1:0)+'|'+(document.body?document.body.innerHTML:'');}catch(e){return 'S246W|0|0|';}})()";
        let raw = await this._wvExec(wv, kill, 400000);
        if (typeof raw !== 'string') raw = String(raw || '');
        if (raw.indexOf("Error") === 0) return raw;
        let wallN = 0, wallTxt = false, html = raw;
        if (raw.indexOf('S246W|') === 0) {
            const p = raw.split('|');
            wallN = parseInt(p[1], 10) || 0;
            wallTxt = p[2] === '1';
            html = raw.slice(('S246W|' + p[1] + '|' + p[2] + '|').length);
        }
        let url = '', title = '';
        try { url = wv.getURL() || ''; } catch (e) {}
        try { title = wv.getTitle() || ''; } catch (e) {}
        return JSON.stringify({ html: html, url: url, title: title, wallN: wallN, wallTxt: wallTxt });
    },

    // 后台开标签：建 tab 并设为当前供 agent 操作，但不切换 activeMenu（不抢用户可见面板）
    // S236：partition=agent 网络出口分区（默认 agent-direct 直连；agent-proxy=设置代理）
    openUrlInBackground(url, partition) {
        if (!url) return "Error: no url";
        this._guardAuthNav(url);
        const newTab = { id: Date.now(), title: 'Loading...', url: url, favicon: '', isLoading: true, loaded: true, canGoBack: false, canGoForward: false, mobile: false, partition: partition || 'persist:agent-direct' };
        this.browserTabs.push(newTab);
        this.currentTabId = newTab.id;
        this.urlInput = url;
        return "Opened in background tab id " + newTab.id;
    },

    // --- 14. S227：重定向护栏（guardRedirect 开启时）---
    // agent 主动导航授权放行（guardRedirect 关闭时为空操作）
    _guardAuthNav(url) {
        try {
            if (this.chromeMCPSettings && this.chromeMCPSettings.guardRedirect
                && window.electronAPI && window.electronAPI.guardAuthorize) {
                window.electronAPI.guardAuthorize({ url });
            }
        } catch (e) {}
    },

    // 查询当前被挂起的跳转（guardRedirect 关闭时恒为 []）
    async listPendingRedirects() {
        try {
            if (!(window.electronAPI && window.electronAPI.guardList)) return "[]";
            const r = await window.electronAPI.guardList();
            return JSON.stringify(r || []);
        } catch (e) { return "[]"; }
    },

    // 裁决：allow=true 放行该跳转，否则维持拦截。id 省略时取当前活动 webview
    async resolveRedirect(allow, id) {
        try {
            if (!(window.electronAPI && window.electronAPI.guardDecide)) return "no bridge";
            let wid = id;
            if (wid == null) {
                const wv = this.getWebview();
                try { if (wv && wv.getWebContentsId) wid = wv.getWebContentsId(); } catch (e) {}
            }
            const r = await window.electronAPI.guardDecide({ id: wid, allow: !!allow });
            return r ? ("redirect " + (allow ? "allowed" : "blocked")) : "no pending redirect";
        } catch (e) { return "resolveRedirect err: " + e.message; }
    },

    // 设置页切换 guardRedirect：保存 + 通知主进程实时生效
    onGuardRedirectChange() {
        try { this.autoSaveSettings && this.autoSaveSettings(); } catch (e) {}
        try {
            if (window.electronAPI && window.electronAPI.setGuardFlag) {
                window.electronAPI.setGuardFlag(this.chromeMCPSettings && this.chromeMCPSettings.guardRedirect === true);
            }
        } catch (e) {}
    },

    // --- 13. S227：离屏隐藏渲染动态页 -> 清洗后 HTML（供 web_render 转 Markdown）---
    // 不建标签、不动 currentTab/activeMenu，纯隐藏 webview 渲染后抽取，避免抢占用户视图。
    renderOffscreenPage(url, opts) {
        opts = opts || {};
        const waitText = (opts.waitText || "");
        let total = parseInt(opts.timeout) || 45;
        total = Math.max(5, Math.min(total, 60));
        const totalMs = total * 1000;
        const mobile = !!opts.mobile;
        const MOBILE_UA = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36';
        return new Promise((resolve) => {
            let done = false, hardTimer = null, domReadySeen = false, lastStage = 'connect';
            let wv;
            try {
                wv = document.createElement('webview');
            } catch (e) {
                resolve(JSON.stringify({ ok: false, url: url, error: 'createElement failed' }));
                return;
            }
            const finish = (obj) => {
                if (done) return;
                done = true;
                try { if (hardTimer) clearTimeout(hardTimer); } catch (e) {}
                try { wv.remove(); } catch (e) {}
                resolve(JSON.stringify(obj));
            };
            // S236：agent 工具默认直连分区（免疫系统代理）；useProxy=true 走设置代理分区
            wv.setAttribute('partition', opts.useProxy ? 'persist:agent-proxy' : 'persist:agent-direct');
            if (this.webviewPreloadPath) { try { wv.setAttribute('preload', this.webviewPreloadPath); } catch (e) {} }
            wv.setAttribute('webpreferences', 'contextIsolation=true, nodeIntegration=false, sandbox=true, webSecurity=true, enableRemoteModule=false');
            const _vw = mobile ? 414 : 1280, _vh = mobile ? 896 : 900;
            wv.setAttribute('style', 'position:fixed;left:-20000px;top:0;width:' + _vw + 'px;height:' + _vh + 'px;opacity:0;pointer-events:none;border:0;');
            const _ua = mobile ? MOBILE_UA : this.dynamicUserAgent;
            if (_ua) { try { wv.setAttribute('useragent', _ua); } catch (e) {} }

            const kill = "(function(){"
                + "try{['script','style','noscript','template','svg','canvas','video','audio','iframe'].forEach(function(t){document.querySelectorAll(t).forEach(function(n){try{n.remove()}catch(e){}})});}catch(e){}"
                + "try{var sel='nav,footer,header,aside,[role=banner],[role=contentinfo],[aria-modal=true],[class*=cookie],[id*=cookie],[class*=consent],[class*=paywall]';sel.split(',').forEach(function(s){try{document.querySelectorAll(s).forEach(function(n){try{var r=n.getBoundingClientRect?n.getBoundingClientRect():{width:0,height:0};if((r.width*r.height)>600000)return;n.remove();}catch(e){}})}catch(e){}});}catch(e){}"
                + "try{var walls='" + WALLS_SEL + "';walls.split(',').forEach(function(s){try{document.querySelectorAll(s).forEach(function(n){try{n.remove()}catch(e){}})}catch(e){}});}catch(e){}"
                + "try{return JSON.stringify({title:document.title||'',finalUrl:(window.location?window.location.href:''),body:(document.body?document.body.innerHTML:''),txt:((document.body&&document.body.innerText)||'').slice(0,4000),cookieLen:(document.cookie||'').length,ua:(navigator.userAgent||'').slice(0,60),net:(window.__netcap||[]).slice(0,50)});}catch(e){return JSON.stringify({title:'',finalUrl:'',body:'',txt:'',cookieLen:0,ua:'',net:[]});}"
                + "})()";

            // S248：dom-ready 后注入 fetch/XHR 收集，SPA 数据请求成败一眼可见（≤50 条，随 kill 一并回传）
            const NETCAP = "(function(){try{if(window.__netcap)return 'dup';window.__netcap=[];"
                + "var push=function(u,s){try{if(window.__netcap.length<50)window.__netcap.push({u:String(u).slice(0,180),s:s|0});}catch(e){}};"
                + "var of_=window.fetch;if(of_){window.fetch=function(i){var u=(i&&i.url)||String(i);return of_.apply(this,arguments).then(function(r){push(u,r&&r.status);return r;},function(e){push(u,-1);throw e;});};}"
                + "var oo=XMLHttpRequest.prototype.open,os=XMLHttpRequest.prototype.send;"
                + "XMLHttpRequest.prototype.open=function(m,u){this.__u=u;return oo.apply(this,arguments);};"
                + "XMLHttpRequest.prototype.send=function(){var x=this;x.addEventListener('loadend',function(){push(x.__u,x.status);});return os.apply(this,arguments);};"
                + "return 'ok';}catch(e){return 'err';}})()";

            // S248：骨架屏启发式——短文本且命中 loading 占位文案 = 异步数据未落地，不算正文
            const STALL_RE = /(玩命加载|正在加载|加载中|页面加载中|请稍候|loading\.{0,3}|Loding)/i;
            const isStalled = function (d) {
                try {
                    const txt = (d && d.txt) || '';
                    return txt.replace(/\s+/g, '').length < 300 && STALL_RE.test(txt);
                } catch (e) { return false; }
            };
            let stallSeen = false;

            // 抽取当前 DOM；有正文则 finish 结束（partialFlag=超时兜底，附 reason；S248 骨架屏不算正文）
            const grab = (partialFlag, reason) => {
                if (done) return Promise.resolve(true);
                return wv.executeJavaScript(kill).then(function (s) {
                    let d = {}; try { d = JSON.parse(s); } catch (e) {}
                    let body = (d && d.body) || '';
                    if (body.length > 400000) body = body.slice(0, 400000);
                    if (!partialFlag && isStalled(d)) { stallSeen = true; return false; }
                    if (body.trim()) {
                        finish({
                            ok: true, partial: !!partialFlag, reason: partialFlag ? (reason || 'async_load_stalled') : '',
                            title: (d && d.title) || '', finalUrl: (d && d.finalUrl) || url, html: body,
                            net: (d && d.net) || [], cookieLen: (d && d.cookieLen) || 0, ua: (d && d.ua) || ''
                        });
                        return true;
                    }
                    return false;
                }).catch(function () { return false; });
            };

            // 总超时：先兜底抽取当前 DOM（拿到=部分内容），拿不到才判失败；按是否曾 DCL 分类
            hardTimer = setTimeout(function () {
                grab(true, 'async_load_stalled').then(function (got) {
                    if (!got) finish({ ok: false, url: url, error: domReadySeen ? 'no-content' : 'render timeout', stage: lastStage });
                });
            }, totalMs);

            wv.addEventListener('did-fail-load', function (e) {
                if (!(e && e.isMainFrame === true)) return;
                if (e.errorCode === -3) return; // ERR_ABORTED（多由重定向触发，忽略）
                grab(false).then(function (got) {
                    if (!got) finish({ ok: false, url: url, error: 'load failed', code: e.errorCode, desc: e.errorDescription || '', stage: 'net' });
                });
            });
            wv.addEventListener('did-stop-loading', function () { lastStage = 'load-stop'; grab(false); });

            wv.addEventListener('dom-ready', function () {
                domReadySeen = true; lastStage = 'dom-ready';
                try { wv.executeJavaScript(NETCAP).catch(function () {}); } catch (e) {}
                if (waitText) {
                    const start = Date.now();
                    const poll = function () {
                        if (done) return;
                        wv.executeJavaScript('((document.body&&document.body.innerText)||"").indexOf(' + JSON.stringify(waitText) + ')>=0').then(function (found) {
                            if (done) return;
                            if (found) grab(false);
                            else if (Date.now() - start > totalMs) grab(true, 'wait_text_not_seen').then(function (got) { if (!got) finish({ ok: false, url: url, error: 'wait-text-timeout', stage: 'waittext' }); });
                            else setTimeout(poll, 500);
                        }).catch(function () { grab(false); });
                    };
                    setTimeout(poll, 300);
                } else {
                    // DCL 已触发：给 SPA 几次机会抓正文；仍空且页面不再加载则判空，避免登录墙也死等
                    let tries = 0;
                    const probe = function () {
                        if (done) return;
                        grab(false).then(function (got) {
                            if (got) return;
                            if (tries++ < 4) setTimeout(probe, 800);
                            else if (!wv.isLoading() && !stallSeen) finish({ ok: true, url: url, title: '', finalUrl: url, html: '' });
                        });
                    };
                    setTimeout(probe, 600);
                }
            });

            try {
                wv.src = url;
                document.body.appendChild(wv);
            } catch (e) {
                finish({ ok: false, url: url, error: 'attach failed', desc: (e && e.message) || '' });
            }
        });
    },

    // --- 14. S253：虚拟滚动列表「滚动搜索+点击」原语（贴吧/信息流卡片无 href、点击才路由）---
    // match：CSS 选择器（querySelector 命中即按选择器）或可见文本（最小含文本小块）。
    // action：click=合成点击并等新路由；extract=抠 href/data-*；none=命中即报。
    async scrollAndFind(match, action = "none", maxScrolls = 30, pauseMs = 700, attribute = "") {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const m = String(match || "").trim();
        if (!m) return "Error: scroll_and_find 需要 match（文本或 CSS 选择器）";
        const act = ["click", "extract", "none"].includes(action) ? action : "none";
        let rounds = parseInt(maxScrolls) || 30; rounds = Math.max(1, Math.min(rounds, 100));
        const pause = Math.max(200, Math.min(parseInt(pauseMs) || 700, 4000));
        const attr = String(attribute || "");
        const api = window.electronAPI || {};
        let wcId = 0; try { wcId = wv.getWebContentsId(); } catch (e) {}
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        const hrefExpr = "(function(){return String(window.location?window.location.href:'');})()";
        // S254：人机等价输入——人的滚轮/点击是浏览器输入事件(命中测试自动派发到自己滚的容器)；
        // 旧实现 window.scrollBy 在内层容器滚动的页面(贴吧 uniapp .uni-frs)整体空转。
        // 现：真 wheel(CDP isTrusted)优先 → 内层容器 scrollBy → window 兜底；点击真事件优先。
        const vpExpr = "(function(){return JSON.stringify({w:window.innerWidth||1,h:window.innerHeight||1});})()";
        let vp = { w: 1280, h: 800 };
        try { vp = JSON.parse(await this._wvExec(wv, vpExpr) || "{}") || vp; } catch (e) {}
        const cx = Math.max(24, Math.round(vp.w * 0.5)), cy = Math.max(24, Math.round(vp.h * 0.55));
        const stepPx = Math.max(200, Math.round(vp.h * 0.85));
        // 进度=当前活跃 scroller（window 与最大可滚容器取 scrollTop 更大者）
        const posExpr = "(function(){var se=document.scrollingElement||document.documentElement;"
            + "var winP=Math.round(se.scrollTop||window.scrollY||0),winM=Math.max(0,se.scrollHeight-window.innerHeight);"
            + "var c=document.querySelector('[data-sap-sc]');if(c){try{var cp=Math.round(c.scrollTop),cm=Math.max(0,c.scrollHeight-c.clientHeight);"
            + "if(cp>=winP)return JSON.stringify({p:cp,max:cm});}catch(e){}}"
            + "return JSON.stringify({p:winP,max:winM});})()";
        // 找最大纵向可滚元素并打标（容器模式用；页面重构后标记丢失会重新探测）
        const probeExpr = "(function(){var els=document.querySelectorAll('div,main,ul,section');var best=null,br=0;"
            + "for(var i=0;i<els.length;i++){var el=els[i];try{var st=window.getComputedStyle(el);if(!/auto|scroll/.test(st.overflowY))continue;"
            + "var r=el.getBoundingClientRect();if(r.height<200)continue;var rg=el.scrollHeight-el.clientHeight;if(rg>br){br=rg;best=el;}}catch(e){}}"
            + "var old=document.querySelectorAll('[data-sap-sc]');for(var k=0;k<old.length;k++){try{old[k].removeAttribute('data-sap-sc');}catch(e){}}"
            + "if(best){try{best.setAttribute('data-sap-sc','1');}catch(e){}}"
            + "return JSON.stringify({container:!!best,container_range:Math.round(br)});})()";
        let mode = "window";
        let pos0 = { p: 0, max: 0 };
        try { pos0 = JSON.parse(await this._wvExec(wv, posExpr) || "{}") || pos0; } catch (e) {}
        if (api.cdpInputWheel && wcId) {
            try {
                // S277：探测必须限时——弹窗期间该 IPC 会永挂，无限 await 会吞掉全部 JS 回退。
                const r = await _inputTmo(api.cdpInputWheel({ wcId, x: cx, y: cy, deltaY: 480, steps: 4 }), 1200);
                await sleep(450);
                const pos1 = JSON.parse(await this._wvExec(wv, posExpr) || "{}") || {};
                if (r && r.ok && Math.abs((pos1.p || 0) - (pos0.p || 0)) > 8) mode = "wheel";
            } catch (e) {}
        }
        if (mode !== "wheel") {
            try {
                const pr = JSON.parse(await this._wvExec(wv, probeExpr) || "{}") || {};
                if (pr.container && (pr.container_range || 0) > 100) mode = "container";
            } catch (e) {}
        }
        const doScroll = async () => {
            if (mode === "wheel") {
                try { const r = await _inputTmo(api.cdpInputWheel({ wcId, x: cx, y: cy, deltaY: stepPx, steps: 4 }), 2500); if (r && r.ok) return; } catch (e) {}
                mode = "container";
            }
            if (mode === "container") {
                let ok = "";
                try { ok = String(await this._wvExec(wv, "(function(){var c=document.querySelector('[data-sap-sc]');if(!c)return 'gone';try{c.scrollBy(0," + stepPx + ");return 'ok';}catch(e){return 'err';}})()") || ""); } catch (e) {}
                if (ok === "ok") return;
                let pr = {}; try { pr = JSON.parse(await this._wvExec(wv, probeExpr) || "{}") || {}; } catch (e) {}
                if (pr.container) { try { await this._wvExec(wv, "(function(){var c=document.querySelector('[data-sap-sc]');if(c){try{c.scrollBy(0," + stepPx + ");}catch(e){}}})()"); } catch (e) {} return; }
                mode = "window";
            }
            try { await this._wvExec(wv, "(function(){window.scrollBy(0," + stepPx + ");})()"); } catch (e) {}
        };
        // S256：文本匹配先规范化（贴吧卡片 innerText 混排零宽字符/空白碎片会让裸 indexOf 失配）；
        // 命中后向上走最近可点单元（a/li/tr/onclick/card类）——最小文本块常是无点击反应的 span 碎片。
        const findExpr = "(function(){var m=" + JSON.stringify(m) + ";var attr=" + JSON.stringify(attr) + ";"
            + "var nf=function(s){return String(s).replace(/[\\u200b-\\u200f\\u2060\\ufeff\\u00ad]+/g,'').replace(/\\s+/g,' ').trim().toLowerCase()};"
            + "var clk=function(e){var x=e;for(var j=0;j<6&&x&&x!==document.body;j++){var tg=(x.tagName||'').toLowerCase();"
            + "var cls='';try{cls=String(x.className&&x.className.baseVal!==undefined?x.className.baseVal:x.className)||'';}catch(_e){}"
            + "if(tg==='a'||tg==='li'||tg==='tr'||tg==='button'||(x.onclick)||(x.getAttribute&&x.getAttribute('onclick'))||/card|item|post|thread|topic|row/i.test(cls))return x;"
            + "x=x.parentElement;}return e;};"
            + "var el=null;try{el=document.querySelector(m);}catch(e){}"
            + "if(!el){var mm=nf(m);var all=document.querySelectorAll('a,li,[class*=card],[class*=item],[class*=post],[class*=thread],div,td,tr');"
            + "for(var i=0;i<all.length;i++){var c=all[i];try{if(!c.offsetParent)continue;var t=nf(c.innerText||'');"
            + "if(!mm){continue;}if(t.length>1200||t.indexOf(mm)<0)continue;if(!el||t.length<nf(el.innerText||'').length)el=c;}catch(e){}}"
            + "if(el)el=clk(el);}"
            + "if(!el)return JSON.stringify({found:false});"
            + "try{el.scrollIntoView({block:'center'});}catch(e){}"
            + "var r={width:0,height:0,left:0,top:0};try{r=el.getBoundingClientRect();}catch(e){}"
            + "var out={found:true,tag:el.tagName.toLowerCase(),text:(el.innerText||'').slice(0,160).replace(/\\s+/g,' '),href:el.getAttribute?el.getAttribute('href')||'':''};"
            + "out.cx=Math.round((r.left||0)+r.width/2);out.cy=Math.round((r.top||0)+r.height/2);"
            + "out.inview=!!(r.width>0&&r.height>0&&(r.top||0)>=0&&(r.top||0)<=(window.innerHeight||0));"
            + "if(attr){try{out.attr=el.getAttribute(attr)||'';}catch(e){out.attr='';}}"
            + "window.__sapInner=el;"
            + "return JSON.stringify(out);})()";
        const pollUrl = async (before) => {
            for (let k = 0; k < 10; k++) {
                await sleep(300);
                let a = ""; try { a = String(await this._wvExec(wv, hrefExpr) || ""); } catch (e) { break; }
                if (a && a !== before) return a;
            }
            return before;
        };
        const trustedOrSyntheticClick = async (x, y) => {
            if (api.cdpInputClick && wcId && x > 0 && y > 0) {
                try { const r = await _inputTmo(api.cdpInputClick({ wcId, x, y }), 3000); if (r && r.ok) return "trusted"; } catch (e) {}
            }
            try { await this._wvExec(wv, "(function(){try{window.__sapInner&&window.__sapInner.click();}catch(e){}})()"); } catch (e) {}
            return "synthetic";
        };
        let stable = 0, lastP = -1, lastMax = -1, pos = pos0, execErr = "";
        for (let i = 0; i < rounds; i++) {
            let hit = {};
            try { hit = JSON.parse(await this._wvExec(wv, findExpr) || "{}"); } catch (e) { execErr = String((e && e.message) || e).slice(0, 140); }
            if (hit.found) {
                hit.scroll_rounds = i;
                hit.scroller_mode = mode;
                if (act === "click") {
                    let before = ""; try { before = String(await this._wvExec(wv, hrefExpr) || ""); } catch (e) {}
                    hit.click_via = await trustedOrSyntheticClick(hit.cx, hit.cy);
                    let after = await pollUrl(before);
                    if (after === before) {
                        // 外层无路由反应 → 点内层交互子目标（a/标题），仍真点击优先
                        let ic = {};
                        try {
                            ic = JSON.parse(await this._wvExec(wv, "(function(){var h=window.__sapInner;if(!h)return JSON.stringify({found:false});"
                                + "var t=null;try{t=h.querySelector('a,[role=button],h3,h4,[class*=title],[class*=name]');}catch(e){}"
                                + "if(!t)t=h;try{t.scrollIntoView({block:'center'});}catch(e){}window.__sapInner=t;"
                                + "var r={width:0,height:0,left:0,top:0};try{r=t.getBoundingClientRect();}catch(e){}"
                                + "return JSON.stringify({found:true,cx:Math.round((r.left||0)+r.width/2),cy:Math.round((r.top||0)+r.height/2)});})()") || "{}") || {};
                        } catch (e) {}
                        if (ic.found) {
                            const via2 = await trustedOrSyntheticClick(ic.cx, ic.cy);
                            hit.click_via2 = via2;
                            after = await pollUrl(before);
                        }
                    }
                    hit.url_before = before;
                    hit.url_after = after;
                    hit.url_changed = !!(after && after !== before);
                    if (!hit.url_changed) hit.note = "clicked but URL unchanged（可能是本页路由弹窗——直接 take_snapshot/get_page_markdown 看新状态；或卡片非目标）";
                    else hit.hint = "url_after 即目标页，可直接 web_render/get_page_markdown 读取";
                }
                return JSON.stringify(hit);
            }
            await doScroll();
            await sleep(pause);
            try { pos = JSON.parse(await this._wvExec(wv, posExpr) || "{}") || pos; } catch (e) {}
            if (pos.p + vp.h >= pos.max - 6) {
                if (pos.p === lastP && pos.max === lastMax) { stable++; if (stable >= 2) break; } else stable = 0;
            } else if (pos.p === lastP && pos.max === lastMax && mode === "window" && pos.max === 0) {
                stable++; if (stable >= 2) break; // window 无滚动范围且容器探测也没戏
            }
            lastP = pos.p; lastMax = pos.max;
        }
        return JSON.stringify({ found: false, scroller_mode: mode, scrolled_to: pos.p, scrollable_max: pos.max, exec_err: execErr || undefined, note: "到底/达轮数上限仍未命中：换 match 措辞、加大 max_scrolls，或用 network_watch 抓列表接口 JSON 拿 tid（页面若被吧务移档则主列表永远刷不出）" + (execErr ? "；注意：探测脚本执行报错(" + execErr + ")，命中检测可能未生效，非目标不存在" : "") });
    },

    // --- 14b. S269：虚拟列表「收割」原语——滚动→等新节点挂载→按 fields 批量抽卡→去重，
    // 引擎内循环直到 until 条件命中，一次调用替代 agent 手搓逐屏 snapshot+人工去重。 ---
    // opts:{item(卡片根选择器), fields({字段名:"选择器"|"选择器@属性"}), key(去重字段名,可省),
    //        max_items, max_scrolls, pause_ms, no_new_rounds, older_than(时间线), date_field}
    async collectList(opts = {}) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        let o = opts;
        if (typeof o === "string") { try { o = JSON.parse(o); } catch (e) { o = null; } }
        if (!o || typeof o !== "object") return "Error: collect_list opts 需为 JSON 对象";
        const itemSel = String(o.item || "").trim();
        if (!itemSel) return "Error: collect_list 需要 item（卡片根 CSS 选择器，如 '.thread-card-wrapper'）";
        let fields = (o.fields && typeof o.fields === "object" && !Array.isArray(o.fields)) ? o.fields : null;
        if (fields) {
            const ks = Object.keys(fields);
            if (ks.length > 8) { const cut = {}; ks.slice(0, 8).forEach(function (k) { cut[k] = fields[k]; }); fields = cut; }
        }
        if (!fields || !Object.keys(fields).length) return "Error: collect_list 需要 fields（{字段名: 选择器}，取属性用 '选择器@href'，至少 1 个）";
        const keyField = String(o.key || "");
        let maxItems = parseInt(o.max_items) || 120; maxItems = Math.max(1, Math.min(maxItems, 500));
        let rounds = parseInt(o.max_scrolls) || 40; rounds = Math.max(1, Math.min(rounds, 80));
        const pause = Math.max(200, Math.min(parseInt(o.pause_ms) || 800, 4000));
        let noNewK = parseInt(o.no_new_rounds) || 3; noNewK = Math.max(1, Math.min(noNewK, 10));
        const olderThanMs = o.older_than ? Date.parse(String(o.older_than)) : NaN;
        const dateField = String(o.date_field || "");
        const sleepAt = (ms) => new Promise(r => setTimeout(r, ms));
        const sc = await this._makeScroller(wv);
        // 每轮扫描：按 item 抽卡→fields 逐项 text/attr（空白规范化、单值≤240字符、单轮≤200卡）
        const extractExpr = "(function(){var sel=" + JSON.stringify(itemSel) + ";var F=" + JSON.stringify(fields)
            + ";var nf=function(s){return String(s==null?'':s).replace(/[\\u200b-\\u200f\\u2060\\ufeff\\u00ad]+/g,'').replace(/\\s+/g,' ').trim()};var cards;"
            + "try{cards=document.querySelectorAll(sel);}catch(e){return JSON.stringify({sel_err:String(e&&e.message||e),recs:[]});}"
            + "var out=[];for(var i=0;i<cards.length&&out.length<200;i++){var c=cards[i];var rec={};var any=false;"
            + "for(var k in F){var qs=String(F[k]||'');var at='';var j=qs.lastIndexOf('@');"
            + "if(j>0&&qs.indexOf(']',j)<0&&qs.indexOf(String.fromCharCode(34),j)<0){var maybe=qs.slice(j+1);"
            + "if(/^[a-z0-9_:.-]+$/i.test(maybe)){at=maybe;qs=qs.slice(0,j);}}"
            + "var e2=null;try{e2=qs?c.querySelector(qs):c;}catch(_x){}"
            + "var v='';if(e2){if(at){try{v=nf(e2.getAttribute(at));}catch(_y){}}else{v=nf(e2.innerText||e2.textContent||'');}}"
            + "if(v.length>240)v=v.slice(0,240);rec[k]=v;if(v)any=true;}"
            + "if(any)out.push(rec);}"
            + "return JSON.stringify({cards:cards.length,recs:out});})()";
        const map = new Map();
        let noNew = 0, stop = "", roundsUsed = 0, execErr = "", lastCards = 0;
        for (let i = 0; i < rounds; i++) {
            roundsUsed = i + 1;
            let got = {};
            try { got = JSON.parse(await this._wvExec(wv, extractExpr) || "{}") || {}; } catch (e) { execErr = String((e && e.message) || e).slice(0, 140); }
            if (got.sel_err) return JSON.stringify({ error: "item 选择器非法: " + got.sel_err });
            lastCards = got.cards || 0;
            const recs = Array.isArray(got.recs) ? got.recs : [];
            let added = 0, hitOlder = false;
            for (let rIdx = 0; rIdx < recs.length; rIdx++) {
                const r = recs[rIdx];
                let k = (keyField && r && r[keyField]) ? String(r[keyField]) : JSON.stringify(r);
                if (map.has(k)) continue;
                map.set(k, r); added++;
                if (Number.isFinite(olderThanMs) && dateField) {
                    const t = Date.parse((r && r[dateField]) || "");
                    if (Number.isFinite(t) && t < olderThanMs) hitOlder = true;
                }
                if (map.size >= maxItems) { stop = "max_items"; break; }
            }
            if (stop === "max_items") break;
            if (added === 0) noNew++; else noNew = 0;
            if (hitOlder) { stop = "older_than"; break; }
            if (noNew >= noNewK) { stop = "no_new_rounds"; break; }
            const pos = await sc.readPos();
            if (pos.p + sc.vh >= pos.max - 6) {
                if (pos.p === sc.lastP && pos.max === sc.lastMax) { sc.stable++; if (sc.stable >= 2) { stop = "bottom"; break; } } else sc.stable = 0;
            } else if (pos.p === sc.lastP && pos.max === sc.lastMax && sc.mode === "window" && pos.max === 0) {
                sc.stable++; if (sc.stable >= 2) { stop = "bottom"; break; }
            }
            sc.lastP = pos.p; sc.lastMax = pos.max;
            await sc.scrollOnce();
            await sleepAt(pause);
        }
        if (!stop) stop = "max_scrolls";
        const items = Array.from(map.values()).slice(0, maxItems);
        // S295：零命中不再只回 collected=0——附页面"最像列表容器"的 DOM 骨架，
        // 让模型一轮就能改对 item/fields 选择器，而不是反复盲试。
        let skel;
        if (items.length === 0) {
            try {
                skel = await this._wvExec(wv, "(function(){try{if(!document.body)return 'no-body';"
                    + "function nm(e){var c=(typeof e.className==='string'&&e.className.trim())?'.'+e.className.trim().split(/\\s+/)[0]:'';return e.tagName.toLowerCase()+c;}"
                    + "var all=document.body.querySelectorAll('*');var best=null,bn=0,n=0;"
                    + "for(var i=0;i<all.length&&n<3000;i++){var el=all[i];var tg=el.tagName;"
                    + "if(tg==='DIV'||tg==='UL'||tg==='OL'||tg==='LI'||tg==='TBODY'){n++;if(el.children.length>bn&&el.children.length>=3){bn=el.children.length;best=el;}}}"
                    + "if(!best)return 'no-repeat-container（页面无 ≥3 子节点的重复结构，item 选择器多半选错层级或页面未加载出列表）';"
                    + "var lines=['container: '+nm(best)+' children='+best.children.length];"
                    + "for(var j=0;j<Math.min(best.children.length,5);j++){var ch=best.children[j];var s='  '+nm(ch);var g=[];"
                    + "for(var k=0;k<Math.min(ch.children.length,6);k++)g.push(nm(ch.children[k]));"
                    + "if(g.length)s+=' > '+g.join(', ');lines.push(s);}"
                    + "return lines.join('\\n').slice(0,600);}catch(e){return 'outline_err';}})()");
            } catch (e) { skel = ''; }
            if (typeof skel !== 'string') skel = String(skel || '');
        }
        return JSON.stringify({ collected: items.length, rounds: roundsUsed, stop_reason: stop, scroller_mode: sc.mode, cards_last_scan: lastCards, exec_err: execErr || undefined, skeleton: skel || undefined, hint: (items.length === 0 ? (lastCards > 0 ? 'cards_last_scan>0 但字段全空：fields 选择器没取到内容，参考 skeleton 修正字段路径' : 'cards_last_scan=0：item 选择器一个卡片都没匹配上，参考 skeleton 换选择器') : undefined), items: items });
    },

    // S277：应急复位——清除当前标签的触摸/移动端/UA/视口仿真残留（专治"光标变触摸点、
    // 点击需双击"）。主进程 force 清全套 CDP 覆盖并恢复默认 UA；渲染层同步 tab.mobile
    // 与 414px 收窄样式。reload=true 时顺带重载页面（默认否，先救输入再决定要不要刷页面）。
    async resetPageState(reload) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        let wcId = 0; try { wcId = wv.getWebContentsId(); } catch (e) {}
        if (!wcId) return "Error: could not resolve webContents id";
        const api = window.electronAPI || {};
        if (!api.emulationReset) return "Error: emulation reset bridge unavailable";
        let r = {};
        try { r = (await _inputTmo(api.emulationReset(wcId), 8000)) || {}; } catch (e) { r = { ok: false, err: String((e && e.message) || e) }; }
        if (!r.ok) return "reset_page_state failed: " + (r.err || "unknown") + "（DevTools 可能占用调试器：关闭 DevTools 后重试）";
        try {
            const tab = (this.browserTabs || []).find(t => t.id === this.currentTabId);
            if (tab && tab.mobile) tab.mobile = false;
            wv.style.flex = ''; wv.style.width = ''; wv.style.alignSelf = '';
        } catch (e) {}
        if (reload === true || reload === "true") { try { wv.reload(); } catch (e) {} }
        return "reset_page_state: touch/UA/viewport emulation cleared" + (reload ? " + reloaded" : "") + "（如页面外观仍是移动版，reload 后生效）";
    },

    // S278：取回本标签的自动决策记账并清空（下载接管/上传框拦截/弹窗处置/离页放行/权限拒绝）。
    // 语义同 check_redirect：读了就消，之后新事件再累积。pageIndex 可选（缺省=当前活动标签）。
    async browserPolicyReport(pageIndex) {
        let wv = null;
        try {
            const idx = parseInt(pageIndex);
            if (!isNaN(idx)) {
                const tab = (this.browserTabs || [])[idx];
                if (tab) wv = this.getWebview(tab.id);
            }
        } catch (e) {}
        if (!wv) wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        let wcId = 0; try { wcId = wv.getWebContentsId(); } catch (e) {}
        if (!wcId) return "Error: could not resolve webContents id";
        const api = window.electronAPI || {};
        if (!api.browserPolicyTake) return "Error: policy bridge unavailable";
        let r = [];
        try { r = (await _inputTmo(api.browserPolicyTake(wcId), 5000)) || []; } catch (e) { return "browser_policy_report failed: " + String((e && e.message) || e); }
        if (!Array.isArray(r) || !r.length) return "browser_policy_report: no auto-decisions on this tab";
        const lines = r.map((x) => {
            let hm = ''; try { hm = new Date(x.ts * 1000).toTimeString().slice(0, 5) + ' '; } catch (e) {}
            return hm + '[' + x.kind + '] ' + x.note;
        });
        return "[policy] " + lines.join("\n") + "\n(共 " + lines.length + " 条，本次已清空；后续新事件可再次查询)";
    },

    // S269：collectList 专用滚动器——通道探测与 scrollAndFind 同款：
    // 真轮(CDP isTrusted)优先 → 内层最大可滚容器(打标 data-sap-sc) → window 兜底。
    async _makeScroller(wv) {
        const api = window.electronAPI || {};
        let wcId = 0; try { wcId = wv.getWebContentsId(); } catch (e) {}
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        const vpExpr = "(function(){return JSON.stringify({w:window.innerWidth||1,h:window.innerHeight||1});})()";
        let vp = { w: 1280, h: 800 };
        try { vp = JSON.parse(await this._wvExec(wv, vpExpr) || "{}") || vp; } catch (e) {}
        const cx = Math.max(24, Math.round(vp.w * 0.5)), cy = Math.max(24, Math.round(vp.h * 0.55));
        const stepPx = Math.max(200, Math.round(vp.h * 0.85));
        const posExpr = "(function(){var se=document.scrollingElement||document.documentElement;"
            + "var winP=Math.round(se.scrollTop||window.scrollY||0),winM=Math.max(0,se.scrollHeight-window.innerHeight);"
            + "var c=document.querySelector('[data-sap-sc]');if(c){try{var cp=Math.round(c.scrollTop),cm=Math.max(0,c.scrollHeight-c.clientHeight);"
            + "if(cp>=winP)return JSON.stringify({p:cp,max:cm});}catch(e){}}"
            + "return JSON.stringify({p:winP,max:winM});})()";
        const probeExpr = "(function(){var els=document.querySelectorAll('div,main,ul,section');var best=null,br=0;"
            + "for(var i=0;i<els.length;i++){var el=els[i];try{var st=window.getComputedStyle(el);if(!/auto|scroll/.test(st.overflowY))continue;"
            + "var r=el.getBoundingClientRect();if(r.height<200)continue;var rg=el.scrollHeight-el.clientHeight;if(rg>br){br=rg;best=el;}}catch(e){}}"
            + "var old=document.querySelectorAll('[data-sap-sc]');for(var k=0;k<old.length;k++){try{old[k].removeAttribute('data-sap-sc');}catch(e){}}"
            + "if(best){try{best.setAttribute('data-sap-sc','1');}catch(e){}}"
            + "return JSON.stringify({container:!!best,container_range:Math.round(br)});})()";
        const self = this;
        const sc = { mode: "window", vh: vp.h || 800, lastP: -1, lastMax: -1, stable: 0 };
        let pos0 = { p: 0, max: 0 };
        try { pos0 = JSON.parse(await this._wvExec(wv, posExpr) || "{}") || pos0; } catch (e) {}
        if (api.cdpInputWheel && wcId) {
            try {
                // S277：限时探测（同 scrollAndFind），悬挂时立即落到 JS 滚动阶梯。
                const r = await _inputTmo(api.cdpInputWheel({ wcId, x: cx, y: cy, deltaY: 480, steps: 4 }), 1200);
                await sleep(450);
                const pos1 = JSON.parse(await this._wvExec(wv, posExpr) || "{}") || {};
                if (r && r.ok && Math.abs((pos1.p || 0) - (pos0.p || 0)) > 8) sc.mode = "wheel";
            } catch (e) {}
        }
        if (sc.mode !== "wheel") {
            try {
                const pr = JSON.parse(await this._wvExec(wv, probeExpr) || "{}") || {};
                if (pr.container && (pr.container_range || 0) > 100) sc.mode = "container";
            } catch (e) {}
        }
        sc.scrollOnce = async () => {
            if (sc.mode === "wheel") {
                try { const r = await _inputTmo(api.cdpInputWheel({ wcId, x: cx, y: cy, deltaY: stepPx, steps: 4 }), 2500); if (r && r.ok) return; } catch (e) {}
                sc.mode = "container";
            }
            if (sc.mode === "container") {
                let ok = "";
                try { ok = String(await self._wvExec(wv, "(function(){var c=document.querySelector('[data-sap-sc]');if(!c)return 'gone';try{c.scrollBy(0," + stepPx + ");return 'ok';}catch(e){return 'err';}})()") || ""); } catch (e) {}
                if (ok === "ok") return;
                let pr = {}; try { pr = JSON.parse(await self._wvExec(wv, probeExpr) || "{}") || {}; } catch (e) {}
                if (pr.container) { try { await self._wvExec(wv, "(function(){var c=document.querySelector('[data-sap-sc]');if(c){try{c.scrollBy(0," + stepPx + ");}catch(e){}}})()"); } catch (e) {} return; }
                sc.mode = "window";
            }
            try { await self._wvExec(wv, "(function(){window.scrollBy(0," + stepPx + ");})()"); } catch (e) {}
        };
        sc.readPos = async () => {
            let p = { p: 0, max: 0 };
            try { p = JSON.parse(await self._wvExec(wv, posExpr) || "{}") || p; } catch (e) {}
            return p;
        };
        return sc;
    },

    // --- 15. S253：内置网络观察（替代 agent 手搓 XHR 钩子）：start 挂钩 → 浏览/滚动 → read 增量收割 ---
    // S258：钩子脚本上提为 _netwArmExpr（start 与 dom-ready 自动重挂共用），带幂等守卫。
    // S263：BODY 驻留 CAP 200→80——300KB×200≈60MB/页在贴吧重页上叠加渲染过载（卡顿事故降载）。
    _netwArmExpr(bodyOn) {
        return "(function(){try{if(window.__netw&&window.__netw.armed)return 'armed';var E=[];var BODY=" + (bodyOn ? "true" : "false") + ";var CAP=BODY?80:500;"
            + "window.__netw={armed:true,body:BODY,entries:E,c:0};"
            + "function rec(u,s,r){try{if(E.length>=CAP)return;var o={u:String(u).slice(0,300),s:s|0,t:Date.now()};E.push(o);"
            + "if(BODY&&r&&r.clone){try{r.clone().text().then(function(x){o.bf=x.slice(0,307200);}).catch(function(){});}catch(_e){}};}catch(e){}}"
            + "var of_=window.fetch;if(of_){window.fetch=function(i){var u=(i&&i.url)||String(i);return of_.apply(this,arguments).then(function(r){rec(u,r&&r.status,r);return r;},function(e){rec(u,-1);throw e;});};}"
            + "var oo=XMLHttpRequest.prototype.open,os=XMLHttpRequest.prototype.send;"
            + "XMLHttpRequest.prototype.open=function(m2,u){this.__wu=u;return oo.apply(this,arguments);};"
            + "XMLHttpRequest.prototype.send=function(){var x=this;x.addEventListener('loadend',function(){var L=E.length;rec(x.__wu,x.status);"
            + "if(BODY&&L<E.length){try{var b=x.responseText||'';if(b)E[L].bf=b.slice(0,307200);}catch(e){}}});return os.apply(this,arguments);};"
            + "return 'armed';}catch(e){return 'arm_err:'+String(e&&e.message||e);}})()";
    },
    networkWatch(mode = "start", pattern = "", includeBody = false, pullIdx = -1, trigger = null) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        // S254：include_body 时全量响应体留 guest(o.bf ≤300KB)——2KB 截断曾让 agent 放弃内置钩子
        // 回头手搓（feed JSON parse 失败）。read 只回 2KB 预览+blen，超长正文由 Python 层
        // 经 pull 逐条拉全文落盘 uploaded_files，回 body_url。
        const arm = this._netwArmExpr(includeBody);
        const read = "(function(){var w=window.__netw;if(!w)return JSON.stringify({error:'not armed — call network_watch(mode=start) first'});"
            + "var pat=" + JSON.stringify(String(pattern || "")) + ";var E=w.entries||[];var from=w.c||0;"
            + "var items=[];var lastHit=-1;var skip={};var skipN=0;for(var i=from;i<E.length;i++){var o=E[i];"
            + "if(pat&&o.u.indexOf(pat)<0){skipN++;if(Object.keys(skip).length<12){try{var x=new URL(o.u,location.href);var k2=x.host+x.pathname;if(!skip[k2])skip[k2]=1;}catch(_e2){}}continue;}"
            + "lastHit=i;"
            + "var it={gi:i,u:o.u,s:o.s,t:o.t};var full=o.bf||'';"
            + "if(full){it.b=full.slice(0,2048);if(full.length>2048)it.blen=full.length;}"
            + "items.push(it);}"
            + "w.c=lastHit>=0?lastHit+1:from;"
            + "var out={total:E.length,new_items:items.length,returned:Math.min(items.length,60),origin:String(location.origin||''),items:items.slice(0,60)};"
            + "if(pat&&items.length===0&&skipN>0){out.skipped_urls=Object.keys(skip);out.note='pattern 命中 0 条，但本窗口有 ' + skipN + ' 个新请求被过滤——对照 skipped_urls 修正 pattern，或省略 pattern 直接 read 全部（S295：被过滤条目不再被游标吞掉，仍可补读）';}"
            + "return JSON.stringify(out);})()";
        const pull = "(function(){var w=window.__netw;var gi=" + (parseInt(pullIdx) || -1) + ";"
            + "if(!w||gi<0||!w.entries||!w.entries[gi])return '';return String(w.entries[gi].bf||'').slice(0,524288);})()";
        const stop = "(function(){try{if(window.__netw){window.__netw.entries.length=0;window.__netw.armed=false;window.__netw.stopped=true;}return 'stopped';}catch(e){return 'stop_err';}})()";
        // S260：重挂配置提升到 Vue 实例的 tab 维度（webview 元素会因 mobile↔桌面切换被重建，
        // S258 挂在元素上的监听随之蒸发）。任何 mode 进入都自愈：该 tab 有配置但当前元素没挂
        // 监听 → reattach 并给当前文档补 arm（脚本自带幂等守卫）。
        const tabId = this.currentTabId;
        this.__netwTabs = this.__netwTabs || {};
        const cfg = tabId ? this.__netwTabs[tabId] : null;
        if (cfg && !wv.__netwRe) {
            try {
                wv.__netwBody = !!cfg.body;
                const self0 = this;
                wv.__netwRe = function () {
                    try { wv.executeJavaScript(self0._netwArmExpr(wv.__netwBody)); } catch (e) {}
                };
                wv.addEventListener('dom-ready', wv.__netwRe);
                const p = wv.executeJavaScript(this._netwArmExpr(cfg.body));
                if (p && p.catch) p.catch(function () {});
            } catch (e) {}
        }
        return (async () => {
            try {
                if (mode === "start") {
                    // S258：start 后每次导航 dom-ready 自动重挂。
                    // S260：先等加载停止——导航中 guest executeJavaScript 必抛
                    // GUEST_VIEW_MANAGER_CALL（start 报 Electron Webview Error 的主因：
                    // agent 刚 reload 就 start，3 次重试窗口熬不过加载期）。
                    if (typeof wv.isLoading === "function" && wv.isLoading()) {
                        const done = await this._waitLoadStop(wv, 8000);
                        if (!done) return "network_watch start：页面仍在加载（已等 8s），挂钩未生效——加载完成后重试 start（幂等安全）；start 成功后每次导航都会自动重挂";
                    }
                    if (tabId) this.__netwTabs[tabId] = { body: !!includeBody };
                    try {
                        wv.__netwBody = !!includeBody;
                        if (wv.__netwRe) { try { wv.removeEventListener('dom-ready', wv.__netwRe); } catch (e) {} }
                        const self = this;
                        wv.__netwRe = function () {
                            try { wv.executeJavaScript(self._netwArmExpr(wv.__netwBody)); } catch (e) {}
                        };
                        wv.addEventListener('dom-ready', wv.__netwRe);
                    } catch (e) {}
                    const already = await this._wvExec(wv, "(function(){return !!(window.__netw&&window.__netw.armed);})()");
                    let armedNote;
                    if (already === true) {
                        armedNote = "already armed（保留已收集条目；要清空重收集先 stop 再 start）。导航后会自动重挂，无需手动处理";
                    } else {
                        const r = await this._wvExec(wv, arm);
                        armedNote = String(r || "armed");
                    }
                    // S270：一体化编排——挂钩成功后自动滚 N 轮触发列表接口→等待→立即收割首批。
                    // 目的：把『start→滚动→read』三步压成一步，且从时序上根除"先操作后挂钩"误序。
                    const trig = (trigger && typeof trigger === "object") ? trigger : null;
                    let trigN = trig ? (parseInt(trig.scrolls) || 0) : 0;
                    trigN = trigN > 0 ? Math.min(trigN, 20) : 0;
                    const trigWait = trig ? Math.max(300, Math.min(parseInt(trig.wait_ms) || 800, 5000)) : 800;
                    if (!trigN) {
                        return already === true ? JSON.stringify({ ok: true, note: armedNote }) : armedNote;
                    }
                    if (armedNote.indexOf("arm_err") === 0) {
                        return JSON.stringify({ ok: false, armed: armedNote, note: "钩子脚本执行失败，滚动触发已跳过；修复后重试 start" });
                    }
                    const sc = await this._makeScroller(wv);
                    for (let i = 0; i < trigN; i++) {
                        await sc.scrollOnce();
                        await sleep(trigWait);
                    }
                    let readData = {};
                    try { readData = JSON.parse(await this._wvExec(wv, read) || "{}") || {}; } catch (e) {}
                    return JSON.stringify({ ok: true, armed: armedNote, triggered_rounds: trigN, scroller_mode: sc.mode, read: readData });
                }
                if (mode === "read") {
                    // S258：正常路径 dom-ready 已自动重挂；到这里还丢说明是 start 之前的历史导航
                    const armed = await this._wvExec(wv, "(function(){return !!(window.__netw&&window.__netw.armed);})()");
                    if (armed !== true) return "network_watch: 钩子未挂（本标签从未 start 过）—— mode=start 挂上后，之后每次导航都会自动重挂；导航途中已发出的请求收不到，需要就 start 后 reload 再 read";
                    return String(await this._wvExec(wv, read) || "{}");
                }
                // S256：pull 显式放行 512K——默认 60000 网关会把大响应截成碎 JSON
                if (mode === "pull") return String(await this._wvExec(wv, pull, 524288) || "");
                if (mode === "stop") {
                    try { if (wv.__netwRe) { wv.removeEventListener('dom-ready', wv.__netwRe); delete wv.__netwRe; } } catch (e) {}
                    try { if (tabId) delete this.__netwTabs[tabId]; } catch (e) {}
                    await sleep(0);
                    return String(await this._wvExec(wv, stop) || "stopped");
                }
                return "Error: network_watch mode 需 start|read|stop";
            } catch (e) {
                return "networkWatch err: " + (e && e.message ? e.message : String(e));
            }
        })();
    }
});
