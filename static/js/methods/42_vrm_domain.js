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
    },

    // 加载默认动作列表
  async loadDefaultMotions() {
    try {
      const response = await fetch(`/get_default_vrma_motions`);
      const result = await response.json();
      
      if (result.success) {
        this.VRMConfig.defaultMotions = result.motions;
        console.log('默认动作列表:', this.VRMConfig.defaultMotions);
        await this.autoSaveSettings();
      }
    } catch (error) {
      console.error('加载默认动作失败:', error);
    }
  },

  // 处理动作选择改变
  handleMotionChange(value) {
    console.log('选中的动作:', value);
    // 自动保存设置
    this.autoSaveSettings();
  },

  // 浏览VRMA动作文件
  browseVrmaMotionFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.vrma';
    input.multiple = true; // 允许多选
    input.onchange = (event) => {
      const files = event.target.files;
      if (files.length > 0) {
        // 如果选择了多个文件，只处理第一个（或者你可以修改为支持批量上传）
        const file = files[0];
        // 检查文件扩展名
        if (!file.name.toLowerCase().endsWith('.vrma')) {
          showNotification('只支持.vrma格式的文件', 'error');
          return;
        }
        this.newVrmaMotion.name = file.name;
        this.newVrmaMotion.file = file;
        // 自动设置显示名称（去掉扩展名）
        this.newVrmaMotion.displayName = file.name.replace(/\.vrma$/i, '');
      }
    };
    input.click();
  },

  // 处理VRMA动作拖拽
  handleVrmaMotionDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      const file = files[0];
      // 检查文件扩展名
      if (!file.name.toLowerCase().endsWith('.vrma')) {
        showNotification('只支持.vrma格式的文件', 'error');
        return;
      }
      this.newVrmaMotion.name = file.name;
      this.newVrmaMotion.file = file;
      // 自动设置显示名称（去掉扩展名）
      this.newVrmaMotion.displayName = file.name.replace(/\.vrma$/i, '');
    }
  },

  // 移除已选择的VRMA动作
  removeNewVrmaMotion() {
    this.newVrmaMotion.name = '';
    this.newVrmaMotion.displayName = '';
    this.newVrmaMotion.file = null;
  },

  // 取消VRMA动作上传
  cancelVrmaMotionUpload() {
    this.showVrmaMotionDialog = false;
    this.newVrmaMotion.name = '';
    this.newVrmaMotion.displayName = '';
    this.newVrmaMotion.file = null;
  },

  // 上传VRMA动作
  async uploadVrmaMotion() {
    if (!this.newVrmaMotion.file) {
      showNotification('请先选择VRMA动作文件', 'error');
      return;
    }
    
    if (!this.newVrmaMotion.displayName.trim()) {
      showNotification('请输入动作显示名称', 'error');
      return;
    }
    
    const formData = new FormData();
    formData.append('file', this.newVrmaMotion.file);
    formData.append('display_name', this.newVrmaMotion.displayName.trim());
    
    try {
      const response = await fetch(`/upload_vrma_motion`, {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 添加新动作到用户动作列表
        const newMotionOption = {
          id: result.file.unique_filename,
          name: result.file.display_name,
          path: result.file.path,
          type: 'user' // 标记为用户上传的动作
        };
        
        this.VRMConfig.userMotions.push(newMotionOption);
        
        // 自动选中新上传的动作
        if (!this.VRMConfig.selectedMotionIds.includes(newMotionOption.id)) {
          this.VRMConfig.selectedMotionIds.push(newMotionOption.id);
        }
        
        // 关闭对话框并重置状态
        this.cancelVrmaMotionUpload();
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('VRMA动作上传成功');
      } else {
        showNotification(`上传失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('上传VRMA动作失败:', error);
      showNotification('上传失败，请检查网络连接', 'error');
    }
  },

  // 删除动作选项（只能删除用户上传的动作）
  async deleteMotionOption(motionId) {
    try {
      // 查找要删除的动作选项（只在用户动作中查找）
      const motionIndex = this.VRMConfig.userMotions.findIndex(
        motion => motion.id === motionId
      );
      
      // 调用后端API删除文件
      const response = await fetch(`/delete_vrma_motion/${motionId}`, {
        method: 'DELETE'
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 从用户动作列表中移除
        this.VRMConfig.userMotions.splice(motionIndex, 1);
        
        // 如果当前选中的动作中包含被删除的动作，则从选中列表中移除
        const selectedIndex = this.VRMConfig.selectedMotionIds.indexOf(motionId);
        if (selectedIndex > -1) {
          this.VRMConfig.selectedMotionIds.splice(selectedIndex, 1);
        }
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification(this.t("VRMAactionDeleted"));
      } else {
        showNotification(`error: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('删除VRMA动作失败:', error);
      showNotification(error, 'error');
    }
  },

  // 获取当前选中的动作信息
  getCurrentSelectedMotions() {
    const selectedMotions = [];
    
    // 从默认动作中查找
    this.VRMConfig.defaultMotions.forEach(motion => {
      if (this.VRMConfig.selectedMotionIds.includes(motion.id)) {
        selectedMotions.push(motion);
      }
    });
    
    // 从用户动作中查找
    this.VRMConfig.userMotions.forEach(motion => {
      if (this.VRMConfig.selectedMotionIds.includes(motion.id)) {
        selectedMotions.push(motion);
      }
    });
    
    return selectedMotions;
  },

  // 获取所有可用的动作（默认 + 用户上传）
  getAllAvailableMotions() {
    return [...this.VRMConfig.defaultMotions, ...this.VRMConfig.userMotions];
  },

  // 根据ID获取动作信息
  getMotionById(motionId) {
    // 先在默认动作中查找
    let motion = this.VRMConfig.defaultMotions.find(m => m.id === motionId);
    
    // 如果没找到，再在用户动作中查找
    if (!motion) {
      motion = this.VRMConfig.userMotions.find(m => m.id === motionId);
    }
    
    return motion;
  },

async loadGaussScenes() {
  const [def, user] = await Promise.all([
    fetch('/get_default_gauss_scenes').then(r => r.json()),
    fetch('/get_user_gauss_scenes').then(r => r.json())
  ]);
  this.VRMConfig.gaussDefaultScenes = def.scenes || [];
  this.VRMConfig.gaussUserScenes   = user.scenes || [];
  console.log("默认场景：",this.VRMConfig.gaussDefaultScenes);
  if (!this.VRMConfig.selectedGaussSceneId) {
    this.VRMConfig.selectedGaussSceneId = 'transparent';
  }
  this.autoSaveSettings();
},

async handleGaussSceneChange(sceneId) {
  // 与 VRM 模型切换类似：把场景 id 写进 VRMConfig
  this.VRMConfig.selectedGaussSceneId = sceneId;

  this.autoSaveSettings();
},

browseGaussSceneFile() {
  const ipt = document.createElement('input');
  ipt.type = 'file';
  ipt.accept = '.ply,.spz,.splat,.ksplat,.sog';
  ipt.onchange = e => {
    const file = e.target.files[0];
    if (file) {
      this.newGaussScene.name = file.name;
      this.newGaussScene.file = file;   // 保存原始 File 对象
      this.newGaussScene.displayName = this.newGaussScene.displayName || this.newGaussScene.name;
    }
  };
  ipt.click();
},

handleGaussSceneDrop(e) {
  const file = e.dataTransfer.files[0];
  if (!file) return;
  const ext = file.name.split('.').pop().toLowerCase();
  if (!['ply','spz','splat','ksplat','sog'].includes(ext)) {
    return showNotification('不支持的文件类型', 'error');
  }
  this.newGaussScene.name = file.name;
  this.newGaussScene.file = file;
  this.newGaussScene.displayName = this.newGaussScene.displayName || this.newGaussScene.name;
},

removeNewGaussScene() {
  this.newGaussScene = { name: '', displayName: '' };
},

async uploadGaussScene() {
  const fd = new FormData();
  fd.append('file', this.newGaussScene.file);
  fd.append('display_name', this.newGaussScene.displayName || this.newGaussScene.name);
  console.log("上传场景：",fd);
  const res = await fetch('/upload_gauss_scene', {
    method: 'POST',
    body: fd
  }).then(r => r.json());

  if (res.success) {
    showNotification('场景上传成功');
    this.showGaussSceneDialog = false;
    // 添加新动作到用户动作列表
    const newgaussScenes = {
      id: res.file.unique_filename,
      name: res.file.display_name,
      path: res.file.path,
      type: 'user' // 标记为用户上传的动作
    };
        
    this.VRMConfig.gaussUserScenes.push(newgaussScenes);
    // 自动选中新上传的场景
    if (newgaussScenes) this.handleGaussSceneChange(newgaussScenes.id);
  } else {
    showNotification(res.message || '上传失败', 'error');
  }
},

cancelGaussSceneUpload() {
  this.showGaussSceneDialog = false;
  this.removeNewGaussScene();
},

async deleteGaussSceneOption(sceneId) {
  const scene = this.VRMConfig.gaussUserScenes.find(s => s.id === sceneId);
  if (!scene) return;

  // 提取 uuid 文件名
  const filename = scene.path.split('/').pop();
  const res = await fetch(`/delete_gauss_scene/${filename}`, {
    method: 'DELETE'
  }).then(r => r.json());

  if (res.success) {
    showNotification('场景已删除');
    // 如果当前正在使用被删场景，切回第一个默认场景
    if (this.VRMConfig.selectedGaussSceneId === sceneId) {
      const firstDef = this.VRMConfig.gaussDefaultScenes[0];
      if (firstDef) this.handleGaussSceneChange(firstDef.id);
    }
    await this.loadGaussScenes();
  } else {
    showNotification(res.message || '删除失败', 'error');
  }
},

  async toggleVTSConnection() {
    // 如果正在连接中，禁止重复点击
    if (this.isVTSStarting) return;
    
    this.isVTSStarting = true; // 开启 Loading 动画 (按钮转圈)
    
    try {
      if (this.VTSConfig.enabled) {
        // 动作：停止连接
        // 注意：这里不直接设 enabled = false，而是等待后端确认后再改
        this.sendTTSStatusToVRM('stopVTS_Driver', {});
      } else {
        // 动作：发起连接
        this.sendTTSStatusToVRM('startVTS_Driver', this.VTSConfig);
        
        // 设置一个 10 秒的超时逻辑
        // 如果 10 秒内后端没有通过 WS 返回任何 status 消息，则自动回退状态
        setTimeout(() => {
          if (this.isVTSStarting) {
            this.isVTSStarting = false;
            showNotification('VTS 连接超时，请检查后端程序是否运行', 'warning', '连接超时');
          }
        }, 10000);
      }
    } catch (e) {
      console.error("VTS 操作失败:", e);
      this.isVTSStarting = false;
      showNotification('指令发送失败，请检查网络', 'error');
    }
  },

  async startVTS() {
    // 模拟或实际发送 WS 指令
    this.sendTTSStatusToVRM('startVTS_Driver', this.VTSConfig);
    this.VTSConfig.enabled = true;
    this.autoSaveSettings();
  },

  async stopVTS() {
    this.sendTTSStatusToVRM('stopVTS_Driver', {});
    this.VTSConfig.enabled = false;
    this.autoSaveSettings();
  },

  connectToVTS() {
      this.activeMenu = 'deploy-bot';
      this.subMenu = 'vts_config';
      if(!this.VTSConfig.enabled){
        this.toggleVTSConnection();
      }
  }
});
