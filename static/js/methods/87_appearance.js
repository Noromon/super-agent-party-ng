// R2-1 外观包（A14）：背景图上传/历史、CSS 注入、全局与代码字号缩放
// （Object.assign 装配，移植自上游 vue_methods.js）。
Object.assign(vue_methods, {
    // 触发背景图文件选择框
    triggerBgUpload() {
      if (this.$refs.bgImageInput) {
        this.$refs.bgImageInput.click();
      }
    },

    // 处理背景图文件上传
    async handleBgUpload(event) {
      const file = event.target.files[0];
      if (!file) return;

      // 重置 input value，防止选择相同文件时不触发 change 事件
      event.target.value = '';

      const formData = new FormData();
      // 'files' 字段需与后端 @app.post("/load_file") 中一致
      formData.append('files', file, file.name);

      try {
        const response = await fetch('/load_file', {
          method: 'POST',
          body: formData
        });

        const data = await response.json();

        if (data.success && data.fileLinks && data.fileLinks.length > 0) {
          // 获取后端返回的完整 URL 路径并赋值给 backgroundURL
          const uploadedUrl = data.fileLinks[0].path;
          this.systemSettings.backgroundURL = uploadedUrl;

          // 自动保存配置
          this.autoSaveSettings();

          showNotification(this.t('uploadSuccess') || 'Upload successful', 'success');
        } else {
          showNotification(this.t('uploadFailed') || 'Upload failed', 'error');
        }
      } catch (error) {
        console.error('Background upload error:', error);
        showNotification(error.message || 'Upload error', 'error');
      }
    },

    clearBgImage() {
      this.systemSettings.backgroundURL = '';
      if (typeof this.autoSaveSettings === 'function') {
        this.autoSaveSettings();
      }
    },

    // 打开保存背景图的弹窗
    openSaveBgDialog() {
      if (!this.systemSettings.backgroundURL) {
        showNotification(this.t('noBgToSave'), 'warning');
        return;
      }
      this.newBgName = '';
      this.saveBgDialogVisible = true;
    },

    // 确认保存背景图到历史列表
    confirmSaveBg() {
      if (!this.newBgName.trim()) {
        showNotification(this.t('pleaseInputBgName'), 'warning');
        return;
      }

      // 确保列表已初始化(防范旧数据不存在该字段的情况)
      if (!this.systemSettings.bgHistoryList) {
        this.systemSettings.bgHistoryList = [];
      }

      // 检查当前URL是否已经在历史记录中
      const existingIndex = this.systemSettings.bgHistoryList.findIndex(
        bg => bg.url === this.systemSettings.backgroundURL
      );

      if (existingIndex !== -1) {
        // 如果存在，直接覆盖名字
        this.systemSettings.bgHistoryList[existingIndex].name = this.newBgName.trim();
      } else {
        // 如果不存在，新增一条记录
        this.systemSettings.bgHistoryList.push({
          name: this.newBgName.trim(),
          url: this.systemSettings.backgroundURL
        });
      }

      // 自动保存设置
      this.autoSaveSettings();

      this.saveBgDialogVisible = false;

      showNotification(this.t('bgSavedSuccess'), 'success');
    },

    // 切换历史背景图
    handleBgHistorySelect(url) {
      this.systemSettings.backgroundURL = url;
      if (!url) {
        // 选择"无背景图片"时，触发原有的清除逻辑
        if (typeof this.clearBgImage === 'function') {
          this.clearBgImage();
        } else {
          this.autoSaveSettings();
        }
      } else {
        this.autoSaveSettings();
      }
    },

    // 删除某条历史背景图记录
    deleteBgHistory(url) {
      if (!this.systemSettings.bgHistoryList) return;

      this.systemSettings.bgHistoryList = this.systemSettings.bgHistoryList.filter(
        item => item.url !== url
      );

      // 删除记录后，调用自动保存
      this.autoSaveSettings();

      showNotification(this.t('bgRemovedSuccess'), 'success');
    },

    // 全局字体缩放：基准 14px，范围 0.85 ~ 1.5。
    // Electron 走 webFrame.setZoomFactor 抗锯齿更好；其余环境兜底用 CSS zoom。
    async handleFontScaleChange(val) {
      const safe = Math.max(0.85, Math.min(1.5, Number(val) || 1));
      if (this.isElectron && window.electronAPI?.setZoomFactor) {
        try {
          window.electronAPI.setZoomFactor(safe);
        } catch (e) {
          document.documentElement.style.zoom = safe;
        }
      } else {
        document.documentElement.style.zoom = safe;
      }
      document.documentElement.style.setProperty('--app-zoom', String(safe));
      this.systemSettings.fontScale = safe;
      await this.autoSaveSettings();
    },
    resetFontScale() {
      this.handleFontScaleChange(1);
    },
    // 代码字体独立缩放：基准 12px，范围 0.83 ~ 1.67。
    // 只写 --code-zoom，由 appearance.css 中 pre.code-block 的 calc(--code-zoom / --app-zoom) 抵消全局缩放。
    async handleCodeFontScaleChange(val) {
      const safe = Math.max(0.83, Math.min(1.67, Number(val) || 1));
      document.documentElement.style.setProperty('--code-zoom', String(safe));
      this.systemSettings.codeFontScale = safe;
      await this.autoSaveSettings();
    },
    resetCodeFontScale() {
      this.handleCodeFontScaleChange(1);
    },
});
