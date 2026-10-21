// 批 3 F2：自 vue_methods.js 搬移的 methods/99_skills.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
// 1. 获取技能列表
async fetchSkills() {
  try {
    const response = await fetch('/api/skills/list');
    if (!response.ok) {
      throw new Error(response.statusText);
    }
    const data = await response.json();
    this.skillsList = data.skills;
  } catch (error) {
    showNotification(this.t('fetchSkillsFailed'), 'error');
  }
},

// 2. 删除技能
async removeSkill(id) {
  try {
    const response = await fetch(`/api/skills/${id}`, {
      method: 'DELETE'
    });
    
    if (!response.ok) {
      throw new Error('Delete failed');
    }
    
    showNotification(this.t('deleteSuccess'), 'success');
    this.fetchSkills(); // 刷新
  } catch (error) {
    showNotification(this.t('deleteFailed'), 'error');
  }
},

// 3. GitHub 安装
async installSkillFromGithub() {
  if (!this.newSkillUrl) return;
  this.isSkillInstalling = true;
  showNotification(this.t('waitSkillInstall'), 'success');
  try {
    const response = await fetch('/api/skills/install-from-github', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        url: this.newSkillUrl
      })
    });

    if (!response.ok) {
      // 尝试解析后端返回的 JSON 错误信息
      const errorData = await response.json().catch(() => ({})); 
      const errorMessage = errorData.detail || response.statusText || 'Unknown Error';
      throw new Error(errorMessage);
    }

    showNotification(this.t('installSuccess'), 'success');
    this.showAddSkillDialog = false;
    this.newSkillUrl = '';
    // 稍微延迟后刷新一下，虽然是后台任务，但可能很快完成
    setTimeout(() => this.fetchSkills(), 2000);
  } catch (error) {
    showNotification(this.t('installFailed') + ': ' + error.message, 'error');
  } finally {
    this.isSkillInstalling = false;
  }
},

// 4. 点击 DIV 时，模拟点击隐藏的 input
triggerSkillFileSelect() {
  // 注意：如果你使用的是 Vue 3 <script setup>，需要 const skillFileInput = ref(null) 并使用 skillFileInput.value.click()
  // 如果是 Options API (export default):
  this.$refs.skillFileInput.click();
},

// 5. 处理“点击选择”后的文件变化
handleSkillFileChange(e) {
  const files = e.target.files;
  if (files && files.length > 0) {
    this.processSkillUpload(files[0]);
  }
  // 清空 input，防止同一个文件无法再次触发 change
  e.target.value = ''; 
},

// 6. 处理“拖拽释放”后的文件
handleSkillDrop(e) {
  const files = e.dataTransfer.files;
  if (files && files.length > 0) {
    this.processSkillUpload(files[0]);
  }
},

// 7. 统一的上传逻辑 (核心)
async processSkillUpload(file) {
  // 校验文件类型
  if (!file.name.toLowerCase().endsWith('.zip')) {
    // 这里原来的 ElMessage.error 改为了 showNotification
    showNotification(this.t('skillZipNote'), 'error'); 
    return;
  }

  this.isUploading = true; // 开启遮罩

  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/skills/upload-zip', {
      method: 'POST',
      body: formData
      // 注意：使用 fetch 发送 FormData 时，千万不要手动设置 Content-Type！
      // 浏览器会自动计算 boundary 并设置为 multipart/form-data
    });
    
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || this.t('installFailed'));
    }

    showNotification(this.t('installSuccess'), 'success');
    this.showAddSkillDialog = false;
    this.fetchSkills(); // 刷新列表
  } catch (error) {
    showNotification(error.message, 'error');
  } finally {
    this.isUploading = false; // 关闭遮罩
  }
},

