// 批 3 F2：自 vue_methods.js 搬移的 methods/98_browser_tabs.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // AI浏览器相关
    openUrlInNewTab(url) {
        // 如果 url 为空或者无效，可以做个判断，或者直接打开
        if (!url) return;

        const newTab = {
            id: Date.now(),
            title: 'Loading...',
            url: url,
            favicon: '',
            isLoading: true,
            loaded: true,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
        this.activeMenu = 'ai-browser';
    },

    // 切换标签
    switchTab(id) {
        this.currentTabId = id;
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) {
            if (!tab.loaded && tab.url) tab.loaded = true; // S94: 切到才真正加载（隐藏懒 tab 唤醒点）
            // --- ✅ 修改此处 ---
            // 优先显示页面实际所在的 currentUrl，否则显示 tab.url
            this.urlInput = tab.currentUrl || tab.url;
            
            // 如果是欢迎页，清空地址栏显示
            if (!tab.url) this.urlInput = '';
        }
    },

    // 关闭标签
    closeTab(id, event) {
        if (event) event.stopPropagation(); // 防止触发点击切换
        
        const index = this.browserTabs.findIndex(t => t.id === id);
        if (index === -1) return;

        // 如果关闭的是当前标签，需要切换到另一个
        if (this.currentTabId === id) {
            if (this.browserTabs.length > 1) {
                // 优先切到右边，没右边切左边
                const nextTab = this.browserTabs[index + 1] || this.browserTabs[index - 1];
                this.currentTabId = nextTab.id;
                this.urlInput = nextTab.url;
            } else {
                // 如果只剩这一个，重置它而不是删除
                this.addNewTab(); // 加个新的
                this.browserTabs.splice(index, 1); // 删掉旧的
                return;
            }
        }
        
        this.browserTabs.splice(index, 1);
    },

    // 地址栏回车
    handleUrlEnter() {
        let val = this.urlInput.trim();
        if (!val) return;

        // 简单的 URL 补全逻辑
        if (!/^https?:\/\//i.test(val)) {
            // 如果看起来像域名
            if (/^([\w-]+\.)+[\w-]+/.test(val) && !val.includes(' ')) {
                val = 'https://' + val;
            } else {
                // 否则当做搜索
                if (this.searchEngine === 'google') {
                    val = `https://www.google.com/search?q=${encodeURIComponent(val)}`;
                } else if (this.searchEngine === 'bing') {
                    val = `https://www.bing.com/search?q=${encodeURIComponent(val)}`;
                } else {
                    if (this.chromeMCPSettings.enabled == false || this.chromeMCPSettings.type != 'internal') {
                        showNotification(this.t('notEnabledInternalBrowserBontrol'), 'error')
                    }
                    this.showBrowserChat = true;
                    this.userInput = val;
                    this.sendMessage();
                    return;
                }
            }
        }

        this.navigateTo(val);
    },

    getTabIdByIndex(index) {
        if (index >= 0 && index < this.browserTabs.length) {
            return this.browserTabs[index].id;
        }
        return null;
    },

    // 欢迎页搜索回车
    handleWelcomeSearch() {
        const query = this.welcomeSearchQuery.trim();
        this.welcomeSearchQuery = ''; // 清空输入框
        if (!query) return;

        // --- 新增逻辑：URL 检测与直接跳转 ---
        if (this.isUrl(query)) {
            let targetUrl = query;
            // 如果没有以 http:// 或 https:// 开头，默认补全 https://
            if (!/^https?:\/\//i.test(targetUrl)) {
                targetUrl = 'https://' + targetUrl;
            }
            this.navigateTo(targetUrl);
            return;
        }
        // ------------------------------------

        let searchUrl = '';
        if (this.searchEngine === 'google') {
            searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        } else if (this.searchEngine === 'bing') {
            searchUrl = `https://www.bing.com/search?q=${encodeURIComponent(query)}`;
        } else {
            if (this.chromeMCPSettings.enabled == false || this.chromeMCPSettings.type != 'internal') {
                showNotification(this.t('notEnabledInternalBrowserBontrol'), 'error')
            }
            this.showBrowserChat = true;
            this.userInput = query;
            this.sendMessage();
            return;
        }

        this.navigateTo(searchUrl);
    },

    /**
     * 辅助函数：判断字符串是否为 URL
     * 规则：
     * 1. 以 http/https 开头
     * 2. 或者符合 域名.后缀 (如 google.com)
     * 3. 或者 localhost
     * 4. 或者 IP 地址
     * 5. 且不包含空格
     */
    isUrl(str) {
        // 简单判断：如果包含空格，通常是搜索词（除非是编码后的URL，但用户输入通常带空格）
        if (str.includes(' ')) return false;

        // 正则解释：
        // ^(https?:\/\/)?  -> 可选的 http:// 或 https://
        // (
        //   ([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}  -> 标准域名 (如 a.com, b.co.uk)
        //   | localhost                     -> 本地 localhost
        //   | (\d{1,3}\.){3}\d{1,3}         -> IP 地址 (如 192.168.1.1)
        // )
        // (:\d+)?          -> 可选端口号 (如 :8080)
        // (\/.*)?$         -> 可选路径
        const pattern = /^(https?:\/\/)?(([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}|localhost|(\d{1,3}\.){3}\d{1,3})(:\d+)?(\/.*)?$/i;
        
        return pattern.test(str);
    },

    // 核心导航方法
    navigateTo(url) {
        if (!this.currentTab) return;
        
        // 如果是刷新当前页面（URL 没变）
        // 注意：这里比较时最好也比较 currentUrl
        const activeUrl = this.currentTab.currentUrl || this.currentTab.url;
        
        if (activeUrl === url) {
            // ... (保持原有的 reload 逻辑)
            const wv = document.getElementById('webview-' + this.currentTabId);
            if (wv) wv.reload();
            return;
        }

        // 2. 如果是新 URL
        this.currentTab.url = url;      // 这会触发 :src 更新，开始加载
        this.currentTab.loaded = true;  // S95: 懒加载 webview 的 URL 写回必须同步放行
        this.currentTab.currentUrl = url; // 同步更新实际地址状态
        this.urlInput = url;
    },

    // 回到主页 (新标签页)
    goHome() {
        if(this.currentTab) {
            this.currentTab.url = '';
            this.currentTab.loaded = true; // S95
            this.currentTab.title = 'New Tab';
            this.currentTab.favicon = '';
            this.urlInput = '';
        }
    },

    // --- Webview 导航控制 ---
    getWebview(id) {
        const wv = document.getElementById('webview-' + (id || this.currentTabId));
        
        // 1. 基础非空检查
        if (!wv) {
            console.warn("getWebview: Element not found for ID", id || this.currentTabId);
            return null;
        }

        // 2. ★ 核心修改：检查元素是否真正连接在 DOM 树上
        // 如果元素存在但 isConnected 为 false，说明 Vue 正在销毁它或还没挂载好
        // 此时返回 null，让 Python 端捕获 "No active webview" 错误并触发重试
        if (!wv.isConnected) {
            console.warn("getWebview: Element found but detached from DOM (Zombie node).");
            return null;
        }

        // 3. (可选) 检查 Electron 内部状态
        // getWebContentsId 是 Electron webview 的原生方法，如果报错说明内部未初始化
        try {
            if (typeof wv.getWebContentsId !== 'function') {
                return null;
            }
        } catch (e) {
            return null;
        }

        return wv;
    },

    browserGoBack() {
        const wv = this.getWebview();
        if (wv && wv.canGoBack()) wv.goBack();
    },

    browserGoForward() {
        const wv = this.getWebview();
        if (wv && wv.canGoForward()) wv.goForward();
    },

    browserReload() {
        const wv = this.getWebview();
        if(!wv) return;
        if (this.currentTab.isLoading) {
            wv.stop();
        } else {
            wv.reload();
        }
    },

    onDidStartLoading(id) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) tab.isLoading = true;
    },

    // 修改前
    onDidStopLoading(id) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) {
            tab.isLoading = false;
            const wv = document.getElementById('webview-' + id);
            if (wv) {
                tab.canGoBack = wv.canGoBack();
                tab.canGoForward = wv.canGoForward();
                
                // --- ✅ 修正后的代码 ---
                if (wv.getURL()) {
                    // 1. 将实际 URL 存入一个新字段，不触碰 tab.url (src)
                    tab.currentUrl = wv.getURL(); 
                    
                    // 2. 只更新顶部的地址栏 UI
                    if (this.currentTabId === id) {
                        this.urlInput = tab.currentUrl;
                    }
                }
            }
        }
    },

    onPageTitleUpdated(id, event) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) tab.title = event.title;
    },

    onPageFaviconUpdated(id, event) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab && event.favicons && event.favicons.length > 0) {
            tab.favicon = event.favicons[0];
        }
    },

    // 处理网页内部 window.open
    onNewWindow(id, event) {
        // 在应用内新建标签页打开，而不是弹出新窗口
        const { url } = event;
        const newTab = {
            id: Date.now(),
            title: 'Loading...',
            url: url,
            favicon: '',
            isLoading: true,
            loaded: true,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
    },

    // 在 methods 中添加或修改 onDomReady
    onDomReady(tabId) {
        const webview = document.getElementById('webview-' + tabId);
        if (!webview) return;

        webview.addEventListener('context-menu', (e) => {
            // ★★★ 关键调试点：打印出 Electron 传来的所有参数 ★★★
            console.log('Webview Context Menu Params:', e.params);
            
            const params = e.params;
            let menuType = 'default';
            let data = {};

            // 重新审视和调整判断逻辑的顺序，确保最具体的匹配优先
            if (params.mediaType === 'image' && params.srcURL && params.srcURL.length > 0) {
                menuType = 'image';
                data = { src: params.srcURL };
                console.log('Detected Image Context:', data); // 调试
            } else if (params.linkURL && params.linkURL.length > 0) {
                menuType = 'link';
                data = { 
                    url: params.linkURL, 
                    text: params.linkText || params.selectionText || '' 
                };
                console.log('Detected Link Context:', data); // 调试
            } else if (params.selectionText && params.selectionText.length > 0) {
                menuType = 'text';
                data = { text: params.selectionText };
                console.log('Detected Text Context:', data); // 调试
            } else {
                menuType = 'default';
                console.log('Detected Default Context'); // 调试
            }

            // 再次打印最终决定发送的类型和数据
            console.log(`Sending context menu request: Type = ${menuType}, Data =`, data);

            window.electronAPI.showContextMenu(menuType, data);
        });
        webview.send('set-i18n', {
            translate: this.t('translate') || '翻译',
            askAI: this.t('ask_ai') || '问 AI',
            read: this.t('read') || '朗读',
            copy: this.t('copy') || '复制'
        });
        //webview.openDevTools();
    },

    // 1. 修改 IPC 消息处理函数
    async handleWebviewIpcMessage(event) {
        if (event.channel === 'ai-toolbar-action') {
            const { action, text } = event.args[0];
            if (!text) return;

            // 获取 webview 实例，用于回传数据
            // 注意：event.target 就是 webview 元素
            const webview = event.target; 

            switch (action) {
                case 'translate':
                    // --- 1. 翻译/总结：直接调用后端 + 流式回传 ---
                    // 不打开侧边栏，直接在 webview 原地显示
                    this.streamTranslateInWebview(webview, text);
                    break;

                case 'ask':
                    // --- 2. 问 AI：保留原逻辑，去侧边栏 ---
                    this.showBrowserChat = true;
                    // 如果你想自动添加提示词：
                    this.userInput = `${text}`; 
                    // this.sendMessage(); // 也就是让用户自己点发送，或者你取消注释自动发
                    break;

                case 'read':
                    // --- 3. 朗读：调用 TTS ---
                    this.handleBrowserTTS(text);
                    break;
            }
        }
    },

    // 2. 新增：流式请求后端并发送给 Webview
    async streamTranslateInWebview(webview, text) {
        if (!webview) return;
        
        console.log('开始请求翻译:', text);
        webview.send('ai-stream-start');

        try {
            const host = window.electron?.server?.host || '127.0.0.1';
            const port = window.electron?.server?.port || 3456;
            const apiUrl = `http://${host}:${port}/simple_chat`;
            const targetLang = this.target_lang || 'Simplified Chinese';
            const sysPrompt = `You are a helpful translation assistant. Translate the following text to ${targetLang}. Only output the translated text.`;

            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [
                        { role: "system", content: sysPrompt },
                        { role: "user", content: text }
                    ],
                    stream: true
                })
            });

            if (!response.ok) throw new Error(`API Error: ${response.status}`);

            // S108: 每 token 一次 webview.send 曾灌爆 DOMWebSocket（host 侧
            // onmessage 实测 1s 长任务）→ 80ms 批量合并发送；迭代器让位保证出口 flush
            let tvBuf = '';
            let tvTimer = 0;
            const tvFlush = () => {
                if (tvTimer) { clearTimeout(tvTimer); tvTimer = 0; }
                if (!tvBuf) return;
                const c = tvBuf; tvBuf = '';
                try { webview.send('ai-stream-chunk', c); } catch (_) {}
            };
            await iterateNdjsonLines(response, (data) => {
                    const content = data.choices?.[0]?.delta?.content;
                    if (!content) return;
                    tvBuf += content;
                    if (!tvTimer) tvTimer = setTimeout(tvFlush, 80);
            }, { stripDataPrefix: true });
            tvFlush();
            webview.send('ai-stream-end');
            console.log('流式传输结束');

        } catch (error) {
            console.error('Translation error:', error);
            webview.send('ai-stream-chunk', `\n[Error: ${error.message}]`);
        }
    },

    // 3. 修改：TTS 处理逻辑
    handleBrowserTTS(text) {
        // 停止之前的播放（如果有）
        this.stopTTSActivities();
        
        // 设置长文本内容
        this.readConfig.longText = text;
        
        // 稍微延迟确保状态更新，然后开始朗读
        setTimeout(() => {
            this.startRead();
            
            // 提示用户 (可选)
            // showNotification(this.t('tts_started'), 'success');
        }, 500);
    },

    // 切换引擎下拉
    toggleEngineDropdown() {
        this.showEngineDropdown = !this.showEngineDropdown;
    },

    // 设置引擎并关闭下拉
    setSearchEngine(engine) {
        this.searchEngine = engine;
        this.showEngineDropdown = false;
        // 如果想要切换后自动聚焦输入框
        this.$nextTick(() => {
            const input = document.querySelector('.ios-search-input');
            if(input) input.focus();
        });
    },

    // 搜索框失焦处理 (延迟关闭下拉，防止点击菜单项时菜单先消失)
    handleSearchBlur() {
        this.isSearchFocused = false;
        setTimeout(() => {
            this.showEngineDropdown = false;
        }, 200);
    },

    handleSelectorEnter() {
        if (this.dropdownTimer) clearTimeout(this.dropdownTimer);
        this.showEngineDropdown = true;
    },

    // 鼠标离开区域：延迟 200ms 关闭，给用户移动鼠标的时间
    handleSelectorLeave() {
        this.dropdownTimer = setTimeout(() => {
            this.showEngineDropdown = false;
        }, 200); // 200ms 延迟
    },

    // ★★★ 核心：处理边缘滚动 ★★★
    handleTabsMouseMove(e) {
      // 在 Options API 中，通过 this.$refs 访问 DOM
      const container = this.$refs.tabsContainerRef;
      
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left; // 鼠标相对于容器左侧的距离
      const width = rect.width;
      const threshold = 60; // 边缘触发滚动的范围 (px)
      const speed = 8;      // 滚动速度

      // 先清除可能存在的旧定时器
      this.stopEdgeScroll();

      // 定义滚动函数
      const scroll = (direction) => {
        if (direction === 'left') {
          container.scrollLeft -= speed;
        } else {
          container.scrollLeft += speed;
        }
        // 持续循环
        this.scrollInterval = requestAnimationFrame(() => scroll(direction));
      };

      // 判断鼠标位置
      if (x < threshold) {
        // 鼠标在左边缘 -> 向左滑
        scroll('left');
      } else if (x > width - threshold) {
        // 鼠标在右边缘 -> 向右滑
        scroll('right');
      } else {
        // 在中间 -> 停止滚动
        this.stopEdgeScroll();
      }
    },

    // 停止滚动
    stopEdgeScroll() {
      if (this.scrollInterval) {
        cancelAnimationFrame(this.scrollInterval);
        this.scrollInterval = null;
      }
    },

    controlDownload(id, action) {
        window.downloadAPI.controlDownload(id, action);
    },

    handleStopOrRemove(item) {
        if (item.state === 'progressing' || item.state === 'paused') {
            // 如果还在下载，就是取消
            this.controlDownload(item.id, 'cancel');
        } else {
            // 如果已完成或已取消，就是从列表中删除记录
            this.downloads = this.downloads.filter(d => d.id !== item.id);
        }
    },

    openFileFolder(path) {
        if(path) window.downloadAPI.showItemInFolder(path);
    },

    clearFinishedDownloads() {
        // 只保留正在下载的项目
        this.downloads = this.downloads.filter(d => d.state === 'progressing' || d.state === 'paused');
    },

    // 字节格式化工具
    formatBytes(bytes, decimals = 1) {
        if (!bytes) return '0 B';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    },

    handleDropdownEnter() {
        // 1. 如果有关闭的定时器正在倒计时，立刻取消它！
        if (this.dropdownTimer) {
            clearTimeout(this.dropdownTimer);
            this.dropdownTimer = null;
        }
        // 2. 显示面板
        this.showDownloadDropdown = true;
    },

    // ★ 鼠标离开
    handleDropdownLeave() {
        // 给用户 300ms 的反应时间
        this.dropdownTimer = setTimeout(() => {
            this.showDownloadDropdown = false;
            this.dropdownTimer = null;
        }, 300); 
    },

    getFaviconUrl(tab) {
      // 1. 浏览器已经给的就直接用
      if (tab.favicon) return tab.favicon;

      // 2. 用 Chrome 官方提供的“小彩蛋”API，0 成本
      //    注意：这个 API 不需要额外权限，也不会触发网络请求，只是读缓存
      if (chrome && chrome.tabs && typeof chrome.tabs.get === 'function') {
        // 同步读缓存，拿不到也不报错
        try {
          const url = new URL(tab.url);
          return `chrome://favicon/size/16@2x/${url.origin}`;
        } catch (_) {}
      }

      // 3. 兜底：拼一个最可能的地址
      try {
        const u = new URL(tab.url);
        return `${u.origin}/favicon.ico`;
      } catch (_) {}

      // 4. 实在没有就空字符串
      return '';
    },

    // 切换当前标签页的收藏状态
    toggleFavorite(tab) {
        if (!tab || !tab.url) return;

        const index = this.favorites.findIndex(f => f.url === tab.url);
        if (index !== -1) {
            // 已存在 -> 移除
            this.favorites.splice(index, 1);
            showNotification(this.t('favoriteRemoved') || 'Favorite removed', 'info');
        } else {
            // 不存在 -> 添加
            this.favorites.push({
                title: tab.title || 'New Tab',
                url: tab.url,
                favicon: this.getFaviconUrl(tab)
            });
            showNotification(this.t('favoriteAdded') || 'Favorite added', 'success');
        }
        this.saveFavorites();
    },

    // 从网格中移除特定收藏
    removeFavorite(url) {
        const index = this.favorites.findIndex(f => f.url === url);
        if (index !== -1) {
            this.favorites.splice(index, 1);
            this.saveFavorites();
        }
    },

    // 点击收藏图标时，在当前标签页加载 URL
    loadUrlInCurrentTab(url) {
        if (this.currentTab) {
            // 更新当前标签的 URL
            this.currentTab.url = url;
            this.currentTab.loaded = true; // S95: 懒加载放行
            // 更新地址栏输入框显示
            this.urlInput = url; 
            // 触发加载状态 (如果您的 webview逻辑依赖这个)
            this.currentTab.isLoading = true;
        } else {
            // 如果没有当前标签，创建一个新的
            this.addNewTab(url);
        }
    },

    // 持久化：保存收藏到本地存储
    saveFavorites() {
        try {
            localStorage.setItem('browser_favorites', JSON.stringify(this.favorites));
            // 保存显示状态配置
            localStorage.setItem('browser_show_favorites', JSON.stringify(this.showFavorites));
        } catch (e) {
            console.error('Failed to save favorites:', e);
        }
    },

    // 持久化：从本地存储加载
    loadFavorites() {
        try {
            const storedFavs = localStorage.getItem('browser_favorites');
            if (storedFavs) {
                this.favorites = JSON.parse(storedFavs);
            }
            
            const storedShow = localStorage.getItem('browser_show_favorites');
            if (storedShow !== null) {
                this.showFavorites = JSON.parse(storedShow);
            }
        } catch (e) {
            console.error('Failed to load favorites:', e);
        }
    }
});
