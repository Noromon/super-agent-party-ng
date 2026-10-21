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
    },

  toggleAssistantMode() {
    if (this.activeMenu != 'home' && this.activeMenu != 'dashboard'){
      this.activeMenu = 'home';
    }

    this.isPttMode = false;
    console.log('切换助手模式，当前状态:', this.isAssistantMode);

    if (this.isAssistantMode && !this.isMac) {
      // 退出助手模式，最大化窗口
      console.log('退出助手模式，最大化窗口');
      window.electronAPI.windowAction('maximize'); // 恢复默认大小
    } else {
      // 进入助手模式，设置为300x屏幕高度
      console.log('进入助手模式，设置大小为:', 340, 800);
      window.electronAPI.toggleWindowSize(340, 800);
    }

    this.sidePanelOpen = false;
    this.isAssistantMode = !this.isAssistantMode;
    console.log('切换完成，新状态:', this.isAssistantMode);
  },

    fixedWindow() {
    // 把新状态取反
    const next = !this.isFixedWindow;
    // 告诉主进程设置置顶
    window.electronAPI.setAlwaysOnTop(next);
    // 本地状态同步
    this.isFixedWindow = next;
  },

  handleScreenshotCommand(command) {
    if (command === 'hide') {
      // 点击了"隐藏窗口截图" -> 传入 true
      this.toggleScreenshot(true);
    } else if (command === 'no-hide') {
      // 点击了"当前窗口截图" -> 传入 false
      this.toggleScreenshot(false);
    }
  },

  // 修改：保留原有的截图逻辑，参数 hideMainWindow 决定是否隐藏
  async toggleScreenshot(hideMainWindow = true) {
    try {
      // 1. 调用遮罩
      const rect = await window.electronAPI.showScreenshotOverlay(hideMainWindow)
      
      if (!rect) return // 用户取消

      // 2. 裁剪
      const buf = await window.electronAPI.cropDesktop({ rect })

      // 3. 创建 Blob 和 File
      const blob = new Blob([buf], { type: 'image/png' })
      const file = new File([blob], `desktop_${Date.now()}.png`, { type: 'image/png' })

      // 4. ★ 关键修复：创建本地 URL 用于预览，并推入 images 数组
      const localUrl = URL.createObjectURL(blob)
      
      // 推入 images 数组（假设 allItems 是计算属性包含 images）
      this.images.push({ 
        file, 
        name: file.name, 
        path: localUrl,  // ★ 使用 blob URL 而不是空字符串
        type: 'image'    // ★ 明确标记类型，便于 allItems 处理
      })

      // ★ 如果 allItems 是独立数组，也需要同步推送
      // this.allItems.push({
      //   name: file.name,
      //   path: localUrl,
      //   type: 'image',
      //   file: file
      // })

    } catch (e) {
      console.error('截图失败:', e)
    } finally {
      // 5. 清理并恢复窗口
      await window.electronAPI.cancelScreenshotOverlay();
      window.electronAPI.windowAction('show');
    }
  },

  async toggleCapsuleMode() {
    this.activeMenu = 'home';
    this.isPttMode = false;
    if (this.isCapsuleMode && !this.isMac) {
      window.electronAPI.windowAction('maximize') // 恢复默认大小
    } else{
      window.electronAPI.toggleWindowSize(210, 80);
    }
    this.sidePanelOpen = false;
    this.isCapsuleMode = !this.isCapsuleMode;
  },

openAiBrowser(){
  this.activeMenu = 'ai-browser';
  this.chromeMCPSettings.type = 'internal';
  this.chromeMCPSettings.enabled = true;
  this.changeChromeMCPEnabled();
}
});
