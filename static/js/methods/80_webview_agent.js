// 批 3 F2：自 vue_methods.js 搬移的 js/methods/80_webview_agent.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
// S229：移动端 App 拉活/扫码登录/全屏遮罩选择器（定向、避免误伤正文），供离屏清洗与反广告注入共用。
const WALLS_SEL = '[class*=open-app],[class*=openapp],[class*=callapp],[class*=call-native],[class*=call_native],[class*=download-app],[class*=downloadapp],[class*=app-download],[class*=app-banner],[class*=appopen],[class*=OpenApp],[class*=AppDownload],[class*=AppBanner],[class*=login-mask],[class*=loginMask],[class*=LoginMask],[id*=loginbox],[class*=scan-login],[class*=scanlogin],[class*=qrcode-login],[class*=QRLogin],[class*=modal-backdrop],[class*=interstitial],[class*=downloadTop],[id*=downloadTop]';
// S230：软档反广告选择器上提为常量，_applyAdblock 与 getPageHtml（markdown 路径）共用。
const AD_SOFT_SEL = '#onetrust-consent-sdk,#onetrust-banner-sdk,#onetrust-popup,.qc-cmp2-container,#cmpwrapper,#cookie-banner,#cookieConsent,.cookie-consent,.cookie-banner,[id^="didomi-"],#didomi-host,#didomi-consent,.adns-popup,.adns-overlay,iframe[src*="doubleclick"],iframe[src*="googlesyndication"],iframe[src*="adservice"],iframe[src*="amazon-adsystem"],ins.adsbygoogle,.adsbygoogle,div[id^="google_ads_"],div[class*="ad-slot"],[aria-label="Advertisement"]';
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
                    let iline = '[' + iuid + '] ' + irole + (nm ? ' "' + nm + '"' : '') + ' ' + Math.round(nw) + 'x' + Math.round(nh) + ' [' + loaded + ']' + off;
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
        
        try {
            const r = await this._wvExec(wv, script);
            return (typeof r === 'string') ? (r + loadNote) : r;
        } catch (e) {
            return "Vue Snapshot Error: " + e.message;
        }
    },

    // --- 2. 点击 (增加延迟) ---
    async webviewClick(uid, dblClick = false) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        wv.focus();
        const script = `
        (async function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return "Element not found: ${uid}";
            
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
        wv.focus();
        // 注意：这里需要把 value 传给 JS，使用 JSON.stringify 确保安全
        const script = `
        (async function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return "Element not found: ${uid}";
            
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
        wv.focus();
        const script = `
        (function() {
            const el = document.querySelector('[data-ai-id="${uid}"]');
            if (!el) return "Element not found";
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
            if (!rect) return "Element not found: " + uid;

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
    async webviewWaitFor(text, timeout) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        
        const script = `
        (function() {
            return new Promise((resolve) => {
                const start = Date.now();
                const check = () => {
                    // 1. 优先检查文本是否存在
                    if (document.body.innerText.includes(${JSON.stringify(text)})) {
                        resolve("Found: " + ${JSON.stringify(text)});
                    } 
                    // 2. 检查是否超时
                    else if (Date.now() - start > ${timeout}) {
                        // 3. 关键修改：超时后，检查页面加载状态
                        if (document.readyState === 'complete') {
                            // 页面已加载完毕，但文本未找到（S230: 明确 Not found 语义，不再用歧义短语）
                            resolve("Not found: " + ${JSON.stringify(text)} + " (page loaded)");
                        } else {
                            // 页面还在加载中，且超时
                            resolve("Timeout: " + ${JSON.stringify(text)} + " not found (page still loading)");
                        }
                    } 
                    // 4. 继续轮询
                    else {
                        setTimeout(check, 100);
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
                if (info.err) return "Screenshot Error: element not found: " + uid;
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
    getPageHtml() {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";
        if (wv.isLoading()) return "Error: Page is loading...";
        const kill = "(function(){"
            + "try{var sel=" + JSON.stringify(AD_SOFT_SEL + ',' + WALLS_SEL) + ";sel.split(',').forEach(function(s){try{document.querySelectorAll(s).forEach(function(n){try{n.remove()}catch(e){}})}catch(e){}});}catch(e){}"
            + "try{document.querySelectorAll('img[src^=\"data:\"]').forEach(function(n){try{n.remove()}catch(e){}});}catch(e){}"
            + "try{['script','style','noscript','template','svg','canvas','video','audio','iframe','nav','footer','header','aside'].forEach(function(t){document.querySelectorAll(t).forEach(function(n){try{n.remove()}catch(e){}})});}catch(e){}"
            + "try{var walls=" + JSON.stringify(WALLS_SEL) + ";walls.split(',').forEach(function(s){try{document.querySelectorAll(s).forEach(function(n){try{n.remove()}catch(e){}})}catch(e){}});}catch(e){}"
            + "try{return document.body?document.body.innerHTML:'';}catch(e){return '';}})()";
        return this._wvExec(wv, kill, 400000);
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
                + "try{return JSON.stringify({title:document.title||'',finalUrl:(window.location?window.location.href:''),body:(document.body?document.body.innerHTML:'')});}catch(e){return JSON.stringify({title:'',finalUrl:'',body:''});}"
                + "})()";

            // 抽取当前 DOM；有正文则 finish 结束（partialFlag 标记是否为超时兜底的部分内容）
            const grab = (partialFlag) => {
                if (done) return Promise.resolve(true);
                return wv.executeJavaScript(kill).then(function (s) {
                    let d = {}; try { d = JSON.parse(s); } catch (e) {}
                    let body = (d && d.body) || '';
                    if (body.length > 400000) body = body.slice(0, 400000);
                    if (body.trim()) {
                        finish({ ok: true, partial: !!partialFlag, title: (d && d.title) || '', finalUrl: (d && d.finalUrl) || url, html: body });
                        return true;
                    }
                    return false;
                }).catch(function () { return false; });
            };

            // 总超时：先兜底抽取当前 DOM（拿到=部分内容），拿不到才判失败；按是否曾 DCL 分类
            hardTimer = setTimeout(function () {
                grab(true).then(function (got) {
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
                if (waitText) {
                    const start = Date.now();
                    const poll = function () {
                        if (done) return;
                        wv.executeJavaScript('((document.body&&document.body.innerText)||"").indexOf(' + JSON.stringify(waitText) + ')>=0').then(function (found) {
                            if (done) return;
                            if (found) grab(false);
                            else if (Date.now() - start > totalMs) finish({ ok: false, url: url, error: 'wait-text-timeout', stage: 'waittext' });
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
                            else if (!wv.isLoading()) finish({ ok: true, url: url, title: '', finalUrl: url, html: '' });
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
    }
});
