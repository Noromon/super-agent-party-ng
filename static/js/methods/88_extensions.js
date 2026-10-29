// 批 3 F2：自 vue_methods.js 搬移的 methods/88_extensions.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 加载指定扩展
  async loadExtension(extension) {
    if (!extension) {
      this.currentExtension = null;
      this.sidePanelURL = '';
      return;
    }
    
    /* 1. 尝试 Node 模式 */
    try {
      const r = await fetch(`/api/extensions/${extension.id}/start-node`, { method: 'POST' });
      const res = await r.json();

      if (res.mode === 'node') {
        // ✅ Node 成功
        this.currentExtension = extension;
        this.sidePanelURL = `/api/extensions/${extension.id}/node/`;
        showNotification(`${this.t('loadExtension(node)')}: ${extension.name}`, 'success');
        return;
      } else if (res.mode === 'error') {
        // ❌ Node 服务启动失败！必须拦截并展示错误，不能往下走
        showNotification(`插件服务启动失败: ${res.message}`, 'error');
        console.error("【Node Extension 报错】:", res.message);
        return; 
      }
      
      // 只有 res.mode === 'static'，才允许跳出 if，去走下面的静态路由兜底
    } catch (e) {
      // 网络断开或解析异常，也建议拦截
      showNotification(`请求插件服务异常: ${e.message}`, 'error');
      console.error(e);
      return; 
    }

    /* 2. 回退静态路由 */
    this.currentExtension = extension;
    this.sidePanelURL = `/ext/${extension.id}/index.html`;
    showNotification(`${this.t('loadExtension(static)')}: ${extension.name}`, 'success');
    this.extensionsSystemPromptsDict[extension.id] = extension.systemPrompt || ""; // 更新提示词
  },

// 切换到默认视图 (主页书签)
  resetToDefaultView() {
    // 1. 切换焦点为 null，利用 v-show 机制隐藏所有 iframe，展示主页内容
    this.currentExtension = null;
    this.sidePanelURL = ''; // 清除旧的全局URL状态，防止污染
    this.activeSideView = 'list'; // 确保侧边栏内部路由切回“列表”

    // 2. 关闭可能开着的弹窗
    this.showExtensionsDialog = false;

    // 3. ✨ 核心修改：移除这下面两行代码！
    // this.expandChatArea();     // ❌ 不要强行扩张聊天区
    // this.collapseSidePanel();  // ❌ 不要强行收起侧边栏，用户只是切回主标签，侧边栏应该开着！

    // 4. 重置当前对话的附加提示词（切回默认对话，清空扩展的系统 Prompt 是合理的）
    this.extensionsSystemPromptsDict = {}; 

    // 5. 如果离开任务中心，清除任务刷新定时器以节省性能（保持原逻辑）
    if (this.taskRefreshTimer) {
      clearInterval(this.taskRefreshTimer);
      this.taskRefreshTimer = null; // 顺手置空是个好习惯
    }

    console.log('已切换到侧边栏主视图 (Home Tab)');
  },

  // 打开扩展选择对话框
  openExtensionsDialog() {
    this.showExtensionsDialog = true;
  },