isSkillInProject(skillId) {
  return this.skillsInProject && this.skillsInProject.includes(skillId);
},

    // 1. 升级获取项目状态：顺便保存详细信息
    async fetchProjectSkillsStatus() {
      if (!this.CLISettings.cc_path) {
        this.skillsInProject = [];
        this.projectSkillsDetails = [];
        return;
      }
      try {
        const res = await fetch(`/api/skills/project-status?path=${encodeURIComponent(this.CLISettings.cc_path)}`);
        if (res.ok) {
          const data = await res.json();
          this.skillsInProject = data.installed_ids || [];
          this.projectSkillsDetails = data.project_skills || []; // 存入详情
        }
      } catch (e) {
        console.error("获取项目技能状态失败", e);
      }
    },

    // 2. 反向同步：从项目 -> 全局
    async syncToGlobal(skillId) {
      try {
        const response = await fetch('/api/skills/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill_id: skillId, project_path: this.CLISettings.cc_path, action: 'sync_to_global' })
        });
        const data = await response.json();
        if (response.ok && data.status === 'success') {
          showNotification('Skill synced to Global', 'success');
          this.fetchSkills(); // 刷新全局状态即可
        } else {
          throw new Error(data.detail || 'Sync failed');
        }
      } catch (e) {
        showNotification(e.message, 'error');
      }
    },

    // 3. 正向同步：从全局 -> 项目 (原逻辑略微简化)
    async syncToProject(skillId) {
      if (!this.CLISettings.cc_path) return;
      try {
        const response = await fetch('/api/skills/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ skill_id: skillId, project_path: this.CLISettings.cc_path, action: 'install' })
        });
        if (response.ok) {
          showNotification('Skill synced to Workspace', 'success');
          this.fetchProjectSkillsStatus(); // 刷新项目状态
        } else {
          throw new Error('Sync failed');
        }
      } catch (e) {
        showNotification(e.message, 'error');
      }
    },

    // 4. 从全局删除（智能提示）
    async removeGlobalSkill(skill) {
      const execDelete = async () => {
        try {
          const response = await fetch(`/api/skills/${encodeURIComponent(skill.id)}`, { method: 'DELETE' });
          if (response.ok) {
            showNotification('Removed globally', 'success');
            await this.fetchSkills(); 
          } else {
            throw new Error('Remove failed');
          }
        } catch (e) {
          showNotification(e.message, 'error');
        }
      };

      // 核心判断：如果项目里也没有了，说明这是彻底删除，必须警告！
      if (!skill.isProject) {
        this.$confirm(this.t('deleteSkillConfirm'), this.t('warning'), { type: 'warning' })
          .then(execDelete).catch(() => {});
      } else {
        // 项目里还有，属于安全操作，静默删除
        execDelete();
      }
    },

    // 5. 从项目删除（智能提示）
    async removeProjectSkill(skill) {
      const execDelete = async () => {
        try {
          const response = await fetch('/api/skills/sync', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ skill_id: skill.id, project_path: this.CLISettings.cc_path, action: 'remove' })
          });
          if (response.ok) {
            showNotification('Removed from Workspace', 'success');
            await this.fetchProjectSkillsStatus(); 
          } else {
            throw new Error('Remove failed');
          }
        } catch (e) {
          showNotification(e.message, 'error');
        }
      };

      // 核心判断：如果全局里也没有了，说明这是彻底删除，必须警告！
      if (!skill.isGlobal) {
        this.$confirm('此操作将彻底删除该技能文件，是否继续？', 'Warning', { type: 'warning' })
          .then(execDelete).catch(() => {});
      } else {
        // 全局里还有，属于安全操作，静默删除
        execDelete();
      }
    },

// 切换技能同步状态
async toggleSkillInProject(skillId, isInstall) {
  if (!this.CLISettings.cc_path) return;

  const action = isInstall ? 'install' : 'remove';
  try {
    const response = await fetch('/api/skills/sync', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        skill_id: skillId,
        project_path: this.CLISettings.cc_path,
        action: action
      })
    });

    if (!response.ok) throw new Error('Sync failed');

    // 更新本地状态列表
    if (isInstall) {
      if (!this.skillsInProject.includes(skillId)) this.skillsInProject.push(skillId);
    } else {
      this.skillsInProject = this.skillsInProject.filter(id => id !== skillId);
    }
    
    showNotification(this.t('operationSuccess'), 'success');
  } catch (error) {
    showNotification(this.t('operationFailed'), 'error');
    // 刷新状态以回滚 UI 开关
    this.fetchProjectSkillsStatus();
  }
},

