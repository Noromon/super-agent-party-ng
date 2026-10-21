// 批 3 F2：自 vue_methods.js 搬移的 methods/60_system_settings.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    async autoSaveSettings() {
      if (this.isElectron) {
        await window.electronAPI.saveChromeSettings(JSON.parse(JSON.stringify(this.chromeMCPSettings)));
      }
      return new Promise((resolve, reject) => {
        this.ensureConversationGroups();
        // payload 由 settings_schema.js 单一事实源生成（批 0-④，替代 71 对手写清单）
        const payload = window.SETTINGS_SCHEMA.buildSettingsPayload(this);
        const correlationId = uuid.v4();
        // 发送保存请求
        this.ws.send(JSON.stringify({
          type: 'save_settings',
          data: payload,
          correlationId: correlationId // 添加唯一请求 ID
        }));
        // 设置响应监听器
        const handler = (event) => {
          const response = JSON.parse(event.data);
          
          // 匹配对应请求的确认消息
          if (response.type === 'settings_saved' && 
              response.correlationId === correlationId) {
            this.ws.removeEventListener('message', handler);
            resolve();
          }
          
          // 错误处理（根据后端实现）
          if (response.type === 'save_error') {
            this.ws.removeEventListener('message', handler);
            reject(new Error('保存失败'));
          }
        };
        // 设置 10 秒超时
        const timeout = setTimeout(() => {
          this.ws.removeEventListener('message', handler);
          reject(new Error('保存超时'));
        }, 10000);
        this.ws.addEventListener('message', handler);
      });
    },

    // 修改copyEndpoint方法
    copyEndpoint() {
      navigator.clipboard.writeText(`${this.partyURL}/v1`)
        .then(() => {
          showNotification(this.t('copy_success'), 'success');
        })
        .catch(() => {
          showNotification(this.t('copy_fail'), 'error');
        });
    },

    copyMCPEndpoint(){
      navigator.clipboard.writeText(`${this.partyURL}/mcp`)
        .then(() => {
          showNotification(this.t('copy_success'), 'success');
        })
        .catch(() => {
          showNotification(this.t('copy_fail'), 'error');
        });
    },

    copyVrmEndpoint(){
      navigator.clipboard.writeText(`${this.partyURL}/vrm.html`)
        .then(() => {
          showNotification(this.t('copy_success'), 'success');
        })
        .catch(() => {
          showNotification(this.t('copy_fail'), 'error');
        });
    },

    copyURL(url) {
      navigator.clipboard.writeText(url)
        .then(() => {
          showNotification(this.t('copy_success'), 'success');
        })
        .catch(() => {
          showNotification(this.t('copy_fail'), 'error');
        });
    },

    copyModel() {
      navigator.clipboard.writeText('super-model')
        .then(() => {
          showNotification(this.t('copy_success'));
        })
        .catch(() => {
          showNotification(this.t('copy_fail'), 'error');
        });
    },

    toggleSection(section) {
      this.expandedSections[section] = !this.expandedSections[section]
      this.autoSaveSettings()
    },

    // 新增点击头部的处理
    handleHeaderClick(section) {
      this.toggleSection(section)
    },

    async clearMessages(groupId = null) {
      this.stopGenerate();
      const targetGroupId = groupId || this.activeConversationGroupId || this.draftConversationGroupId || 'default';
      this.activeConversationGroupId = targetGroupId;
      this.draftConversationGroupId = targetGroupId;
      if (this.system_prompt){
        this.messages = [{ role: 'system', content: this.system_prompt }];
      } else {
        this.messages = [{ role: 'system', content: ' ' }];
      }
      this.conversationId = null;
      this.fileLinks = [];
      this.isThinkOpen = false; // 重置思考模式状态
      this.asyncToolsID = [];
      this.inAutoMode = false; // 重置自动模式状态
      this.randomGreetings(); // 重新生成随机问候语
      this.requestScrollToBottom();    // 触发界面更新
      this.autoSaveSettings();
      this.sendMessagesToExtension(true); // 发送消息到插件
    },

    switchToApiBox() {
      // 切换到 API 钥匙箱界面
      this.activeMenu = 'model-config';
      this.subMenu = 'service';
    },

    highlightCode() {
      this.$nextTick(() => {
        document.querySelectorAll('pre code').forEach(block => {
          hljs.highlightElement(block);
        });
        this.initCopyButtons();
      });
    },

    async handleSystemLanguageChange(val) {
      this.systemSettings.language = val;
      if (val === 'auto') {
        // 获取系统设置，默认是'en-US'，如果系统语言是中文，则设置为'zh-CN'
        const systemLanguage = navigator.language || navigator.userLanguage || 'en-US';
        val = systemLanguage.startsWith('zh') ? 'zh-CN' : 'en-US';
      }
      this.currentLanguage = val; // 更新当前语言
      await this.autoSaveSettings();
      this.$forceUpdate();
    },

    // renderer.js 增强方法
    async handleThemeChange(val) {
      // 更新根属性
      document.documentElement.setAttribute('data-theme', val);
      
      this.systemSettings.theme = val;

      await this.autoSaveSettings();
    },

    async handleNetworkChange(val) {
      this.systemSettings.network = val;
      await window.electronAPI.setNetworkVisibility(val);
      this.showRestartDialog = true;
      await this.autoSaveSettings();
    },

    restartApp() {
      window.electronAPI.restartApp();
    },

    // 方法替换为：
    launchBrowserMode() {
      this.isBrowserOpening = true;
      
      setTimeout(() => {
        const url = this.partyURL;
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
        
        // 2秒后恢复状态
        setTimeout(() => {
          this.isBrowserOpening = false;
        }, 2000);
      }, 500);
    },

    launchAPIKeyManager() {
      this.isBrowserOpening = true;
      
      setTimeout(() => {
        const url = this.partyURL + '/token.html';
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
        
        // 2秒后恢复状态
        setTimeout(() => {
          this.isBrowserOpening = false;
        }, 2000);
      }, 500);
    },

