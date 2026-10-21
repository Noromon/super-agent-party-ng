// 批 3 F2：自 vue_methods.js 搬移的 methods/54_ui_nav.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    switchTollmTools() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'llmTool';
    },

    switchToHttpTools() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'customHttpTool';
    },

    switchToComfyui() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'comfyui';
    },

    switchToStickerPacks() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'sticker';
    },

    switchToMainAgent() {
      this.activeMenu = 'api-group';
      this.subMenu = 'agents';
    },

    switchToTTS() {
      this.activeMenu = 'model-config';
      this.subMenu = 'tts';
    },

    switchToExtensionPage() {
      this.activeMenu = 'api-group';
      this.subMenu = 'extension';
    },

    switchToagents() {
      this.activeMenu = 'api-group';
      this.subMenu = 'agents';
      this.activeAgentTab = 'add'
    },

    switchToa2aServers() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'a2a';
    },

    switchToSystemPrompts() {
      this.showEditDialog = false;
      this.activeMenu = 'role';
      this.subMenu = 'memory';
      this.activeMemoryTab = 'prompts';
    },

    switchTomcpServers() {
      this.activeMenu = 'toolkit';
      this.subMenu = 'mcp'
    },

    // 窗口控制
    minimizeWindow() {
      if (isElectron) window.electronAPI.windowAction('minimize');
    },

    maximizeWindow() {
      if (isElectron) window.electronAPI.windowAction('maximize');
    },

    closeWindow() {
      if (isElectron) window.electronAPI.windowAction('close');
    },

    goToURL(provider) {
        let url = '';
        if (provider.vendor === 'custom') {
          url = provider.url;
          // 移除url尾部的/v1
          if (url.endsWith('/v1')) {
            url = url.slice(0, -3);
          }
        }
        else if (provider.vendor === 'customAnthropic'){
          url = provider.url;
        }
        else {
          url = this.vendorAPIpage[provider.vendor];
        }
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
    },

    goToMCPURL(value) {
        const url = this.MCPpage[value]
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
    },

    goToPromptURL(value) {
        const url = this.promptPage[value]
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
    },

    goToCardURL(value) {
        const url = this.cardPage[value]
        if (isElectron) {
          window.electronAPI.openExternal(url);
        } else {
          window.open(url, '_blank');
        }
    }
});
