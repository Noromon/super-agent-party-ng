// S91(THA)：桌宠域方法（Object.assign 装配，加载顺序在宿主之后、renderer 之前）。
// 自上游 vue_methods THA 段移植终态；方法体互调仍走 this。
Object.assign(vue_methods, {
  // ========== THA Desktop Pet Methods ==========
  async startTHA() {
    if (this.isTHAStarting) return;
    if (this.isElectron) {
      this.THAConfig.name = 'default';
      await this.autoSaveSettings();
      try {
        this.isTHAStarting = true;
        const windowConfig = {
          width: this.THAConfig.windowWidth,
          height: this.THAConfig.windowHeight,
        };
        await window.electronAPI.startTHAWindow(windowConfig);
      } catch (error) {
        console.error('启动THA失败:', error);
      } finally {
        this.isTHAStarting = false;
      }
    } else {
      window.open(`${this.partyURL}/tha.html`, '_blank');
    }
  },

  async startTHAweb() {
    if (this.isElectron) {
      window.electronAPI.openExternal(`${this.partyURL}/tha.html`);
    } else {
      window.open(`${this.partyURL}/tha.html`, '_blank');
    }
  },

  async stopTHA() {
    if (this.isElectron) {
      try {
        await window.electronAPI.stopTHAWindow();
      } catch (error) {
        console.error('停止THA失败:', error);
      }
    }
  },

  copyTHAEndpoint() {
    navigator.clipboard.writeText(`${this.partyURL}/tha.html`)
      .then(() => {
        showNotification(this.t('copy_success'), 'success');
      })
      .catch(() => {
        showNotification(this.t('copy_fail'), 'error');
      });
  },

  async uploadTHAModel() {
    if (!this.newThaModel.file) {
      showNotification('请先选择模型文件', 'error');
      return;
    }
    if (!this.newThaModel.displayName.trim()) {
      showNotification('请输入模型显示名称', 'error');
      return;
    }

    const formData = new FormData();
    formData.append('file', this.newThaModel.file);
    formData.append('display_name', this.newThaModel.displayName.trim());

    try {
      const response = await fetch('/upload_tha_model', {
        method: 'POST',
        body: formData
      });
      const result = await response.json();

      if (result.success) {
        const newModelOption = {
          id: result.model.id,
          name: result.model.name,
          type: 'user'
        };
        this.THAConfig.userModels.push(newModelOption);
        this.cancelTHAModelUpload();
        await this.autoSaveSettings();
        showNotification('THA模型上传成功');
        await this.loadTHAModels();
      } else {
        showNotification(`上传失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('上传THA模型失败:', error);
      showNotification('上传失败，请检查网络连接', 'error');
    }
  },

  async deleteTHAModel(modelId) {
    try {
      const modelIndex = this.THAConfig.userModels.findIndex(
        model => model.id === modelId
      );
      if (modelIndex === -1) {
        showNotification('无法删除默认模型', 'error');
        return;
      }

      const response = await fetch(`/delete_tha_model/${modelId}`, {
        method: 'DELETE'
      });
      const result = await response.json();

      if (result.success) {
        this.THAConfig.userModels.splice(modelIndex, 1);
        if (this.THAConfig.selectedModelId === modelId) {
          if (this.THAConfig.defaultModels.length > 0) {
            this.THAConfig.selectedModelId = this.THAConfig.defaultModels[0].id;
          } else {
            this.THAConfig.selectedModelId = '';
          }
        }
        await this.autoSaveSettings();
        showNotification('THA模型已删除');
      } else {
        showNotification(`删除失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('删除THA模型失败:', error);
      showNotification('删除失败，请稍后再试', 'error');
    }
  },

  async loadTHAModels() {
    try {
      const [defaultRes, userRes] = await Promise.all([
        fetch('/get_default_tha_models'),
        fetch('/get_user_tha_models')
      ]);
      const defaultData = await defaultRes.json();
      const userData = await userRes.json();

      if (defaultData.success) {
        this.THAConfig.defaultModels = defaultData.models;
      }
      if (userData.success) {
        this.THAConfig.userModels = userData.models;
      }
    } catch (error) {
      console.error('加载THA模型列表失败:', error);
    }
  },

  handleTHAModelFileDrop(event) {
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      this.newThaModel.file = files[0];
      this.newThaModel.name = files[0].name;
    }
  },

  browseTHAModelFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.onnx,.zip';
    input.onchange = (e) => {
      if (e.target.files.length > 0) {
        this.newThaModel.file = e.target.files[0];
        this.newThaModel.name = e.target.files[0].name;
      }
    };
    input.click();
  },

  cancelTHAModelUpload() {
    this.newThaModel = { file: null, displayName: '' };
    this.showThaModelDialog = false;
  },

  removeNewTHAModel() {
    this.newThaModel.file = null;
    this.newThaModel.name = '';
  },
});
