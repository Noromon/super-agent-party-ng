// 批 3 F2：自 vue_methods.js 搬移的 js/methods/80_webview_agent.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {

    // S106: guest 端结果截断网关。MB 级页面内容原样回传宿主时，DOMWebSocket
    // host handler 实测 1s+ 长任务（LoAF 点名 DOMWebSocket.onmessage=1080ms）。
    _wvExec(wv, script) {
      const cap = '(async()=>{const __r=await eval(' + JSON.stringify(script) + ');' +
        "if(typeof __r==='string'&&__r.length>60000)return __r.slice(0,60000)+'\\n...[S106 truncated '+(__r.length-60000)+' chars]';" +
        "if(__r&&typeof __r==='object'){try{const __s=JSON.stringify(__r);if(__s.length>60000)return __s.slice(0,60000)+'...[S106 truncated]';}catch(_e){}}" +
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

    browserNavigate(type, url, ignoreCache) {
        const wv = this.getWebview();
        if (!wv) return "Error: No active webview";

        try {
            this.activeMenu = 'ai-browser'; // 切换到 AI Browser 菜单
            switch (type) {
                case 'url':
                    if (!url) return "Error: URL is required";
                    this.navigateTo(url);
                    return "Navigating to " + url;
                case 'back':
                    if (wv.canGoBack()) {
                        wv.goBack();
                        return "Navigated Back";
                    }
                    return "Error: Cannot go back";
                case 'forward':
                    if (wv.canGoForward()) {
                        wv.goForward();
                        return "Navigated Forward";
                    }
                    return "Error: Cannot go forward";
                case 'reload':
                    if (ignoreCache) wv.reloadIgnoringCache();
                    else wv.reload();
                    return "Reloaded";
                default:
                    // 默认为 URL 导航
                    if (url) {
                        this.navigateTo(url);
                        return "Navigated to " + url;
                    }
                    return "Error: Unknown navigation type";
            }
        } catch (e) {
            return "Navigation Exception: " + e.message;
        }
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
        if (wv.isLoading()) return "Error: Page is loading...";

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

                if (lines.length === 0) return "Page empty or no interactive elements found.";
                return lines.join('\\n');
            } catch (e) {
                return "Snapshot Script Error: " + e.message;
            }
        })()
        `;
        
        try {
            return await this._wvExec(wv, script);
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
                            // 页面已加载完毕，但文本未找到
                            resolve("Page loaded");
                        } else {
                            // 页面还在加载中，且超时
                            resolve("Timeout waiting for text");
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
            // 1. 滚动 (如果指定元素)
            if (uid) {
                await this.webviewClick(uid);
                await this._humanDelay();
            }

            // 2. 捕获页面
            const image = await wv.capturePage();

            // 3. 缩放 (AI 不需要 4K，1280 宽足够，节省 Token)
            const size = image.getSize();
            let resized = image;
            if (size.width > 1280) {
                resized = image.resize({ width: 1280 });
            }

            // 4. 转为 JPEG Buffer (质量 70)
            const buffer = resized.toJPEG(70);

            // 5. 调用主进程保存文件
            // 注意：Buffer 通过 IPC 传输非常快，比 Base64 字符串快得多
            const filename = await window.electronAPI.saveScreenshotDirect(buffer);
            
            // 6. 拼接 URL
            // window.electron.server.port 是在 preload 里暴露的后端端口
            const host = window.electron.server.host || '127.0.0.1';
            const port = window.electron.server.port || 3456;
            
            const fileUrl = `http://${host}:${port}/uploaded_files/${filename}`;
            
            return fileUrl;

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
    }
});