// 切换（或新开）扩展标签页
  async switchExtension(extension) {
    // 1. 关闭扩展弹窗，展开侧边栏
    this.showExtensionsDialog = false; 
    const sidePanel = this.$refs.sidePanelRef;
    if (sidePanel.style.width == 0 ){
        this.expandSidePanel();
    }

    // 2. 检查这个扩展是否已经在多开数组里了
    const existingExt = this.openedExtensions.find(e => e.id === extension.id);

    if (existingExt) {
      // 🌟 【已打开过】：直接切换焦点，不重新加载，保留页面状态！
      this.currentExtension = existingExt;
      this.activeSideView = 'iframe'; // 确保视图模式是 iframe
      
      // 如果你的底层代码仍依赖全局的 sidePanelURL，这里做个同步
      if (existingExt.iframeUrl) {
        this.sidePanelURL = existingExt.iframeUrl;
      }
      
    } else {
      // 🌟 【第一次打开】：需要走加载逻辑
      // 为了让 loading 动画立刻出来，先将当前扩展指向它
      this.currentExtension = extension;
      this.activeSideView = 'iframe';
      this.sidePanelURL = ''; // 清空全局URL防止闪烁旧画面
      
      // 加入顶部标签栏数组
      this.openedExtensions.push(extension);

      // 执行你原本的获取 URL/Token 逻辑
      await this.loadExtension(extension);

      // 💡 极其关键的一步：loadExtension 执行完后，通常会给 this.sidePanelURL 赋值。
      // 我们需要把这个生成的专属 URL，保存到当前这个扩展对象里，这样下次切换回来才不会丢！
      const targetExt = this.openedExtensions.find(e => e.id === extension.id);
      if (targetExt) {
        // 将全局生成的 URL 永久绑定给这个 Tab
        targetExt.iframeUrl = this.sidePanelURL; 
      }
    }
  },

  // ✨ 配套新增：关闭扩展标签页
  closeExtensionTab(extId) {
    // 1. 从已打开数组中移除
    const index = this.openedExtensions.findIndex(e => e.id === extId);
    if (index === -1) return;
    
    this.openedExtensions.splice(index, 1);

    // 2. 如果关闭的刚好是【当前正在看】的标签页，需要处理焦点回退
    if (this.currentExtension && this.currentExtension.id === extId) {
      if (this.openedExtensions.length > 0) {
        // 如果还有其他标签，自动跳到最后一个标签
        const lastExt = this.openedExtensions[this.openedExtensions.length - 1];
        this.switchExtension(lastExt);
      } else {
        // 如果全关光了，退回默认的列表主页
        this.resetToDefaultView();
      }
    }
  },

  // 工具函数：返回扩展真正能访问的地址（Node > 静态）
  async getExtensionURL(ext) {
    console.log('获取扩展URL', ext);
    // 1. 先尝试启动 Node
    try {
      const r = await fetch(`/api/extensions/${ext.id}/start-node`, { method: 'POST' });
      const res = await r.json();
      if (res.mode === 'node') {
        return `/api/extensions/${ext.id}/node/`;   // ✅ Node 代理路径
      }
      console.log('启动 Node 失败，回退静态',res);
    } catch { 
     }
    // 2. 回退静态
    return `/ext/${ext.id}/index.html`;
  },

    async openExtension(extension) {
      const url = await this.getExtensionURL(extension);   // ⬅️ 异步拿地址
      console.log('打开扩展', `${this.partyURL}${url}`);
      if (isElectron) {
        window.electronAPI.openExternal(`${this.partyURL}${url}`);
      } else {
        window.open(url, '_blank');
      }
    },

    // 删除扩展
    async removeExtension(ext) {
      // 若是 Node 模式就停进程，忽略错误
      await fetch(`/api/extensions/${ext.id}/stop-node`, { method: 'POST' }).catch(() => {});
      try {
        const res = await fetch(`/api/extensions/${ext.id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('删除失败');
        showNotification(this.t('deleteSuccess'), 'success');
        this.scanExtensions(); // 刷新列表
      } catch (e) {

         showNotification(e.message, 'error');
      }
    },

    // 打开「添加扩展」对话框
    openAddExtensionDialog() {
      this.newExtensionUrl = '';
      this.showExtensionForm = true;
      this.fetchRemotePlugins();
    },

    async pollInstallStatus(extId, onSuccess, onError) {
      const poll = async () => {
        try {
          const res = await fetch(`/api/extensions/task-status/${extId}`);
          const data = await res.json();

          if (data.status === 'success') {
            // 安装成功
            onSuccess(data.detail);
          } else if (data.status === 'error') {
            // 安装失败
            onError(data.detail);
          } else if (data.status === 'installing') {
             // 仍在安装中，继续轮询 (这里可以顺便更新界面提示，如果你有对应UI的话)
             // 例如：console.log(data.detail); 
             setTimeout(poll, 1000); // 1秒后再次检查
          } else {
             // 未知状态，可能是重启了或者ID错了
             onError("任务状态丢失");
          }
        } catch (e) {
          onError("网络请求错误");
        }
      };
      // 开始第一次轮询
      poll();
    },

    // 真正「安装」按钮触发
    async addExtension() {
      const url = this.newExtensionUrl.trim();
      if (!url) return showNotification('请输入 GitHub 地址', 'error');
      
      this.installLoading = true; // 开启 Loading 遮罩
      
      try {
        const res = await fetch('/api/extensions/install-from-github', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            url,
            backupUrl: ""  
          }),
        });
        
        if (res.status === 409) throw new Error(this.t('extensionExists'));
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || this.t('deleteFailed'));
        }

        const resData = await res.json();
        const extId = resData.ext_id;

        // --- 核心修改：开始轮询 ---
        showNotification('正在后台下载，请稍候...', 'info');
        
        this.pollInstallStatus(
          extId,
          (msg) => {
            // 成功回调
            this.installLoading = false;
            showNotification(msg || '安装成功！', 'success');
            this.showExtensionForm = false; // 关闭弹窗
            this.scanExtensions(); // 立即刷新列表
          },
          (errMsg) => {
            // 失败回调
            this.installLoading = false;
            showNotification(`安装失败: ${errMsg}`, 'error');
          }
        );

      } catch (e) {
        this.installLoading = false;
        showNotification(e.message, 'error');
      }
    },

    // 打开文件选择器
    selectLocalZip() {
      this.$refs.zipInput.click();
    },

    // 选中文件后自动上传
    async onZipSelected(e) {
      const file = e.target.files?.[0];
      if (!file) return;
      
      this.installLoading = true;
      const form = new FormData();
      form.append('file', file);
      
      try {
        const res = await fetch('/api/extensions/upload-zip', {
          method: 'POST',
          body: form,
        });
        
        if (res.status === 409) throw new Error(this.t('extensionExists'));
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || '上传失败');
        }
        
        const resData = await res.json();
        const extId = resData.ext_id;
        
        // 开始轮询，与 GitHub 安装一致
        showNotification(this.t('waitExtensionInstall'), 'info');
        this.showExtensionForm = false;
        
        this.pollInstallStatus(
          extId,
          (msg) => {
            this.installLoading = false;
            showNotification(msg || this.t('installSuccess'), 'success');
            this.scanExtensions();
          },
          (errMsg) => {
            this.installLoading = false;
            showNotification(`${this.t('installFailed')}: ${errMsg}`, 'error');
          }
        );
        
      } catch (err) {
        this.installLoading = false;
        showNotification(err.message, 'error');
      } finally {
        e.target.value = '';
      }
    },

    async fetchRemotePlugins() {
      try {
        await this.scanExtensions(); // 刷新
        const res = await fetch('/api/extensions/remote-list');
        const { plugins } = await res.json();   // 取出 plugins 数组
        console.log(plugins);
        const localRes = await fetch('/api/extensions/list');
        const { extensions } = await localRes.json();
        console.log(extensions);
        this.remotePlugins = plugins.map(r => ({
          ...r,
          installed: extensions.some(l => l.repository.trim() === r.repository.trim()),
        }));
      } catch (e) {
        
      }
    },

async togglePlugin(plugin) {
    if (plugin.installed) {
      // 卸载逻辑保持不变...
      await this.removeExtension(plugin);
      plugin.installed = false;
    } else {
      // --- 安装逻辑 ---
      
      // 1. 设置局部 loading 状态 (如果你的 plugin 对象支持)
      // 如果没有局部 loading，就用全局 this.installLoading = true
      plugin.installing = true
      this.installLoading = true; 

      try {
        const res = await fetch('/api/extensions/install-from-github', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            url: plugin.repository,
            backupUrl: plugin.backupRepository || "" 
          }),
        });

        if (res.status === 409) throw new Error('插件已存在');
        if (!res.ok) throw new Error('请求失败');
        
        const resData = await res.json();
        const extId = resData.ext_id;

        showNotification('已开始下载，请耐心等待...', 'info');

        // --- 核心修改：开始轮询 ---
        this.pollInstallStatus(
          extId,
          (msg) => {
            // 成功
            this.installLoading = false;
            if (plugin) plugin.installing = false;
            plugin.installed = true; // 更新前端状态
            showNotification('安装成功！', 'success');
            this.scanExtensions(); // 刷新完整列表以确保数据一致
          },
          (errMsg) => {
            // 失败
            this.installLoading = false;
            if (plugin) plugin.installing = false;
            showNotification(`安装失败: ${errMsg}`, 'error');
          }
        );

      } catch (e) {
        this.installLoading = false;
        if (plugin) plugin.installing = false;
        showNotification(e.message, 'error');
      }
    }
  },

  handleRefreshClick() {
    this.refreshing = true;
    
    // 调用原有的刷新方法
    this.fetchRemotePlugins().then(() => {
      // 请求完成后
      this.refreshing = false;
      this.refreshButtonText = this.t('refreshedSuccess') || '已刷新';
      
      // 2秒后恢复按钮文字
      setTimeout(() => {
        this.refreshButtonText = this.t('refreshList');
      }, 2000);
    }).catch(error => {
      // 处理错误情况
      this.refreshing = false;
      this.refreshButtonText = this.t('refreshFailed') || '刷新失败';
      
      // 2秒后恢复按钮文字
      setTimeout(() => {
        this.refreshButtonText = this.t('refreshList');
      }, 2000);
    });
  },

  openRepository(url) {
    if (isElectron) {
      window.electronAPI.openExternal(url)   // 主进程会新建可关闭的独立窗口
    } else {
      window.open(url, '_blank')
    }
  },

  // 修改 openExtensionInWindow 方法
  async openExtensionInWindow(extension) {
    const url = await this.getExtensionURL(extension);   // ⬅️ 同样先启动/拿地址

    // 下面逻辑你原来就有，只把 url 换成异步得到的即可
    this.showExtensionsDialog = false;
    let windowWidth = 800;
    let windowHeight = 600;
    if (window.electronAPI && window.electronAPI.openExtensionWindow) {
      try {
        if (extension.enableVrmWindowSize){
          console.log('VRM window size enabled')
          windowWidth = this.VRMConfig.windowWidth;
          windowHeight = this.VRMConfig.windowHeight
        }
        else{
          windowWidth = extension.width || 800;
          windowHeight = extension.height || 600;
        }
        const windowId = await window.electronAPI.openExtensionWindow(`${this.partyURL}${url}`, {
          id: extension.id,
          name: extension.name,
          transparent: extension.transparent || false,
          width: windowWidth,
          height: windowHeight,
        });
        console.log(`Extension window opened with ID: ${windowId}`);
      } catch (error) {
        console.error('Failed to open extension window:', error);
        window.open(`${this.partyURL}${url}`, '_blank');
      }
    } else {
      window.open(`${this.partyURL}${url}`, '_blank');
    }
  },

  async updatePlugin(plugin) {
    // 临时响应式标记
    plugin._updating = true // 发送更新请求
    try {
      const res = await fetch(`/api/extensions/${plugin.id}/update`, { method: 'PUT' })
      if (!res.ok) throw new Error(await res.text())
      showNotification(this.t('updateSuccess'))
      // 更新完后刷新本地列表，重新标 installed 状态
      this.fetchRemotePlugins();
    } catch (e) {
      showNotification(this.t('updateFailed') + ': ' + e.message, 'error')
    } finally {
      plugin._updating = false
    }
  },

// 核心逻辑：判断并控制扩展页面的轮询
  handleExtensionsPolling(menu, sub) {
    if (menu === 'api-group' && sub === 'extension') {
      this.startExtensionsPolling();
    } else {
      this.stopExtensionsPolling();
    }
  },

  // 进入设置类页面时自动拉取原本需手动点「刷新」才加载的列表
  handleAutoLoadOnMenu(menu, sub) {
    if (menu === 'system') {
      this.loadBackupList();
      this.eosGuardInit();          // S160 潜龙勿用：状态与巡检基线
      this.eosGuardLoadQuarantine();
    } else if (menu === 'deploy-bot' && sub === 'im_bot') {
      this.fetchBotConversations();
      this.fetchXmppCertPending();
    }
  },

  // 启动扩展轮询
  startExtensionsPolling() {
    if (this.extensionsPollingTimer) return;
    
    // 立即执行一次刷新
    this.scanExtensions(); 

    this.extensionsPollingTimer = setInterval(() => {
      console.log('正在轮询获取 Extensions...');
      this.scanExtensions();
    }, 5000);
  },

  // 停止扩展轮询
  stopExtensionsPolling() {
    if (this.extensionsPollingTimer) {
      clearInterval(this.extensionsPollingTimer);
      this.extensionsPollingTimer = null;
      console.log('已停止轮询 Extensions');
    }
  },

  // 辅助方法：对比本地和远程，同步更新状态
  syncExtensionUpdateStatus() {
    if (!this.extensions || !this.remotePlugins) return;

    // 1. 遍历远程列表，标记 "installed" 和 "hasUpdate" 状态
    this.remotePlugins = this.remotePlugins.map(r => {
      const local = this.extensions.find(l => 
          (l.repository && r.repository && l.repository.trim().toLowerCase() === r.repository.trim().toLowerCase()) || 
          (l.id && r.id && l.id === r.id)
      );
      let installed = !!local;
      let hasUpdate = false;
      
      if (local && local.version && r.version) {
        if (this.compareVersions(local.version, r.version) < 0) {
          hasUpdate = true;
        }
      }
      return { ...r, installed, hasUpdate };
    });

    // 2. 遍历本地列表，标记 "hasUpdate" 状态
    this.extensions = this.extensions.map(l => {
      const remote = this.remotePlugins.find(r => 
          (l.repository && r.repository && l.repository.trim().toLowerCase() === r.repository.trim().toLowerCase()) || 
          (l.id && r.id && l.id === r.id)
      );
      let hasUpdate = false;
      if (remote && l.version && remote.version) {
        if (this.compareVersions(l.version, remote.version) < 0) {
          hasUpdate = true;
        }
      }
      return { ...l, hasUpdate };
    });
  },

  // 辅助方法：语义化版本比较
  compareVersions(v1, v2) {
    if (!v1 || !v2) return 0;
    const parts1 = v1.toString().replace(/[^0-9.]/g, '').split('.').map(Number);
    const parts2 = v2.toString().replace(/[^0-9.]/g, '').split('.').map(Number);
    for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
      const num1 = parts1[i] || 0;
      const num2 = parts2[i] || 0;
      if (num1 < num2) return -1;
      if (num1 > num2) return 1;
    }
    return 0;
  },

// 4. 扩展收藏逻辑
toggleFavoriteExtension(ext) {
  const index = this.favoriteExtensionIds.indexOf(ext.id);
  if (index > -1) {
    this.favoriteExtensionIds.splice(index, 1);
  } else {
    this.favoriteExtensionIds.push(ext.id);
  }
  // 持久化存储
  localStorage.setItem('favorite_extensions', JSON.stringify(this.favoriteExtensionIds));
},

gotoAddExtension(){
  this.activeMenu = 'api-group';
  this.subMenu = 'extension';
  this.openAddExtensionDialog();
},

  // 2. 添加这两个处理鼠标状态的方法
  handleExtMouseMove() {
    this.extButtonVisible = true;
    
    // 清除上一次的定时器
    if (this.extMouseTimer) {
      clearTimeout(this.extMouseTimer);
    }
    
    // 如果鼠标停止移动 1.5 秒，自动隐藏按钮
    this.extMouseTimer = setTimeout(() => {
      this.extButtonVisible = false;
    }, 1500);
  },

  hideExtButton() {
    this.extButtonVisible = false;
    if (this.extMouseTimer) {
      clearTimeout(this.extMouseTimer);
    }
  },

connectToChatApp(){
  this.activeMenu = 'deploy-bot';
  this.subMenu = 'im_bot';
}
});
