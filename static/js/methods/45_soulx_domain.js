// S136(SoulX)：真人伴侣域方法（Object.assign 装配，加载顺序在宿主之后、renderer 之前）。
// 自上游 vue_methods SoulX 段移植终态；connectToSoulx 的 subMenu 改为 fork 磁贴 id。
Object.assign(vue_methods, {
  // ========== SoulX FlashHead Methods ==========
  async startSoulx() {
    if (this.isSoulxStarting) return;
    if (this.isElectron) {
      this.SoulxConfig.name = 'default';
      await this.autoSaveSettings();
      try {
        this.isSoulxStarting = true;
        const windowConfig = {
          width: this.SoulxConfig.windowWidth,
          height: this.SoulxConfig.windowHeight,
        };
        await window.electronAPI.startSoulxWindow(windowConfig);
      } catch (error) {
        console.error('启动SoulX失败:', error);
      } finally {
        this.isSoulxStarting = false;
      }
    } else {
      window.open(`${this.partyURL}/soulx.html`, '_blank');
    }
  },

  async startSoulxweb() {
    if (this.isElectron) {
      window.electronAPI.openExternal(`${this.partyURL}/soulx.html`);
    } else {
      window.open(`${this.partyURL}/soulx.html`, '_blank');
    }
  },

  async stopSoulx() {
    if (this.isElectron) {
      try {
        await window.electronAPI.stopSoulxWindow();
      } catch (error) {
        console.error('停止SoulX失败:', error);
      }
    }
  },

  async loadSoulxImages() {
    try {
      const res = await fetch('/get_soulx_images');
      const data = await res.json();
      if (data.success) {
        this.SoulxConfig.images = data.images || [];
        // 旧版单图(base64存SQLite)自动迁移到多图管理
        if (this.SoulxConfig.images.length === 0 && this.SoulxConfig.condImage) {
          await this.migrateLegacySoulxImage();
        }
        // 选中项失效时回退到第一张
        const ids = this.SoulxConfig.images.map(i => i.id);
        if (this.SoulxConfig.selectedImageId && !ids.includes(this.SoulxConfig.selectedImageId)) {
          this.SoulxConfig.selectedImageId = ids[0] || '';
          await this.autoSaveSettings();
        }
      }
    } catch (error) {
      console.error('加载SoulX参考图列表失败:', error);
    }
  },

  async migrateLegacySoulxImage() {
    try {
      const byteString = atob(this.SoulxConfig.condImage);
      const bytes = new Uint8Array(byteString.length);
      for (let i = 0; i < byteString.length; i++) bytes[i] = byteString.charCodeAt(i);
      const blob = new Blob([bytes], { type: 'image/png' });
      const formData = new FormData();
      formData.append('file', blob, 'legacy.png');
      formData.append('display_name', '默认形象');
      const response = await fetch('/upload_soulx_image', { method: 'POST', body: formData });
      const result = await response.json();
      if (result.success) {
        this.SoulxConfig.images = [result.image];
        this.SoulxConfig.selectedImageId = result.image.id;
        this.SoulxConfig.condImage = '';
        await this.autoSaveSettings();
      }
    } catch (error) {
      console.error('迁移旧版SoulX参考图失败:', error);
    }
  },

  async uploadSoulxImage() {
    if (!this.newSoulxImage.file) {
      showNotification('请先选择图片文件', 'error');
      return;
    }
    const formData = new FormData();
    formData.append('file', this.newSoulxImage.file);
    formData.append('display_name', this.newSoulxImage.displayName.trim() || this.newSoulxImage.name.replace(/\.[^.]+$/, ''));

    try {
      const response = await fetch('/upload_soulx_image', { method: 'POST', body: formData });
      const result = await response.json();
      if (result.success) {
        this.SoulxConfig.images.push(result.image);
        this.SoulxConfig.selectedImageId = result.image.id;
        this.cancelSoulxImageUpload();
        await this.autoSaveSettings();
        showNotification('参考图上传成功');
      } else {
        showNotification(`上传失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('上传SoulX参考图失败:', error);
      showNotification('上传失败，请检查网络连接', 'error');
    }
  },

  async deleteSoulxImage(imageId) {
    try {
      const img = this.SoulxConfig.images.find(i => i.id === imageId);
      if (img && img.default) {
        showNotification('默认形象不可删除', 'warning');
        return;
      }
      const response = await fetch(`/delete_soulx_image/${imageId}`, { method: 'DELETE' });
      const result = await response.json();
      if (result.success) {
        const idx = this.SoulxConfig.images.findIndex(i => i.id === imageId);
        if (idx !== -1) this.SoulxConfig.images.splice(idx, 1);
        if (this.SoulxConfig.selectedImageId === imageId) {
          this.SoulxConfig.selectedImageId = this.SoulxConfig.images.length > 0 ? this.SoulxConfig.images[0].id : '';
        }
        await this.autoSaveSettings();
        showNotification('参考图已删除');
      } else {
        showNotification(`删除失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('删除SoulX参考图失败:', error);
      showNotification('删除失败，请稍后再试', 'error');
    }
  },

  handleSoulxImageFileDrop(event) {
    const files = event.dataTransfer.files;
    if (files.length > 0 && files[0].type.startsWith('image/')) {
      this.newSoulxImage.file = files[0];
      this.newSoulxImage.name = files[0].name;
      if (!this.newSoulxImage.displayName) {
        this.newSoulxImage.displayName = files[0].name.replace(/\.[^.]+$/, '');
      }
    }
  },

  browseSoulxImageFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/*';
    input.onchange = (e) => {
      if (e.target.files.length > 0) {
        this.newSoulxImage.file = e.target.files[0];
        this.newSoulxImage.name = e.target.files[0].name;
        if (!this.newSoulxImage.displayName) {
          this.newSoulxImage.displayName = e.target.files[0].name.replace(/\.[^.]+$/, '');
        }
      }
    };
    input.click();
  },

  cancelSoulxImageUpload() {
    this.newSoulxImage = { file: null, name: '', displayName: '' };
    this.showSoulxImageDialog = false;
  },

  connectToSoulx() {
    this.activeMenu = 'deploy-bot';
    this.subMenu = 'Soulx_pet';
  }
});
