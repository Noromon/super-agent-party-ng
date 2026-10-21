// 批 3 F2：自 vue_methods.js 搬移的 methods/42_vrm_domain.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    colorBlend(color1, color2, ratio) {
        // 确保ratio在0-1范围内
        ratio = Math.max(0, Math.min(1, ratio));
        
        // 解析十六进制颜色值
        const parseHex = (hex) => {
          hex = hex.replace(/^#/, '');
          // 处理3位简写格式
          if (hex.length === 3) {
            hex = hex.split('').map(char => char + char).join('');
          }
          return {
            r: parseInt(hex.substring(0, 2), 16),
            g: parseInt(hex.substring(2, 4), 16),
            b: parseInt(hex.substring(4, 6), 16)
          };
        };

        // 转换为两位十六进制字符串
        const toHex = (value) => {
          const hex = Math.round(value).toString(16);
          return hex.length === 1 ? '0' + hex : hex;
        };

        const rgb1 = parseHex(color1);
        const rgb2 = parseHex(color2);

        // 计算混合后的RGB值
        const r = rgb1.r * ratio + rgb2.r * (1 - ratio);
        const g = rgb1.g * ratio + rgb2.g * (1 - ratio);
        const b = rgb1.b * ratio + rgb2.b * (1 - ratio);

        // 组合成十六进制颜色
        return `#${toHex(r)}${toHex(g)}${toHex(b)}`;
      },

    // 触发文件选择框
    triggerAvatarUpload() {
      this.$refs.avatarInput.click();
    },

    // 处理文件上传
    async handleAvatarUpload(event) {
      const file = event.target.files[0];
      if (!file) return;

      // 重置 input value，防止选择相同文件时不触发 change 事件
      event.target.value = '';

      const formData = new FormData();
      // 注意：这里的 'files' 字段名必须与后端 @app.post("/load_file") 中定义的一致
      formData.append('files', file, file.name);

      try {
        // 可选：在这里显示加载动画
        // const loading = this.$loading({ lock: true, text: 'Uploading...' });

        const response = await fetch('/load_file', {
          method: 'POST',
          body: formData
        });

        const data = await response.json();
        
        // loading.close(); // 关闭加载动画

        if (data.success && data.fileLinks && data.fileLinks.length > 0) {
          // 获取后端返回的完整 URL
          const uploadedUrl = data.fileLinks[0].path;
          
          // 赋值给 newMemory.avatar
          this.newMemory.avatar = uploadedUrl;
          
          // 如果您有全局通知组件
          showNotification(this.t('uploadSuccess') || 'Upload successful', 'success');
        } else {
          showNotification(this.t('uploadFailed') || 'Upload failed', 'error');
        }
      } catch (error) {
        console.error('Avatar upload error:', error);
        showNotification(error.message || 'Upload error', 'error');
      }
    },

    handleFileUpload(file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        try {
          const jsonData = JSON.parse(event.target.result); // 解析 JSON 数据
          this.importMemoryData(jsonData); // 调用导入方法
          this.jsonFile = file; // 保存文件信息
        } catch (error) {
          showNotification('Invalid JSON file.', 'error'); // 错误提示
        }
      };

      reader.readAsText(file); // 读取文件内容
    },

  // 处理VRM模型拖拽
  handleVrmModelDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      // 检查文件扩展名
      if (!file.name.toLowerCase().endsWith('.vrm')) {
        showNotification('只支持.vrm格式的文件', 'error');
        return;
      }
      this.newVrmModel.name = file.name;
      this.newVrmModel.file = file;
      // 自动设置显示名称（去掉扩展名）
      this.newVrmModel.displayName = file.name.replace(/\.vrm$/i, '');
    }
  },

  // 移除已选择的VRM模型
  removeNewVrmModel() {
    this.newVrmModel.name = '';
    this.newVrmModel.displayName = '';
    this.newVrmModel.file = null;
  },

  // 取消上传
  cancelVrmModelUpload() {
    this.showVrmModelDialog = false;
    this.newVrmModel.name = '';
    this.newVrmModel.displayName = '';
    this.newVrmModel.file = null;
  },

  // 处理模型选择改变
  handleModelChange(value) {
    // 自动保存设置
    this.autoSaveSettings();
  },

    // 加载默认模型列表
  async loadDefaultModels() {
    try {
      const response = await fetch(`/get_default_vrm_models`);
      const result = await response.json();
      
      if (result.success) {
        this.VRMConfig.defaultModels = result.models;
        console.log(this.VRMConfig.defaultModels);
        // 如果没有选中任何模型，默认选择第一个默认模型
        if (!this.VRMConfig.selectedModelId && result.models.length > 0) {
          this.VRMConfig.selectedModelId = result.models[0].id;
        }
        await this.autoSaveSettings();
      }
    } catch (error) {
      console.error('加载默认模型失败:', error);
    }
  },

  // 修改上传VRM模型方法
  async uploadVrmModel() {
    if (!this.newVrmModel.file) {
      showNotification('请先选择VRM模型文件', 'error');
      return;
    }
    
    if (!this.newVrmModel.displayName.trim()) {
      showNotification('请输入模型显示名称', 'error');
      return;
    }
    
    const formData = new FormData();
    formData.append('file', this.newVrmModel.file);
    formData.append('display_name', this.newVrmModel.displayName.trim());
    
    try {
      const response = await fetch(`/upload_vrm_model`, {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 添加新模型到用户模型列表
        const newModelOption = {
          id: result.file.unique_filename,
          name: result.file.display_name,
          path: result.file.path,
          type: 'user' // 标记为用户上传的模型
        };
        
        this.VRMConfig.userModels.push(newModelOption);
        
        // 关闭对话框并重置状态
        this.cancelVrmModelUpload();
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('VRM模型上传成功');
      } else {
        showNotification(`上传失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('上传VRM模型失败:', error);
      showNotification('上传失败，请检查网络连接', 'error');
    }
  },

  // 修改删除模型选项方法（只能删除用户上传的模型）
  async deleteModelOption(modelId) {
    try {
      // 查找要删除的模型选项（只在用户模型中查找）
      const modelIndex = this.VRMConfig.userModels.findIndex(
        model => model.id === modelId
      );
      
      if (modelIndex === -1) {
        showNotification('无法删除默认模型', 'error');
        return;
      }
      
      // 调用后端API删除文件
      const response = await fetch(`/delete_vrm_model/${modelId}`, {
        method: 'DELETE'
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 从用户模型列表中移除
        this.VRMConfig.userModels.splice(modelIndex, 1);
        
        // 如果当前选中的模型被删除，则重置为默认模型
        if (this.VRMConfig.selectedModelId === modelId) {
          if (this.VRMConfig.defaultModels.length > 0) {
            this.VRMConfig.selectedModelId = this.VRMConfig.defaultModels[0].id;
          } else {
            this.VRMConfig.selectedModelId = '';
          }
        }
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('VRM模型已删除');
      } else {
        showNotification(`删除失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('删除VRM模型失败:', error);
      showNotification('删除失败，请稍后再试', 'error');
    }
  },

  // 获取当前选中的模型信息
  getCurrentSelectedModel() {
    // 先在默认模型中查找
    let selectedModel = this.VRMConfig.defaultModels.find(
      model => model.id === this.VRMConfig.selectedModelId
    );
    
    // 如果没找到，再在用户模型中查找
    if (!selectedModel) {
      selectedModel = this.VRMConfig.userModels.find(
        model => model.id === this.VRMConfig.selectedModelId
      );
    }
    
    return selectedModel;
  },

    // --- [4] 辅助函数：二进制打包打包器 ---
    sendBinaryToVRM(metadata, audioArrayBuffer) {
        if (!this.ttsWebSocket || this.ttsWebSocket.readyState !== WebSocket.OPEN) return;
        const metadataBytes = new TextEncoder().encode(JSON.stringify(metadata));
        const totalBuffer = new Uint8Array(4 + metadataBytes.byteLength + audioArrayBuffer.byteLength);
        const view = new DataView(totalBuffer.buffer);
        view.setUint32(0, metadataBytes.byteLength, true); // JSON长度
        totalBuffer.set(metadataBytes, 4);
        totalBuffer.set(new Uint8Array(audioArrayBuffer), 4 + metadataBytes.byteLength);
        this.ttsWebSocket.send(totalBuffer);
    }
});