// 修改 handleSkillsPolling，在进入技能标签页时同时刷新项目状态
handleSkillsPolling(activeMenu, menu, tab) {
  if (activeMenu === 'toolkit' && menu === 'CLI' && tab === 'skills') {
    this.fetchProjectSkillsStatus(); // 额外执行这一步
    this.startSkillsPolling();
  } else {
    this.stopSkillsPolling();
  }
},

  // 启动轮询
  startSkillsPolling() {
    if (this.skillsPollingTimer) return; // 如果已经在轮询了，就不重复启动
    
    // 立即先执行一次，不要等第一个 5 秒
    this.fetchSkills(); 

    // 设置每 5 秒执行一次
    this.skillsPollingTimer = setInterval(() => {
      console.log('正在轮询获取 Skills...');
      this.fetchSkills();
    }, 5000);
  },

  // 停止轮询
  stopSkillsPolling() {
    if (this.skillsPollingTimer) {
      clearInterval(this.skillsPollingTimer);
      this.skillsPollingTimer = null;
      console.log('已停止轮询 Skills');
    }
  },

// 预览技能
async previewSkill(id) {
  this.showSkillPreviewDialog = true;
  this.skillPreviewLoading = true;
  this.renderedSkillContent = '';

  try {
    const response = await fetch(`/api/skills/${id}/content`);
    if (!response.ok) throw new Error('Fetch failed');
    const data = await response.json();
    let rawContent = data.content || '';

    // 1. 剥离 YAML Frontmatter (--- ... ---)
    // 这样预览时不会显示冗余的元数据
    const yamlRegex = /^---\s*\n([\s\S]*?)\n---\s*\n?/;
    const contentToRender = rawContent.replace(yamlRegex, '');

    // 2. 使用你已有的 md 实例进行渲染
    // 注意：这里直接调用 md.render。
    // 如果你希望保持和聊天框完全一致的逻辑（含 LaTeX、think 标签处理等），
    // 可以调用你写的 this.formatMessage(contentToRender)
    this.renderedSkillContent = this.formatMessage(contentToRender);

  } catch (error) {
    showNotification(this.t('fetchFailed'), 'error');
    this.showSkillPreviewDialog = false;
  } finally {
    this.skillPreviewLoading = false;
  }
},

  handleRemoteMCPInstall(data) {
    console.log('handleRemoteMCPInstall', data);

    // 1. 自动切换路由/菜单到 MCP 管理页面
    this.activeMenu = 'toolkit'; 
    this.subMenu = 'mcp';

    // 2. 初始化对话框状态为“添加模式”
    this.isEditMode = false;
    this.activeDialogTab = 'config'; // 默认显示配置标签
    
    if (data.mcpType) {
        this.newMCPType = data.mcpType;
    } else {
        this.newMCPType = 'stdio'; // 默认值
    }

    // 3. 设置输入模式为 JSON（因为远程传来的通常是完整配置对象）
    this.mcpInputType = 'json';
    this.updateMCPExample(); // 更新示例配置
    // data 现在包含 { type: 'mcp', config: '...', repo: null }
    let configStr = data.config;
    
    // 1. 尝试解码（因为主进程发过来的是原始 URL 参数，可能还带着编码）
    try {
      configStr = decodeURIComponent(configStr);
    } catch(e) {}

    this.newMCPJson = configStr; // 填入文本框
    this.showAddMCPDialog = true; // 弹窗
  },

// 在 methods 中添加
async openSkillsFolder() {
  try {
    const response = await fetch('/api/skills/get_path', {
      method: 'GET',
      headers: { 'Content-Type': 'application/json' }
    });
    if (response.ok) {
      const data = await response.json();
      if (this.isElectron && data.path) {
        // 调用 Electron 接口打开本地路径
        window.electronAPI.openPath(data.path);
      }
    }
  } catch (error) {
    console.error("Failed to open skills folder:", error);
  }
}
});
