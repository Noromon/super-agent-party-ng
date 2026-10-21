// 批 3 F2：自 vue_methods.js 搬移的 methods/58_shortcuts_input.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
   async updateGlobalShortcut() {
      if (this.asrSettings.interactionMethod === 'globalKeyTriggered' || this.asrSettings.interactionMethod === 'keyTriggered'){
        this.stopASR();
      }else if (this.asrSettings.enabled){
        await this.startASR();
      }

      if (!window.electronAPI?.unregisterGlobalShortcut) return;
      
      // 每次更新前，先注销旧的
      await window.electronAPI.unregisterGlobalShortcut();

      // 如果启用了 ASR 且为全局快捷键模式
      if (this.asrSettings.interactionMethod === 'globalKeyTriggered') {
        const globalKeyCombo = this.getGlobalAccelerator(this.asrSettings.hotkey);
        
        const success = await window.electronAPI.registerGlobalShortcut(globalKeyCombo);
        if (!success) {
          this.$message.error(`全局快捷键 ${globalKeyCombo} 注册失败，可能被系统或其他软件占用`);
        } else {
          console.log(`全局快捷键已更新为: ${globalKeyCombo}`);
        }
      }
    },

    // 【新增】将你的单键转换为 Electron 系统的组合键格式
    getGlobalAccelerator(localKey) {
      if (localKey === 'Alt') return 'Alt+Space';
      if (localKey === 'Control') return 'Control+Space';
      if (localKey === 'Shift') return 'Shift+Space';
      return 'Alt+Space'; // 默认 fallback
    },

    // 【修改】键盘按下事件 (只处理局部 keyTriggered)
    async handleKeyDown(event) {
      if (event?.repeat) return; 
      if (event.isComposing || event.keyCode === 229) return;

      // ====== 局部模式 (按住说话) ======
      if (this.asrSettings.interactionMethod === "keyTriggered") {
        // 如果按下的键和设置的键严格匹配 (例如 'Alt' === 'Alt')
        if (event.key === this.asrSettings.hotkey) {
          event.preventDefault(); 
          await this.handlePttPress(event); // 开始录音
          return; 
        }
      }

      // -- 下方是你原有的播放控制及回车发送逻辑，保持不变 --
      if (event.code === 'Space' && event.shiftKey) {
        event.preventDefault();
        if (this.readState.ttsChunks.length > 0 && !this.readState.isPlaying) {
          this.playNextSegmentOnce();
        }
        return;
      }
      
      const isTextArea = event.target.tagName === 'TEXTAREA';
      if (event.key === 'Enter' && (this.activeMenu === 'home' || this.activeMenu ==='ai-browser')) {
        if (isTextArea) {
            if (event.shiftKey) {
              return;
            } else {
              event.preventDefault();
              await this.sendMessage();
            }
        }
      }

      if (event.key === 'Enter' && this.activeMenu ==='dashboard') {
            if (event.shiftKey) {
              return;
            } else {
              event.preventDefault();
              this.handleDashboardSend();
            }
      }
    },

    // 【修改】键盘松开事件 (只处理局部 keyTriggered)
    async handleKeyUp(event) {
      if (event?.repeat) return;

      // ====== 局部模式 (松开结束) ======
      if (this.asrSettings.interactionMethod === "keyTriggered") {
        if (event.key === this.asrSettings.hotkey) {
          event.preventDefault();
          await this.handlePttRelease(event); // 结束录音
          return;
        }
      }  
    }
});