openEnvPage(menu) {
  this.activeMenu = menu;
},

      toggleInputExpand() {
        this.isInputExpanded = !this.isInputExpanded
    },

    checkMobile() {
      this.isMobile = window.innerWidth <= 768;
      this.isAssistantMode = window.innerWidth <= 350 && window.innerHeight <= 820;
      this.isCapsuleMode = window.innerWidth <= 220 && window.innerHeight <= 100;
      if (this.isMobile) {
        this.MoreButtonDict = this.smallMoreButtonDict;
      }
      else{
        this.MoreButtonDict = this.largeMoreButtonDict;
      }
      if (this.isAssistantMode){
        if(!this.isFixedWindow){
          this.isFixedWindow = true;
          if (isElectron){
            window.electronAPI.setAlwaysOnTop(this.isFixedWindow);
          }
        }
        
      }else{
        if(this.isFixedWindow){
          this.isFixedWindow = false;
          if (isElectron){
            window.electronAPI.setAlwaysOnTop(this.isFixedWindow);
          }
        }
      }
      if(this.isMobile) this.sidebarVisible = false;
    },

  toggleBriefly(index){
    if (this.messages[index].briefly){
      this.messages[index].briefly = !this.messages[index].briefly;
    }else{
      this.messages[index].briefly = true;
    }
  },

  async rewrite(index){
    if (index != 1){
      // 删除this.messages中从index起之后的所有元素，包括index
      this.messages.splice(index);
      this.userInput = this.messages[index-1].pure_content??this.messages[index-1].content;
      // 删除this.messages中最后一个元素
      this.messages.pop();
    }else{
      // 替换开场白
      this.randomGreetings();
    }

    await this.sendMessage();
  },

  async updateProxy(){
    await this.autoSaveSettings();
    const response = await fetch('/api/update_proxy',{
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    if (response.ok) {
      const data = await response.json();
      console.log(data);
    }else {
      console.error('更新代理失败');
    }
  },

  async openUserfile(){
    const response = await fetch('/api/get_userfile',{
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    if (response.ok) {
      // 拿到userfile
      const data = await response.json();
      let userfile = data.userfile;    // 打开文件夹
      if (this.isElectron){
        window.electronAPI.openPath(userfile);
      }
    }
  },

  async openLogfile(){
    const response = await fetch('/api/get_userfile',{
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    if (response.ok) {
      // 拿到userfile
      const data = await response.json();
      let userfile = data.userfile;    // 打开文件夹
      if (this.isElectron){
        window.electronAPI.openPath(userfile+'/logs');
      }
    }
  },

  async openExtfile(){
    const response = await fetch('/api/get_extfile',{
      method: 'GET',
      headers: {
        'Content-Type': 'application/json'
      }
    });
    if (response.ok) {
      // 拿到Extfile
      const data = await response.json();
      let extfile = data.extfile;    // 打开文件夹
      if (this.isElectron){
        window.electronAPI.openPath(extfile);
      }
    }
  },

  async changeHAEnabled(){
    if (this.HASettings.enabled){
      const response = await fetch('/start_HA',{
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          data: this.HASettings
        })
      });
      if (response.ok) {
        const data = await response.json();
        console.log(data);
        showNotification(this.t('success_start_HA'));
      }else {
        this.HASettings.enabled = false;
        console.error('启动HA失败');
        showNotification(this.t('error_start_HA'), 'error');
      }
    }else{
      const response = await fetch('/stop_HA',{
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        }
      });
      if (response.ok) {
        const data = await response.json();
        console.log(data);
        showNotification(this.t('success_stop_HA'));
      }else {
        this.HASettings.enabled = true;
        console.error('停止HA失败');
        showNotification(this.t('error_stop_HA'), 'error');
      }
    }
    this.autoSaveSettings();
  },

  async changeChromeMCPEnabled(){

    if (this.chromeMCPSettings.enabled && this.chromeMCPSettings.type === 'internal' && this.isElectron) {
        if (!window.electronAPI) return;
        await this.autoSaveSettings();
        // 获取主进程实际状态
        const cdpInfo = await window.electronAPI.getInternalCDPInfo();

        if (!cdpInfo.active) {
            // 严重情况：前端想开，但主进程没开端口（说明没重启）
            // this.chromeMCPSettings.enabled = false; // 回滚开关
            this.showCDPRestartDialog = true;
            
            return; // 终止后续流程
        }

        // 主进程已开启端口 -> 关键步骤：同步随机端口！
        // 这样发给后端的 JSON 里 CDPport 才是主进程真正监听的端口 (例如 9527)
        this.chromeMCPSettings.CDPport = cdpInfo.port;
        console.log(`[CDP] 准备启动 MCP，使用实际端口: ${cdpInfo.port}`);
        
        // 保存最新的端口到配置文件 (可选，为了稳妥)
        await this.autoSaveSettings();
        showNotification(this.t('success_start_browserControl'));
    }
    if (this.chromeMCPSettings.enabled && this.chromeMCPSettings.type === 'external'){
      const response = await fetch('/start_ChromeMCP',{
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          data: this.chromeMCPSettings
        })
      });
      if (response.ok){
        const data = await response.json();
        console.log(data);
        showNotification(this.t('success_start_browserControl'));
      }else {
        this.chromeMCPSettings.enabled = false;
        console.error('启动ChromeMCP失败');
        showNotification(this.t('error_start_browserControl'), 'error');
      }
    }else{
      const response = await fetch('/stop_ChromeMCP',{
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        },
      });
      if (response.ok){
        const data = await response.json();
        console.log(data);
        if (this.chromeMCPSettings.type === 'external'||!this.chromeMCPSettings.enabled){
          showNotification(this.t('success_stop_browserControl'));
        }
      }else {
        this.chromeMCPSettings.enabled = true;
        console.error('停止ChromeMCP失败');
        if (this.chromeMCPSettings.type === 'external'||!this.chromeMCPSettings.enabled){
          showNotification(this.t('error_stop_browserControl'), 'error');
        }
      }
    }
    this.autoSaveSettings();
  },

  async changeSqlEnabled() {
    if (this.sqlSettings.enabled) {
      
      // ==========================================
      // 1. 启动前置校验 (新增逻辑)
      // ==========================================
      const settings = this.sqlSettings;
      let errorMsg = '';

      if (settings.engine === 'sqlite') {
        // SQLite 只需要校验 dbpath
        if (!settings.dbpath?.trim()) {
          errorMsg = this.t('pleaseConfigSqliteDbpath');
        }
      } else {
        // 其他数据库校验 host, port, user, password, dbname
        if (!settings.host?.trim()) {
          errorMsg = this.t('pleaseConfigSqlHost');
        } else if (settings.port === undefined || settings.port === null || settings.port === '') {
          errorMsg = this.t('pleaseConfigSqlPort');
        } else if (!settings.user?.trim()) {
          errorMsg = this.t('pleaseConfigSqlUser');
        } else if (!settings.password?.trim()) {
          errorMsg = this.t('pleaseConfigSqlPassword');
        } else if (!settings.dbname?.trim()) {
          errorMsg = this.t('pleaseConfigSqlDbname');
        }
      }

      // 校验失败：弹窗报错，重置开关并阻断执行
      if (errorMsg) {
        const errorTitle = this.t ? this.t('configIncomplete') : 'Configuration Incomplete';
        showNotification(errorMsg, 'error', errorTitle);

        this.$nextTick(() => {
          this.sqlSettings.enabled = false;
        });
        
        return; // ⚠️ 必须 return，防止继续执行下方的 fetch 请求
      }

      // ==========================================
      // 2. 原有的启动逻辑 (校验通过后执行)
      // ==========================================
      const response = await fetch('/start_sql', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          data: this.sqlSettings
        })
      });
      if (response.ok) {
        const data = await response.json();
        console.log(data);
        showNotification(this.t('success_start_sqlControl'));
      } else {
        this.sqlSettings.enabled = false;
        console.error('启动sql失败');
        showNotification(this.t('error_start_sqlControl'), 'error');
      }

    } else {
      
      // ==========================================
      // 3. 原有的停止逻辑 (用户关闭开关时执行)
      // ==========================================
      const response = await fetch('/stop_sql', {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json'
        },
      });
      if (response.ok) {
        const data = await response.json();
        console.log(data);
        showNotification(this.t('success_stop_sqlControl'));
      } else {
        this.sqlSettings.enabled = true;
        console.error('停止sql失败');
        showNotification(this.t('error_stop_sqlControl'), 'error');
      }
    }
    
    // ==========================================
    // 4. 操作成功后保存配置
    // ==========================================
    this.autoSaveSettings();
  },

    openBrainEdit(brainKey) {
      this.currentEditingKey = brainKey;
      this.showBrainEditDialog = true;
    },

    handleFirecrawlPresetChange(val) {
      if (val === 'official') {
        this.webSearchSettings.firecrawl_url = 'https://api.firecrawl.dev/v2';
      } else {
        this.webSearchSettings.firecrawl_url = 'http://localhost:3002/v1';
      }
      this.autoSaveSettings();
    },

    async initChromeMCPSettings() {
        if (!window.electronAPI) return;

        // 1. 询问主进程：你现在开 CDP 了吗？端口是多少？
        const cdpInfo = await window.electronAPI.getInternalCDPInfo();
        
        // 2. 如果主进程确实开启了内部模式
        if (cdpInfo.active) {
            console.log(`[Frontend] 检测到内部 CDP 已激活，端口: ${cdpInfo.port}`);
            
            // 强制同步前端数据
            this.chromeMCPSettings.type = 'internal'; 
            this.chromeMCPSettings.CDPport = cdpInfo.port;
            
            // 这里不一定强制 enabled = true，因为 enabled 代表“Python服务是否在运行”
            // 但如果 Electron 开了端口，通常意味着配置里 enabled 是 true
            // 我们更新配置文件，确保端口是最新的
            await this.autoSaveSettings();
        }
    }
});
