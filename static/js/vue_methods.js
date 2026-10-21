const md = window.markdownit({
    html: true,
    linkify: true,
    typographer: true,
    highlight: function (str, lang) {
    let language = lang === 'a2ui' || (lang && hljs.getLanguage(lang)) ? lang : 'plaintext';
    const isPotentialMermaid = (code) => {
    // 检测标准语法特征
    const mermaidPatterns = [
        // 检测图表类型声明
        /^\s*(graph|sequenceDiagram|gantt|classDiagram|pie|stateDiagram|gitGraph|journey|flowchart|mindmap|quadrantChart|erDiagram|requirementDiagram|gitGraph|C4Context|timeline|zenuml|sankey-beta|xychart-beta|block-beta|packet-beta|kanban|architecture-beta|radar-beta)\b/i,
        // 检测节点关系语法
        /-->|==>|:::|\|\|/,
        // 检测样式配置语法
        /^style\s+[\w]+\s+/im,
        // 检测注释语法
        /%%\{.*\}\n?/
    ];
    
    return mermaidPatterns.some(pattern => pattern.test(code));
    };
    // 自动升级普通文本中的 Mermaid 内容
    if (language === 'plaintext' && isPotentialMermaid(str)) {
    language = 'mermaid';
    };
    const previewable = ['html', 'mermaid'].includes(language);
    const downloadButton = previewable ? 
    `<button class="download-button" data-lang="${language}"><i class="fa-solid fa-download"></i></button>` : '';
    // 添加预览按钮
    const previewButton = previewable ? 
    `<button class="preview-button" data-lang="${language}"><i class="fa-solid fa-eye"></i></button>` : '';
    try {
    return `<pre class="code-block"><div class="code-header"><span class="code-lang">${language}</span><div class="code-actions">${previewButton}${downloadButton}<button class="copy-button"><i class="fa-solid fa-copy"></i></button></div></div><div class="code-content"><code class="hljs language-${language}">${hljs.highlight(str, { language }).value}</code></div></pre>`;
    } catch (__) {
    return `<pre class="code-block"><div class="code-header"><span class="code-lang">${language}</span><div class="code-actions">${previewButton}${downloadButton}<button class="copy-button"><i class="fa-solid fa-copy"></i></button></div></div><div class="code-content"><code class="hljs">${md.utils.escapeHtml(str)}</code></div></pre>`;
    }
}
});

// 1. 重写表格开始标签：直接输出带 wrapper 的 HTML
md.renderer.rules.table_open = function(tokens, idx, options, env, self) {
  // 返回：<div class="markdown-table-wrapper"><table>
  return '<div class="markdown-table-wrapper"><table' + self.renderAttrs(tokens[idx]) + '>';
};

// 2. 重写表格结束标签：闭合 table，添加按钮，闭合 div
md.renderer.rules.table_close = function(tokens, idx, options, env, self) {
  // 这里我们添加一个特殊的 class "download-xlsx-btn" 用于后续事件代理
  // 注意：onclick 这里不直接写逻辑，而是通过 Vue 的事件代理来处理
  return '</table><button class="table-download-btn download-xlsx-trigger" type="button"><i class="fa-solid fa-file-excel"></i> XLSX</button></div>';
};

if (window.markdownitFootnote) {
    md.use(window.markdownitFootnote);
    
    // 【新增】覆盖默认的脚注渲染规则，只返回数字，去掉方括号 []
    md.renderer.rules.footnote_caption = (tokens, idx) => {
        var n = Number(tokens[idx].meta.id + 1).toString();
        return n;
    };
}

if (window.markdownitTaskLists) {
    md.use(window.markdownitTaskLists, {
        enabled: true,   // 渲染为 <input type="checkbox">
        label: true,     // 将文字包裹在 <label> 中
        labelAfter: true // label 放在 checkbox 之后
    });
} else {
    console.warn('markdown-it-task-lists 插件未加载，任务列表将不会渲染。');
}

// 检查插件是否已加载
if (window.markdownitContainer) {
    
    // 1. 定义 "warning" 容器 (对应 CSS 中的 .highlight-block-reasoning)
    // 使用方法: 
    // ::: warning 标题
    // 内容...
    // :::
    md.use(window.markdownitContainer, 'warning', {
        validate: function(params) {
            return params.trim().match(/^warning\s*(.*)$/);
        },
        render: function (tokens, idx) {
            var m = tokens[idx].info.trim().match(/^warning\s*(.*)$/);
            if (tokens[idx].nesting === 1) {
                // 开头标签: <div class="highlight-block-reasoning"> ...
                var title = m[1] ? md.utils.escapeHtml(m[1]) : '';
                var titleHtml = title ? '<strong>' + title + '</strong><br>' : '';
                return '<div class="highlight-block-reasoning">' + titleHtml;
            } else {
                // 结束标签: </div>
                return '</div>\n\n';
            }
        }
    });

    // 2. 定义 "info" 容器 (对应 CSS 中的 .highlight-block)
    // 使用方法: 
    // ::: info 提示
    // 内容...
    // :::
    md.use(window.markdownitContainer, 'info', {
        validate: function(params) {
            return params.trim().match(/^info\s*(.*)$/);
        },
        render: function (tokens, idx) {
            var m = tokens[idx].info.trim().match(/^info\s*(.*)$/);
            if (tokens[idx].nesting === 1) {
                var title = m[1] ? md.utils.escapeHtml(m[1]) : '';
                var titleHtml = title ? '<strong>' + title + '</strong><br>' : '';
                return '<div class="highlight-block">' + titleHtml;
            } else {
                return '</div>\n\n';
            }
        }
    });
} else {
    console.warn('markdown-it-container 插件未加载，自定义容器将不会渲染。');
}


// 添加更复杂的临时占位符
const LATEX_PLACEHOLDER_PREFIX = 'LATEX_PLACEHOLDER_';
let latexPlaceholderCounter = 0;

const ALLOWED_EXTENSIONS =[
  // 办公文档
  'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'pdf', 'pages', 
  'numbers', 'key', 'rtf', 'odt', 'epub',

  // 编程开发
  'js', 'ts', 'py', 'java', 'c', 'cpp', 'h', 'hpp', 'go', 'rs',
  'swift', 'kt', 'dart', 'rb', 'php', 'html', 'css', 'scss', 'less',
  'vue', 'svelte', 'jsx', 'tsx', 'json', 'xml', 'yml', 'yaml', 
  'sql', 'sh',

  // 数据配置
  'csv', 'tsv', 'txt', 'md', 'log', 'conf', 'ini', 'env', 'toml'
];

// MIME类型白名单
const MIME_WHITELIST =[
  'text/plain',
  'application/msword',
  'application/vnd.openxmlformats-officedocument',
  'application/pdf',
  'application/json',
  'text/csv',
  'text/x-python',
  'application/xml',
  'text/x-go',
  'text/x-rust',
  'text/x-swift',
  'text/x-kotlin',
  'text/x-dart',
  'text/x-ruby',
  'text/x-php'
];

// 图片上传相关配置
const ALLOWED_IMAGE_EXTENSIONS =['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'];
const IMAGE_MIME_WHITELIST =[
  'image/png',
  'image/jpeg',
  'image/gif',
  'image/webp',
  'image/bmp'
];

// ✨ 新增：视频上传相关配置
const ALLOWED_VIDEO_EXTENSIONS =['mp4', 'webm', 'ogg', 'mov', 'avi'];
const VIDEO_MIME_WHITELIST =[
  'video/mp4',
  'video/webm',
  'video/ogg',
  'video/quicktime',
  'video/x-msvideo'
];

// ✨ 修改：将视频扩展名合并到总允许列表中
const ALL_ALLOWED_EXTENSIONS = [...new Set([
  ...ALLOWED_EXTENSIONS, 
  ...ALLOWED_IMAGE_EXTENSIONS, 
  ...ALLOWED_VIDEO_EXTENSIONS // 加入这里
])];

let vue_methods = {
  stringifyEntityId(value) {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    return String(value);
  },
  handleUpdateAction() {
    if (this.updateDownloaded) {
      window.electronAPI.quitAndInstall();
    } else if (this.updateAvailable) {
      window.electronAPI.downloadUpdate();
    }
  },
  formatFileUrl(originalUrl) {
    if (!this.isElectron) {
      try {
        const url = new URL(originalUrl);
        // 替换0.0.0.0为当前域名
        if (url.hostname === '0.0.0.0' || url.hostname === 'localhost' || url.hostname === '127.0.0.1') {
          url.hostname = window.location.hostname;
          // 如果需要强制使用HTTPS可以添加：
          url.protocol = window.location.protocol;
          url.port = window.location.port;
        }
        return url.toString();
      } catch(e) {
        return originalUrl;
      }
    }
    else {
      try {
        const url = new URL(originalUrl);
        if (url.hostname === '127.0.0.1') {
          url.hostname = "localhost";
          // 如果需要强制使用HTTPS可以添加：
          url.protocol = window.location.protocol;
          url.port = window.location.port;
        }
        return url.toString();
      } catch(e) {
        return originalUrl;
      }
    }
    return originalUrl;
  },
  // A2: 系统提示词改动写入当前会话副本并持久化（防过期副本在重启后覆盖顶层值）
  async _persistSystemPrompt() {
    if (!this.conversationId) return;
    const conv = this.conversations.find(c => c.id === this.conversationId);
    if (conv) {
      conv.system_prompt = this.system_prompt;
      this.markConvDirty(conv.id);
      await this.flushDirtyConversations();
    }
  },
  async resetMessage(index) {
    this.messages[index].content = " ";
    this.system_prompt = " ";
    await this._persistSystemPrompt();
    await this.autoSaveSettings();
  },

  async deleteMessage(index) {
    this.stopGenerate();
    this.messages.splice(index, 1);
    if (this.conversationId === null) {
        this.conversationId = uuid.v4();
        const newConv = {
            id: this.conversationId,
            title: this.generateConversationTitle(this.messages),
            mainAgent: this.mainAgent,
            groupId: this.activeConversationGroupId || this.draftConversationGroupId || 'default',
            timestamp: Date.now(),
            messages: this.messages,
            fileLinks: this.fileLinks,
            system_prompt: this.system_prompt,
        };
        this.conversations.unshift(newConv);
    } else {
        const conv = this.conversations.find(conv => conv.id === this.conversationId);
        if (conv) {
            conv.messages = this.messages;
            conv.timestamp = Date.now();
            conv.fileLinks = this.fileLinks;
            conv.groupId = conv.groupId || this.activeConversationGroupId || this.draftConversationGroupId || 'default';
        }
    }
    await this.autoSaveSettings();
    this.markConvDirty(this.conversationId);
    await this.flushDirtyConversations();
    console.log("delete message");
  },

  openEditDialog(type, content, index = null) {
    this.editType = type;
    this.editContent = content;
    this.editIndex = index;
    this.showEditDialog = true;
    this.selectSystemPromptId =null;
  },
  async saveEdit() {
    this.showEditDialog = false;
    if (this.editType === 'system') {
      this.system_prompt = this.editContent;
      await this._persistSystemPrompt();
    }
    if (this.editType === 'user') {
      // 移除this.editIndex之后的所有消息
      this.messages.splice(this.editIndex);
      this.userInput = this.editContent;
      this.stopGenerate();
      await this.sendMessage();
    }else{
      this.messages[this.editIndex].content = this.editContent; // 更新this.editIndex对应的消息内容
      // A2: 编辑的若是系统消息本体，同步顶层与会话副本
      if (this.editIndex === 0 && this.messages[0] && this.messages[0].role === 'system') {
        this.system_prompt = this.editContent;
        await this._persistSystemPrompt();
      }
    }
    await this.autoSaveSettings();
  },
    async addParam() {
      this.settings.extra_params.push({
        name: '',
        type: 'string',  // 默认类型
        value: ''        // 根据类型自动初始化
      });
      await this.autoSaveSettings();
    },

    async addFastParam() {
      this.fastSettings.extra_params.push({
        name: '',
        type: 'string',  // 默认类型
        value: ''        // 根据类型自动初始化
      });
      await this.autoSaveSettings();
    },

    isInvalidJson(param) {
      // 如果不是 json 类型，不需要进行 JSON 校验
      if (param.type !== 'json') return false;
      
      // 为空或纯空格视为无效
      if (!param.value || param.value.trim() === '') return true; 

      try {
        const parsed = JSON.parse(param.value);
        
        // 既然单独选了 json 类型，通常排除了基础类型(string/integer/boolean)。
        // 这里我们限制它解析后必须是 对象({}) 或 数组([])，且不能是 null
        if (typeof parsed !== 'object' || parsed === null) {
          return true;
        }
        
        return false; // 解析成功且是对象/数组，校验通过
      } catch (e) {
        return true; // JSON 语法错误，校验失败
      }
    },

  getParamPlaceholder(type) {
    if (type === 'dict') return '{"type": "enabled"}';
    if (type === 'list') return '["item1", "item2"]';
    return this.t('paramValue'); // 默认使用翻译
  },

    async updateParamType(index) {
      const param = this.settings.extra_params[index];
      switch(param.type) {
        case 'json':
          param.value = '{}'; // 默认给一个对象，用户需要数组自己改成[] 即可
          break;
        case 'boolean':
          param.value = false;
          break;
        case 'integer':
        case 'float':
          param.value = 0;
          break;
        default:
          param.value = '';
      }
      await this.autoSaveSettings();
    },

    async updateFastParamType(index) {
      const param = this.fastSettings.extra_params[index];
      // 根据类型初始化值
      switch(param.type) {
        case 'json':
          param.value = '{}'; // 默认给一个对象，用户需要数组自己改成[] 即可
          break;
        case 'boolean':
          param.value = false;
          break;
        case 'integer':
        case 'float':
          param.value = 0;
          break;
        default:
          param.value = '';
      }
      await this.autoSaveSettings();
    },


    async removeParam(index) {
      this.settings.extra_params.splice(index, 1);
      await this.autoSaveSettings();
    },
    async removeFastParam(index) {
      this.fastSettings.extra_params.splice(index, 1);
      await this.autoSaveSettings();
    },

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
    cancelLLMTool() {
      this.showLLMForm = false
      this.resetForm()
    },
    handleTypeChange(val) {
      this.newLLMTool.base_url = this.defaultBaseURL
      this.newLLMTool.api_key = this.defaultApikey
      this.fetchModelsForType(val)
    },
    changeImgHost(val) {
      this.BotConfig.img_host = val;
      this.autoSaveSettings()
    },
    // 获取模型列表
    async fetchModelsForType(type) {
      try {
        // C-4: /llm_models 后端从不存在（调用必 404 被 catch 吞）=改用真实端点
        const response = await fetch(`/v1/providers/models`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: type,
            url: this.newLLMTool.base_url,
            api_key: this.newLLMTool.api_key
          })
        })
        
        const { data } = await response.json()
        this.modelOptions = data.models || []
      } catch (error) {
        console.error('Failed to fetch models:', error)
      }
    },
    // 保存工具
    saveLLMTool() {
      const tool = { ...this.newLLMTool }
      // 添加工具ID
      tool.id = uuid.v4();
      if (this.editingLLM) {
        this.llmTools[this.editingLLM] = tool
      } else {
        this.llmTools.push(tool)
      }
      this.showLLMForm = false
      this.resetForm()
      this.autoSaveSettings()
    },
    // 删除工具
    removeLLMTool(index) {
      this.llmTools.splice(index, 1)
      this.autoSaveSettings()
    },
    // 重置表单
    resetForm() {
      this.newLLMTool = {
        name: '',
        type: 'openai',
        description: '',
        base_url: '',
        api_key: '',
        model: '',
        enabled: true
      }
      this.editingLLM = null
    },
    // 类型标签转换
    toolTypeLabel(type) {
      const found = this.llmInterfaceTypes.find(t => t.value === type)
      return found ? found.label : type
    },
    // 检查更新
    async checkForUpdates() {
      if (isElectron) {
        try {
          await window.electronAPI.checkForUpdates();
        } catch (err) {
          showNotification(err.message, 'error');
        }
      }
    },

    // 下载更新
    async downloadUpdate() {
      if (isElectron && this.updateAvailable) {
        try {
          await window.electronAPI.downloadUpdate();
        } catch (err) {
          showNotification(err.message, 'error');
        }
      }
    },

    // 安装更新
    async installUpdate() {
      if (isElectron && this.updateDownloaded) {
        await window.electronAPI.quitAndInstall();
      }
    },

    // 处理更新按钮点击
    async handleUpdate() {
      if (!this.updateSuccess) {
        try {
          await this.downloadUpdate();
          this.updateSuccess = true;
          setTimeout(() => {
            this.installUpdate();
          }, 1000);
        } catch (err) {
          showNotification(err.message, 'error');
        }
      } else {
        await this.installUpdate();
      }
    },

    generateConversationTitle(messages) {
      const lastUserMessage = [...messages].reverse().find(m => m.role === 'user');
      
      if (lastUserMessage) {
        let textContent;
        
        // 判断 content 是否为字符串还是对象数组
        if (typeof lastUserMessage.content === 'string') {
          textContent = lastUserMessage.content;
        } else if (Array.isArray(lastUserMessage.content)) {
          // 提取所有文本类型的内容并拼接
          textContent = lastUserMessage.content.filter(item => item.type === 'text')
                           .map(item => item.text).join(' ');
        } else {
          // 如果既不是字符串也不是对象数组，设置为空字符串或其他默认值
          textContent = '';
        }
    
        // 拼接 fileLinks_content 部分，如果有
        const fullContent = textContent + (lastUserMessage.fileLinks_content ?? '');
        
        return fullContent.substring(0, 30) + (fullContent.length > 30 ? '...' : '');
      }
      
      return this.t('newChat');
    },
    openDeleteConversationDialog(conversation) {
      if (!conversation?.id) return;
      this.deleteConversationForm = {
        id: conversation.id,
        title: conversation.title || this.t('untitled'),
        deleteMemory: false,
      };
      this.showDeleteConversationDialog = true;
    },
    async confirmDeleteConversation(convId) {
      const conversation = this.conversations.find(c => c.id === convId);
      if (!conversation) return;
      this.openDeleteConversationDialog(conversation);
    },
    ensureConversationGroups() {
      const defaultGroup = {
        id: 'default',
        name: this.t('defaultConversationGroup'),
        createdAt: 0,
        memoryConfig: {}
      };

      const rawGroups = Array.isArray(this.conversationGroups) ? this.conversationGroups : [];
      const groups = rawGroups
        .filter(group => group && group.id && group.id !== 'default')
        .map(group => ({
          ...group,
          memoryConfig: group.memoryConfig || {}
        }));

      this.conversationGroups = [defaultGroup, ...groups];
      if (Array.isArray(this.conversations)) {
        this.conversations.forEach(conv => {
          if (!conv.groupId) {
            conv.groupId = 'default';
          }
        });
      }
      const nextCollapsedState = { ...(this.collapsedConversationGroups || {}) };
      this.conversationGroups.forEach(group => {
        if (typeof nextCollapsedState[group.id] !== 'boolean') {
          nextCollapsedState[group.id] = false;
        }
      });
      Object.keys(nextCollapsedState).forEach(groupId => {
        if (!this.conversationGroups.some(group => group.id === groupId)) {
          delete nextCollapsedState[groupId];
        }
      });
      this.collapsedConversationGroups = nextCollapsedState;

      if (!this.conversationGroups.some(group => group.id === this.draftConversationGroupId)) {
        this.draftConversationGroupId = 'default';
      }
      if (!this.conversationGroups.some(group => group.id === this.activeConversationGroupId)) {
        this.activeConversationGroupId = this.draftConversationGroupId || 'default';
      }
    },
    setActiveConversationGroup(groupId = 'default') {
      this.ensureConversationGroups();
      const nextGroupId = this.conversationGroups.some(group => group.id === groupId) ? groupId : 'default';
      this.activeConversationGroupId = nextGroupId;
      this.draftConversationGroupId = nextGroupId;
    },
    isConversationGroupCollapsed(groupId = 'default') {
      return !!this.collapsedConversationGroups?.[groupId];
    },
    toggleConversationGroupCollapsed(groupId = 'default') {
      this.ensureConversationGroups();
      this.collapsedConversationGroups = {
        ...(this.collapsedConversationGroups || {}),
        [groupId]: !this.isConversationGroupCollapsed(groupId),
      };
    },
    toggleChatHistoryPanel() {
      if (this.isMobile) {
        this.showHistoryDialog = true;
        return;
      }
      this.chatHistoryPanelOpen = !this.chatHistoryPanelOpen;
    },
    createConversationGroup() {
      this.conversationGroupDialogMode = 'create';
      this.conversationGroupForm = {
        id: null,
        name: '',
        memoryEnabled: false,
      };
      this.showConversationGroupDialog = true;
    },
    openRenameConversationGroupDialog(group) {
      if (!group?.id || group.id === 'default') return;
      this.conversationGroupDialogMode = 'rename';
      this.conversationGroupForm = {
        id: group.id,
        name: group.name || '',
        memoryEnabled: !!group.memoryConfig?.enabled,
      };
      this.showConversationGroupDialog = true;
    },
    async submitConversationGroupDialog() {
      this.ensureConversationGroups();
      const name = String(this.conversationGroupForm?.name || '').trim();
      if (!name) {
        showNotification(this.t('groupNameRequired'), 'error');
        return;
      }

      const currentGroupId = this.conversationGroupForm?.id || null;
      const exists = this.conversationGroups.some(group =>
        group.id !== currentGroupId && (group.name || '').trim() === name
      );
      if (exists) {
        showNotification(this.t('groupNameExists'), 'error');
        return;
      }

      if (this.conversationGroupDialogMode === 'rename' && currentGroupId) {
        const targetGroup = this.conversationGroups.find(group => group.id === currentGroupId);
        if (!targetGroup) return;
        targetGroup.name = name;
        targetGroup.memoryConfig = {
          ...(targetGroup.memoryConfig || {}),
          enabled: !!this.conversationGroupForm?.memoryEnabled,
        };
        await this.saveConversations();
        this.showConversationGroupDialog = false;
        showNotification(this.t('groupRenamed'), 'success');
        return;
      }

      const newGroup = {
        id: uuid.v4(),
        name,
        createdAt: Date.now(),
        memoryConfig: {
          enabled: !!this.conversationGroupForm?.memoryEnabled,
        }
      };

      this.conversationGroups.push(newGroup);
      this.draftConversationGroupId = newGroup.id;
      this.activeConversationGroupId = newGroup.id;
      await this.saveConversations();
      this.showConversationGroupDialog = false;
      showNotification(this.t('groupCreated'), 'success');
    },
    async startConversationInGroup(groupId = null) {
      this.ensureConversationGroups();
      const targetGroupId = groupId || this.activeConversationGroupId || this.draftConversationGroupId || 'default';
      this.setActiveConversationGroup(targetGroupId);
      await this.clearMessages(targetGroupId);
    },
    async moveConversationToGroup(convId, groupId) {
      this.ensureConversationGroups();
      const targetGroupId = groupId || 'default';
      const conversation = this.conversations.find(conv => conv.id === convId);
      if (!conversation) return;

      conversation.groupId = targetGroupId;
      if (convId === this.conversationId) {
        this.draftConversationGroupId = targetGroupId;
        this.activeConversationGroupId = targetGroupId;
      }
      this.markConvDirty(convId);
      await this.flushDirtyConversations();
    },
    openDeleteGroupDialog(group) {
      if (!group?.id || group.id === 'default') return;
      this.deleteGroupForm = {
        id: group.id,
        name: group.name || '',
        conversationCount: this.conversations.filter(conv => (conv.groupId || 'default') === group.id).length,
      };
      this.showDeleteGroupDialog = true;
    },
    getDeleteGroupWarningText() {
      const count = this.deleteGroupForm?.conversationCount || 0;
      return String(this.t('deleteGroupWillDeleteChats')).replace('{count}', count);
    },
    async deleteConversationById(conversationId, options = {}) {
      const response = await fetch('/api/conversations/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          conversation_id: this.stringifyEntityId(conversationId),
          delete_memory: !!options.deleteMemory,
        }),
      });

      if (!response.ok) {
        throw new Error('delete_failed');
      }

      if (conversationId === this.conversationId) {
        this.conversationId = null;
        this.messages = [{ id: Date.now() + Math.random(), role: 'system', content: this.system_prompt }];
        this.fileLinks = [];
      }

      this.conversations = this.conversations.filter(c => c.id !== conversationId);
    },
    async clearGroupMemoriesByGroupId(groupId) {
      const response = await fetch('/api/group-memory/clear-group', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          group_id: this.stringifyEntityId(groupId),
        }),
      });

      if (!response.ok) {
        throw new Error('delete_failed');
      }
    },
    async clearAllGroupMemories() {
      const response = await fetch('/api/group-memory/clear-all', {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('delete_failed');
      }
    },
    async clearAllHistoryRecords() {
      try {
        await this.$confirm(this.t('confirmClearAllHistory'), this.t('warning'), {
          confirmButtonText: this.t('confirm'),
          cancelButtonText: this.t('cancel'),
          type: 'warning'
        });

        const conversationIds = this.conversations.map(conv => conv.id);
        for (const conversationId of conversationIds) {
          await this.deleteConversationById(conversationId, {
            deleteMemory: true,
          });
        }
        await this.clearAllGroupMemories();

        this.conversationId = null;
        this.messages = [{ id: Date.now() + Math.random(), role: 'system', content: this.system_prompt }];
        this.fileLinks = [];
        this.conversationGroups = [{
          id: 'default',
          name: this.t('defaultConversationGroup'),
          createdAt: 0,
          memoryConfig: {}
        }];
        this.collapsedConversationGroups = { default: false };
        this.activeConversationGroupId = 'default';
        this.draftConversationGroupId = 'default';
        await this.saveConversations();
      } catch (error) {
        if (error?.message === 'delete_failed') {
          showNotification(this.t('deleteFailed') || 'Delete failed', 'error');
        }
      }
    },
    async pruneHistoryToLastWeek() {
      try {
        await this.$confirm(this.t('confirmKeepLastWeek'), this.t('warning'), {
          confirmButtonText: this.t('confirm'),
          cancelButtonText: this.t('cancel'),
          type: 'warning'
        });

        const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
        const expiredConversationIds = this.conversations
          .filter(conv => !conv.timestamp || conv.timestamp < oneWeekAgo)
          .map(conv => conv.id);

        for (const conversationId of expiredConversationIds) {
          await this.deleteConversationById(conversationId, {
            deleteMemory: true,
          });
        }

        if (this.conversations.length === 0) {
          this.conversationId = null;
          this.messages = [{ id: Date.now() + Math.random(), role: 'system', content: this.system_prompt }];
          this.fileLinks = [];
        }

        await this.saveConversations();
      } catch (error) {
        if (error?.message === 'delete_failed') {
          showNotification(this.t('deleteFailed') || 'Delete failed', 'error');
        }
      }
    },
    async deleteConversationGroup(groupId, options = {}) {
      this.ensureConversationGroups();
      if (!groupId || groupId === 'default') return;

      const groupConversationIds = this.conversations
        .filter(conv => (conv.groupId || 'default') === groupId)
        .map(conv => conv.id);

        for (const conversationId of groupConversationIds) {
          await this.deleteConversationById(conversationId, {
            deleteMemory: true,
          });
        }
        await this.clearGroupMemoriesByGroupId(groupId);

        this.conversationGroups = this.conversationGroups.filter(group => group.id !== groupId);

      if (this.draftConversationGroupId === groupId) {
        this.draftConversationGroupId = 'default';
      }
      if (this.activeConversationGroupId === groupId) {
        this.activeConversationGroupId = 'default';
      }

      await this.saveConversations();
      if (!options.silent) {
        showNotification(this.t('groupDeleted'), 'success');
      }
    },

    async clearConversationGroupChats(groupId) {
      this.ensureConversationGroups();
      if (!groupId) return;
      try {
        await this.$confirm(this.t('clearGroupChatsConfirm'), this.t('warning'), {
          confirmButtonText: this.t('confirm'),
          cancelButtonText: this.t('cancel'),
          type: 'warning'
        });

        const groupConversationIds = this.conversations
          .filter(conv => (conv.groupId || 'default') === groupId)
          .map(conv => conv.id);

        for (const conversationId of groupConversationIds) {
          await this.deleteConversationById(conversationId, {
            deleteMemory: true,
          });
        }
        await this.clearGroupMemoriesByGroupId(groupId);

        if (this.conversationId === null) {
          this.messages = [{ id: Date.now() + Math.random(), role: 'system', content: this.system_prompt }];
          this.fileLinks = [];
        }

        await this.saveConversations();
        showNotification(this.t('groupChatsCleared'), 'success');
      } catch (error) {
        if (error?.message === 'delete_failed') {
          showNotification(this.t('deleteFailed') || 'Delete failed', 'error');
        }
      }
    },

    async confirmDeleteGroupDeletion() {
      const groupId = this.deleteGroupForm?.id;
      if (!groupId) return;
      try {
        await this.deleteConversationGroup(groupId);
        this.showDeleteGroupDialog = false;
      } catch (error) {
        showNotification(this.t('deleteFailed') || 'Delete failed', 'error');
      }
    },
    openRenameConversationDialog(conversation) {
      if (!conversation?.id) return;
      this.conversationRenameForm = {
        id: conversation.id,
        name: conversation.title || '',
      };
      this.showConversationRenameDialog = true;
    },
    async submitConversationRename() {
      const name = String(this.conversationRenameForm?.name || '').trim();
      if (!name) {
        showNotification(this.t('conversationNameRequired'), 'error');
        return;
      }
      const conversation = this.conversations.find(conv => conv.id === this.conversationRenameForm?.id);
      if (!conversation) return;
      conversation.title = name;
      await this.saveConversations();
      this.showConversationRenameDialog = false;
      showNotification(this.t('conversationRenamed'), 'success');
    },
    async confirmDeleteConversationDeletion() {
      const conversationId = this.deleteConversationForm?.id;
      if (!conversationId) return;
      try {
        await this.deleteConversationById(conversationId, {
          deleteMemory: !!this.deleteConversationForm?.deleteMemory,
        });
      } catch (error) {
        showNotification(this.t('deleteFailed') || 'Delete failed', 'error');
        return;
      }
      await this.saveConversations();
      this.showDeleteConversationDialog = false;
      showNotification(this.t('conversationDeleted'), 'success');
    },
    async loadConversation(convId) {
      const conversation = this.conversations.find(c => c.id === convId);
      if (conversation) {
        console.log("convid:"+convId);
        this.conversationId = convId;
        this.messages = [...conversation.messages];
        this.fileLinks = conversation.fileLinks;
        const _agent = conversation.mainAgent;
        if (_agent === 'super-model' || (this.agents && Object.prototype.hasOwnProperty.call(this.agents, _agent))) {
          this.mainAgent = _agent;
        } else {
          console.warn(`[mainAgent] 会话记录的 agent "${_agent}" 不存在，已回退 super-model`);
          this.mainAgent = 'super-model';
        }
        this.showHistoryDialog = false;
        // A2: 会话副本缺失/纯空白 → 保留顶层恢复值（防过期副本覆盖重启恢复的正确值）
        const _spConv = conversation.system_prompt;
        if (typeof _spConv === 'string' && _spConv.trim()) {
          this.system_prompt = _spConv;
        } else if (!(typeof this.system_prompt === 'string' && this.system_prompt.trim())) {
          this.system_prompt = " ";
        }
        this.draftConversationGroupId = conversation.groupId || 'default';
        this.activeConversationGroupId = conversation.groupId || 'default';
      }
      else {
        this.system_prompt = " ";
        this.messages = [{ id: Date.now() + Math.random(), role: 'system', content: this.system_prompt }];
      }
      if(this.allBriefly){
        this.messages.forEach((m) => {
          m.briefly = true;
        })
      }else{
        this.messages.forEach((m) => {
          m.briefly = false;
        })
      }
      this.inAutoMode = false; // 重置自动模式状态
      this.requestScrollToBottom();
      this.sendMessagesToExtension(); // 发送消息到插件
      this.$nextTick(() => {
          setTimeout(() => {
              if (window.MathJax) {
                  const els = document.querySelectorAll('.stream-content');
                  window.MathJax.typesetClear([...els]); // 先清除旧渲染
                  window.MathJax.typesetPromise([...els]).catch(() => {});
              }
          }, 200);
      });

      // A2: 恢复结果回写会话副本（自愈旧污染数据），随后才允许全局保存
      if (conversation && conversation.system_prompt !== this.system_prompt) {
        conversation.system_prompt = this.system_prompt;
        this.markConvDirty(convId);
        this.flushDirtyConversations();
      }
      this.autoSaveSettings();
    },
    formatConversationTime(timestamp) {
      if (!timestamp) return '';
      const date = new Date(timestamp);
      const now = new Date();
      if (date.toDateString() === now.toDateString()) {
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      }
      return date.toLocaleDateString([], { month: 'numeric', day: 'numeric' });
    },
    // 修改 getConversationPreview，移除沉重的 DOM/正则替换，改用极简截取
    getConversationPreview(conversation) {
      const messages = Array.isArray(conversation?.messages) ? conversation.messages :[];
      const firstUsefulMessage = messages.find(msg => msg && msg.role !== 'system' && msg.content);
      if (!firstUsefulMessage) return this.t('newChat');
      
      // 仅做简单的字符串截取（最高效），或者直接返回首句的纯文本部分
      const rawContent = Array.isArray(firstUsefulMessage.content)
        ? firstUsefulMessage.content.map(item => item?.text || '').join(' ')
        : String(firstUsefulMessage.content);
        
      // 只取前 30 个字符，放弃全局正则替换
      return rawContent.substring(0, 30) + (rawContent.length > 30 ? '...' : '') || this.t('newChat');
    },
    async syncGroupMemoryAfterReply(userMessage, assistantMessage) {
      const groupId = this.activeConversationGroupId || this.draftConversationGroupId || 'default';
      if (!groupId || groupId === 'default') return;
      if (!userMessage?.id || !assistantMessage?.id) return;

      try {
        await fetch('/api/group-memory/extract', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            group_id: this.stringifyEntityId(groupId),
            conversation_id: this.stringifyEntityId(this.conversationId),
            user_message_id: this.stringifyEntityId(userMessage.id),
            assistant_message_id: this.stringifyEntityId(assistantMessage.id),
            user_message: userMessage.pure_content ?? userMessage.content ?? '',
            assistant_message: assistantMessage.pure_content ?? assistantMessage.content ?? '',
          }),
        });
      } catch (error) {
        console.error('Failed to sync group memory:', error);
        showNotification(this.t('memorySyncFailed'), 'error');
      }
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
    async syncProviderConfig(targetConfig) {
      if (targetConfig.selectedProvider) {
        const provider = this.modelProviders.find(
          p => p.id === targetConfig.selectedProvider && !p.disabled
        );
        if (provider) {
          let targetUrl = provider.url;

          // 判断当前同步的对象是否为 ccSettings (通过引用比较)
          // 如果是 CC 配置，则应用特殊的 vendor_list 映射逻辑
          if (targetConfig === this.ccSettings) {
             const vendor_list = {
              "Anthropic": "https://api.anthropic.com/",
              "Deepseek": "https://api.deepseek.com/anthropic/",
              "siliconflow": "https://api.siliconflow.cn/",
              "ZhipuAI":"https://open.bigmodel.cn/api/anthropic/",
              "moonshot":"https://api.moonshot.cn/anthropic/",
              "aliyun": "https://dashscope.aliyuncs.com/apps/anthropic/",
              "modelscope":"https://api-inference.modelscope.cn/",
              "302.AI":"https://api.302.ai/cc/",
              "MiMo":"https://api.xiaomimimo.com/anthropic/",
              "longcat":"https://api.longcat.chat/anthropic/",
              "newapi": provider.url.replace(/\/v1\/?$/, ''),
              "Ollama":provider.url.replace(/\/v1\/?$/, '')
            };
            // 使用映射的 URL，如果没有匹配则回退到默认 url
            targetUrl = vendor_list[provider.vendor] || provider.url;
          }

          // 同步核心配置 (注意：这里比较和赋值时使用 targetUrl)
          const shouldUpdate = 
            targetConfig.model !== provider.modelId ||
            targetConfig.base_url !== targetUrl || // 比较 targetUrl
            targetConfig.api_key !== provider.apiKey;
            
          if (shouldUpdate) {
            targetConfig.model = provider.modelId || '';
            targetConfig.base_url = targetUrl || ''; // 赋值 targetUrl
            targetConfig.api_key = provider.apiKey || '';
            console.log(`已同步 ${provider.vendor} 配置 (CC模式: ${targetConfig === this.ccSettings})`);
          }
        } else {
          // ... (保持原本的清理逻辑不变)
          console.warn('找不到匹配的供应商，已重置配置');
          targetConfig.selectedProvider = null;
          targetConfig.model = '';
          targetConfig.base_url = '';
          targetConfig.api_key = '';
        }
        await this.autoSaveSettings();
      }
    },
    updateMCPExample() {
      this.currentMCPExample = this.mcpExamples[this.newMCPType];
    },
    
    toggleMCPServer(name, status) {
      this.mcpServers[name].disabled = !status
      this.autoSaveSettings()
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
    async handleSelect(key) {
      if (key === 'model-config') {
        this.activeMenu = 'model-config';
        this.subMenu = 'service'; // 默认显示第一个子菜单
      }
      else if (key === 'role') {
        this.activeMenu = 'role';
        this.subMenu = 'memory'; // 默认显示第一个子菜单
      }
      else if (key === 'toolkit') {
        this.activeMenu = 'toolkit';
        this.subMenu = 'tools'; // 默认显示第一个子菜单
      }
      else if (key === 'api-group') {
        this.activeMenu = 'api-group';
        this.subMenu = 'openai'; // 默认显示第一个子菜单
      }
      else if (key === 'storage') {
        this.activeMenu = 'storage';
        this.subMenu = 'text'; // 默认显示第一个子菜单
        const response = await fetch(`/update_storage`, {
            method: 'GET',
            headers: {
              'Content-Type': 'application/json'
            }
        });
        if (response.ok) {
          console.log('Storage files updated successfully');
          const data = await response.json();
          this.textFiles = data.textFiles;
          this.imageFiles = data.imageFiles;
          this.videoFiles = data.videoFiles;
          this.autoSaveSettings();
        }
        else {
          console.error('Failed to update storage files');
        }
      }
      else if (key === 'deploy-bot') {
        this.activeMenu = 'deploy-bot';
        this.subMenu = 'table_pet'; // 默认显示第一个子菜单
      }
      else {
        this.activeMenu = key;
      }
      this.activeMenu = key;
    }, 
    toggleIcon() {
      this.isExpanded = !this.isExpanded; // 点击时切换状态
      this.maximizeWindow();
    },

    throttledUpdate(index, newContent) {
      // 更新原始数据
      this.messages[index].content = newContent;
      
      // 如果已经有定时器在跑，则跳过（防抖）
      if (this.renderTimers[index]) return;

      this.renderTimers[index] = setTimeout(() => {
        // 执行真正的渲染
        this.messages[index].renderedHtml = this.formatMessage(newContent, index);
        // 清除定时器
        this.renderTimers[index] = null;
      }, 80); // 80ms 延迟，约等于 12fps，人眼感觉流畅且不卡顿
    },


    //  使用占位符处理 LaTeX 公式
    formatMessage(content, index) {
      if (!content) return '';

      // 目的是防止 markdown-it 因为最后一行缺少 '|' 而在 Table 和 Paragraph 之间反复横跳
      let processedForRender = content.trimEnd(); 
      
      // 获取最后一行
      const lines = content.split('\n');
      const lastLine = lines[lines.length - 1].trim();

      // 如果最后一行以 '|' 开头（看起来像是表格行）
      // 并且它还不是分隔行（即不是 |---| 这种）
      // 并且它没有以 '|' 结尾
      if (lastLine.startsWith('|') && !lastLine.endsWith('|') && !/^[|\s-:]+$/.test(lastLine)) {
        // 临时在渲染用的字符串末尾补上 ' |'，让解析器认为这一行结束了
        // 注意：这不会修改 this.messages 里的真实数据，只影响本次渲染
        processedForRender += ' |';
      }

      // --- 预处理阶段 ---
      const parts = this.splitCodeAndText(content);
      let latexPlaceholderCounter = 0;
      const latexPlaceholders = [];
      let inUnclosedCodeBlock = false;

      let processedContent = parts.map(part => {
        if (part.type === 'code') {
          inUnclosedCodeBlock = !part.closed;
          return part.content; 
        } else if (inUnclosedCodeBlock) {
          return part.content; 
        } else {
          let formatted = part.content;

          // ============================================================
          // 智能标签过滤：保留合法 HTML，过滤非法自定义标签
          // ============================================================
          
          // 这个正则会匹配所有的 <标签> 或 </标签>
          // $1: 是否有 "/" (闭合标签)
          // $2: 标签名 (TagName)
          // $3: 标签属性 (Attributes)
          const anyTagRegex = /<(\/?)([^\s>/>]+)([^>]*)>/g;

          formatted = formatted.replace(anyTagRegex, (match, slash, tagName, attrs) => {
            const lowerTagName = tagName.toLowerCase();

            // 1. 必须保留的特殊标签
            if (lowerTagName === 'think') return match;

            // 2. 合法性判断：
            // 标准 HTML 标签名只允许：英文字母开头，后面跟着字母、数字或中划线
            // 且不能包含中文字符或特殊符号（如 ·）
            const isStandardHtmlName = /^[a-zA-Z][a-zA-Z0-9-]*$/.test(tagName);

            if (isStandardHtmlName) {
              // 如果是合法标签名（如 div, span, a, br, my-component 等），原样保留
              return match;
            } else {
              // 如果包含中文（如 <雷电将军>）或特殊符号（如 <Character·A>），则视作非法，过滤掉
              return ''; 
            }
          });

          // ============================================================
          // [原有逻辑] 处理 <think> 标签的 UI 转换
          // ============================================================
          const thinkTagRegexWithClose = /<think>([\s\S]*?)<\/think>/g;
          const thinkTagRegexOpenOnly = /<think>[\s\S]*$/;
          
          formatted = formatted
            .replace(thinkTagRegexWithClose, match => 
              match.replace('<think>', '<div class="highlight-block-reasoning">').replace('</think>', '</div>')
            )
            .replace(thinkTagRegexOpenOnly, match => 
              match.replace('<think>', '<div class="highlight-block-reasoning">')
            );

          // [原有逻辑] 处理 LaTeX 公式
          const latexRegex = /(\$(?:\\.|[^\$\\])*\$)|(\\\[(?:\\.|[^\\])*\\\])/g;
          return formatted.replace(latexRegex, (match) => {
            const placeholder = `LATEX_PLACEHOLDER_${latexPlaceholderCounter++}`;
            latexPlaceholders.push({ placeholder, latex: match });
            return placeholder;
          });
        }
      }).join('');

      let rendered = md.render(processedContent);
      // --- 恢复阶段 ---
      // 恢复 LaTeX
      latexPlaceholders.forEach(({ placeholder, latex }) => {
        rendered = rendered.replace(placeholder, latex);
      });

      // 处理未闭合代码块的转义 (如果有)
      rendered = rendered.replace(/\\\`/g, '`').replace(/\\\$/g, '$');

      // 处理思考中的状态 (Thinking...)
      const currentMsg = this.messages[index];
      // 只有当是最后一条消息、角色是助手、且正在输入时才显示“思考中”图标
      if (index === this.messages.length - 1 && currentMsg?.role === 'assistant' && this.isTyping && currentMsg.content !== currentMsg.pure_content) {
        // 注意：这里不要直接加在 rendered 字符串里，最好在模板中通过 v-if 控制，
        // 但为了兼容您的逻辑，我们保留：
        rendered = `<div class="thinking-header"><i class="fa-solid fa-lightbulb"></i> ${this.t('thinking')}</div>` + rendered;
      }

      // --- 后处理 (MathJax & Mermaid) ---
      // 我们不再在 formatMessage 内部直接调用 MathJax，而是将其推入队列
      this.$nextTick(() => {
        this.queueMathJax(index, content);
        this.initCopyButtons();
        this.initPreviewButtons();
        // Mermaid 也可以在这里懒加载
      });

      // 处理链接 (保持您原有的 DOM 操作逻辑，但建议用正则替换以提高性能)
      // 使用正则替换 href，比创建 DOM 树快得多
      rendered = rendered.replace(/<a\s+(?:[^>]*?\s+)?href="([^"]*)"([^>]*)>/g, (match, href, otherAttrs) => {
        // 检查是否为脚注
        if (otherAttrs.includes('footnote-ref') || otherAttrs.includes('footnote-backref') || href.startsWith('#')) {
          return match; 
        }
        const formattedHref = this.formatFileUrl(href);
        return `<a href="${formattedHref}" target="_blank"${otherAttrs}>`;
      });

      return rendered;
    },

  // 3. MathJax 队列处理 (解决流式输出时的公式闪烁/报错)
  queueMathJax(index, content) {
    // 仅当内容确实包含公式时才处理，避免流式期间每次更新都入队
    const text = (typeof content === 'string' ? content : '') || '';
    if (!/\$[^$\n]+\$|\\\[[\s\S]*?\\\]/.test(text)) return;
    if (!window.MathJax) return;
    if (!this.mathJaxTimers) this.mathJaxTimers = {};
    // 每消息防抖：取消上一次待执行的 typeset，静默 300ms 后只执行一次（替代无限 Promise 链）
    clearTimeout(this.mathJaxTimers[index]);
    this.mathJaxTimers[index] = setTimeout(() => {
      const element = document.getElementById(`message-content-${index}`);
      if (!element) return;
      window.MathJax.typesetPromise([element]).catch(err => { console.debug('MathJax rendering skipped:', err.message); });
    }, 300);
  },
    formatMessageWrapper(content) {
        // 调用您现有的 formatMessage，这里传 index = -1 避免产生副作用（如 thinking 图标）
        return this.formatMessage(content, -1); 
    },
    copyLink(uniqueFilename) {
      const url = `${this.partyURL}/uploaded_files/${uniqueFilename}`
      navigator.clipboard.writeText(url)
        .then(() => {
          showNotification(this.t('copy_success'))
        })
        .catch(() => {
          showNotification(this.t('copy_failed'), 'error')
        })
    },
    copyApiKey(apiKey){
      navigator.clipboard.writeText(apiKey)
        .then(() => {
          showNotification(this.t('copy_success'))
        })
        .catch(() => {
          showNotification(this.t('copy_failed'), 'error')
        })
    },
    copyProvider(provider,index){
      // 在this.modelProviders的index之后插入一个复制版本
      this.modelProviders.splice(index + 1, 0, { ...provider, id: Date.now() });
      this.autoSaveSettings();
    },
    previewImage(img) {
      this.previewImageUrl = `${this.partyURL}/uploaded_files/${img.unique_filename}`
      this.previewVisible = true
      console.log(this.previewImageUrl)
    },
    copyMessageContent(message) {
      // 获取原始内容（用户消息直接复制，AI消息复制原始markdown）
      let content = message.role === 'user' 
        ? message.content 
        : message.pure_content || message.rawContent || message.content;
      // 处理文件链接
      if (message.fileLinks?.length) {
        content += '\n\n' + message.fileLinks.map(link => `[${link.name}](${link.path})`).join('\n');
      }
      navigator.clipboard.writeText(content)
        .then(() => showNotification(this.t('copy_success')))
        .catch(() => showNotification(this.t('copy_failed'), 'error'));
    },
    initPreviewButtons() {
      // 清理旧事件监听器
      if (this._previewEventHandler) {
        document.body.removeEventListener('click', this._previewEventHandler);
      }
      // 主事件处理器
      this._previewEventHandler = (e) => {
        const button = e.target.closest('.preview-button');
        if (!button) return;
        e.preventDefault();
        e.stopPropagation();
        console.debug('🏁 预览按钮触发:', button);
        // 获取代码上下文
        const codeBlock = button.closest('.code-block');
        if (!codeBlock) {
          console.error('❌ 未找到代码块容器');
          return;
        }
        // 获取代码内容
        const lang = button.dataset.lang;
        const codeContent = codeBlock.querySelector('code')?.textContent?.trim();
        if (!codeContent) {
          console.warn('⚠️ 空代码内容', codeBlock);
          this.showErrorToast('代码内容为空');
          return;
        }
        // codeBlock中查找/创建预览容器
        let previewContainer = codeBlock.querySelector('.preview-container');
        const isNewContainer = !previewContainer;
        
        if (isNewContainer) {
          previewContainer = document.createElement('div');
          previewContainer.className = 'preview-container loading';
          codeBlock.appendChild(previewContainer);
        }
        // 状态切换逻辑
        if (previewContainer.classList.contains('active')) {
          this.collapsePreview(previewContainer, button);
        } else {
          this.expandPreview({ previewContainer, button, lang, codeContent });
        }
      };
      // 绑定事件监听
      document.body.addEventListener('click', this._previewEventHandler);
      //console.log('🔧 预览按钮事件监听已初始化');
    },
    // 展开预览面板
    expandPreview({ previewContainer, button, lang, codeContent }) {
      console.log('🔼 展开预览:', { lang, length: codeContent.length });
      
      const codeBlock = button.closest('.code-block');
  
      // 检查是否已有预览
      const existingPreview = codeBlock.querySelector('.preview-container.active');
      if (existingPreview) {
        this.collapsePreview(existingPreview, button);
        return;
      }
      // 标记代码块状态
      codeBlock.dataset.previewActive = "true";
      
      // 隐藏代码内容
      const codeContentDiv = codeBlock.querySelector('.code-content');
      codeContentDiv.style.display = 'none';
      
      // 更新按钮状态
      button.innerHTML = '<i class="fa-solid fa-eye-slash"></i>';
      
      previewContainer.classList.add('active', 'loading');
      if (lang === 'mermaid'){
        previewContainer.style.width =  '85vw';
      }
      
      // 渲染内容
      requestAnimationFrame(() => {
        try {
          if (lang === 'html') {
            this.renderHtmlPreview(previewContainer, codeContent);
            // 动态调整iframe高度
            const iframe = previewContainer.querySelector('iframe');
            iframe.onload = () => {
              iframe.style.height = iframe.contentWindow.document.body.scrollHeight + 'px';
            };
          } else if (lang === 'mermaid') {
            this.renderMermaidPreview(previewContainer, codeContent).then(() => {
              // Mermaid渲染完成后调整高度
              const svg = previewContainer.querySelector('svg');
              if (svg) {
                previewContainer.style.minHeight = svg.getBBox().height + 'px';
              }
            });
          }
          previewContainer.classList.remove('loading');
        } catch (err) {
          console.error('🚨 预览渲染失败:', err);
          this.showPreviewError(previewContainer, err);
        }
      });
    },
    // 修改 collapsePreview 方法
    collapsePreview(previewContainer, button) {
      console.log('🔽 收起预览');
      
      const codeBlock = previewContainer.parentElement;
  
      // 重置代码块状态
      delete codeBlock.dataset.previewActive;
      
      // 显示代码内容
      const codeContentDiv = codeBlock.querySelector('.code-content');
      codeContentDiv.style.display = 'block';
      
      // 移除预览容器
      previewContainer.remove();
      
      // 重置按钮状态
      button.innerHTML = '<i class="fa-solid fa-eye"></i>';
    },
    // HTML渲染器
    renderHtmlPreview(container, code) {
      console.log('🌐 渲染HTML预览');
      
      const sandbox = document.createElement('iframe');
      sandbox.srcdoc = `<!DOCTYPE html>
        <html>
          <head>
            <base href="/">
          </head>
          <body>${code}</body>
        </html>`;
      
      sandbox.style.cssText = `
        width: 70vw;
        height: 70vh;
        border: none;
        border-radius: 8px;
        background: transparent;
      `;
      
      container.replaceChildren(sandbox);
    },
    // Mermaid渲染器（带重试机制）
    async renderMermaidPreview(container, code) {
      console.log('📊 渲染Mermaid图表');
      
      const diagramContainer = document.createElement('div');
      diagramContainer.className = 'mermaid-diagram';
      container.replaceChildren(diagramContainer);
      // 异步渲染逻辑
      let retryCount = 0;
      const maxRetries = 3;
      
      const attemptRender = async () => {
        try {
          diagramContainer.textContent = code;
          await mermaid.run({
            nodes: [diagramContainer],
            suppressErrors: false
          });
          console.log('✅ Mermaid渲染成功');
        } catch (err) {
          if (retryCount < maxRetries) {
            retryCount++;
            console.warn(`🔄 重试渲染 (${retryCount}/${maxRetries})`);
            diagramContainer.innerHTML = '';
            await new Promise(resolve => setTimeout(resolve, 500 * retryCount));
            await attemptRender();
          } else {
            throw new Error(`Mermaid渲染失败: ${err.message}`);
          }
        }
      };
      await attemptRender();
    },
    // 错误处理
    showPreviewError(container, error) {
      container.classList.add('error');
      container.innerHTML = `
        <div class="error-alert">
          <i class="fa-solid fa-triangle-exclamation"></i>
          <div>
            <h4>预览渲染失败</h4>
            <code>${error.message}</code>
          </div>
        </div>
      `;
    },
    // 新增方法：检测未闭合代码块
    hasUnclosedCodeBlock(parts) {
      return parts.some(p => p.type === 'code' && !p.closed);
    },

    splitCodeAndText(content) {
      const codeFenceRegex = /(```[\s\S]*?)(?:```|$)/g; // 修改正则表达式
      const parts = [];
      let lastIndex = 0;
      let hasUnclosed = false;

      // 处理代码块
      let match;
      while ((match = codeFenceRegex.exec(content)) !== null) {
        const textBefore = content.slice(lastIndex, match.index);
        if (textBefore) parts.push({ type: 'text', content: textBefore });

        // 判断是否闭合
        const isClosed = match[0].endsWith('```');
        const codeContent = isClosed ? 
          match[0] : 
          match[0] + '\n```'; // 自动补全闭合

        parts.push({
          type: 'code',
          content: codeContent,
          closed: isClosed
        });

        lastIndex = codeFenceRegex.lastIndex;
        hasUnclosed = !isClosed;
      }

      // 处理剩余内容
      const remaining = content.slice(lastIndex);
      if (remaining) {
        if (hasUnclosed) {
          // 将剩余内容视为代码块
          parts.push({
            type: 'code',
            content: remaining + '\n```',
            closed: false
          });
        } else {
          parts.push({ type: 'text', content: remaining });
        }
      }

      return parts;
    },
    initDownloadButtons() {
        document.body.addEventListener('click', async (e) => {
            const button = e.target.closest('.download-button');
            if (!button) return;
            const lang = button.dataset.lang;
            const codeBlock = button.closest('.code-block');
            const previewButton = codeBlock.querySelector('.preview-button');
            const existingPreview = codeBlock.querySelector('.preview-container.active');
            // 如果previewButton不在预览状态，则执行预览操作
            if (!existingPreview) {
                // 触发预览按钮的点击事件
                previewButton.click();
                // 等待预览完成
                await new Promise(resolve => setTimeout(resolve, 500)); // 根据实际情况调整延时
            }
            const previewContainer = codeBlock.querySelector('.preview-container');
            try {
                if (lang === 'mermaid') {
                    // 使用html2canvas来截图
                    html2canvas(previewContainer, {
                        // 如果Mermaid图表面板有滚动条，你可能需要设置宽度和高度
                        width: previewContainer.offsetWidth,
                        height: previewContainer.offsetHeight,
                    }).then(canvas => {
                        canvas.toBlob(blob => {
                            this.triggerDownload(blob, 'mermaid-diagram.png');
                        });
                    }).catch(error => {
                        console.error('截图失败:', error);
                        showNotification('截图失败，请检查控制台', 'error');
                    });
                }
                else if (lang === 'html') {
                    const iframe = previewContainer.querySelector('iframe');
                    const canvas = await html2canvas(iframe.contentDocument.body);
                    canvas.toBlob(blob => {
                        this.triggerDownload(blob, 'html-preview.png');
                    });
                }
            } catch (error) {
                console.error('下载失败:', error);
                showNotification('下载失败，请检查控制台', 'error');
            }
        });
    },

    triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    },
    
    handleCopy(event) {
      const button = event.target.closest('.copy-button')
      if (button) {
        const codeBlock = button.closest('.code-block')
        const codeContent = codeBlock?.querySelector('code')?.textContent || ''
        
        navigator.clipboard.writeText(codeContent).then(() => {
          showNotification(this.t('copy_success'))
        }).catch(() => {
          showNotification(this.t('copy_failed'), 'error')
        })
        
        event.stopPropagation()
        event.preventDefault()
      }
    },
    
    initCopyButtons() {
      // 移除旧的ClipboardJS初始化代码
      document.querySelectorAll('.copy-button').forEach(btn => {
        btn.removeEventListener('click', this.handleCopy)
        btn.addEventListener('click', this.handleCopy)
      })
    },  
    // 滚动到最新消息
    /* 判断元素是否接近底部 */
    isElemNearBottom(el, threshold = 300) {
      if (!el) return true;               // 元素不存在就默认“需要滚底”
      return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
    },

      /* ==========================================
       滚动区域逻辑优化（支持内部区块跟随滚动）
       ========================================== */
    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.messagesContainer;
        if (container) {
          // 1. 滚动外层主容器
          if (this.isElemNearBottom(container) || this.isForceScrollToBottom) {
            container.scrollTop = container.scrollHeight;
          }
          
          // 2. 滚动内层带有滚动条的区块 (工具代码块、思考过程块)
          const innerBlocks = container.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              // 同样复用 isElemNearBottom 判断，如果用户没故意往上翻，就自动贴底
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
      
      this.scrollPanelToBottom();
      // 兼容你原有的写法
      if (typeof isElectron !== 'undefined' ? isElectron : this.isElectron) {
        this.browserPanelToBottom();
      }
    },

    /* 侧边栏滚动 */
    scrollPanelToBottom() {
      this.$nextTick(() => {
        const panel = this.$refs.messagesPanel;
        if (panel) {
          // 1. 滚动侧边栏外层容器
          if (this.isElemNearBottom(panel) || this.isForceScrollToBottom) {
            panel.scrollTop = panel.scrollHeight;
          }

          // 2. 滚动侧边栏内层区块
          const innerBlocks = panel.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
    },

    /* 独立浏览器面板滚动 */
    browserPanelToBottom() {
      this.$nextTick(() => {
        const panel = this.$refs.browserMessagesContainer;
        if (panel) {
          // 1. 滚动独立面板外层容器
          if (this.isElemNearBottom(panel) || this.isForceScrollToBottom) {
            panel.scrollTop = panel.scrollHeight;
          }

          // 2. 滚动独立面板内层区块
          const innerBlocks = panel.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
    },
    changeMainAgent(agent) {
      this.mainAgent = agent;
      if (agent === 'super-model') {
        this.system_prompt = " "
      }
      else {
        this.system_prompt = this.agents[agent].system_prompt;
        console.log(this.system_prompt);
      }
      this.syncSystemPromptToMessages(this.system_prompt);
    },
    async changeQQAgent(agent) {
      this.qqBotConfig.QQAgent = agent;
      await this.autoSaveSettings();
    },
    // WebSocket相关
    initWebSocket() {
      const http_protocol = window.location.protocol;
      const ws_protocol = http_protocol === 'https:' ? 'wss:' : 'ws:';
      const ws_url = `${ws_protocol}//${window.location.host}/ws`;

      // 【重连保护】如果已有旧连接，说明是重连而非首次连接
      const isReconnect = !!this.ws;
      if (isReconnect) {
        this._isWsReconnect = true;
        console.log('[WS] 检测到重连，将保护当前对话状态不被覆盖');
      }

      this.ws = new WebSocket(ws_url);

      // 设置心跳间隔和重连间隔（单位：毫秒）
      const HEARTBEAT_INTERVAL = 10000; // 每10秒发送一次 ping
      const RECONNECT_INTERVAL = 5000;  // 断开后每5秒尝试重连一次

      let heartbeatTimer = null;
      let reconnectTimer = null;

      const startHeartbeat = () => {
        heartbeatTimer = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
              this.ws.send(JSON.stringify({ type: 'ping' })); // 发送心跳包
            } catch (e) {
              console.error('Failed to send ping:', e);
            }
          }
        }, HEARTBEAT_INTERVAL);
      };

      const stopHeartbeat = () => {
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
      };

      const scheduleReconnect = () => {
        stopHeartbeat();
        if (!reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            console.log('Reconnecting WebSocket...');
            this.initWebSocket(); // 重新初始化
            reconnectTimer = null;
          }, RECONNECT_INTERVAL);
        }
      };

      // WebSocket 打开事件
      this.ws.onopen = () => {
        console.log('WebSocket connection established');
        stopHeartbeat(); // 防止重复心跳
        startHeartbeat();
        if (!this._covsSaveTimer) {
          this._covsSaveTimer = setInterval(() => { this.flushDirtyConversations(); }, 30000);
        }
      };

      // 接收消息
      this.ws.onmessage = async (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (e) {
          console.log('Message from server:', event.data);
          return;
        }

      if (data.type === 'pong') {
        // 可以在这里处理 pong 回复，比如记录状态
        console.log('Received pong from server.');
      } 
      else if (data.type === 'settings_update') {
          // 增量广播：payload 为 settings 子集，schema 驱动恢复自动跳过未推送键
          // （批 0-④：原手写清单缺 agents/systemSettings 等键，推送被静默忽略，已并入单源）
          this.settings = window.SETTINGS_SCHEMA.buildSettingsFromWire(data.data);
          window.SETTINGS_SCHEMA.applySettingsPayload(this, data.data);
      }
      else if (data.type === 'settings') {
          // 【重连保护】如果是重连，保护当前对话状态不被服务端全量覆盖
          const isReconnect = this._isWsReconnect;
          if (isReconnect) {
            console.log('[WS] 重连模式：保护当前对话状态，仅同步非对话配置');
            this._isWsReconnect = false;
            // 【修复】重连后补发被缓存的扩展消息，确保插件收到完整回复
            if (this._pendingExtensionMessage) {
              setTimeout(() => {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                  try {
                    this.ws.send(this._pendingExtensionMessage);
                    this._pendingExtensionMessage = null;
                    console.log('[WS] 重连后已补发缓存的扩展消息');
                  } catch (e) {
                    console.error('[WS] 补发缓存消息失败:', e);
                  }
                }
              }, 500); // 延迟500ms确保连接稳定
            }
          }
          this.ensureConversationGroups();
          this.isdocker = data.data.isdocker || false;
          // settings 展开字段与常规设置对均由 settings_schema.js 单一事实源驱动（批 0-④）
          this.settings = window.SETTINGS_SCHEMA.buildSettingsFromWire(data.data);
          // 【重连保护】重连时不覆盖对话数据，避免丢失正在进行的对话
          if (!isReconnect) {
            this.conversations = data.data.conversations || this.conversations;
            this.conversationGroups = data.data.conversationGroups || this.conversationGroups;
            this.conversationId = data.data.conversationId || this.conversationId;
          } else if (Array.isArray(data.data.conversations)) {
            // 重连：与服务器副本按 id+timestamp 双向合并，本地未落盘的会话保留并补推
            this.mergeRemoteConversations(data.data.conversations);
          }
          // 常规设置对恢复（truthy 覆盖），清单在 settings_schema.js 单源维护
          window.SETTINGS_SCHEMA.applySettingsPayload(this, data.data);
          if (data.data.largeMoreButtonDict) {
            this.largeMoreButtonDict = this.largeMoreButtonDict.map(existingButton => {
              const newButton = data.data.largeMoreButtonDict.find(button => button.name === existingButton.name);
              if (newButton) {
                return { ...existingButton, enabled: newButton.enabled };
              }
              return existingButton;
            });
          }
          if (data.data.smallMoreButtonDict) {
            this.smallMoreButtonDict = this.smallMoreButtonDict.map(existingButton => {
              const newButton = data.data.smallMoreButtonDict.find(button => button.name === existingButton.name);
              if (newButton) {
                return { ...existingButton, enabled: newButton.enabled };
              }
              return existingButton;
            });
          }
          // 【重连保护】重连时不重新加载对话，避免覆盖正在进行的 SSE 流消息
          if (!isReconnect) {
            this.loadConversation(this.conversationId);
          }
          // 初始化时确保数据一致性
          this.edgettsLanguage = this.ttsSettings.edgettsLanguage;
          this.edgettsGender = this.ttsSettings.edgettsGender;
          this.handleSystemLanguageChange(this.systemSettings.language);
          this.refreshButtonText = this.t('refreshList');
          if (this.HASettings.enabled) {
            this.changeHAEnabled();
          };
          await this.initChromeMCPSettings();
          if (this.chromeMCPSettings.enabled){
            this.changeChromeMCPEnabled();
          }
          if (this.sqlSettings.enabled){
            this.changeSqlEnabled();
          }
          this.changeMemory();
          // this.target_lang改成navigator.language || navigator.userLanguage;
          this.target_lang = this.targetLangSelected!="system"? this.targetLangSelected: navigator.language || navigator.userLanguage || 'zh-CN';
          this.loadDefaultModels();
          this.loadDefaultMotions();
          this.loadGaussScenes();
          this.checkMobile();
          this.checkQQBotStatus(); 
          this.checkFeishuBotStatus();
          this.checkTelegramBotStatus();
          this.checkXmppBotStatus();
          this.checkDiscordBotStatus();
          this.checkLiveStatus();
          this.fetchRemotePlugins();
          this.fetchSkills();
          this.fetchTetosVoices(this.ttsSettings.engine);
          if (this.asrSettings.enabled && this.asrSettings.interactionMethod != 'globalKeyTriggered' && this.asrSettings.interactionMethod != 'keyTriggered') {
            this.startASR();
          }
          if (this.activeMenu === 'home') this.startDriverGuide();
        } 
          // 在 initWebSocket() 的 onmessage 逻辑中添加
          else if (data.type === 'task_notification') {
              // 调用前端的弹窗提醒
              showNotification(`${data.data.title}\n${this.t('intask')}`, 'success');
          }
        else if (data.type === 'settings_saved') {
          if (!data.success) {
            showNotification(this.t('settings_save_failed'), 'error');
          }
        }
        // 新增：处理用户输入更新
        else if (data.type === 'update_user_input') {
          this.userInput = data.data.text;
          // [XMPP Bridge] 接收扩展注入的图片附件（已上传到 uploaded_files，形如 [{path, name, type}]）
          const extImages = Array.isArray(data.data.images) ? data.data.images : [];
          if (extImages.length > 0) {
            this.extensionImageLinks = [...(this.extensionImageLinks || []), ...extImages];
          }
        }
        // 更新或添加提示词
        else if (data.type === 'update_system_prompt') {
            const id = data.data.id;
            const text = data.data.text;
            this.extensionsSystemPromptsDict[id] = text; 
        }
        
        // 移除提示词 (对应后端 finally 中的逻辑)
        else if (data.type === 'remove_system_prompt') {
            const id = data.data.id;
            
            if (this.extensionsSystemPromptsDict[id]) {
                delete this.extensionsSystemPromptsDict[id];
            }
        }
        // 新增：处理工具输入
        else if (data.type === 'update_tool_input') {
          this.userInput = data.data.text;
          this.sendMessage('system')
        }
        // 新增：处理TTS输入
        else if (data.type === 'start_tts') {
          this.readConfig.longText = data.data.text;
          // 等待0.5s
          setTimeout(() => {
            this.startRead();
          }, 500);
        }
        // 新增：停止TTS
        else if (data.type === 'stop_tts') {
          this.stopTTSActivities();
          this.readConfig.longText = '';
        }
        // 新增：处理关闭扩展侧边栏
        else if (data.type === 'trigger_close_extension') {
          console.log('关闭侧边栏')
          this.resetToDefaultView();
        }
        // 新增：处理触发发送消息
        else if (data.type === 'trigger_send_message') {
          this.sendMessage();
        }
        // 新增：清空消息列表
        else if (data.type === "trigger_clear_message" ){
          this.clearMessages();
        }
        // 新增：响应请求消息列表
        else if (data.type === 'request_messages') {
          // 发送当前消息列表给请求方
          this.sendMessagesToExtension();
        }
      };

      // WebSocket 关闭事件
      this.ws.onclose = (event) => {
        console.log('WebSocket connection closed:', event.reason);
        stopHeartbeat();
        scheduleReconnect();
      };

      // WebSocket 错误事件
      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.ws.close(); // 主动关闭连接，触发 onclose 事件
      };
    },

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
    },
    escapeHtml(unsafe) {
      return unsafe
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    },  
    // 新增：发送当前消息列表到所有连接的客户端
    sendMessagesToExtension(force) {
      const now = Date.now();
      if (!force && now - (this._lastExtSendTime || 0) < 500) return; // 流式期间节流：最多每 500ms 序列化一次
      this._lastExtSendTime = now;
      const payload = JSON.stringify({
        type: 'broadcast_messages',
        data: {
          messages: this.messages,
          conversationId: this.conversationId
        }
      });
      if (this.ws && this.ws.readyState === WebSocket.OPEN) {
        try {
          this.ws.send(payload);
        } catch (e) {
          console.error('Failed to send messages to extension:', e);
          // 发送失败也暂存，等重连后补发
          this._pendingExtensionMessage = payload;
        }
      } else {
        // WS 未连接，暂存消息，等重连后补发
        this._pendingExtensionMessage = payload;
      }
    },
    async syncSystemPromptToMessages(newPrompt) {
      // 情况 1: 新提示词为空
      if (!newPrompt) {
        if (this.messages.length > 0 && this.messages[0].role === 'system') {
          this.messages.splice(0, 1); // 删除系统消息
        }
        return;
      }
  
      // 情况 2: 已有系统消息
      if (this.messages[0]?.role === 'system') {
        // 更新系统消息内容
        this.messages[0].content = newPrompt;
        console.log('Updated system message:', this.messages[0]);
        return;
      }
  
      // 情况 3: 没有系统消息
      this.messages.unshift({
        id: Date.now() + Math.random(), // 添加唯一ID
        role: 'system',
        content: newPrompt
      });
      console.log('Added system message:', this.messages[0]);
      await this.autoSaveSettings();
    },


    // 敏感路径检测函数
    isDangerousPath(path) {
        if (!path) return false;

        // 1. 规范化路径：统一斜杠，转小写，去掉末尾斜杠
        let normalized = path.trim().replace(/\\/g, '/').toLowerCase();
        if (normalized.length > 1 && normalized.endsWith('/')) {
            normalized = normalized.slice(0, -1);
        }

        // --- A. 绝对禁止的磁盘/系统根目录 ---
        // 匹配: "c:", "d:", "/"
        const winRootRegex = /^[a-z]:$/;
        if (winRootRegex.test(normalized) || normalized === '/' || normalized === '') {
            return true; 
        }

        // --- B. 仅禁止目录本身，但允许其子目录 (User Containers) ---
        // 比如禁止选择 "C:/Users"，但允许 "C:/Users/YourName/Documents"
        const userContainers = [
            'c:/users',
            '/users',
            '/home'
        ];
        if (userContainers.includes(normalized)) {
            return true;
        }

        // --- C. 禁止该目录及其所有子目录 (System Core) ---
        // 这些地方无论如何都不该让本地引擎去跑
        const strictSystemPaths = [
            'c:/windows',
            'c:/program files',
            'c:/program files (x86)',
            'c:/boot',
            'c:/recovery',
            'c:/system volume information',
            '/bin', '/boot', '/dev', '/etc', '/lib', '/lib64', '/proc', 
            '/root', '/run', '/sbin', '/sys', '/usr', '/var', '/opt',
            '/system', '/library', '/volumes'
        ];

        return strictSystemPaths.some(prefix => {
            // 只有在匹配系统核心目录或其子路径时才拦截
            return normalized === prefix || normalized.startsWith(prefix + '/');
        });
    },










    // === 辅助函数 ===

    














    // 辅助：转义 HTML (如果已有可忽略)
    escapeHtml(text) {
        if (!text) return '';
        return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    },
    async handleInputPaste(event) {
      const items = (event.clipboardData || window.clipboardData).items;
      
      // 🆕 配置: 超过多少字符转为文件
      const TEXT_TO_FILE_THRESHOLD = 2000; 

      const imageFiles = []; // 待上传的图片列表
      const videoFiles = []; // 🆕 待上传的视频列表
      const docFiles = [];   // 待上传的普通文件列表
      let hasValidContent = false;

      // 1. 遍历剪贴板中的项目
      for (const item of items) {
        if (item.kind === 'file') {
          const file = item.getAsFile();
          if (!file) continue;

          const ext = (file.name.split('.').pop() || '').toLowerCase();
          const isImageMime = item.type.startsWith('image/');
          const isVideoMime = item.type.startsWith('video/'); // 🆕 识别视频MIME

          // --- 视频处理逻辑 ---
          if (isVideoMime || ALLOWED_VIDEO_EXTENSIONS.includes(ext)) {
            videoFiles.push(file);
            hasValidContent = true;
          } 
          // --- 图片处理逻辑 ---
          else if (isImageMime || ALLOWED_IMAGE_EXTENSIONS.includes(ext)) {
            if (file.name === 'image.png' || !file.name.includes('.')) {
              const fileExtension = file.type.split('/')[1] || 'png';
              const namedFile = new File([file], `pasted_image_${Date.now()}.${fileExtension}`, { type: file.type });
              imageFiles.push(namedFile);
            } else {
              imageFiles.push(file);
            }
            hasValidContent = true;
          } 
          // --- 普通文档处理逻辑 ---
          else if (ALLOWED_EXTENSIONS.includes(ext)) {
            docFiles.push(file);
            hasValidContent = true;
          }
        }
      }

      // 2. 如果没有检测到实体文件，检查纯文本是否过长
      if (!hasValidContent) {
          const pastedText = event.clipboardData.getData('text');
          if (pastedText && pastedText.length > TEXT_TO_FILE_THRESHOLD) {
              const fileName = `paste_text_${Date.now()}.txt`;
              const textFile = new File([pastedText], fileName, { type: 'text/plain' });
              docFiles.push(textFile);
              hasValidContent = true;
          }
      }

      // 3. 如果找到了有效内容
      if (hasValidContent) {
        event.preventDefault();

        // 🆕 处理视频
        if (videoFiles.length > 0) {
          this.addFiles(videoFiles, 'video');
        }

        if (imageFiles.length > 0) {
          this.addFiles(imageFiles, 'image');
        }

        if (docFiles.length > 0) {
          this.addFiles(docFiles, 'file');
        }
      }
    },
    getRoleAvatar(name) {
        // 尝试从记忆列表查找
        const mem = this.memories.find(m => m.name === name);
        if (mem && mem.avatar) return mem.avatar;
        // 如果需要，也可以尝试从 agents 列表查找 (如果 agent 对象里存了 avatar)
        // const agentKey = Object.keys(this.agents).find(key => this.agents[key].name === name);
        // if (agentKey && this.agents[agentKey].avatar) return this.agents[agentKey].avatar;
        
        return 'source/Avatar.png';
    },

    async playPCMChunk(b64, currentText = '', message = null) {
        this.isOmniPlaying = true;
        if (message) {
            message.isPlaying = true;
            if (message.omniDuration === undefined) message.omniDuration = 0;
            if (message.omniCurrentTime === undefined) message.omniCurrentTime = 0;
            if (!message.generationFinished) message.omniAudioChunks.push(b64);
        }

        try {
            if (!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (this.audioCtx.state === 'suspended') await this.audioCtx.resume();

            // 解码数据
            const raw = atob(b64);
            const pcm16 = new Int16Array(raw.length / 2);
            for (let i = 0; i < raw.length; i += 2) {
                pcm16[i >> 1] = raw.charCodeAt(i) | (raw.charCodeAt(i + 1) << 8);
            }

            const sampleRate = 24000;
            const buf = this.audioCtx.createBuffer(1, pcm16.length, sampleRate);
            const floatData = buf.getChannelData(0);
            for (let i = 0; i < pcm16.length; i++) floatData[i] = pcm16[i] / 32768;

            const chunkDuration = buf.duration;
            if (message && message.isOmni && !message.generationFinished) {
                message.omniDuration += chunkDuration;
            }

            // ======= 【核心修改：利用二进制同步到 VRM】 =======
            if ((this.vrmOnline || this.vtsOnline) && this.ttsWebSocket) {
                const pcmUint8 = new Uint8Array(raw.length);
                for(let i=0; i<raw.length; i++) pcmUint8[i] = raw.charCodeAt(i);
                
                this.sendBinaryToVRM({
                    type: 'omni_chunk',
                    text: currentText, // 传入当前文本
                    sampleRate: sampleRate
                }, pcmUint8.buffer);
            }
            // ===============================================

            const now = this.audioCtx.currentTime;
            if (this.audioStartTime < now) this.audioStartTime = now;

            const src = this.audioCtx.createBufferSource();
            src.buffer = buf;
            if (!this.activeSources) this.activeSources = [];
            this.activeSources.push(src);

            const gainNode = this.audioCtx.createGain();
            gainNode.gain.value = this.vrmOnline ? 0.000001 : 1.0;

            src.connect(gainNode);
            gainNode.connect(this.audioCtx.destination);

            src.onended = () => {
                if (this.activeSources) this.activeSources = this.activeSources.filter(s => s !== src);
                if (message && message.isOmni && !src.isForceStopped) {
                    message.omniCurrentTime += chunkDuration;
                    if (message.omniCurrentTime > message.omniDuration) message.omniCurrentTime = message.omniDuration;

                    if (message.generationFinished && this.activeSources.length === 0) {
                        message.isPlaying = false;
                        message.omniCurrentTime = message.omniDuration;
                        if (this.vrmOnline || this.vtsOnline) this.sendTTSStatusToVRM('allChunksCompleted', {});
                        this.isOmniPlaying = false;
                    }
                }
                try { src.disconnect(); gainNode.disconnect(); } catch (e) {}
            };

            src.start(this.audioStartTime);
            this.audioStartTime += buf.duration;
        } catch (error) {
            console.error('Error in playPCMChunk:', error);
            if (message) message.isPlaying = false;
        }
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

    async translateMessage(index) {
      const msg = this.messages[index];
      const originalContent = msg.content;
      if (msg.isTranslating) return;
      if (originalContent.trim() === '') return;

      // 1. 先占坑
      this.messages[index] = {
        ...msg,
        content: this.t('translating') + '...',
        isTranslating: true,
        originalContent
      };

      try {
        const abortController = new AbortController();
        this.abortController = abortController;

        // 2. 组装 TTS 提示
        let newttsList = [];
        if (this.ttsSettings?.newtts) {
          for (const key in this.ttsSettings.newtts) {
            if (this.ttsSettings.newtts[key].enabled) newttsList.push(key);
          }
        }
        const ttsMsg = (newttsList.length === 0 || !this.ttsSettings?.enabled)
          ? '如果被翻译的文字与目标语言一致，则返回原文即可'
          : `你还需要在翻译的同时，添加对应的音色标签。如果被翻译的文字与目标语言一致，则只需要添加对应的音色标签。注意！不要使用<!--  -->这会导致部分文字不可见！你可以使用以下音色：\n${newttsList.join(', ')}\n，当你生成回答时，将不同的旁白或角色的文字用<音色名></音色名>括起来，以表示这些话是使用这个音色，以控制不同TTS转换成对应音色。对于没有对应音色的部分，可以不括。即使音色名称不为英文，还是可以照样使用<音色名>使用该音色的文本</音色名>来启用对应音色。注意！如果是你扮演的角色的名字在音色列表里，你必须用这个音色标签将你扮演的角色说话的部分括起来！只要是非人物说话的部分，都视为旁白！角色音色应该标记在人物说话的前后！例如：<Narrator>现在是下午三点，她说道：</Narrator><角色名>”天气真好哇！“</角色名><Narrator>说完她伸了个懒腰。</Narrator>\n\n`;

        // 3. 发起流式请求
        const response = await fetch('/simple_chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: this.mainAgent,
            messages: [
              {
                role: 'system',
                content: `你是一位专业翻译，请将用户提供的任何内容严格翻译为${this.target_lang}，保持原有格式（如Markdown、换行等），不要添加任何额外内容。只需返回翻译结果。${ttsMsg}`
              },
              {
                role: 'user',
                content: `请翻译以下内容到${this.target_lang}：\n\n${originalContent}`
              }
            ],
            stream: true,
            temperature: 0.1
          }),
          signal: abortController.signal
        });

        if (!response.ok) throw new Error('Translation failed');

            await iterateNdjsonLines(response, (chunk) => {
          const delta = chunk.choices?.[0]?.delta?.content ?? '';
          if (delta) {
            translated += delta;
            this.messages[index].content = translated; // 实时渲染
          }
            });

        // 5. 翻译完成
        this.messages[index].isTranslating = false;
        this.messages[index].translated = true;

      } catch (error) {
        if (error.name === 'AbortError') {
          // 用户中断，恢复原文
          this.messages[index] = { ...msg, content: originalContent, isTranslating: false };
        } else {
          this.messages[index].content = `Translation error: ${error.message}`;
          this.messages[index].isTranslating = false;
        }
      } finally {
        this.abortController = null;
      }
    },




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



    




  // 粘贴处理 (同时也支持截图粘贴)
  handleInputPaste(event) {
    const items = event.clipboardData.items;
    const files = [];
    let hasFiles = false;
    
    for (let i = 0; i < items.length; i++) {
      if (items[i].kind === 'file') {
        files.push(items[i].getAsFile());
        hasFiles = true;
      }
    }
    
    if (hasFiles) {
      // 有文件时阻止默认行为
      event.preventDefault();
      this.handleFiles(files);
    }
    // 没有文件时，让浏览器正常处理文本粘贴
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










    // 在 methods 中添加
    t(key) {
      const lang = this.translations[this.currentLanguage];
      const fallback = this.translations['en-US'];
      return (lang && lang[key]) || (fallback && fallback[key]) || key;
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
    // --- 数据安全网（M4-lite 快照备份 UI）---
    async loadBackupList() {
      this.backupListLoading = true;
      try {
        const resp = await fetch('/api/backup/list');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.backupSnapshots = (data.snapshots || []).slice().reverse();
      } catch (e) {
        this.$message?.error(this.t('dataGuardLoadFail') + ': ' + e.message);
      } finally {
        this.backupListLoading = false;
      }
    },
    async backupNow() {
      if (this.backupNowRunning) return;
      this.backupNowRunning = true;
      try {
        const resp = await fetch('/api/backup/now', { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data.ok === false) {
          throw new Error(data.reason || ('HTTP ' + resp.status));
        }
        this.$message?.success(this.t('dataGuardBackupOk') + ` (${data.files} ${this.t('dataGuardFiles')} / ${this.formatBackupBytes(data.bytes)})`);
        await this.loadBackupList();
      } catch (e) {
        this.$message?.error(this.t('dataGuardBackupFail') + ': ' + e.message);
      } finally {
        this.backupNowRunning = false;
      }
    },
    async verifyBackup(name) {
      this.verifyBackupName = name;
      try {
        const resp = await fetch('/api/backup/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || ('HTTP ' + resp.status));
        if (data.ok) this.$message?.success(`${name}: ` + this.t('dataGuardVerifyOk'));
        else this.$message?.error(`${name}: ` + this.t('dataGuardVerifyFail'));
      } catch (e) {
        this.$message?.error(this.t('dataGuardVerifyFail') + ': ' + e.message);
      } finally {
        this.verifyBackupName = '';
      }
    },
    formatBackupBytes(n) {
      n = Number(n) || 0;
      if (n < 1024) return n + ' B';
      if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
      if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
      return (n / 1073741824).toFixed(2) + ' GB';
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
















    
    
    


    

    
  // 启动QQ机器人
  async startQQBot() {
    this.isStarting = true;
    
    try {
      // 显示连接中的提示
      showNotification('正在连接QQ机器人...', 'info');
      
      const response = await fetch(`/start_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.qqBotConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        this.isQQBotRunning = true;
        showNotification('QQ机器人已成功启动并就绪', 'success');
      } else {
        // 显示具体错误信息
        const errorMessage = result.message || '启动失败，请检查配置';
        showNotification(`启动失败: ${errorMessage}`, 'error');
        
        // 如果是超时错误，给出更具体的提示
        if (errorMessage.includes('超时')) {
          showNotification('提示：请检查网络连接和机器人配置是否正确', 'warning');
        }
      }
    } catch (error) {
      console.error('启动QQ机器人时出错:', error);
      showNotification('启动QQ机器人失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isStarting = false;
    }
  },

  // 停止QQ机器人
  async stopQQBot() {
    this.isStopping = true;
    
    try {
      const response = await fetch(`/stop_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      const result = await response.json();
      
      if (result.success) {
        this.isQQBotRunning = false;
        showNotification('QQ机器人已成功停止', 'success');
      } else {
        const errorMessage = result.message || '停止失败';
        showNotification(`停止失败: ${errorMessage}`, 'error');
      }
    } catch (error) {
      console.error('停止QQ机器人时出错:', error);
      showNotification('停止QQ机器人失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isStopping = false;
    }
  },

  // 重载QQ机器人配置
  async reloadQQBotConfig() {
    this.isReloading = true;
    
    try {
      const response = await fetch(`/reload_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.qqBotConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        if (result.config_changed) {
          showNotification('QQ机器人配置已重载并重新启动', 'success');
        } else {
          showNotification('QQ机器人配置已更新', 'success');
        }
      } else {
        const errorMessage = result.message || '重载失败';
        showNotification(`重载失败: ${errorMessage}`, 'error');
      }
    } catch (error) {
      console.error('重载QQ机器人配置时出错:', error);
      showNotification('重载QQ机器人配置失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isReloading = false;
    }
  },
  
  // 添加状态检查方法
  async checkQQBotStatus() {
    try {
      const response = await fetch(`/qq_bot_status`);
      const status = await response.json();
      
      // 更新机器人运行状态
      this.isQQBotRunning = status.is_running;
      
      // 如果机器人正在运行但前端状态不一致，更新状态
      if (status.is_running && !this.isQQBotRunning) {
        this.isQQBotRunning = true;
      }
    } catch (error) {
      console.error('检查机器人状态失败:', error);
    }
  },

    // 新增的方法：供主进程请求关闭机器人
    async requestStopQQBotIfRunning() {
      try {
        const response = await fetch(`/qq_bot_status`)
        const status = await response.json()

        if (status.is_running) {
          // 调用 stopQQBot 来关闭机器人
          await this.stopQQBot()
          console.log('机器人已关闭')
        }
      } catch (error) {
        console.error('检查或停止机器人失败:', error)
      }
    },

 async requestFeishuBotStopIfRunning(){
      try {
        const response = await fetch(`/feishu_bot_status`)
        const status = await response.json()

        if (status.is_running) {
          // 调用 stopQQBot 来关闭机器人
          await this.stopFeishuBot()
          console.log('机器人已关闭')
        }
      } catch (error) {
        console.error('检查或停止机器人失败:', error)
      }
 },

async startFeishuBot() {
  this.isFeishuStarting = true;
  try {
    showNotification('正在连接飞书机器人...', 'info');
    const res = await fetch('/start_feishu_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.feishuBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isFeishuBotRunning = true;
      showNotification('飞书机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuStarting = false;
  }
},
async stopFeishuBot() {
  this.isFeishuStopping = true;
  try {
    const res = await fetch('/stop_feishu_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isFeishuBotRunning = false;
      showNotification('飞书机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuStopping = false;
  }
},
async reloadfeishuBotConfig() {
  this.isFeishuReloading = true;
  try {
    const res = await fetch('/reload_feishu_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.feishuBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('飞书机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuReloading = false;
  }
},
async checkFeishuBotStatus() {
  try {
    const res = await fetch('/feishu_bot_status');
    const st = await res.json();
    this.isFeishuBotRunning = st.is_running;
  } catch (e) {
    console.error('检查飞书机器人状态失败', e);
  }
},
handleCreateFeishuSeparator(val) {
  this.feishuBotConfig.separators.push(val);
},

async requestWechatBotStopIfRunning() {
  try {
    const res = await fetch(`/wechat_bot_status`)
    const status = await res.json()
    if (status.is_running) {
      await this.stopWechatBot()
    }
  } catch (error) { console.error('检查或停止微信机器人失败:', error) }
},
async startWechatBot() {
  this.isWechatStarting = true;
  this.showWechatQR = false; // 隐藏旧的弹窗
  this.wechatQRCodeBase64 = null; // 清空旧的二维码
  try {
    showNotification('正在启动微信机器人服务...', 'info');
    const res = await fetch('/start_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.wechatBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isWechatBotRunning = true;
      // 启动成功后，开启 1.5 秒一次的高频轮询，去抓后台的 Base64 图片
      if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
      this.wechatStatusTimer = setInterval(() => {
        this.checkWechatBotStatus();
      }, 1500);
      
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isWechatStarting = false;
  }
},

async stopWechatBot() {
  this.isWechatStopping = true;
  if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
  try {
    const res = await fetch('/stop_wechat_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isWechatBotRunning = false;
      showNotification('微信机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatStopping = false;
  }
},
async reloadWechatBotConfig() {
  this.isWechatReloading = true;
  try {
    const res = await fetch('/reload_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.wechatBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('微信机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatReloading = false;
  }
},
async checkWechatBotStatus() {
  try {
    const res = await fetch('/wechat_bot_status');
    const st = await res.json();
    this.isWechatBotRunning = st.is_running;
    
    // 弹出二维码：如果后端有二维码，并且和当前界面的不一样
    if (st.qr_base64 && this.wechatQRCodeBase64 !== st.qr_base64) {
      this.wechatQRCodeBase64 = st.qr_base64;
      this.showWechatQR = true; 
    }

    // --- 核心修复：触发自动秒关弹窗的逻辑 ---
    // 条件1: 后端识别到登录成功的特征 (st.is_logged_in)
    // 条件2: 原本正在显示二维码，但下一秒发现后端的 qr_base64 变成了 null (被系统清除了)
    if (st.is_logged_in || (this.showWechatQR && !st.qr_base64 && this.wechatQRCodeBase64)) {
        this.showWechatQR = false;         // 瞬间关闭弹窗
        this.wechatQRCodeBase64 = null;    // 清空本地图片缓存
        showNotification('✅ 微信已成功登录，机器人开始工作！', 'success');
        
        // 扫码成功后，取消极速轮询定时器，减轻服务器压力
        if (this.wechatStatusTimer) {
            clearInterval(this.wechatStatusTimer);
            this.wechatStatusTimer = null;
        }
    }

    // 意外停止时的清理逻辑
    if (!st.is_running && this.wechatStatusTimer) {
       clearInterval(this.wechatStatusTimer);
       this.wechatStatusTimer = null;
    }
  } catch (e) {
    console.error('检查微信状态失败', e);
  }
},
handleCreateWechatSeparator(val) {
  this.wechatBotConfig.separators.push(val);
},

async forceReLoginWechatBot() {
  // 1. 如果当前正在运行，先停止它，释放被占用的凭证文件
  if (this.isWechatBotRunning) {
    showNotification('正在关闭当前实例并物理粉碎凭证缓存...', 'info');
    await this.stopWechatBot();
    
    // 关键：强制等待 2.5 秒，给操作系统足够的时间释放文件句柄和销毁底层线程
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  
  this.isWechatStarting = true;
  this.showWechatQR = false; 
  this.wechatQRCodeBase64 = null; 
  
  try {
    showNotification('强制获取全新二维码中，请稍候...', 'info');
    // 在 payload 中追加强制标识，后端检测到就会先执行物理删除
    const payload = { ...this.wechatBotConfig, force_relogin: true };
    
    const res = await fetch('/start_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const json = await res.json();
    
    if (json.success) {
      this.isWechatBotRunning = true;
      if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
      
      // 开启极速轮询，一旦后端生成了新二维码就会自动弹窗
      this.wechatStatusTimer = setInterval(() => {
        this.checkWechatBotStatus();
      }, 1500);
    } else {
      showNotification(`拉取新二维码失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatStarting = false;
  }
},
  // --- 企微方法 ---

  async requestWeComBotStopIfRunning() {
    try {
      const response = await fetch(`/wecom_bot_status`);
      const status = await response.json();

      if (status.is_running) {
        // 调用 stopWeComBot 来关闭机器人
        await this.stopWeComBot();
        console.log('机器人已关闭');
      }
    } catch (error) {
      console.error('检查或停止机器人失败:', error)
    }
  },
  async startWeComBot() {
    this.isWeComStarting = true;
    try {
      showNotification('正在连接企微机器人...', 'info');
      const res = await fetch('/start_wecom_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.weComBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        this.isWeComBotRunning = true;
        showNotification('企微机器人启动成功', 'success');
      } else {
        showNotification(`启动失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误或服务器未响应', 'error');
    } finally {
      this.isWeComStarting = false;
    }
  },
  async stopWeComBot() {
    this.isWeComStopping = true;
    try {
      const res = await fetch('/stop_wecom_bot', { method: 'POST' });
      const json = await res.json();
      if (json.success) {
        this.isWeComBotRunning = false;
        showNotification('企微机器人已停止', 'success');
      } else {
        showNotification(`停止失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isWeComStopping = false;
    }
  },
  async reloadWeComBotConfig() {
    this.isWeComReloading = true;
    try {
      const res = await fetch('/reload_wecom_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.weComBotConfig),
      });
      const json = await res.json();
      if (json.success) showNotification('企微机器人已重载', 'success');
      else showNotification(`重载失败：${json.message}`, 'error');
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isWeComReloading = false;
    }
  },
  async checkWeComBotStatus() {
    try {
      const res = await fetch('/wecom_bot_status');
      const st = await res.json();
      this.isWeComBotRunning = st.is_running;
    } catch (e) { }
  },

async requestTelegramBotStopIfRunning() {
  try {
    const res = await fetch('/telegram_bot_status');
    const st = await res.json();
    if (st.is_running) await this.stopTelegramBot();
  } catch (e) {
    console.error('检查或停止 Telegram 机器人失败:', e);
  }
},

  // 1. 启动钉钉机器人
  async startDingtalkBot() {
    this.isDingtalkStarting = true;
    try {
      showNotification('正在建立钉钉 Stream 连接...', 'info');
      const res = await fetch('/start_dingtalk_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.dingtalkBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        this.isDingtalkBotRunning = true;
        showNotification('钉钉机器人启动成功 (Stream模式)', 'success');
      } else {
        showNotification(`启动失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误：钉钉服务未响应', 'error');
    } finally {
      this.isDingtalkStarting = false;
    }
  },

  // 2. 停止钉钉机器人
  async stopDingtalkBot() {
    this.isDingtalkStopping = true;
    try {
      const res = await fetch('/stop_dingtalk_bot', { method: 'POST' });
      const json = await res.json();
      if (json.success) {
        this.isDingtalkBotRunning = false;
        showNotification('钉钉机器人连接已断开', 'success');
      } else {
        showNotification(`停止失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isDingtalkStopping = false;
    }
  },

  // 3. 重载钉钉机器人配置
  async reloadDingtalkBot() {
    this.isDingtalkReloading = true;
    try {
      const res = await fetch('/reload_dingtalk_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.dingtalkBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        showNotification('钉钉机器人配置已实时重载', 'success');
      } else {
        showNotification(`重载失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isDingtalkReloading = false;
    }
  },

  // 4. 检查钉钉机器人状态 (常用于 mounted 钩子)
  async checkDingtalkBotStatus() {
    try {
      const res = await fetch('/dingtalk_bot_status');
      const st = await res.json();
      this.isDingtalkBotRunning = st.is_running;
    } catch (e) {
      console.error('检查钉钉机器人状态失败', e);
    }
  },

  // 其他辅助方法
  handleCreateDingtalkSeparator(val) {
    if (!this.dingtalkBotConfig.separators) this.dingtalkBotConfig.separators = [];
    this.dingtalkBotConfig.separators.push(val);
  },

  // 联动停止：当其他机器人启动时，确保停止当前的钉钉机器人
  async requestDingtalkBotStopIfRunning() {
    try {
      const res = await fetch('/dingtalk_bot_status');
      const st = await res.json();
      if (st.is_running) await this.stopDingtalkBot();
    } catch (e) {
      console.error('停止钉钉机器人失败:', e);
    }
  },

async startTelegramBot() {
  this.isTelegramStarting = true;
  try {
    showNotification('正在连接 Telegram 机器人...', 'info');
    const res = await fetch('/start_telegram_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.telegramBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      this.isTelegramBotRunning = true;
      showNotification('Telegram 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramStarting = false;
  }
},
async stopTelegramBot() {
  this.isTelegramStopping = true;
  try {
    const res = await fetch('/stop_telegram_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isTelegramBotRunning = false;
      showNotification('Telegram 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramStopping = false;
  }
},
async reloadTelegramBotConfig() {
  this.isTelegramReloading = true;
  try {
    const res = await fetch('/reload_telegram_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.telegramBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Telegram 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramReloading = false;
  }
},
async checkTelegramBotStatus() {
  try {
    const res = await fetch('/telegram_bot_status');
    const st = await res.json();
    this.isTelegramBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Telegram 机器人状态失败', e);
  }
},
handleCreateTelegramSeparator(val) {
  this.telegramBotConfig.separators.push(val);
},

/* ------- XMPP 机器人（收编版第九通道） ------- */
async startXmppBot() {
  this.isXmppStarting = true;
  try {
    showNotification('正在连接 XMPP 服务器...', 'info');
    const res = await fetch('/start_xmpp_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.xmppBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      this.isXmppBotRunning = true;
      showNotification('XMPP 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppStarting = false;
    this.fetchXmppCertPending();
  }
},
async stopXmppBot() {
  this.isXmppStopping = true;
  try {
    const res = await fetch('/stop_xmpp_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isXmppBotRunning = false;
      showNotification('XMPP 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppStopping = false;
    this.fetchXmppCertPending();
  }
},
async reloadXmppBotConfig() {
  this.isXmppReloading = true;
  try {
    const res = await fetch('/reload_xmpp_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.xmppBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      showNotification('XMPP 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppReloading = false;
    this.fetchXmppCertPending();
  }
},
async checkXmppBotStatus() {
  try {
    const res = await fetch('/xmpp_bot_status');
    const st = await res.json();
    this.isXmppBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 XMPP 机器人状态失败', e);
  }
},
async requestXmppBotStopIfRunning() {
  try {
    const res = await fetch('/xmpp_bot_status');
    const st = await res.json();
    if (st.is_running) await this.stopXmppBot();
  } catch (e) {
    console.error('检查或停止 XMPP 机器人失败:', e);
  }
},
handleCreateXmppSeparator(val) {
  this.xmppBotConfig.separators.push(val);
},
async fetchXmppCertPending() {
  try {
    const res = await fetch('/xmpp_cert_pending');
    const json = await res.json();
    this.xmppCertPending = json.pending || [];
  } catch (e) {
    this.xmppCertPending = [];
  }
},
async fetchBotConversations() {
  try {
    const res = await fetch('/bot_conversations');
    const json = await res.json();
    this.xmppBotSessions = json.conversations || [];
  } catch (e) {
    this.xmppBotSessions = [];
  }
},
async openBotConversation(c) {
  try {
    const res = await fetch('/bot_conversation?id=' + encodeURIComponent(c.conv_id));
    const json = await res.json();
    if (json.success) {
      this.xmppSessionDetail = json.messages || [];
      this.xmppSessionTitle = c.peer || c.conv_id;
      this.xmppSessionOpen = true;
    } else {
      showNotification(json.message || '会话读取失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误：会话读取失败', 'error');
  }
},
async clearBotConversation(id) {
  if (!window.confirm('清空该 bot 会话的历史记录？')) return;
  try {
    const res = await fetch('/bot_conversation/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    });
    const json = await res.json();
    if (json.success) {
      showNotification('会话已清空', 'success');
      if (this.xmppSessionTitle && ('bot:xmpp:' + this.xmppSessionTitle) === id) {
        this.xmppSessionDetail = [];
      }
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '清空失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},
async deleteBotConversation(id) {
  if (!window.confirm('删除该 bot 会话？（不可恢复）')) return;
  try {
    const res = await fetch('/bot_conversation?id=' + encodeURIComponent(id), { method: 'DELETE' });
    const json = await res.json();
    if (json.success) {
      showNotification('会话已删除', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '删除失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},
async newBotConversation(row) {
  if (!window.confirm('归档当前会话并开启新会话？下一条入站消息将从空白开始（旧会话保留在归档中）。')) return;
  try {
    const res = await fetch('/bot_conversation/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: row.conv_id })
    });
    const json = await res.json();
    if (json.success) {
      showNotification(json.archive_id ? '已归档，下一条消息开启新会话' : '会话已是空白，无需归档', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '操作失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},
async activateBotConversation(row) {
  if (!window.confirm('将该归档会话置为 live？当前进行中的同对端会话会被归档，下一条入站消息接续此会话。')) return;
  try {
    const res = await fetch('/bot_conversation/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: row.conv_id, into: `bot:${row.channel}:${row.peer}` })
    });
    const json = await res.json();
    if (json.success) {
      showNotification('已置为 live，下一条入站消息将接续该会话', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '操作失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},
openEnvPage(menu) {
  this.activeMenu = menu;
},
formatBotTime(ts) {
  if (!ts) return '';
  try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return String(ts); }
},
botMsgText(msg) {
  const c = msg && msg.content;
  if (typeof c === 'string') return c.length > 800 ? c.slice(0, 800) + '…' : c;
  if (Array.isArray(c)) {
    return c.map(p => (p && p.type === 'text' ? p.text
      : (p && p.type === 'image_url' ? '[图片]' : ''))).filter(Boolean).join(' ');
  }
  return '';
},
async xmppCertDecision(key, decision) {
  try {
    const res = await fetch('/xmpp_cert_decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, decision })
    });
    const json = await res.json();
    if (!json.success) {
      showNotification(`证书决策失败：${json.message}`, 'error');
      return;
    }
    await this.fetchXmppCertPending();
    if (decision === 'once') showNotification('本次运行内信任该证书（重启后需重新确认）', 'info');
    if (decision === 'always') showNotification('已永久信任该证书，正在重新启动机器人...', 'success');
    if (decision !== 'reject') {
      await this.startXmppBot();
      await this.fetchXmppCertPending();
    } else {
      showNotification('已拒绝该证书', 'info');
    }
  } catch (e) {
    showNotification('网络错误：证书决策未送达', 'error');
  }
},

/* ------- Discord 机器人 ------- */
async startDiscordBot() {
  this.isDiscordStarting = true;
  try {
    showNotification('正在连接 Discord 机器人...', 'info');
    const res = await fetch('/start_discord_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.discordBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isDiscordBotRunning = true;
      showNotification('Discord 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordStarting = false;
  }
},
async stopDiscordBot() {
  this.isDiscordStopping = true;
  try {
    const res = await fetch('/stop_discord_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isDiscordBotRunning = false;
      showNotification('Discord 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordStopping = false;
  }
},
async reloadDiscordBot() {
  this.isDiscordReloading = true;
  try {
    const res = await fetch('/reload_discord_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.discordBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Discord 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordReloading = false;
  }
},
async checkDiscordBotStatus() {
  try {
    const res = await fetch('/discord_bot_status');
    const st = await res.json();
    this.isDiscordBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Discord 机器人状态失败', e);
  }
},
handleCreateDiscordSeparator(val) {
  this.discordBotConfig.separators.push(val);
},

async requestSlackBotStopIfRunning() {
    try {
      // 1. 先从后端确认 Slack 机器人的真实运行状态
      const response = await fetch(`/slack_bot_status`);
      const status = await response.json();

      // 2. 如果后端返回正在运行 (is_running 为 true)
      if (status.is_running) {
        // 3. 调用你之前在 methods 里写好的 stopSlackBot 方法
        // 该方法包含了停止逻辑、Loading 状态切换以及 showNotification 通知
        await this.stopSlackBot();
        console.log('Slack 机器人已应系统请求成功关闭');
      }
    } catch (error) {
      // 捕获网络错误或后端未启动的情况
      console.error('检查或停止 Slack 机器人失败:', error);
    }
  },

/* ------- Slack 机器人 ------- */
async startSlackBot() {
  this.isSlackStarting = true;
  try {
    showNotification('正在连接 Slack 机器人...', 'info');
    // 注意：这里发送的是 slackBotConfig，但后端会自动处理共用的 memorySettings 状态
    const res = await fetch('/start_slack_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...this.slackBotConfig,
        // 显式传一下 memory 配置，确保后端能拿到最新的
        memory_settings: this.memorySettings 
      }),
    });
    const json = await res.json();
    if (json.success) {
      this.isSlackBotRunning = true;
      showNotification('Slack 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isSlackStarting = false;
  }
},
async stopSlackBot() {
  this.isSlackStopping = true;
  try {
    const res = await fetch('/stop_slack_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isSlackBotRunning = false;
      showNotification('Slack 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isSlackStopping = false;
  }
},
async reloadSlackBot() {
  this.isSlackReloading = true;
  try {
    const res = await fetch('/reload_slack_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...this.slackBotConfig,
        memory_settings: this.memorySettings
      }),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Slack 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isSlackReloading = false;
  }
},
async checkSlackBotStatus() {
  try {
    const res = await fetch('/slack_bot_status');
    const st = await res.json();
    this.isSlackBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Slack 状态失败', e);
  }
},
handleCreateSlackSeparator(val) {
  this.slackBotConfig.separators.push(val);
},

    async handleSeparatorChange(val) {
      this.qqBotConfig.separators = val.map(s => 
        s.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
      );
      await this.autoSaveSettings();
    },
    formatSeparator(s) {
      return s.replace(/\n/g, '\\n')
              .replace(/\t/g, '\\t')
              .replace(/\r/g, '\\r');
    },
    // 新增创建分隔符处理方法
    async handleCreateSeparator(newSeparator) {
      const processed = this.escapeSeparator(newSeparator)
      if (!this.qqBotConfig.separators.includes(processed)) {
        this.qqBotConfig.separators.push(processed)
        await this.autoSaveSettings()
      }
    },

    // 处理回车键冲突
    handleEnter(e) {
      if (e.target.value) {
        e.stopPropagation()
      }
    },

    escapeSeparator(s) {
      return s.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
    },

    // 一键重置
    resetNewMemory() {
      this.newMemory = {
        id: null,
        name: '',
        infer:false,
        providerId: null,
        model: '',
        base_url: '',
        api_key: '',
        vendor: '',
        description: '',
        avatar: '',
        personality: '',
        mesExample: '',
        systemPrompt: '',
        firstMes: '',
        alternateGreetings: [],
        characterBook: [{ keysRaw: '', content: '' }]
      };
    },
    copyExistingMemoryData(selectedId) {
      const src = this.memories.find(m => m.id === selectedId);
      if (src) {
        /* 把旧字段映射到新字段，没有的就给默认值 */
        this.newMemory = {
          id: null,
          name: src.name || '',
          infer: src.infer || false,
          providerId: src.providerId || null,
          model: src.model || '',
          base_url: src.base_url || '',
          api_key: src.api_key || '',
          vendor: src.vendor || '',

          /* 旧→新 */
          description: src.basic_character || src.description || '',
          avatar: src.avatar || '',
          personality: src.personality || '',
          mesExample: src.mesExample || '',
          systemPrompt: src.systemPrompt || '',
          firstMes: src.firstMes || (Array.isArray(src.random) ? src.random[0]?.value : ''),
          alternateGreetings:
            Array.isArray(src.alternateGreetings)
              ? src.alternateGreetings
              : (src.random || []).slice(1).map(r => r.value),
          characterBook:
            Array.isArray(src.characterBook)
              ? src.characterBook
              : (src.lorebook || []).map(l => ({
                  keysRaw: l.name,
                  content: l.value
                }))  
        };
           if (this.newMemory.characterBook.length == 0 ){
              this.newMemory.characterBook = [{ keysRaw: '', content: '' }]
           }   
      } else {
        /* 新建：直接给空模板 */
        this.resetNewMemory();
      }
    },
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
    // 添加ComfyUI服务器
    addComfyUIServer() {
      this.comfyuiServers.push('http://localhost:8188')
      this.autoSaveSettings()
    },

    // 移除服务器
    removeComfyUIServer(index) {
      if (this.comfyuiServers.length > 1) {
        this.comfyuiServers.splice(index, 1)
        this.autoSaveSettings()
      }
    },

    // 连接服务器
    async connectComfyUI(index) {
      this.isConnecting = true
      try {
        const url = this.comfyuiServers[index]
        const response = await fetch(`${url}/history`, {
          method: 'HEAD',
          mode: 'cors'
        })
        if (response.ok) {
          this.activeComfyUIUrl = url
          showNotification('服务器连接成功')
        }
      } catch (e) {
        showNotification('无法连接ComfyUI服务器', 'error')
      }
      this.isConnecting = false
    },
    // 浏览文件
    browseWorkflowFile() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json';
      input.onchange = (event) => {
        const files = event.target.files;
        if (files.length > 0) {
          this.workflowFile = files[0];
          this.loadWorkflowFile(this.workflowFile); // 确保在文件已选择后调用
        }
      };
      input.click();
    },
    // 移除文件
    removeWorkflowFile() {
      this.workflowFile = null;
    },
    // 删除工作流
    async deleteWorkflow(filename) {
      try {
        const response = await fetch(`/delete_workflow/${filename}`, {
          method: 'DELETE',
        });
        const data = await response.json();
        if (data.success) {
          this.workflows = this.workflows.filter(file => file.unique_filename !== filename);
          await this.autoSaveSettings();
          showNotification('删除成功');
        } else {
          this.workflows = this.workflows.filter(file => file.unique_filename !== filename);
          await this.autoSaveSettings();
          showNotification('删除失败', 'error');
        }
      } catch (error) {
        console.error('删除失败:', error);
       showNotification('删除失败', 'error');
      }
    },
      // 处理文件拖拽
  handleWorkflowDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      this.workflowFile = files[0];
      this.loadWorkflowFile(this.workflowFile); // 加载工作流文件以生成选择项
    }
  },
  
  // 加载工作流文件
  async loadWorkflowFile(file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      const workflowJson = JSON.parse(event.target.result);
      this.populateInputOptions(workflowJson);
    };
    reader.readAsText(file);
  },

  // 填充输入选择项
  populateInputOptions(workflowJson) {
    this.textInputOptions = [];
    this.imageInputOptions = [];
    this.seedInputOptions = [];
    
    for (const nodeId in workflowJson) {
      const node = workflowJson[nodeId];
      if (!node.inputs) continue;
      
      // 查找所有包含text/value/prompt的文本输入字段
      const textInputKeys = Object.keys(node.inputs).filter(key => 
        (key.includes('text') || key.includes('value') || key.includes('prompt')) &&
        typeof node.inputs[key] === 'string' // 确保值是字符串类型
      );
      
      // 为每个符合条件的字段创建选项
      textInputKeys.forEach(key => {
        this.textInputOptions.push({
          label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
          value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
        });
      });
      
      // 查找图片输入字段
      if (node.class_type === 'LoadImage') {
        const imageKeys = Object.keys(node.inputs).filter(key => 
          key.includes('image') && 
          typeof node.inputs[key] === 'string' // 确保值是字符串类型
        );
        
        imageKeys.forEach(key => {
          this.imageInputOptions.push({
            label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
            value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
          });
        });
      }

      // 查找所有包含seed的种子输入字段
      const seedInputKeys = Object.keys(node.inputs).filter(
        key => key.includes('seed') && typeof node.inputs[key] === 'number' // 确保值是数字类型
      )
      seedInputKeys.forEach(key => {
        this.seedInputOptions.push({
          label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
          value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
        });
      })
    }
  },

    // 上传文件
    async uploadWorkflow() {
      if (!this.workflowFile) return;

      const formData = new FormData();
      formData.append('file', this.workflowFile);

      // 记录所选的输入位置
      const workflowData = {
        textInput: this.selectedTextInput,
        textInput2: this.selectedTextInput2,
        imageInput: this.selectedImageInput,
        imageInput2: this.selectedImageInput2,
        seedInput: this.selectedSeedInput,
        seedInput2: this.selectedSeedInput2,
        description: this.workflowDescription,
      };

      // 发送 JSON 字符串作为普通字段
      formData.append('workflow_data', JSON.stringify(workflowData));

      try {
        const response = await fetch(`/add_workflow`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) { // 检查响应状态
          const errorText = await response.text(); // 获取错误文本
          console.error("Server error:", errorText); // 输出错误信息
          throw new Error("Server error");
        }

        const data = await response.json();
        if (data.success) {
          this.workflows.push(data.file);
          this.showWorkflowUploadDialog = false;
          this.workflowFile = null;
          this.selectedTextInput = null; // 重置选中
          this.selectedImageInput = null; // 重置选中
          this.selectedTextInput2 = null; // 重置选中
          this.selectedImageInput2 = null; // 重置选中
          this.selectedSeedInput = null; // 重置选中
          this.selectedSeedInput2 = null; // 重置选中
          this.workflowDescription = ''; // 清空描述
          await this.autoSaveSettings();
          showNotification('上传成功');
        } else {
          showNotification('上传失败', 'error');
        }
      } catch (error) {
        console.error('上传失败:', error);
        showNotification('上传失败', 'error');
      }
    },
    cancelWorkflowUpload() {
      this.showWorkflowUploadDialog = false;
      this.workflowFile = null;
      this.selectedTextInput = null; // 重置选中
      this.selectedImageInput = null; // 重置选中
      this.selectedTextInput2 = null; // 重置选中
      this.selectedImageInput2 = null; // 重置选中
      this.selectedSeedInput = null; // 重置选中
      this.selectedSeedInput2 = null; // 重置选中
      this.workflowDescription = ''; // 清空描述
    },
    async deleteVideo(video) {
      this.videoFiles = this.videoFiles.filter(i => i !== video);
      await this.autoSaveSettings();
      const fileName = video.unique_filename
      try {
        // 向/delete_file发送请求
        const response = await fetch(`/delete_file`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileName: fileName })
        });
        // 处理响应
        if (response.ok) {
          console.log('File deleted successfully');
          showNotification(this.t('fileDeleted'), 'success');
        }
      } catch (error) {
        console.error('Error:', error);
        showNotification(this.t('fileDeleteFailed'), 'error');
      }
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
    handleBeforeUpload(file) {
      const reader = new FileReader()
      reader.readAsDataURL(file)
      reader.onload = () => {
        this.uploadedStickers.push({
          uid: file.uid,
          url: reader.result,
          description: "",
          file: file
        })
      }
      return false // 阻止自动上传
    },

    handleStickerRemove(file) {
      this.uploadedStickers = this.uploadedStickers.filter(f => f.uid !== file.uid)
    },

    async createStickerPack() {
      try {
        // 验证输入
        if (!this.newStickerPack.name || this.uploadedStickers.length === 0) {
          showNotification(this.t('fillAllFields'), 'warning');
          return;
        }
        

        // 创建FormData对象
        const formData = new FormData();
        
        // 添加表情包名称
        formData.append('pack_name', this.newStickerPack.name);
        
        // 添加所有表情描述
        this.uploadedStickers.forEach(sticker => {
          formData.append('descriptions', sticker.description);
        });
        
        // 添加所有表情文件
        this.uploadedStickers.forEach(sticker => {
          formData.append('files', sticker.file);
        });

        // 发送请求
        const response = await fetch(`/create_sticker_pack`, {
          method: 'POST',
          body: formData
        });
        
        // 处理响应
        if (!response.ok) {
          const errorData = await response.json();
          console.error("服务器错误详情:", errorData);
          
          let errorMsg = this.t('uploadFailed');
          if (errorData.detail) {
            if (typeof errorData.detail === 'string') {
              errorMsg = errorData.detail;
            } else if (errorData.detail[0]?.msg) {
              errorMsg = errorData.detail[0].msg;
            }
          }
          
          throw new Error(errorMsg);
        }

        const data = await response.json();
        if (data.success) {
          // 更新前端状态
          this.stickerPacks.push({
            id: data.id,
            name: data.name,
            stickers: data.stickers,
            cover: data.cover,
            enabled: true
          });
          
          this.imageFiles = [...this.imageFiles, ...data.imageFiles];
          this.resetStickerForm();
          await this.autoSaveSettings();
          
          showNotification(this.t('stickerPackCreated'));
          this.showStickerDialog = false;
        } else {
          showNotification(data.message || this.t('createFailed'), 'error');
          this.showStickerDialog = false;
        }
      } catch (error) {
        console.error('创建失败:', error);
        showNotification(
          error.message || this.t('createFailed'), 
          'error'
        );
        this.showStickerDialog = false;
      }
    },

    deleteStickerPack(stickerPack) {
      this.stickerPacks = this.stickerPacks.filter(pack => pack.id !== stickerPack.id);
      this.autoSaveSettings();
      showNotification(this.t('stickerPackDeleted'));
    },
    cancelStickerUpload() {
      this.showStickerDialog = false;
      this.resetStickerForm();
    },

    resetStickerForm() {
      this.newStickerPack = {
        name: '',
        stickers: [],
      };
      this.uploadedStickers = [];
    },
    handlePictureCardPreview(file) {
      this.imageUrl = file.url || URL.createObjectURL(file.raw)
      this.dialogVisible = true
    },
    downloadMemory(memory) {
      // 仅导出酒馆 V3 所需字段，敏感信息全部剔除
      const card = {
        spec: 'chara_card_v3',
        spec_version: '3.0',
        name: memory.name,
        description: memory.description || '',
        avatar: memory.avatar || '',
        personality: memory.personality || '',
        mes_example: memory.mesExample || '',
        first_mes: memory.firstMes || '',
        system_prompt: memory.systemPrompt || '',
        alternate_greetings: Array.isArray(memory.alternateGreetings)
          ? memory.alternateGreetings.filter(Boolean)
          : [],
        character_book: {
          name: memory.name,
          entries: Array.isArray(memory.characterBook)
            ? memory.characterBook
                .filter(e => e.keysRaw?.trim() && e.content?.trim())
                .map((e, idx) => ({
                  id: idx,
                  keys: e.keysRaw
                    .split(/\r?\n/)
                    .map(k => k.trim())
                    .filter(Boolean),
                  secondary_keys: [],
                  content: e.content,
                  comment: '',
                  constant: false,
                  selective: true,
                  insertion_order: 100,
                  enabled: true,
                  position: 'before_char',
                  use_regex: true,
                  extensions: {}
                }))
            : []
        }
        // 其余字段如 avatar、tags、scenario…按需补空
      };

      const blob = new Blob([JSON.stringify(card, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${memory.name}_v3.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },
    changeMemory() {
      if (this.memorySettings.is_memory){
        // 根据selectedMemory获取当前的memories中的对应的记忆
        let curMemory = this.memories.find(memory => memory.id === this.memorySettings.selectedMemory);
        this.firstMes = curMemory.firstMes;
        this.alternateGreetings= curMemory.alternateGreetings;
      }
      else{
        this.firstMes = '';
        this.alternateGreetings = [];
      }
      this.randomGreetings();
      this.autoSaveSettings(); // 保存设置
    },
    randomGreetings() {
      let greetings = [this.firstMes, ...this.alternateGreetings];
      // 过滤掉空字符串
      greetings = greetings.filter(greeting => greeting.trim() !== '');
      // 替换掉开场白中的所有的{{user}}为this.memorySettings.userName
      greetings = greetings.map(greeting => greeting.replace(/{{user}}/g, this.memorySettings.userName));
      // 根据selectedMemory获取当前的memories中的对应的记忆
      let curMemory = this.memories.find(memory => memory.id === this.memorySettings.selectedMemory);
      // 替换掉开场白中的所有的{{char}}为curMemory.name
      greetings = greetings.map(greeting => greeting.replace(/{{char}}/g, curMemory.name));
      if (greetings.length > 0) {
        let randomIndex = Math.floor(Math.random() * greetings.length);
        // 将随机的开场白立刻加入的this.messages中
        // 如果this.messages中第二个元素是开场白，则替换，否则在第一个元素之后插入
        if (this.messages.length > 1 && this.messages[1].role === 'assistant') {
          this.messages[1].content = greetings[randomIndex];
          this.messages[1].pure_content = greetings[randomIndex];
        } else {
          this.messages.splice(1, 0, {
            role: 'assistant',
            content: greetings[randomIndex],
            pure_content: greetings[randomIndex],
          });
        }
      } 
      else{
        // 如果this.messages中第二个元素是开场白，则移除
        if (this.messages.length > 1 && this.messages[1].role === 'assistant') {
          this.messages.splice(1, 1);
        }
      }
    },
    browseJsonFile() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,.png';          // 关键：多给一个 png
      input.onchange = (event) => {
        const file = event.target.files[0];
        if (!file) return;
        if (file.name.toLowerCase().endsWith('.png')) {
          this.handlePngAsJson(file);        // 新增分支
        } else {
          this.handleFileUpload(file);       // 原 JSON 分支
        }
      };
      input.click();
    },

    handleJsonDrop(event) {
      const file = event.dataTransfer.files[0];
      if (!file) return;
      const isPng = file.type === 'image/png' ||
                    file.name.toLowerCase().endsWith('.png');
      const isJson = file.type === 'application/json' ||
                    file.name.toLowerCase().endsWith('.json');

      if (isPng) {
        this.handlePngAsJson(file);
      } else if (isJson) {
        this.handleFileUpload(file);
      } else {
        showNotification('Please upload a valid JSON or PNG character card.', 'error');
      }
    },

    async handlePngAsJson(file) {
      // 1. 把 PNG 当成普通图片先上传，拿外链
      const formData = new FormData();
      formData.append('files', file);   // 字段名跟 /load_file 接口保持一致

      let imageUrl;
      try {
        const up = await fetch('/load_file', { method: 'POST', body: formData });
        if (!up.ok) throw new Error('upload failed');
        const res = await up.json();
        if (!res.success || !res.fileLinks || !res.fileLinks[0])
          throw new Error('no url returned');
        imageUrl = res.fileLinks[0].path;          // 后端返回的完整 URL
        // 可选：把这张图片也塞进 imageFiles 列表，保持界面同步
        this.imageFiles = [...this.imageFiles, ...res.imageFiles];
      } catch (e) {
        console.error(e);
        showNotification('PNG upload failed', 'error');
        return;
      }

      // 2. 拆包拿 JSON
      const jsonText = await this.extractJsonFromPng(file);
      if (!jsonText) return;   // 通知已在内部弹过

      // 3. 把 avatar 换成刚上传的 URL
      let jsonData;
      try {
        jsonData = JSON.parse(jsonText);
      } catch {
        showNotification('Invalid JSON inside PNG', 'error');
        return;
      }
      // 兼容 V2/V3
      const target = jsonData.data || jsonData;
      target.avatar = imageUrl;   // 直接覆盖

      // 4. 走现有逻辑回填表单
      this.importMemoryData(jsonData);
      this.jsonFile = file;       // 保留文件对象，方便移除按钮
      showNotification('Character card imported from PNG', 'success');
    },

    async extractJsonFromPng(file) {
      const buffer = await file.arrayBuffer();
      const png = new Uint8Array(buffer);
      const sign = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
      if (!sign.every((b, i) => b === png[i])) {
        showNotification('Not a valid PNG file', 'error');
        return null;
      }

      let pos = 8;
      const view = new DataView(buffer);
      let jsonText = null;

      while (pos < png.length) {
        const len  = view.getUint32(pos);
        const type = String.fromCharCode(...png.slice(pos + 4, pos + 8));
        const start = pos + 8;
        const end   = start + len;

        if (type === 'tEXt') {
          const data = png.slice(start, end);
          const zero = data.indexOf(0);
          if (zero > 0) {
            const key = new TextDecoder().decode(data.slice(0, zero)).toLowerCase();
            if (key === 'chara' || key === 'ccv3') {
              const b64 = new TextDecoder().decode(data.slice(zero + 1));
              try {
                jsonText = new TextDecoder().decode(
                  Uint8Array.from(atob(b64), c => c.charCodeAt(0))
                );
                if (key === 'ccv3') break;
              } catch {}
            }
          }
        }
        if (type === 'IEND') break;
        pos = end + 4; // 跳过 CRC
      }

      if (!jsonText) showNotification('No character data found in PNG', 'error');
      return jsonText;
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

    importMemoryData(jsonData) {
      // 兼容 V2/V3：统一抽出 data
      const data = jsonData.data || jsonData;

      this.newMemory = {
        ...this.newMemory,                      // 保持 providerId 等旧字段
        name: data.name || '',
        description: data.description || '',
        avatar: data.avatar || '',
        personality: data.personality || '',
        mesExample: data.mes_example || '',
        systemPrompt: data.system_prompt || '',
        firstMes: data.first_mes || '',
        alternateGreetings: Array.isArray(data.alternate_greetings)
          ? data.alternate_greetings
          : [''],
        characterBook:
          Array.isArray(data.character_book?.entries) &&
          data.character_book.entries.length
            ? data.character_book.entries.map(e => ({
                keysRaw: (e.keys || []).join('\n'),
                content: e.content || ''
              }))
            : [{ keysRaw: '', content: '' }]
      };
    },
















    // 修改：统一的语音开始处理


    async handleFrameProcessed(frame) {
      if (!frame || !(frame instanceof Float32Array)) return;

      // 🌟 修复点：增加 WebSocket 状态检查，避免发送报错
      if (!this.asrWs || this.asrWs.readyState !== WebSocket.OPEN) {
        return;
      }

      try {
        const int16Pcm = new Int16Array(frame.length);
        for (let i = 0; i < frame.length; i++) {
          int16Pcm[i] = Math.max(-32768, Math.min(32767, frame[i] * 32767));
        }

        const base64Audio = btoa(
          String.fromCharCode(...new Uint8Array(int16Pcm.buffer))
        );

        this.asrWs.send(JSON.stringify({
          type: 'audio_stream',
          id: this.currentTranscriptionId,
          audio: base64Audio,
          format: 'pcm',
          sample_rate: 16000 
        }));
      } catch (e) {
        console.error('Frame processing error:', e);
      }
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
  // 启动直播监听
  async startLive() {
    if (!this.isLiveConfigValid || this.isLiveRunning || this.isLiveStarting) {
      return;
    }

    this.isLiveStarting = true;
    
    try {
      // 发送启动请求到FastAPI后端
      const response = await fetch('/api/live/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          config: this.liveConfig
        })
      });

      const result = await response.json();
      
      if (result.success) {
        this.isLiveRunning = true;
        this.shouldReconnectWs = true; // 启动时允许重连
        this.connectLiveWebSocket();
        this.startDanmuProcessor(); // 启动弹幕处理器
        showNotification(result.message || this.t('live_started_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_start_live'), 'error');
      }
    } catch (error) {
      console.error('启动直播监听失败:', error);
      showNotification(this.t('failed_to_start_live'), 'error');
    } finally {
      this.isLiveStarting = false;
    }
  },

  // 停止直播监听
  async stopLive() {
    if (!this.isLiveRunning || this.isLiveStopping) {
      return;
    }

    this.isLiveStopping = true;
    
    try {
      // 先设置状态，阻止WebSocket重连
      this.shouldReconnectWs = false;
      this.isLiveRunning = false;
      
      // 停止弹幕处理器
      this.stopDanmuProcessor();
      
      // 关闭WebSocket连接
      this.disconnectLiveWebSocket();
      
      // 发送停止请求到FastAPI后端
      const response = await fetch('/api/live/stop', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });

      const result = await response.json();
      
      if (result.success) {
        this.danmu = []; // 清空弹幕数据
        showNotification(result.message || this.t('live_stopped_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_stop_live'), 'error');
        // 如果后端停止失败，恢复状态
        this.isLiveRunning = true;
        this.shouldReconnectWs = true;
        this.startDanmuProcessor(); // 重新启动弹幕处理器
      }
    } catch (error) {
      console.error('停止直播监听失败:', error);
      showNotification(this.t('failed_to_stop_live'), 'error');
      // 如果出错，恢复状态
      this.isLiveRunning = true;
      this.shouldReconnectWs = true;
      this.startDanmuProcessor(); // 重新启动弹幕处理器
    } finally {
      this.isLiveStopping = false;
    }
  },

  // 重载直播配置
  async reloadLiveConfig() {
    if (!this.isLiveRunning || this.isLiveReloading) {
      return;
    }

    this.isLiveReloading = true;
    
    try {
      const response = await fetch('/api/live/reload', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          config: this.liveConfig
        })
      });

      const result = await response.json();
      
      if (result.success) {
        // 重新连接WebSocket
        this.shouldReconnectWs = false; // 先阻止重连
        this.disconnectLiveWebSocket();
        
        setTimeout(() => {
          this.shouldReconnectWs = true; // 重新允许重连
          this.connectLiveWebSocket();
        }, 1000);
        
        showNotification(result.message || this.t('live_config_reloaded_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_reload_live_config'), 'error');
      }
    } catch (error) {
      console.error('重载直播配置失败:', error);
      showNotification(this.t('failed_to_reload_live_config'), 'error');
    } finally {
      this.isLiveReloading = false;
    }
  },

  // 启动弹幕处理器
  startDanmuProcessor() {
    console.log('启动弹幕处理器');
    
    // 如果已经有定时器在运行，先清除
    if (this.danmuProcessTimer) {
      clearInterval(this.danmuProcessTimer);
    }
    
    // 每秒检查一次弹幕队列
    this.danmuProcessTimer = setInterval(async () => {
      await this.processDanmuQueue();
    }, 1000);
  },

  // 停止弹幕处理器
  stopDanmuProcessor() {
    console.log('停止弹幕处理器');
    
    if (this.danmuProcessTimer) {
      clearInterval(this.danmuProcessTimer);
      this.danmuProcessTimer = null;
    }
    
    this.isProcessingDanmu = false;
  },

// 1. 拷贝 URL 方法
  copyDanmakuOverlayEndpoint() {
    const url = this.partyURL + '/danmaku_overlay';
    navigator.clipboard.writeText(url).then(() => {
      if(typeof showNotification === 'function') showNotification(this.t('copySuccess') || 'Copied!', 'success');
    }).catch(() => {
      if(typeof showNotification === 'function') showNotification('Copy failed', 'error');
    });
  },

copySubtitleOverlayEndpoint(){
  const url =  this.partyURL + '/subtitle_overlay';
  navigator.clipboard.writeText(url).then(() => {
    if(typeof showNotification === 'function') showNotification(this.t('copySuccess') || 'Copied!', 'success');
  }).catch(() => {
    if(typeof showNotification === 'function') showNotification('Copy failed', 'error');
  });
},

// 处理弹幕队列 - 新版
  async processDanmuQueue() {
    try {
      // 基础检查 (保持不变)
      if (!this.isLiveRunning || this.danmu.length === 0 || this.isTyping || 
          (this.TTSrunning && this.ttsSettings.enabled) || this.isProcessingDanmu) {
        return;
      }

      this.isProcessingDanmu = true;
      const oldestDanmu = this.danmu[this.danmu.length - 1];
      
      if (oldestDanmu && oldestDanmu.content) {
        if (this.lastProcessedContent === oldestDanmu.content) {
            this.danmu.pop();
            this.isProcessingDanmu = false;
            return;
        }

        console.log('开始处理弹幕:', oldestDanmu.content);
        this.lastProcessedContent = oldestDanmu.content;
        
        // 【关键修复点 1】：将弹幕存入临时变量，准备注入 TTS 队列
        this.pendingDanmakuToRead = oldestDanmu.content;

        // 设置 LLM 的输入
        this.userInput = oldestDanmu.content;
        
        // 触发 OBS 弹窗显示 (调用后端 API)
        try {
            fetch('/api/overlay/danmaku', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(oldestDanmu)
            }).catch(()=>{});
        } catch(e) {}

        // 发送消息，启动 AI 生成流程
        await this.sendMessage();
        
        this.danmu.pop(); 
      }
    } catch (error) {
      console.error('处理弹幕出错:', error);
      this.danmu.pop(); 
    } finally {
      this.isProcessingDanmu = false;
    }
  },
  // 连接WebSocket
  connectLiveWebSocket() {
    try {
      // 根据当前协议选择ws或wss
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/live/danmu`;
      
      this.bilibiliWs = new WebSocket(wsUrl);
      
      this.bilibiliWs.onopen = (event) => {
        console.log('WebSocket连接已建立');
      };
      
      this.bilibiliWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleDanmuMessage(data);
        } catch (error) {
          console.error('解析WebSocket消息失败:', error);
        }
      };
      
      this.bilibiliWs.onclose = (event) => {
        console.log('WebSocket连接已关闭');
        
        // 只有在允许重连且直播还在运行时才重连
        if (this.shouldReconnectWs && this.isLiveRunning) {
          console.log('准备重连WebSocket...');
          setTimeout(() => {
            // 再次检查状态，确保仍然需要重连
            if (this.shouldReconnectWs && this.isLiveRunning) {
              console.log('开始重连WebSocket');
              this.connectLiveWebSocket();
            } else {
              console.log('取消重连WebSocket');
            }
          }, 3000);
        } else {
          console.log('不需要重连WebSocket');
        }
      };
      
      this.bilibiliWs.onerror = (error) => {
        console.error('WebSocket连接错误:', error);
      };
    } catch (error) {
      console.error('创建WebSocket连接失败:', error);
    }
  },

  // 断开WebSocket连接
  disconnectLiveWebSocket() {
    console.log('断开WebSocket连接');
    
    if (this.bilibiliWs) {
      // 先设置为null，避免onclose事件中的重连逻辑
      const ws = this.bilibiliWs;
      this.bilibiliWs = null;
      
      // 然后关闭连接
      ws.close();
    }
  },

  async checkLiveStatus() {
    try {
      const response = await fetch('/api/live/status');
      const result = await response.json();
      
      // 更新状态
      this.isLiveRunning = result.is_running;

      // 关键点：如果后台正在运行，前端刷新后需要重新挂载 WebSocket 和处理器
      if (this.isLiveRunning) {
        console.log('检测到后台直播监听正在运行，正在恢复连接...');
        this.shouldReconnectWs = true;
        
        // 重新连接 WebSocket 接收弹幕
        this.connectLiveWebSocket();
        
        // 重新启动弹幕队列处理定时器
        this.startDanmuProcessor();
      }
    } catch (error) {
      console.error('检查直播状态失败:', error);
    }
  },

  // 处理弹幕消息
  handleDanmuMessage(data) {
    if (data.type !== 'message') {
      if (data.type === 'error') showNotification(data.message, 'error');
      return;
    }

    // --- 1. ID 级去重 ---
    if (data.id) {
      if (this.receivedMsgIds.has(data.id)) return;
      this.receivedMsgIds.add(data.id);
      if (this.receivedMsgIds.size > 500) {
        const firstVal = this.receivedMsgIds.values().next().value;
        this.receivedMsgIds.delete(firstVal);
      }
    }

    // --- 2. 统一定义消息属性 ---
    const danmuType = data.danmu_type; // danmaku, super_chat, gift, buy_guard, enter_room, follow, like
    const isDanmaku = (danmuType === "danmaku" || danmuType === "super_chat");
    const isPaid = (danmuType === "gift" || danmuType === "buy_guard" || danmuType === "super_chat");
    const isInteraction = (danmuType === "enter_room" || danmuType === "follow" || danmuType === "like");

    // --- 3. 模式过滤判断 ---
    let modePass = false;
    const mode = this.liveConfig.filterMode || 'all';

    if (mode === 'all') {
      modePass = true;
    } else if (mode === 'danmaku_paid') {
      modePass = (isDanmaku || isPaid);
    } else if (mode === 'danmaku_only') {
      modePass = isDanmaku;
    }

    if (!modePass) return;

    // --- 4. 唤醒词校验 (仅针对文本类消息) ---
    const wakeStr = this.liveConfig.wakeWord || "";
    const wakeKeywords = wakeStr.split(/[\r\n]+/).map(k => k.trim()).filter(k => k.length > 0);
    
    const isMatchWakeWord = (text) => {
      if (wakeKeywords.length === 0) return true;
      return wakeKeywords.some(keyword => text.includes(keyword));
    };

    let shouldAdd = false;
    if (isDanmaku) {
      // 弹幕和 SC 必须匹配唤醒词
      if (isMatchWakeWord(data.content)) shouldAdd = true;
    } else {
      // 礼物、舰长、关注等互动，直接放行 (不被唤醒词拦截)
      shouldAdd = true;
    }

    // --- 5. 入队 ---
    if (shouldAdd) {
      const danmuItem = {
        id: data.id,
        content: data.content,
        type: danmuType,
        platform: data.platform || 'bilibili',
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false })
      };

      // 连续重复内容防刷屏
      if (this.danmu.length > 0 && this.danmu[0].content === danmuItem.content) return;

      this.danmu.unshift(danmuItem);
      if (this.danmu.length > this.liveConfig.danmakuQueueLimit) {
        this.danmu = this.danmu.slice(0, this.liveConfig.danmakuQueueLimit);
      }
    }
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

/* 生命周期：读取场景列表 */
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
/* 选择场景后实时切换背景 */
async handleGaussSceneChange(sceneId) {
  // 与 VRM 模型切换类似：把场景 id 写进 VRMConfig
  this.VRMConfig.selectedGaussSceneId = sceneId;

  this.autoSaveSettings();
},

/* 上传区域点击 */
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

/* 拖拽上传 */
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

/* 移除待上传文件 */
removeNewGaussScene() {
  this.newGaussScene = { name: '', displayName: '' };
},

/* 真正上传 */
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

/* 取消上传 */
cancelGaussSceneUpload() {
  this.showGaussSceneDialog = false;
  this.removeNewGaussScene();
},

/* 删除用户场景 */
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


  async confirmClearAll() {
    await this.clearAllHistoryRecords();
  },

  async keepLastWeek() {
    try {
      await this.$confirm(this.t('confirmKeepLastWeek'), this.t('warning'), {
        confirmButtonText: this.t('confirm'),
        cancelButtonText: this.t('cancel'),
        type: 'warning'
      });

      const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
      this.conversations = this.conversations.filter(conv => 
        conv.timestamp && conv.timestamp >= oneWeekAgo
      );
      if (this.conversations.length === 0){
        this.conversationId = null; // 清空当前对话ID
      }
      
      await this.saveConversations();
    } catch (error) {
      // 用户取消操作
    }
  },
    /* ===============  朗读主流程  =============== */
toggleRead() {
  if (this.isReadRunning) {
    if (this.isReadPaused) {
      this.resumeRead();
    } else {
      this.pauseRead();
    }
  } else {
    this.startRead();
  }
},

// 修改后的startRead方法
async startRead() {
  if (!this.readConfig.longText.trim()) return;
  
  this.stopSegmentTTS();
  this.readState.currentChunk = 0;
  this.isReadStarting = true;
  this.isReadRunning  = true;
  this.isReadPaused   = false;  // 重置暂停状态
  this.isReadStopping = false;

  /* 清空上一次的残留 */
  this.readState.ttsChunks  = [];
  this.readState.audioChunks = [];
  this.readState.currentChunk = 0;
  this.readState.isPlaying = false;
  this.readState.chunks_voice = [];
  this.cur_voice = 'default';
  
  /* 重置音频计数状态 */
  this.audioChunksCount = 0;
  this.totalChunksCount = 0;

  /* 分段处理逻辑（保持原有） */
  const {
    chunks,
    chunks_voice,
    remaining,
    remaining_voice
  } = this.splitTTSBuffer(this.readConfig.longText);

  if (remaining) {
    chunks.push(remaining);
    chunks_voice.push(remaining_voice);
  }

  /* 去标签 + 去空白并同步删除 */
  const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());
  const finalChunks = [];
  const finalChunksVoice = [];

  cleanedChunks.forEach((txt, idx) => {
    if (txt) {
      finalChunks.push(txt);
      finalChunksVoice.push(chunks_voice[idx]);
    }
  });

  if (!finalChunks.length) {
    this.isReadRunning  = false;
    this.isReadStarting = false;
    return;
  }

  this.readState.ttsChunks   = finalChunks;
  this.readState.chunks_voice = finalChunksVoice;
  this.totalChunksCount = finalChunks.length;

  /* 通知 VRM 开始朗读 */
  this.sendTTSStatusToVRM('ttsStarted', {
    totalChunks: this.readState.ttsChunks.length
  });

  this.isReadStarting = false;

  /* 并发 TTS */
  this.isAudioSynthesizing = true;
  await this.startReadTTSProcess();
},

// 新增：暂停朗读
pauseRead() {
  if (!this.isReadRunning || this.isReadPaused) return;
  
  this.isReadPaused = true;
  
  // 暂停当前音频
  if (this.currentReadAudio) {
    this.currentReadAudio.pause();
  }
  
  // 通知 VRM 暂停
  this.sendTTSStatusToVRM('pauseSpeaking', {});
},

// 新增：恢复朗读
resumeRead() {
  if (!this.isReadRunning || !this.isReadPaused) return;
  
  this.isReadPaused = false;
  
  // 恢复当前音频播放
  if (this.currentReadAudio) {
    this.currentReadAudio.play().catch(console.error);
  }
  
  // 通知 VRM 恢复
  this.sendTTSStatusToVRM('resumeSpeaking', {});
  
  // 尝试继续播放后续音频
  this.checkReadAudioPlayback();
},

    // 修改 processReadTTSChunk 方法
    async processReadTTSChunk(index) {
      try {
        const chunk = this.readState.ttsChunks[index];
        const voice = this.readState.chunks_voice[index];
        const cachedAudio = this.readState.audioChunks[index];

        // 检查缓存是否命中
        if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
          this.cur_audioDatas[index] = cachedAudio.base64;
        }
        else{
          /* —— 与对话版完全一致的文本清洗 —— */
          let chunk_text = chunk;
          let  chunk_expressions = [];
          if (chunk.indexOf('<') !== -1) {
              const tagReg = /<[^>]+>/g;
              chunk_expressions = (chunk.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
              chunk_text = chunk.replace(tagReg, '').trim();
          }

          const res = await fetch('/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ttsSettings: this.ttsSettings,
              text: chunk_text,
              index,
              voice
            })
          });

          if (!res.ok) throw new Error('TTS failed');

          const blob = await res.blob();
          const url  = URL.createObjectURL(blob);

          /* Base64 给 VRM */
          const base64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload  = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          });
          this.cur_audioDatas[index] = `data:${blob.type};base64,${base64}`;
          /* 缓存两样东西 */
          this.readState.audioChunks[index] = {
            url,                       // 本地播放用
            expressions: chunk_expressions,
            base64: this.cur_audioDatas[index], // VRM 播放用
            text: chunk_text,
            index,
            voice
          };
        }

        /* 新增: 增加已生成片段计数 */
        this.audioChunksCount++;
        
        /* 新增: 检查是否全部合成完成 */
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }

        /* 立刻尝试播放 */
        this.checkReadAudioPlayback();
      } catch (e) {
        console.error(`Read TTS chunk ${index} error`, e);
        // chunk_text/chunk_expressions 声明在 try 的 else 块内，catch 不可见：
        // 错误槽位直接用原始 chunk 回填（url:null 不会被缓存命中）
        this.readState.audioChunks[index] = { url: null, expressions: [], text: this.readState.ttsChunks[index] ?? "", index };
        this.cur_audioDatas[index] = null;
        
        /* 新增: 处理错误时也增加计数 */
        this.audioChunksCount++;
        
        /* 新增: 检查是否全部合成完成 */
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
        
        this.checkReadAudioPlayback();
      }
    },

    async ClickToListen(SampleText,voice='default') {
      if (!SampleText) {
        SampleText ='super agent party链接一切！'
      }

    try {
      // 创建副本，避免直接修改 this.ttsSettings
      let Settings = { ...this.ttsSettings };

      if (this.showAddTTSDialog) {
        Settings = { ...Settings, ...this.newTTSConfig };
      } else if (voice !== 'default' && this.ttsSettings.newtts && this.ttsSettings.newtts[voice]) {
        // 从角色语音卡片调用：合并角色配置
        Settings = { ...Settings, ...this.ttsSettings.newtts[voice] };
      }

      // ★ 关键修复：附带 modelProviders，供后端查找 API Key
      // 后端逻辑：如果角色配置缺少api_key但有selectedProvider，会从这里查找
      if (this.modelProviders && Array.isArray(this.modelProviders)) {
        Settings.modelProviders = this.modelProviders;
      }

        const res = await fetch('/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ttsSettings: Settings,
            text: SampleText,
            index: 0,          // 随便给个 index，后端不关心
            voice: voice || 'default'
          })
        });
        if (!res.ok) throw new Error('TTS failed');

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        /* 直接播放 */
        const audio = new Audio(url);
        audio.play().catch(console.error);

        /* 播放完清掉内存 */
        audio.onended = () => URL.revokeObjectURL(url);
      } catch (e) {
        console.error('ClickToListen error', e);
      }
    },

    // 添加下载方法
    downloadAudio() {
      // 确保有音频片段可以下载
      if (this.audioChunksCount === 0) {
        showNotification(this.t('noAudioToDownload'));
        return;
      }

      // 检查是否有有效的音频片段
      const validChunks = this.readState.audioChunks.filter(chunk => chunk && chunk.url);
      if (validChunks.length === 0) {
        showNotification(this.t('noValidAudioChunks'));
        return;
      }

      try {
        // 创建合并的音频文件，只包含有效的片段
        this.createCombinedAudio(validChunks, this.getAudioMimeType());
      } catch (error) {
        console.error('Audio download failed:', error);
        showNotification(this.t('audioDownloadFailed'));
      }
    },



    // 1. 修改 downloadAudio：不再需要传入 MIME 类型，交给内部探测
    downloadAudio() {
      if (this.audioChunksCount === 0) {
        showNotification(this.t('noAudioToDownload'));
        return;
      }

      // 过滤无效片段
      const validChunks = this.readState.audioChunks.filter(chunk => chunk && chunk.url);
      if (validChunks.length === 0) {
        showNotification(this.t('noValidAudioChunks'));
        return;
      }

      try {
        // 直接调用，不需要传参，函数内部会自己识别格式
        this.createCombinedAudio(validChunks);
      } catch (error) {
        console.error('Audio download failed:', error);
        showNotification(this.t('audioDownloadFailed'));
      }
    },

    // 2. 重写 createCombinedAudio：核心修改是“自动识别真实格式”
    async createCombinedAudio(chunks) {
      if (!chunks || chunks.length === 0) return;

      showNotification(this.t('audioProcessingStarted') || '正在处理音频...');

      try {
        // ================= 关键步骤：探测真实格式 =================
        // 先 Fetch 第一个片段，查看 HTTP 头或 Blob 类型，以此为准
        const firstResponse = await fetch(chunks[0].url);
        const firstBlob = await firstResponse.blob();
        
        // 获取真实的 MIME (例如: "audio/ogg; codecs=opus" -> "audio/ogg")
        const realMimeType = firstBlob.type.split(';')[0]; 
        
        console.log('Detected Real Audio Format:', realMimeType);

        // 根据真实 MIME 推导后缀名和处理逻辑
        let extension = 'mp3'; // 默认
        let isWav = false;

        if (realMimeType.includes('wav')) {
          extension = 'wav';
          isWav = true;
        } else if (realMimeType.includes('ogg')) {
          extension = 'ogg';
        } else if (realMimeType.includes('aac')) {
          extension = 'aac';
        } else if (realMimeType.includes('flac')) {
          extension = 'flac';
        } else if (realMimeType.includes('webm')) {
          extension = 'webm';
        } else if (realMimeType.includes('mp4') || realMimeType.includes('m4a')) {
          extension = 'm4a';
        }

        // ================= 开始获取所有数据 =================
        // 重用第一个 Blob，减少一次请求
        const firstBuffer = await firstBlob.arrayBuffer();
        
        // 并发获取剩余片段
        const restPromises = chunks.slice(1).map(async (chunk) => {
          const response = await fetch(chunk.url);
          return response.arrayBuffer();
        });
        
        const restBuffers = await Promise.all(restPromises);
        const allBuffers = [firstBuffer, ...restBuffers];

        // ================= 根据真实格式合并 =================
        let combinedBuffer;

        if (isWav) {
          // WAV 专用处理：去头
          combinedBuffer = this.mergeWavBuffers(allBuffers);
        } else {
          // 其他格式（MP3, OGG等）：直接拼接
          // 注意：OGG 直接拼接在浏览器中播放可能只能听第一句（Chained Ogg），
          // 但下载后用本地播放器（VLC/PotPlayer）是完整的。这是无损拼接的特性。
          combinedBuffer = this.mergeGeneralBuffers(allBuffers);
        }

        // ================= 下载文件 =================
        const blob = new Blob([combinedBuffer], { type: realMimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        
        a.href = url;
        // 使用探测到的真实后缀名
        a.download = `tts-merged-${timestamp}.${extension}`; 
        
        document.body.appendChild(a);
        a.click();
        
        // 清理
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 100);
        
        showNotification(this.t('audioDownloadStarted'));

      } catch (error) {
        console.error('Audio merging failed:', error);
        showNotification(this.t('audioMergeFailed'));
      }
    },

    // --- 辅助函数保持不变 ---
    
    // 通用拼接 (MP3/OGG/AAC)
    mergeGeneralBuffers(buffers) {
      const totalLength = buffers.reduce((acc, buffer) => acc + buffer.byteLength, 0);
      const result = new Uint8Array(totalLength);
      
      let offset = 0;
      buffers.forEach(buffer => {
        result.set(new Uint8Array(buffer), offset);
        offset += buffer.byteLength;
      });
      
      return result;
    },

    // WAV 专用拼接
    mergeWavBuffers(buffers) {
      if (buffers.length === 0) return new Uint8Array(0);
      if (buffers.length === 1) return new Uint8Array(buffers[0]);

      const HEADER_SIZE = 44; 
      let totalDataLength = 0;
      
      buffers.forEach((buffer, index) => {
        if (index === 0) totalDataLength += buffer.byteLength;
        else totalDataLength += Math.max(0, buffer.byteLength - HEADER_SIZE);
      });

      const result = new Uint8Array(totalDataLength);
      
      // 写入第一个文件（含头）
      result.set(new Uint8Array(buffers[0]), 0);
      let offset = buffers[0].byteLength;

      // 写入后续文件（去头）
      for (let i = 1; i < buffers.length; i++) {
        const buffer = new Uint8Array(buffers[i]);
        if (buffer.byteLength > HEADER_SIZE) {
            const dataChunk = buffer.subarray(HEADER_SIZE);
            result.set(dataChunk, offset);
            offset += dataChunk.byteLength;
        }
      }

      // 修正 WAV 头
      const view = new DataView(result.buffer);
      view.setUint32(4, result.byteLength - 8, true); 
      view.setUint32(40, result.byteLength - HEADER_SIZE, true);

      return result;
    },


// 修改 stopRead 方法
stopRead() {
  if (!this.isReadRunning) return;
  
  this.isReadStopping = true;
  this.isReadRunning  = false;
  this.isReadPaused   = false;  // 重置暂停状态
  this.readState.isPlaying = false;

  /* 停掉当前音频 */
  if (this.currentReadAudio) {
    this.currentReadAudio.pause();
    this.currentReadAudio = null;
  }
  
  this.sendTTSStatusToVRM('stopSpeaking', {});
  
  /* 重置音频计数状态 */
  this.isAudioSynthesizing = false;
  this.audioChunksCount = 0;
  this.totalChunksCount = 0;
  
  this.isReadStopping = false;
},

// 修改 stopTTSActivities 方法
stopTTSActivities() {
  // 停止朗读流程
  if (this.isReadRunning) {
    this.isReadStopping = true;
    this.isReadRunning = false;
    this.isReadPaused = false;  // 重置暂停状态
    this.readState.isPlaying = false;
    
    /* 停掉当前音频 */
    if (this.currentReadAudio) {
      this.currentReadAudio.pause();
      this.currentReadAudio = null;
    }
    this.sendTTSStatusToVRM('stopSpeaking', {});
    
    /* 重置音频计数状态 */
    this.isAudioSynthesizing = false;
    
    this.isReadStopping = false;
  }
  
  // 停止音频转换流程（保持原有）
  if (this.isConvertingAudio) {
    this.isConvertStopping = true;
    this.isConvertingAudio = false;
    this.isAudioSynthesizing = false;
    showNotification(this.t('audioConversionStopped'));
    this.isConvertStopping = false;
  }
},
  /* ===============  复用 / 微调 TTS 流程  =============== */
  async startReadTTSProcess() {
    let max_concurrency = this.ttsSettings.maxConcurrency || 1;
    let nextIndex = 0;

    /* 与对话版唯一区别：readState 代替 messages[last] */
    while (this.isReadRunning) {
      while (
        this.readState.ttsQueue.size < max_concurrency &&
        nextIndex < this.readState.ttsChunks.length
      ) {
        if (!this.isReadRunning) break;

        const index = nextIndex++;
        this.readState.ttsQueue.add(index);

        this.processReadTTSChunk(index).finally(() => {
          this.readState.ttsQueue.delete(index);
        });

        /* 首包加速 */
        if (index === 0) await new Promise(r => setTimeout(r, 800));
      }
      await new Promise(r => setTimeout(r, 10));
    }
    console.log('Read TTS queue processing completed');
  },

  // 修改后的 convertAudioOnly 方法
  async convertAudioOnly() {
    if (!this.readConfig.longText.trim()) {
      showNotification(this.t('noTextToConvert'));
      return;
    }

    this.isConvertingAudio = true;
    
    try {
      // 1. 清空上一次的残留
      this.readState.ttsChunks = [];
      this.readState.audioChunks = [];
      this.readState.chunks_voice = [];
      this.audioChunksCount = 0;
      this.totalChunksCount = 0;

  /* 2. 分段 */
      const {
        chunks,
        chunks_voice,
        remaining,
        remaining_voice
      } = this.splitTTSBuffer(this.readConfig.longText);

      // 追加 remaining
      if (remaining) {
        chunks.push(remaining);
        chunks_voice.push(remaining_voice);
      }

      /* ================= 新增：去标签 + 去空白并同步删除 ================= */
      // 1. 去 HTML 标签
      const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());

      // 2. 过滤空白并同步删除 chunks_voice 对应项
      const finalChunks       = [];
      const finalChunksVoice  = [];

      cleanedChunks.forEach((txt, idx) => {
        if (txt) {                      // 非空才保留
          finalChunks.push(txt);
          finalChunksVoice.push(chunks_voice[idx]);
        }
      });

      // 3. 覆盖原来的数组
      chunks.length       = 0;
      chunks_voice.length = 0;
      chunks.push(...finalChunks);
      chunks_voice.push(...finalChunksVoice);
      /* ================================================================ */
      
      if (!chunks.length) {
        this.isConvertingAudio = false;
        return;
      }
      
      this.readState.ttsChunks = chunks;
      this.readState.chunks_voice = chunks_voice;
      this.totalChunksCount = chunks.length;

      // 3. 开始转换（复用 processReadTTSChunk 但禁用播放）
      this.isAudioSynthesizing = true;
      
      // 使用并发控制处理所有片段
      const maxConcurrency = this.ttsSettings.maxConcurrency || 1;
      let nextIndex = 0;
      const activeTasks = new Set();
      
      // 使用 Promise 来等待所有任务完成
      await new Promise((resolve) => {
        const processNext = async () => {
          // 检查是否被用户停止
          if (!this.isConvertingAudio) {
            resolve();
            return;
          }
          
          // 所有任务完成
          if (nextIndex >= chunks.length && activeTasks.size === 0) {
            resolve();
            return;
          }
          
          // 添加新任务（如果有空位且还有任务）
          while (activeTasks.size < maxConcurrency && nextIndex < chunks.length) {
            const index = nextIndex++;
            activeTasks.add(index);
            
            this.processTTSChunkWithoutPlayback(index)
              .finally(() => {
                activeTasks.delete(index);
                processNext(); // 检查是否可添加新任务
              });
          }
        };
        
        processNext();
      });
      
      // 只有在没有被停止的情况下才显示完成通知
      if (this.isConvertingAudio) {
        this.isAudioSynthesizing = false;
        showNotification(this.t('audioConversionCompleted', { count: chunks.length }));
      }
      
    } catch (error) {
      console.error('Audio conversion failed:', error);
      showNotification(this.t('audioConversionFailed'));
    } finally {
      this.isConvertingAudio = false;
    }
  },

    // 处理TTS片段但不播放
    async processTTSChunkWithoutPlayback(index) {
      const chunk = this.readState.ttsChunks[index];
      const voice = this.readState.chunks_voice[index];
      console.log(`Processing TTS chunk ${index}`);
      // 文本清洗
      let chunk_text = chunk;
      let chunk_expressions =[];
      if (chunk.indexOf('<') !== -1) {
        const tagReg = /<[^>]+>/g;
        chunk_expressions = (chunk.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
        chunk_text = chunk.replace(tagReg, '').trim(); // 把标签从正文里删掉
      }

      try {
        const res = await fetch('/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ttsSettings: this.ttsSettings,
            text: chunk_text,
            index,
            voice
          })
        });

        if (!res.ok) throw new Error('TTS failed');

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        /* Base64 给 VRM */
        const base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload  = () => resolve(reader.result.split(',')[1]);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
        this.cur_audioDatas[index] = `data:${blob.type};base64,${base64}`;
        /* 缓存两样东西 */
        this.readState.audioChunks[index] = {
          url,                       // 本地播放用
          expressions: chunk_expressions,
          base64: this.cur_audioDatas[index], // VRM 播放用
          text: chunk_text,
          index,
          voice
        };
        // 增加计数
        this.audioChunksCount++;
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
      } catch (e) {
        console.error(`TTS chunk ${index} error`, e);
        this.readState.audioChunks[index] = { 
          url: null, 
          expressions: chunk_expressions, 
          text: chunk_text, 
          index 
        };
        
        // 错误时也增加计数
        this.audioChunksCount++;
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
      }
    },

  /* ===============  播放监控  =============== */
  async startReadAudioPlayProcess() {
    /* 与对话版的 startAudioPlayProcess 完全一致，只是把 readState 替换掉 */
    this.readState.currentChunk = 0;
    this.readState.isPlaying   = false;
    this.audioPlayQueue = [];
  },

  async checkReadAudioPlayback() {
    if (this.isReadPaused) return;
    if (!this.isReadRunning || this.readState.isPlaying) return;

    const curIdx = this.readState.currentChunk;
    const total  = this.readState.ttsChunks.length;
    if (curIdx >= total) {
      /* 全部读完 */
      console.log('All read audio chunks played');
      this.readState.currentChunk = 0;
      this.isReadRunning = false;
      this.cur_audioDatas = [];
      this.sendTTSStatusToVRM('allChunksCompleted', {});
      return;
    }

    const audioChunk = this.readState.audioChunks[curIdx];
    if (!audioChunk) return;

    /* 开始播放这一块 */
    this.readState.isPlaying = true;
    console.log(`Playing read audio chunk ${curIdx}`);
    this.scrollToCurrentChunk(curIdx);
    try {
      this.currentReadAudio = new Audio(audioChunk.url);
      this.currentReadAudio.volume = this.vrmOnline ? 0.0000001 : 1; // VRM在线时静音
      this.sendTTSStatusToVRM('startSpeaking', {
        audioDataUrl: this.cur_audioDatas[curIdx],
        chunkIndex: curIdx,
        totalChunks: total,
        text: audioChunk.text,
        expressions: audioChunk.expressions,
        voice: this.readState.chunks_voice[curIdx]
      });

      await new Promise(resolve => {
        this.currentReadAudio.onended = () => {
          this.sendTTSStatusToVRM('chunkEnded', { chunkIndex: curIdx });
          resolve();
        };
        this.currentReadAudio.onerror = resolve;
        this.currentReadAudio.play().catch(console.error);
      });
    } catch (e) {
      console.error('Read playback error', e);
    } finally {
      this.readState.currentChunk++;
      this.readState.isPlaying = false;
      setTimeout(() => this.checkReadAudioPlayback(), 0);
    }
  },
    async parseSelectedFile() {
        this.readConfig.longText = '';
        this.readConfig.longTextList = [];
        this.longTextListIndex = 0;
        // 根据选择的文件unique_filename在textFiles中查找对应的文件信息
        const selectedFile = this.textFiles.find(file => file.unique_filename === this.selectedFile);
        try {
          if (selectedFile) {
            // 构建完整的请求URL
            const url = `/get_file_content?file_url=${selectedFile.unique_filename}`;
            
            // 发送请求获取文件内容
            const response = await fetch(url, {
              method: 'GET',
              headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (selectedFile.unique_filename.toLowerCase().endsWith('.epub')){
              // data.content转成字典
              let data_json = JSON.parse(data.content);
              this.readConfig.longTextList = data_json.chapters || [];
              if (this.readConfig.longTextList.length > 0){
                this.longTextListIndex = 0;
                this.readConfig.longText = this.readConfig.longTextList[0];
              }else{
                this.readConfig.longText = data.content;
              }
            }else{
              this.readConfig.longText = data.content;
            }
            // 如果this.readConfig.longText太长了，就只取前100000个
            // if (this.readConfig.longText.length > 100000) {
            //   this.readConfig.longText = this.readConfig.longText.substring(0, 100000);
            //   showNotification(this.t('contentTooLong'))
            // }
          }
        }
        catch (error) {
          console.error('Error:', error);
        }
    },
  NextPage() {
    if (this.longTextListIndex < this.readConfig.longTextList.length - 1) {
      this.longTextListIndex++;
      this.readConfig.longText = this.readConfig.longTextList[this.longTextListIndex];
    }
  },
  PrevPage() {
    if (this.longTextListIndex > 0) {
      this.longTextListIndex--;
      this.readConfig.longText = this.readConfig.longTextList[this.longTextListIndex];
    }
  },
  openAddTTSDialog() {
    this.newTTSConfig = {
      name: '',
      enabled: true,
      SampleText: 'super agent party链接一切！',
      engine: 'moss',
      edgettsLanguage: 'zh-CN',
      edgettsGender: 'Female',
      edgettsVoice: 'XiaoyiNeural',
      edgettsRate: 1.0,
      gsvServer: "http://127.0.0.1:9880",
      gsvTextLang: 'zh',
      gsvRate: 1.0,
      gsvPromptLang: 'zh',
      gsvPromptText: '',
      gsvRefAudioPath: '',
      gsvAudioOptions: [],
      selectedProvider: null,
      vendor: "OpenAI",
      model: "",
      base_url: "",
      api_key: "",
      openaiVoice:"alloy",
      openaiSpeed: 1.0,
      customTTSserver: "http://127.0.0.1:9880",
      customTTSspeaker: "",
      customTTSspeed: 1.0,
      mossVoice: 'Junhao',
      mossSpeed: 1.0,
    };
    this.showAddTTSDialog = true;
  },

  saveNewTTSConfig() {
    const name = this.newTTSConfig.name;
    if (!name) return;

    this.ttsSettings.newtts[name] = { ...this.newTTSConfig };
    this.showAddTTSDialog = false;
    this.autoSaveSettings();
  },

  deleteTTS(name) {
    delete this.ttsSettings.newtts[name];
  },

  editTTS(name) {
    this.newTTSConfig = { ...this.ttsSettings.newtts[name] };
    this.showAddTTSDialog = true;
  },

  openAddAppearanceDialog() {
    this.newAppearanceConfig = {
      name: '',
      windowWidth: 540,
      windowHeight: 960,
      selectedModelId: 'alice', // 默认选择Alice模型
      selectedMotionIds: [],
    };
    this.showAddAppearanceDialog = true;
  },
  editAppearance(name) {
    this.newAppearanceConfig = { ...this.VRMConfig.newVRM[name] };
    this.showAddAppearanceDialog = true;
  },
  deleteAppearance(name) {
    delete this.VRMConfig.newVRM[name];
  },
  saveNewAppearanceConfig() {
    const name = this.newAppearanceConfig.name;
    if (!name) return;

    this.VRMConfig.newVRM[name] = { ...this.newAppearanceConfig };
    this.showAddAppearanceDialog = false;
    this.autoSaveSettings();
  },
  addBehavior() {
    // 深拷贝一份默认模板
    this.behaviorSettings.behaviorList.push(JSON.parse(JSON.stringify(this.newBehavior)));
    this.autoSaveSettings();
  },
  removeBehavior(idx) {
    this.behaviorSettings.behaviorList[idx].enabled = false;
    this.behaviorSettings.behaviorList.splice(idx, 1);
    showNotification(this.t('deleteBehaviorSuccess'))
    this.autoSaveSettings();
  },
  resetBehavior(idx) {
    this.behaviorSettings.behaviorList[idx] = JSON.parse(JSON.stringify(this.newBehavior));
    this.autoSaveSettings();
  },
  removeAllBehavior() {
    this.behaviorSettings.behaviorList.forEach((b) => {
      b.enabled = false;
    });
    this.behaviorSettings.behaviorList = [];
    showNotification(this.t('deleteAllBehaviorSuccess'))
    this.autoSaveSettings();
  },
    /* 真正执行行为 */
    runBehavior(b) {
      if (!b.enabled) return
      if (!this.noInputFlag){
        this.stopGenerate()
      }
      if (b.action.type === 'prompt' && b.action.prompt) {
        console.log('Prompt:', b.action.prompt)
        this.userInput= '[system]:'+ b.action.prompt
        // 这里把 prompt 发给你的模型即可，举例：
        this.sendMessage();
      }
      if (b.action.type === 'random' && b.action.random) {
        if(b.action.random.events.length > 0){
          if (b.action.random.type === 'random'){
            let randomEvent = b.action.random.events[Math.floor(Math.random() * b.action.random.events.length)];
            if(randomEvent){
              this.userInput= '[system]:'+randomEvent;
              // 这里把 prompt 发给你的模型即可，举例：
              this.sendMessage();
            }
          }else if( b.action.random.type === 'order'){
            if(b.action.random.orderIndex >= b.action.random.events.length){
              b.action.random.orderIndex = 0;
            }
            if(b.action.random.events[b.action.random.orderIndex]){
              let randomEvent = b.action.random.events[b.action.random.orderIndex];
              b.action.random.orderIndex += 1;
              if(randomEvent){
                this.userInput= '[system]:'+randomEvent;
                // 这里把 prompt 发给你的模型即可，举例：
                this.sendMessage();
              }
            }
          }
        }
      }
    },

    /* 触发一次后，如果是“不重复”就把 enabled 关掉 */
    disableOnceBehavior(b) {
      if (b.trigger.type === 'time' && !b.trigger.time.days.length && b.platform === 'chat') {
        b.enabled = false
        this.autoSaveSettings()
      }
    },
    handleAllBriefly(){
      this.allBriefly = !this.allBriefly;
      if(this.allBriefly){
        this.messages.forEach((m) => {
          m.briefly = true;
        })
      }else{
        this.messages.forEach((m) => {
          m.briefly = false;
        })
      }
    },
    async handleDownload(file) {
      // 构造文件URL（确保是完整URL）
      const fileUrl = `${this.partyURL}/uploaded_files/${file.unique_filename}`;
      console.log(fileUrl);
      if (isElectron) {
        try {
          await window.electronAPI.downloadFile({
            url: fileUrl,
            filename: file.original_filename || file.unique_filename
          });
        } catch (e) {
          console.error(e);
        }
      } else {
        // 非Electron环境保留原逻辑
        const link = document.createElement('a');
        link.href = fileUrl;
        link.download = file.unique_filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
    },
  removeEvent(idx,index) {
    this.behaviorSettings.behaviorList[idx].action.random.events.splice(index, 1);
    this.autoSaveSettings(); // 删除后也触发自动保存
  },
  addNewEvent(idx) {
    this.behaviorSettings.behaviorList[idx].action.random.events.push(''); // 添加一个新的空事件，从而新增一个输入框
    this.autoSaveSettings();
  },

  // 初始化周期定时器
initCycleTimer(behavior, index) {
  if (this.cycleTimers[index]) {
    clearInterval(this.cycleTimers[index]);
  }
  const [hours, minutes, seconds] = behavior.trigger.cycle.cycleValue.split(':').map(Number);
  const cycleMs = (hours * 3600 + minutes * 60 + seconds) * 1000;
  let currentCount = 0;
  
  this.cycleTimers[index] = setInterval(() => {
    // 运行前再次确认启用状态和平台
    if (!behavior || !behavior.enabled || !this.isTargetPlatform(behavior, 'chat')) return;
    
    if (behavior.trigger.cycle.isInfiniteLoop || currentCount < behavior.trigger.cycle.repeatNumber) {
      this.runBehavior(behavior);
      currentCount++;
      if (!behavior.trigger.cycle.isInfiniteLoop && currentCount >= behavior.trigger.cycle.repeatNumber) {
        clearInterval(this.cycleTimers[index]);
        this.cycleTimers[index] = null;
        behavior.enabled = false;
      }
    }
  }, cycleMs);
},

// --- 修改重置逻辑 ---
resetCycleTimers() {
  // 防护：如果设置还没加载好，或者列表不存在，直接跳过
  if (!this.behaviorSettings || !Array.isArray(this.behaviorSettings.behaviorList)) {
    return;
  }

  // 确保 cycleTimers 是个数组
  if (!Array.isArray(this.cycleTimers)) {
    this.cycleTimers = [];
  }

  // 清除旧的计时器
  this.cycleTimers.forEach((timer, index) => {
    if (timer) clearInterval(timer);
    this.cycleTimers[index] = null;
  });

  // 重新初始化
  this.behaviorSettings.behaviorList.forEach((b, index) => {
    // 增加 b && b.trigger 的判断
    if (b && b.enabled && b.trigger && b.trigger.type === 'cycle' && this.isTargetPlatform(b, 'chat')) {
      this.initCycleTimer(b, index);
    }
  });
},


isTargetPlatform(behavior, platformKey) {
  // 1. 如果 behavior 本身不存在
  if (!behavior) return false;

  // 2. 检查新字段 platforms (数组)
  // 必须先判断 Array.isArray 且长度 > 0，才能读取 [0]
  if (behavior.platforms && Array.isArray(behavior.platforms) && behavior.platforms.length > 0) {
    if (behavior.platforms.includes('all')) return true;
    return behavior.platforms.includes(platformKey);
  }

  // 3. 兼容老数据：检查旧字段 platform (字符串)
  if (behavior.platform && typeof behavior.platform === 'string') {
    return behavior.platform === 'all' || behavior.platform === platformKey;
  }

  // 4. 兜底逻辑
  return platformKey === 'chat';
},

    startDriverGuide() {
      const KEY = 'driver_guide_shown';
      if (localStorage.getItem(KEY)) return;
      localStorage.setItem(KEY, '1');

      const driver = window.driver.js.driver;

      const d = driver({
        allowClose: true,
        disableActiveInteraction: false,
        showProgress: true,
        nextBtnText: this.t('next'),
        prevBtnText: this.t('prev'),
        doneBtnText: this.t('done'),
        steps: [
          {
            element: '#driver-guide-btn',
            popover: {
              title: this.t('guide.driver-guide-btn'),
              description: this.t('guide.driver-guide-btn-notice'),
              side: 'right',
              align: 'start',
            },
          },
          {
            element: '#model-config',
            popover: {
              title: this.t('guide.model-config'),
              description: this.t('guide.model-config-notice'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: async () => {
                await this.handleSelect('model-config');
                // 手动触发下一步导航
                d.moveNext();
              }
            },
          },
          {
            element: '#add-provider-card',
            popover: {
              title: this.t('guide.add-provider-card'),
              description: this.t('guide.add-provider-card-notice'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: () => {
                this.showAddDialog = true;
                setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
              }
            }
          },
          {
            element: '#show-Add-Dialog',
            popover: {
              title: this.t('guide.show-Add-Dialog'),
              description: this.t('guide.show-Add-Dialog-notice'),
              side: 'top',
              // 添加 onNextClick 处理逻辑
              onNextClick: async () => {
                // 1. 判断是否已选择供应商 (假设 newProviderTemp.vendor 为空即未选)
                if (!this.newProviderTemp.vendor) {
                  // 2. 确保供应商列表至少有3个，防止报错
                  if (this.vendorOptions && this.vendorOptions.length >= 3) {
                    // 取出第三个供应商的值 (数组索引从0开始，所以是2)
                    const thirdVendorValue = this.vendorOptions[2].value;
                    
                    // 调用你的选择方法，或者直接赋值
                    // this.newProviderTemp.vendor = thirdVendorValue; 
                    this.handleSelectVendor(thirdVendorValue);
                    
                    // 3. 等待 Vue 更新 DOM (这一步很重要，因为下一步要高亮"确认"按钮，
                    // 需要确保按钮的 disable 状态已被移除)
                    await this.$nextTick(); 
                  }
                }
                
                // 4. 手动触发下一步
                d.moveNext();
              }
            }
          },
          {
            element: '#confirm-Add-Provider-Button',
            popover: {
              title: this.t('guide.confirm-Add-Provider-Button'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: async () => {
                this.confirmAddProvider();
                // 手动触发下一步导航
                d.moveNext();
              }
            }
          },
          {
            element: '#get-API-key',
            popover: {
              title: this.t('guide.get-API-key'),
              description: this.t('guide.get-API-key-notice'),
              side: 'right',
              onPrevClick: () => {
                this.showAddDialog = true;
                setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
              },
            }
          },
          {
            element: '#input-api-Key',
            popover: {
              title: this.t('guide.input-api-Key'),
              description: this.t('guide.input-api-Key-notice'),
              side: 'right',
            }
          },
          {
            element: '#get-Models-List',
            popover: {
              title: this.t('guide.get-Models-List'),
              description: this.t('guide.get-Models-List-notice'),
              side: 'right',
            }
          },
          {
            element: '#model-Id',
            popover: {
              title: this.t('guide.model-Id'),
              description: this.t('guide.model-Id-notice'),
              side: 'right',
            }
          },
        ]
      });

      // 监听高亮元素点击
      const checkClick = (e) => {
        if (e.target.closest('#model-config')) {
          d.moveNext();
        }
        if (e.target.closest('#add-provider-card')) {
          d.moveNext();
        }
        if (e.target.closest('#confirm-Add-Provider-Button')) {
          d.moveNext();
        }
        if (e.target.closest('#get-API-key')) {
          d.moveNext();
        }
        if (e.target.closest('#get-Models-List')) {
          d.moveNext();
        }
        if (e.target.closest('#vendor-Option')) {
          setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
        }
      };
      document.addEventListener('click', checkClick);

      // 清理监听
      d.onDestroyed = () => document.removeEventListener('click', checkClick);

      setTimeout(() => d.drive(), 300);
    },


  // 手动重开引导（可绑定到按钮）
  restartDriverGuide() {
    localStorage.removeItem('driver_guide_shown');
    this.startDriverGuide();
  },
  showToolInfo(tool) {
    this.toolForShowInfo = tool;
    this.showToolInfoDialog = true;
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
  addPrompt() {
    this.promptForm = { id: null, name: '', content: '' };
    this.showPromptDialog = true;
  },
  editPrompt(row) {
    this.promptForm = { ...row };
    this.showPromptDialog = true;
  },
  savePrompt() {
    if (!this.promptForm.name || !this.promptForm.content) {
      showNotification(this.t('pleaseCompleteForm'), 'warning')
      return
    }
    if (!this.promptForm.id) {
      // 新增
      this.SystemPromptsList.push({
        id: Date.now(),
        name: this.promptForm.name,
        content: this.promptForm.content
      })
    } else {
      // 编辑：找到索引直接替换
      const idx = this.SystemPromptsList.findIndex(p => p.id === this.promptForm.id)
      if (idx > -1) {
        // 直接赋值即可，不需要 $set
        this.SystemPromptsList[idx] = { ...this.promptForm }
      }
    }
    this.showPromptDialog = false
    this.autoSaveSettings()
  },

  removePrompt(id) {
    const idx = this.SystemPromptsList.findIndex(p => p.id === id);
    if (idx > -1) this.SystemPromptsList.splice(idx, 1);
    this.autoSaveSettings();
  },
  /* 点击“使用”按钮 */
  usePrompt(content) {
    this.messages[0].content = content;
    this.activeMenu = 'home';      // 切换到主界面
    this.showEditDialog = false;
  },
  /* 主入口 */
  async handleTranslate() {
    if (!this.sourceText.trim() || this.isTranslating) return;
    this.isTranslating = true;
    this.translatedText = this.t('translating') + '…';

    const controller = new AbortController();
    this.translateAbortController = controller;

    // 构造 TTS 提示（与 translateMessage 保持一致）
    let newttsList = [];
    if (this.ttsSettings?.newtts) {
      for (const key in this.ttsSettings.newtts) {
        if (this.ttsSettings.newtts[key].enabled) newttsList.push(key);
      }
    }
    const ttsPrompt = '如果被翻译的文字与目标语言一致，则返回原文即可'

    try {
      const res = await fetch('/simple_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.mainAgent,
          messages: [
            {
              role: 'system',
              content: `你是一位专业翻译，请将用户提供的任何内容严格翻译为${this.target_lang}，保持原有格式（如Markdown、换行等），不要添加任何额外内容。只需返回翻译结果。${ttsPrompt}`
            },
            {
              role: 'user',
              content: `请翻译以下内容到${this.target_lang}：\n\n${this.sourceText}`
            }
          ],
          stream: true,
          temperature: 0.1
        }),
        signal: controller.signal
      });

      if (!res.ok) throw new Error('Network error');

            await iterateNdjsonLines(res, (chunk) => {
        const delta = chunk.choices?.[0]?.delta?.content ?? '';
        if (delta) {
          result += delta;
          this.translatedText = result; // 实时渲染
        }
            });
    } catch (e) {
      if (e.name !== 'AbortError') {
        this.translatedText = `Translation error: ${e.message}`;
      }
    } finally {
      this.isTranslating = false;
      this.translateAbortController = null;
    }
  },

  abortTranslate () {
    this.translateAbortController?.abort()
    this.isTranslating = false
  },

  clearAll () {
    this.sourceText = ''
    this.translatedText = ''
  },
  changeLanguage() {
    this.target_lang = this.targetLangSelected!="system"? this.targetLangSelected: navigator.language || navigator.userLanguage || 'zh-CN';
    this.autoSaveSettings()
  },
  copyTranslated() {
    if (!this.translatedText) return
    navigator.clipboard.writeText(this.translatedText)
    showNotification(this.t('copy_success'))
  },
  handleShowAddMemoryDialog() {
    if (this.isGenerating){
      showNotification(this.t('AIgening'))
       return;
    }
    this.showAddMemoryDialog = true
  },
  async handleQuickGen() {
    if (!this.quickCreatePrompt.trim() || this.isGenerating) return;

    this.isGenerating = true;
    showNotification(this.t('startGen'));

    const controller = new AbortController();
    this.QuickGenAbortController = controller;

    const systemPrompt = `你是一名专业的角色设计师。  
  生成的角色卡内容必须与用户输入的语言保持一致。 比如，用户输入的是中文，那么角色卡内容也必须是中文。如果用户输入的是英文，那么角色卡内容也必须是英文。以此类推！
  用户会提供一个简短的创意，你必须仅回复一段**有效的 JSON**，并放在一个标准的Markdown 代码块中。  
  JSON的值必须用双引号括起来，而值内部的内容如果需要引号，一律改成单引号。
  JSON 结构必须为：

    {
      "name": "角色名称",
      "description": "简要背景/世界观设定，尽可能详细",
      "personality": "性格特征",
      "mesExample": "展示 2~5 轮聊天示例，格式：用户:xxx\n角色:xxx",
      "systemPrompt": "用于驱动角色的系统提示",
      "firstMes": "角色的第一句问候语",
      "alternateGreetings": ["可选问候2","可选问候3"],
      "characterBook": [
          {"keysRaw":"关键词1\n关键词2","content":"这里填入当用户提到关键词1或关键词2时，需要返回给AI看的内容……"},
          {"keysRaw":"关键词3","content":"这里填入当用户提到关键词3时，需要返回给AI看的内容……"}
      ]
    }

  所有字段都必须提供；characterBook也请尽可能的丰富，最好可以在10条以上，每条的字数可以不用太多。alternateGreetings最好也有5条以上。
  绝不可包含 avatar 字段。`;

    try {
      const res = await fetch('/simple_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          messages: [
            { role: 'system', content: systemPrompt },
            { role: 'user', content: this.quickCreatePrompt }
          ],
          stream: true,   // ★ 打开流式
          temperature: 0.8
        }),
        signal: controller.signal
      });

      if (!res.ok) throw new Error('Network error');

            await iterateNdjsonLines(res, (chunk) => {
        const delta = chunk.choices?.[0]?.delta?.content ?? '';
        if (delta) {
          fullText += delta;
          this.quickCreatePrompt = fullText; // 实时显示
        }
            });

      // 2. 流结束，再走原来的解析逻辑
      let raw = fullText.trim();

      // 去 code-block
      const codeBlock = raw.match(/^```json\s*([\s\S]*?)```$/);
      if (codeBlock) raw = codeBlock[1];
      const tildeBlock = raw.match(/^```\s*([\s\S]*?)```$/);
      if (tildeBlock) raw = tildeBlock[1];

      // 解析 JSON
      let json;
      try {
        json = JSON.parse(raw);
      } catch (e) {
        throw new Error('AI 返回的不是合法 JSON：' + e.message);
      }

      // 3. 写入 newMemory 并保存
      Object.assign(this.newMemory, {
        name: json.name ?? '',
        infer:false,
        providerId: null,
        model: '',
        base_url: '',
        api_key: '',
        vendor: '',
        description: json.description ?? '',
        personality: json.personality ?? '',
        mesExample: json.mesExample ?? '',
        systemPrompt: json.systemPrompt ?? '',
        firstMes: json.firstMes ?? '',
        alternateGreetings: json.alternateGreetings?.filter(Boolean) ?? [],
        characterBook: (json.characterBook ?? []).map(b => ({
          keysRaw: b.keysRaw ?? '',
          content: b.content ?? ''
        })),
        avatar: ''
      });
      this.newMemory.id = null;
      this.addMemory();
      showNotification(this.t('genSuccess'));

    } catch (e) {
      if (e.name === 'AbortError') {
        console.log('QuickGen aborted');
      } else {
        showNotification(this.t('genFailed') + ': ' + e.message, 'error');
      }
    } finally {
      this.isGenerating = false;
      this.QuickGenAbortController = null;
      this.quickCreatePrompt = '';
    }
  },
  stopQuickGen() {
    this.QuickGenAbortController?.abort()
    this.isGenerating = false
  },
  async handleSystemPromptQuickGen() {
    if (!this.quickCreateSystemPrompt.trim() || this.isSystemPromptGenerating) return;
    
    this.isSystemPromptGenerating = true;
    this.promptForm.name = this.quickCreateSystemPrompt;
    showNotification(this.t('startGen'));
    
    const controller = new AbortController();
    this.QuickGenSystemPromptAbortController = controller;
    
    try {
      const res = await fetch('/simple_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.mainAgent,
          messages: [
            {
              role: 'system',
              content: `你需要将用户发给你的简短的系统提示词优化成可以驱动大模型更好的工作的详细的系统提示词。
  注意！生成的系统提示词必须与用户输入的语言保持一致。如果用户说英文，你就必须生成英文的系统提示词；如果用户说中文，你就必须生成中文的系统提示词。以此类推！
  你可以从这几个方面来写，但也不要限于这些方面：角色名、角色定位、核心能力、回答风格、约束、输出格式示例等等`,
            },
            {
              role: 'user',
              content: `${this.quickCreateSystemPrompt}`,
            },
          ],
          stream: true,
          temperature: 0.8
        }),
        signal: controller.signal,
      });

      if (!res.ok) throw new Error('Network error');
      
            await iterateNdjsonLines(res, (data) => {
        
        // 适配新的流式响应格式
        if (data.choices && data.choices[0]) {
          const choice = data.choices[0];
          
          // 处理流式响应中的增量内容
          if (choice.delta && choice.delta.content) {
            result += choice.delta.content;
            this.quickCreateSystemPrompt = result;
          }
          // 或者处理 finish_reason 为 stop 的最终响应
          else if (choice.finish_reason === 'stop') {
            // 最终完成，不需要额外处理
          }
        }
            });
      
      
      // 保存生成的提示词
      this.promptForm.content = this.quickCreateSystemPrompt;
      this.promptForm.id = null;
      await this.savePrompt();
      
      showNotification(this.t('genSuccess'));
      this.quickCreateSystemPrompt = '';
      
    } catch (e) {
      if (e.name === 'AbortError') {
        // 用户取消了生成，不需要显示错误
        console.log('System prompt generation was aborted');
      } else {
        console.error('System prompt generation failed:', e);
        showNotification(this.t('genFailed') + ': ' + e.message, 'error');
      }
    } finally {
      this.isSystemPromptGenerating = false;
      this.QuickGenSystemPromptAbortController = null;
    }
  },
  stopSystemPromptQuickGen() {
    this.QuickGenSystemPromptAbortController?.abort()
    this.isSystemPromptGenerating = false
  },
  async toggleQuickGen(index) {
    let systemPrompt = this.messages[index].content;
    if (!systemPrompt.trim()) {
      showNotification(this.t('noSystemPromptToExtend'), 'error');
      return;
    }
    
    showNotification(this.t('startGen'));
    this.isQuickGenerating = true;
    const abortController = new AbortController();
    this.abortController = abortController;
    
    try {
      const res = await fetch('/simple_chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: this.mainAgent,
          messages: [
            {
              role: 'system',
              content: `你需要将用户发给你的简短的系统提示词优化成可以驱动大模型更好的工作的详细的系统提示词。
  注意！生成的系统提示词必须与用户输入的语言保持一致。如果用户说英文，你就必须生成英文的系统提示词；如果用户说中文，你就必须生成中文的系统提示词。以此类推！
  你可以从这几个方面来写，但也不要限于这些方面：角色名、角色定位、核心能力、回答风格、约束、输出格式示例等等`
            },
            {
              role: 'user',
              content: `${systemPrompt}`,
            },
          ],
          stream: true,
          temperature: 0.8
        }),
        signal: this.abortController.signal,
      });

      if (!res.ok) throw new Error('Network error');
      
            await iterateNdjsonLines(res, (data) => {
        
        // 适配新的流式响应格式
        if (data.choices && data.choices[0]) {
          const choice = data.choices[0];
          
          // 处理流式响应中的增量内容
          if (choice.delta && choice.delta.content) {
            result += choice.delta.content;
            this.messages[index].content = result;
            this.requestScrollToBottom();
          }
          // 或者处理 finish_reason 为 stop 的最终响应
          else if (choice.finish_reason === 'stop') {
            // 最终完成，不需要额外处理
          }
        }
            });
      
      
      showNotification(this.t('genSuccess'));
      
    } catch (e) {
      if (e.name === 'AbortError') {
        // 用户取消了生成，不需要显示错误
        console.log('Quick generation was aborted');
      } else {
        console.error('Quick generation failed:', e);
        showNotification(this.t('genFailed') + ': ' + e.message, 'error');
      }
    } finally {
      this.isQuickGenerating = false;
      this.abortController = null;
    }
  },
  saveSystemPrompt(index) {
    let systemPrompt = this.messages[index].content;
    this.activeMenu = 'role';
    this.subMenu = 'memory';
    this.activeMemoryTab = 'prompts';
    this.promptForm = { id: null, name: '', content: systemPrompt };
    this.showPromptDialog = true;
  },
  async browseDirectory() {
    if (!this.isElectron) {
      // 浏览器环境
      return;
    } else {
      // Electron 环境
      try {
        const result = await window.electronAPI.openDirectoryDialog();
        if (!result.canceled && result.filePaths.length > 0) {
          this.CLISettings.cc_path = result.filePaths[0];
          this.autoSaveSettings();
        }
      } catch (error) {
        console.error('选择目录出错:', error);
        showNotification('选择目录失败', 'error');
      }
    }
  },
  
  _toggleHighlight(e) {
    const blk = e.target.closest('.highlight-block');
    if (!blk) return;
    blk.classList.toggle('expanded');
  },
  changeSystemPrompt() {
    this.editContent = this.SystemPromptsList.find(prompt => prompt.id === this.selectSystemPromptId)?.content;
  },
/* -------------------------------------------------- */
/* 1. 自动分段（复用全文算法）                       */
/* -------------------------------------------------- */
reSegment() {
  this.stopSegmentTTS();          // 停旧音频
    const {
      chunks,
      chunks_voice,
      remaining,
      remaining_voice
    } = this.splitTTSBuffer(this.readConfig.longText);

    if (remaining) {
      chunks.push(remaining);
      chunks_voice.push(remaining_voice);
    }

      /* ================= 新增：去标签 + 去空白并同步删除 ================= */
      // 1. 去 HTML 标签
      const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());

      // 2. 过滤空白并同步删除 chunks_voice 对应项
      const finalChunks       = [];
      const finalChunksVoice  = [];

      cleanedChunks.forEach((txt, idx) => {
        if (txt) {                      // 非空才保留
          finalChunks.push(txt);
          finalChunksVoice.push(chunks_voice[idx]);
        }
      });

      // 3. 覆盖原来的数组
      chunks.length       = 0;
      chunks_voice.length = 0;
      chunks.push(...finalChunks);
      chunks_voice.push(...finalChunksVoice);
      /* ================================================================ */

  this.readState.ttsChunks = chunks;
  this.readState.chunks_voice = chunks_voice;
  this.readState.audioChunks  = new Array(this.readState.ttsChunks.length);
  this.readState.currentChunk = -1;
},

/* -------------------------------------------------- */
/* 2. 播放单句（含 VRM 同步）                        */
/* -------------------------------------------------- */
async playSingleSegment(idx) {
  try{
    if (!this.readState.ttsChunks[idx]) return;
    this.isReadingOnetext = true;
    this.readState.currentChunk = idx;
    const chunk = this.readState.ttsChunks[idx];
    const voice = this.readState.chunks_voice[idx];
    const cachedAudio = this.readState.audioChunks[idx];

    // 检查缓存是否命中
    if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
      this.doPlayAudio(this.readState.audioChunks[idx].url, idx, false); // false=不连播
      return;
    }
    // 未命中先合成
    await this.synthSegment(idx);
    this.doPlayAudio(this.readState.audioChunks[idx].url, idx, false);
  } finally {
    this.isReadingOnetext = false;
  }
},

/* -------------------------------------------------- */
/* 3. 连续播放开关                                   */
/* -------------------------------------------------- */
async toggleContinuousPlay() {
  if (this.readState.isPlaying) {          // 暂停
    this.stopSegmentTTS(false);
    return;
  }
  this.readState.isPlaying   = true;
  if (this.readState.currentChunk < 0 || this.readState.currentChunk >= this.readState.ttsChunks.length) { // 从头开始
    this.readState.currentChunk = 0;         // 从第一句开始
  }
  await this.playNextInQueue(true);        // true 表示连续
},

/* -------------------------------------------------- */
/* 4. 新增：仅播放下一句（播完即停）                  */
/* -------------------------------------------------- */
async playNextSegmentOnce() {
  let next = this.readState.currentChunk + 1;
  this.readState.currentChunk = next;
  if (next >= this.readState.ttsChunks.length) {
    next = 0;
    this.readState.currentChunk = next;
  }
  this.readState.isPlaying = false;      // 确保不自动连播
  await this.playSingleSegment(next);    // 播完即停
},

/* -------------------------------------------------- */
/* 5. 停止所有分段音频                               */
/* -------------------------------------------------- */
stopSegmentTTS(isEnd = true) {
  this.stopTTSActivities();
  if (isEnd){
    this.readState.currentChunk = -1;
  }
  if (this._curAudio) {
    this._curAudio.pause();
    this._curAudio = null;
  }
  this.readState.isPlaying   = false;
},
/* -------------------------------------------------- */
/* 6. 编辑段文本                                      */
/* -------------------------------------------------- */
toggleEditSegment(idx) {
  if (this.activeSegmentIdx === idx) {
    // 保存：把临时值写回正式字段
    this.readState.ttsChunks[idx] = this.segmentEditBuffer
    this.readState.chunks_voice[idx] = this.segmentVoiceEditBuffer[idx] ?? this.readState.chunks_voice[idx]
    this.activeSegmentIdx = -1
  } else {
    // 进入编辑：先给“音色临时数组”对应位置塞个初始值
    this.segmentEditBuffer = this.readState.ttsChunks[idx]
    // Vue3 直接赋值即可
    this.segmentVoiceEditBuffer[idx] = this.readState.chunks_voice[idx]
    this.activeSegmentIdx = idx
  }
},

/* 1. 合成时顺便转 base64 */
async synthSegment(idx) {
  try {
    const text  = this.readState.ttsChunks[idx];
    const voice = this.readState.chunks_voice[idx] || 'default';
    /* —— 与对话版完全一致的文本清洗 —— */
    let chunk_text = text;
    let chunk_expressions =[];
    if (text.indexOf('<') !== -1) {
      const tagReg = /<[^>]+>/g;
      chunk_expressions = (text.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
      chunk_text = text.replace(tagReg, '').trim(); // 把标签从正文里删掉
    }
    const res = await fetch('/tts', {
      method : 'POST',
      headers: { 'Content-Type': 'application/json' },
      body   : JSON.stringify({ ttsSettings: this.ttsSettings, text, index: idx, voice }),
    });
    if (!res.ok) throw new Error('TTS failed');

    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);

    /* 关键：同步转 base64 */
    const base64 = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload  = () => resolve(reader.result.split(',')[1]);
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });

    /* 缓存两样东西 */
    this.readState.audioChunks[idx] = {
      url,                       // 本地播放用
      expressions: chunk_expressions,
      base64: `data:${blob.type};base64,${base64}`, // VRM 播放用
      text: chunk_text,
      idx,
      voice
    };
  } catch (e) {
    console.error(`TTS chunk ${idx} error`, e);
    this.readState.audioChunks[idx] = { 
      url: null, 
      base64: null,
      expressions: [],
      text: "",
      idx 
    };
  }
},
scrollToCurrentChunk(idx) {
  // 使用 nextTick 确保 DOM 更新完成
  this.$nextTick(() => {
    const segmentList = document.querySelector('.segment-list');
    const segmentItem = document.querySelector(`.segment-item:nth-child(${idx + 1})`);
    if (segmentList && segmentItem) {
      segmentItem.scrollIntoView({
        behavior: 'smooth',
        block: 'center'
      });
    }
  });
},

async doPlayAudio(url, idx, continuous = false) {
  if (this._curAudio) {
    this._curAudio.pause();
    this.sendTTSStatusToVRM('stopSpeaking', {});
  }
  try {
    const audio = new Audio(url);
    this._curAudio = audio;

    // 滚动到当前行
    this.scrollToCurrentChunk(idx);

    const chunk = this.readState.audioChunks[idx];
    if (chunk.base64 == null) throw new Error('No base64');
    this._curAudio.volume = this.vrmOnline ? 0.0000001 : 1; // VRM在线时静音
    this.sendTTSStatusToVRM('startSpeaking', {
      audioDataUrl: chunk.base64,
      chunkIndex: idx,
      totalChunks: this.readState.ttsChunks.length,
      text: chunk.text,
      expressions: chunk.expressions || [],
      voice: this.readState.chunks_voice[idx] || 'default',
    });

    // 监听错误事件
    audio.addEventListener('error', (e) => {
      console.error('Audio load error', e);
      this.readState.currentChunk++;
      if (this.readState.currentChunk < this.readState.ttsChunks.length) {
        this.playNextInQueue(true);
      } else {
        this.stopSegmentTTS();
      }
    });

    await new Promise(resolve => {
      this._curAudio.addEventListener('ended', () => {
        this.sendTTSStatusToVRM('chunkEnded', { chunkIndex: idx });
        if (continuous && this.readState.isPlaying) {
          this.readState.currentChunk++;
          if (this.readState.currentChunk < this.readState.ttsChunks.length) {
            this.playNextInQueue(true);
          } else {
            this.stopSegmentTTS();
          }
        } else {
          this.stopSegmentTTS(false);
        }
        resolve();
      });
      console.log('play audio', `${idx + 1}`);
      audio.play().catch(e => {
        console.error('Audio play error', e);
        this.readState.currentChunk++;
        if (this.readState.currentChunk < this.readState.ttsChunks.length) {
          this.playNextInQueue(true);
        } else {
          this.stopSegmentTTS();
        }
        resolve(); // 确保 Promise 被 resolve
      });
    });
  } catch (e) {
    console.error('Read playback error', e);
    this.readState.currentChunk++;
    if (this.readState.currentChunk < this.readState.ttsChunks.length) {
      this.playNextInQueue(true);
    } else {
      this.stopSegmentTTS();
    }
  } finally {
      this.isReadingOnetext = false;
    }
},

// 连续播放专用：自动合成&播放下一帧
async playNextInQueue(continuous) {
  const idx = this.readState.currentChunk;   // 当前要播的索引
  const chunk = this.readState.ttsChunks[idx];
  const voice = this.readState.chunks_voice[idx];
  const cachedAudio = this.readState.audioChunks[idx];

  // 检查缓存是否命中
  if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
    // 命中就无事发生
  }else{
    await this.synthSegment(idx);
  }
  this.doPlayAudio(this.readState.audioChunks[idx].url, idx, continuous);
},

// 清空分段
clearSegments() {
  this.stopSegmentTTS();
  this.readState.ttsChunks   = [];
  this.readState.chunks_voice = [];
  this.readState.audioChunks  = [];
  this.readState.currentChunk = -1;
},
  // 扫描扩展但不自动加载
  async scanExtensions() {
    try {
      // 使用API获取扩展列表
      const response = await fetch('/api/extensions/list');
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || '获取扩展列表失败');
      }
      
      const data = await response.json();
      this.extensions = data.extensions || [];
      
      // 不再自动加载第一个扩展
      // 默认显示 sidePanelText 内容
      this.currentExtension = null;
      this.sidePanelURL = '';
    } catch (error) {
      console.error('扫描扩展出错:', error);
    }
  },
  
    // 加载指定扩展
  async loadExtension(extension) {
    if (!extension) {
      this.currentExtension = null;
      this.sidePanelURL = '';
      return;
    }
    
    /* 1. 尝试 Node 模式 */
    try {
      const r = await fetch(`/api/extensions/${extension.id}/start-node`, { method: 'POST' });
      const res = await r.json();

      if (res.mode === 'node') {
        // ✅ Node 成功
        this.currentExtension = extension;
        this.sidePanelURL = `/api/extensions/${extension.id}/node/`;
        showNotification(`${this.t('loadExtension(node)')}: ${extension.name}`, 'success');
        return;
      } else if (res.mode === 'error') {
        // ❌ Node 服务启动失败！必须拦截并展示错误，不能往下走
        showNotification(`插件服务启动失败: ${res.message}`, 'error');
        console.error("【Node Extension 报错】:", res.message);
        return; 
      }
      
      // 只有 res.mode === 'static'，才允许跳出 if，去走下面的静态路由兜底
    } catch (e) {
      // 网络断开或解析异常，也建议拦截
      showNotification(`请求插件服务异常: ${e.message}`, 'error');
      console.error(e);
      return; 
    }

    /* 2. 回退静态路由 */
    this.currentExtension = extension;
    this.sidePanelURL = `/ext/${extension.id}/index.html`;
    showNotification(`${this.t('loadExtension(static)')}: ${extension.name}`, 'success');
    this.extensionsSystemPromptsDict[extension.id] = extension.systemPrompt || ""; // 更新提示词
  },
  
// 切换到默认视图 (主页书签)
  resetToDefaultView() {
    // 1. 切换焦点为 null，利用 v-show 机制隐藏所有 iframe，展示主页内容
    this.currentExtension = null;
    this.sidePanelURL = ''; // 清除旧的全局URL状态，防止污染
    this.activeSideView = 'list'; // 确保侧边栏内部路由切回“列表”

    // 2. 关闭可能开着的弹窗
    this.showExtensionsDialog = false;

    // 3. ✨ 核心修改：移除这下面两行代码！
    // this.expandChatArea();     // ❌ 不要强行扩张聊天区
    // this.collapseSidePanel();  // ❌ 不要强行收起侧边栏，用户只是切回主标签，侧边栏应该开着！

    // 4. 重置当前对话的附加提示词（切回默认对话，清空扩展的系统 Prompt 是合理的）
    this.extensionsSystemPromptsDict = {}; 

    // 5. 如果离开任务中心，清除任务刷新定时器以节省性能（保持原逻辑）
    if (this.taskRefreshTimer) {
      clearInterval(this.taskRefreshTimer);
      this.taskRefreshTimer = null; // 顺手置空是个好习惯
    }

    console.log('已切换到侧边栏主视图 (Home Tab)');
  },
  // 打开扩展选择对话框
  openExtensionsDialog() {
    this.showExtensionsDialog = true;
  },
  
// 切换（或新开）扩展标签页
  async switchExtension(extension) {
    // 1. 关闭扩展弹窗，展开侧边栏
    this.showExtensionsDialog = false; 
    const sidePanel = this.$refs.sidePanelRef;
    if (sidePanel.style.width == 0 ){
        this.expandSidePanel();
    }

    // 2. 检查这个扩展是否已经在多开数组里了
    const existingExt = this.openedExtensions.find(e => e.id === extension.id);

    if (existingExt) {
      // 🌟 【已打开过】：直接切换焦点，不重新加载，保留页面状态！
      this.currentExtension = existingExt;
      this.activeSideView = 'iframe'; // 确保视图模式是 iframe
      
      // 如果你的底层代码仍依赖全局的 sidePanelURL，这里做个同步
      if (existingExt.iframeUrl) {
        this.sidePanelURL = existingExt.iframeUrl;
      }
      
    } else {
      // 🌟 【第一次打开】：需要走加载逻辑
      // 为了让 loading 动画立刻出来，先将当前扩展指向它
      this.currentExtension = extension;
      this.activeSideView = 'iframe';
      this.sidePanelURL = ''; // 清空全局URL防止闪烁旧画面
      
      // 加入顶部标签栏数组
      this.openedExtensions.push(extension);

      // 执行你原本的获取 URL/Token 逻辑
      await this.loadExtension(extension);

      // 💡 极其关键的一步：loadExtension 执行完后，通常会给 this.sidePanelURL 赋值。
      // 我们需要把这个生成的专属 URL，保存到当前这个扩展对象里，这样下次切换回来才不会丢！
      const targetExt = this.openedExtensions.find(e => e.id === extension.id);
      if (targetExt) {
        // 将全局生成的 URL 永久绑定给这个 Tab
        targetExt.iframeUrl = this.sidePanelURL; 
      }
    }
  },

  // ✨ 配套新增：关闭扩展标签页
  closeExtensionTab(extId) {
    // 1. 从已打开数组中移除
    const index = this.openedExtensions.findIndex(e => e.id === extId);
    if (index === -1) return;
    
    this.openedExtensions.splice(index, 1);

    // 2. 如果关闭的刚好是【当前正在看】的标签页，需要处理焦点回退
    if (this.currentExtension && this.currentExtension.id === extId) {
      if (this.openedExtensions.length > 0) {
        // 如果还有其他标签，自动跳到最后一个标签
        const lastExt = this.openedExtensions[this.openedExtensions.length - 1];
        this.switchExtension(lastExt);
      } else {
        // 如果全关光了，退回默认的列表主页
        this.resetToDefaultView();
      }
    }
  },

  // 工具函数：返回扩展真正能访问的地址（Node > 静态）
  async getExtensionURL(ext) {
    console.log('获取扩展URL', ext);
    // 1. 先尝试启动 Node
    try {
      const r = await fetch(`/api/extensions/${ext.id}/start-node`, { method: 'POST' });
      const res = await r.json();
      if (res.mode === 'node') {
        return `/api/extensions/${ext.id}/node/`;   // ✅ Node 代理路径
      }
      console.log('启动 Node 失败，回退静态',res);
    } catch { 
     }
    // 2. 回退静态
    return `/ext/${ext.id}/index.html`;
  }, 

    async openExtension(extension) {
      const url = await this.getExtensionURL(extension);   // ⬅️ 异步拿地址
      console.log('打开扩展', `${this.partyURL}${url}`);
      if (isElectron) {
        window.electronAPI.openExternal(`${this.partyURL}${url}`);
      } else {
        window.open(url, '_blank');
      }
    },
    // 删除扩展
    async removeExtension(ext) {
      // 若是 Node 模式就停进程，忽略错误
      await fetch(`/api/extensions/${ext.id}/stop-node`, { method: 'POST' }).catch(() => {});
      try {
        const res = await fetch(`/api/extensions/${ext.id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('删除失败');
        showNotification(this.t('deleteSuccess'), 'success');
        this.scanExtensions(); // 刷新列表
      } catch (e) {

         showNotification(e.message, 'error');
      }
    },

    // 打开「添加扩展」对话框
    openAddExtensionDialog() {
      this.newExtensionUrl = '';
      this.showExtensionForm = true;
      this.fetchRemotePlugins();
    },

    async pollInstallStatus(extId, onSuccess, onError) {
      const poll = async () => {
        try {
          const res = await fetch(`/api/extensions/task-status/${extId}`);
          const data = await res.json();

          if (data.status === 'success') {
            // 安装成功
            onSuccess(data.detail);
          } else if (data.status === 'error') {
            // 安装失败
            onError(data.detail);
          } else if (data.status === 'installing') {
             // 仍在安装中，继续轮询 (这里可以顺便更新界面提示，如果你有对应UI的话)
             // 例如：console.log(data.detail); 
             setTimeout(poll, 1000); // 1秒后再次检查
          } else {
             // 未知状态，可能是重启了或者ID错了
             onError("任务状态丢失");
          }
        } catch (e) {
          onError("网络请求错误");
        }
      };
      // 开始第一次轮询
      poll();
    },

    // 真正「安装」按钮触发
    async addExtension() {
      const url = this.newExtensionUrl.trim();
      if (!url) return showNotification('请输入 GitHub 地址', 'error');
      
      this.installLoading = true; // 开启 Loading 遮罩
      
      try {
        const res = await fetch('/api/extensions/install-from-github', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            url,
            backupUrl: ""  
          }),
        });
        
        if (res.status === 409) throw new Error(this.t('extensionExists'));
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || this.t('deleteFailed'));
        }

        const resData = await res.json();
        const extId = resData.ext_id;

        // --- 核心修改：开始轮询 ---
        showNotification('正在后台下载，请稍候...', 'info');
        
        this.pollInstallStatus(
          extId,
          (msg) => {
            // 成功回调
            this.installLoading = false;
            showNotification(msg || '安装成功！', 'success');
            this.showExtensionForm = false; // 关闭弹窗
            this.scanExtensions(); // 立即刷新列表
          },
          (errMsg) => {
            // 失败回调
            this.installLoading = false;
            showNotification(`安装失败: ${errMsg}`, 'error');
          }
        );

      } catch (e) {
        this.installLoading = false;
        showNotification(e.message, 'error');
      }
    },
    // 打开文件选择器
    selectLocalZip() {
      this.$refs.zipInput.click();
    },

    // 选中文件后自动上传
    async onZipSelected(e) {
      const file = e.target.files?.[0];
      if (!file) return;
      
      this.installLoading = true;
      const form = new FormData();
      form.append('file', file);
      
      try {
        const res = await fetch('/api/extensions/upload-zip', {
          method: 'POST',
          body: form,
        });
        
        if (res.status === 409) throw new Error(this.t('extensionExists'));
        if (!res.ok) {
          const data = await res.json();
          throw new Error(data.detail || '上传失败');
        }
        
        const resData = await res.json();
        const extId = resData.ext_id;
        
        // 开始轮询，与 GitHub 安装一致
        showNotification(this.t('waitExtensionInstall'), 'info');
        this.showExtensionForm = false;
        
        this.pollInstallStatus(
          extId,
          (msg) => {
            this.installLoading = false;
            showNotification(msg || this.t('installSuccess'), 'success');
            this.scanExtensions();
          },
          (errMsg) => {
            this.installLoading = false;
            showNotification(`${this.t('installFailed')}: ${errMsg}`, 'error');
          }
        );
        
      } catch (err) {
        this.installLoading = false;
        showNotification(err.message, 'error');
      } finally {
        e.target.value = '';
      }
    },

    async fetchRemotePlugins() {
      try {
        await this.scanExtensions(); // 刷新
        const res = await fetch('/api/extensions/remote-list');
        const { plugins } = await res.json();   // 取出 plugins 数组
        console.log(plugins);
        const localRes = await fetch('/api/extensions/list');
        const { extensions } = await localRes.json();
        console.log(extensions);
        this.remotePlugins = plugins.map(r => ({
          ...r,
          installed: extensions.some(l => l.repository.trim() === r.repository.trim()),
        }));
      } catch (e) {
        
      }
    },
async togglePlugin(plugin) {
    if (plugin.installed) {
      // 卸载逻辑保持不变...
      await this.removeExtension(plugin);
      plugin.installed = false;
    } else {
      // --- 安装逻辑 ---
      
      // 1. 设置局部 loading 状态 (如果你的 plugin 对象支持)
      // 如果没有局部 loading，就用全局 this.installLoading = true
      plugin.installing = true
      this.installLoading = true; 

      try {
        const res = await fetch('/api/extensions/install-from-github', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ 
            url: plugin.repository,
            backupUrl: plugin.backupRepository || "" 
          }),
        });

        if (res.status === 409) throw new Error('插件已存在');
        if (!res.ok) throw new Error('请求失败');
        
        const resData = await res.json();
        const extId = resData.ext_id;

        showNotification('已开始下载，请耐心等待...', 'info');

        // --- 核心修改：开始轮询 ---
        this.pollInstallStatus(
          extId,
          (msg) => {
            // 成功
            this.installLoading = false;
            if (plugin) plugin.installing = false;
            plugin.installed = true; // 更新前端状态
            showNotification('安装成功！', 'success');
            this.scanExtensions(); // 刷新完整列表以确保数据一致
          },
          (errMsg) => {
            // 失败
            this.installLoading = false;
            if (plugin) plugin.installing = false;
            showNotification(`安装失败: ${errMsg}`, 'error');
          }
        );

      } catch (e) {
        this.installLoading = false;
        if (plugin) plugin.installing = false;
        showNotification(e.message, 'error');
      }
    }
  },
  handleRefreshClick() {
    this.refreshing = true;
    
    // 调用原有的刷新方法
    this.fetchRemotePlugins().then(() => {
      // 请求完成后
      this.refreshing = false;
      this.refreshButtonText = this.t('refreshedSuccess') || '已刷新';
      
      // 2秒后恢复按钮文字
      setTimeout(() => {
        this.refreshButtonText = this.t('refreshList');
      }, 2000);
    }).catch(error => {
      // 处理错误情况
      this.refreshing = false;
      this.refreshButtonText = this.t('refreshFailed') || '刷新失败';
      
      // 2秒后恢复按钮文字
      setTimeout(() => {
        this.refreshButtonText = this.t('refreshList');
      }, 2000);
    });
  },
  openRepository(url) {
    if (isElectron) {
      window.electronAPI.openExternal(url)   // 主进程会新建可关闭的独立窗口
    } else {
      window.open(url, '_blank')
    }
  },
  startChatHistoryResize(e) {
    if (this.isMobile || !this.chatHistoryPanelOpen) return;

    const container = this.$refs.chatWrapperRef;
    const panel = this.$refs.chatHistoryPanelRef;
    if (!container || !panel) return;

    this.isHistoryPanelResizing = true;
    const containerRect = container.getBoundingClientRect();
    const minWidth = 220;
    const maxWidth = Math.max(minWidth, Math.min(520, containerRect.width - 320));

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (event) => {
      if (!this.isHistoryPanelResizing) return;
      const nextWidth = Math.max(minWidth, Math.min(event.clientX - containerRect.left, maxWidth));
      this.chatHistoryPanelWidth = nextWidth;
    };

    const handleMouseUp = () => {
      this.isHistoryPanelResizing = false;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  },
  // 开始拖拽调整大小
  startResize(e) {
    if (!this.chatAreaOpen || !this.sidePanelOpen) return;
    
    const container = this.$refs.chatWrapperRef;
    // 获取当前历史侧边栏是否可见并获取宽度
    const historySidebar = container.querySelector('.chat-history-sidebar');
    const isSidebarVisible = this.showHistorySidebar && !this.isMobile;
    const sidebarWidth = isSidebarVisible ? historySidebar.offsetWidth : 0;

    this.isResizing = true;
    const containerRect = container.getBoundingClientRect();
    const availableWidth = containerRect.width - sidebarWidth; // 减去历史栏宽度
    
    container.classList.add('resizing');

    const handleMouseMove = (e) => {
      if (!this.isResizing) return;
      
      // 这里的 mouseX 必须相对于聊天区的左边缘
      const mouseXInChat = e.clientX - (containerRect.left + sidebarWidth);
      const clampedMouseX = Math.max(0, Math.min(mouseXInChat, availableWidth));
      
      const leftWidth = clampedMouseX;
      const rightWidth = availableWidth - clampedMouseX - 10; // 10 是分割条宽
      
      const leftPercent = (leftWidth / availableWidth) * 100;
      const rightPercent = (rightWidth / availableWidth) * 100;
      
      if (leftPercent < this.minPanelWidth) {
        this.collapseChatArea();
        handleMouseUp();
        return;
      }
      
      if (rightPercent < this.minPanelWidth) {
        this.collapseSidePanel();
        handleMouseUp();
        return;
      }
      
      this.updatePanelWidthsWithPixels(leftWidth, rightWidth);
    };

    const handleMouseUp = () => {
      this.isResizing = false;
      container.classList.remove('resizing');
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      this.recalculatePercentages(availableWidth);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  },

  handleHistoryToggle() {
      this.showHistorySidebar = !this.showHistorySidebar;
      console.log('showHistorySidebar:',this.showHistorySidebar)
      // 强制触发一次 recalculate，让右侧聊天区重新适应剩余宽度
      this.$nextTick(() => {
          this.handleResize(); 
      });
      this.autoSaveSettings();
  },

  // 使用像素宽度更新面板
  updatePanelWidthsWithPixels(leftWidth, rightWidth) {
    this.$nextTick(() => {
      const chatArea = this.$refs.chatAreaRef;
      const sidePanel = this.$refs.sidePanelRef;
      
      if (!chatArea || !sidePanel) {
        return;
      }
      
      if (this.chatAreaOpen && this.sidePanelOpen) {
        chatArea.style.width = `${leftWidth}px`;
        sidePanel.style.width = `${rightWidth}px`;
      }
    });
  },

  // 重新计算百分比（用于保存状态和响应式）
  recalculatePercentages(providedAvailableWidth) {
    const container = this.$refs.chatWrapperRef;
    const historySidebar = container?.querySelector('.chat-history-sidebar');
    const sidebarWidth = (historySidebar && !this.isMobile) ? historySidebar.offsetWidth : 0;
    
    // 如果没有传入宽度，则实时计算
    const availableWidth = providedAvailableWidth || (container.offsetWidth - sidebarWidth);
    
    const chatArea = this.$refs.chatAreaRef;
    const sidePanel = this.$refs.sidePanelRef;
    
    if (chatArea && sidePanel && this.chatAreaOpen && this.sidePanelOpen) {
      const chatAreaWidthPx = chatArea.offsetWidth;
      const sidePanelWidthPx = sidePanel.offsetWidth;
      
      // 基于可用宽度计算比例
      this.chatAreaWidth = (chatAreaWidthPx / availableWidth) * 100;
      this.sidePanelWidth = (sidePanelWidthPx / availableWidth) * 100;
    }
  },  

  // 处理分割条点击
  handleResizerClick(e) {
    if (e.target.closest('.expand-chat-btn') || e.target.closest('.expand-side-btn')) {
      return;
    }
    
    // 双击重置为50:50
    if (e.detail === 2) {
      this.resetPanelSizes();
    }
  },

  // 收起对话区域
// 收起左侧对话区域（让右侧面板向左填充）
collapseChatArea() {
  const sidePanel = this.$refs.sidePanelRef;
  const chatArea = this.$refs.chatAreaRef;

  // 1. 核心修复：在隐藏左侧前，先清除右侧的像素限制
  if (sidePanel) sidePanel.style.width = '';
  if (chatArea) chatArea.style.width = '';

  // 2. 更新状态
  this.chatAreaOpen = false;
  this.sidePanelOpen = true; 
  this.sidePanelWidth = 100;
  this.chatAreaWidth = 0;

  // 3. 应用百分比布局
  this.updatePanelWidths();
},

// 收起右侧侧边栏（让左侧对话区向右填充）
collapseSidePanel() {
  const chatArea = this.$refs.chatAreaRef;
  const sidePanel = this.$refs.sidePanelRef;

  if (chatArea) chatArea.style.width = '';
  if (sidePanel) sidePanel.style.width = '';

  this.sidePanelOpen = false;
  this.chatAreaOpen = true;
  this.chatAreaWidth = 100;
  this.sidePanelWidth = 0;

  this.updatePanelWidths();
},

  // 展开对话区域
  expandChatArea() {
    this.chatAreaOpen = true;
    this.chatAreaWidth = 50;
    this.sidePanelWidth = 50;
    this.updatePanelWidths();
  },

  // 展开侧边栏
  expandSidePanel() {
    this.sidePanelOpen = true;
    this.chatAreaWidth = 50;
    this.sidePanelWidth = 50;
    this.updatePanelWidths();
  },

  // 重置面板大小
  resetPanelSizes() {
    this.chatAreaWidth = 50;
    this.sidePanelWidth = 50;
    this.chatAreaOpen = true;
    this.sidePanelOpen = true;
    this.updatePanelWidths();
  },

  // 更新面板宽度样式
  updatePanelWidths() {
    this.$nextTick(() => {
      const chatArea = this.$refs.chatAreaRef;
      const sidePanel = this.$refs.sidePanelRef;
      
      if (!chatArea || !sidePanel) return;
      
      // ✨ 清除之前可能遗留的 px 宽度
      chatArea.style.width = '';
      sidePanel.style.width = '';
      
      if (this.chatAreaOpen && this.sidePanelOpen) {
        chatArea.style.width = `${this.chatAreaWidth}%`;
        sidePanel.style.width = `${this.sidePanelWidth}%`;
      } else if (this.chatAreaOpen) {
        chatArea.style.width = '100%';
      } else if (this.sidePanelOpen) {
        sidePanel.style.width = '100%';
      }
      
      // 🔧 关键修复：强制浏览器重排（读取布局属性）
      sidePanel.offsetWidth;   // 或者 chatArea.offsetWidth
    });
  },

  // 处理窗口大小变化
  handleResize() {
    if (this.chatAreaOpen && this.sidePanelOpen) {
      this.updatePanelWidths();
    }
  },
  // 修改 openExtensionInWindow 方法
  async openExtensionInWindow(extension) {
    const url = await this.getExtensionURL(extension);   // ⬅️ 同样先启动/拿地址

    // 下面逻辑你原来就有，只把 url 换成异步得到的即可
    this.showExtensionsDialog = false;
    let windowWidth = 800;
    let windowHeight = 600;
    if (window.electronAPI && window.electronAPI.openExtensionWindow) {
      try {
        if (extension.enableVrmWindowSize){
          console.log('VRM window size enabled')
          windowWidth = this.VRMConfig.windowWidth;
          windowHeight = this.VRMConfig.windowHeight
        }
        else{
          windowWidth = extension.width || 800;
          windowHeight = extension.height || 600;
        }
        const windowId = await window.electronAPI.openExtensionWindow(`${this.partyURL}${url}`, {
          id: extension.id,
          name: extension.name,
          transparent: extension.transparent || false,
          width: windowWidth,
          height: windowHeight,
        });
        console.log(`Extension window opened with ID: ${windowId}`);
      } catch (error) {
        console.error('Failed to open extension window:', error);
        window.open(`${this.partyURL}${url}`, '_blank');
      }
    } else {
      window.open(`${this.partyURL}${url}`, '_blank');
    }
  },
  async sherpaModelStatus() {
    const res = await fetch('/sherpa-model/status')
    if (!res.ok) return
    const { exists, model } = await res.json()
    this.sherpaModelExists = exists
    this.sherpaModelName  = model ?? ''   // 后端没返回时留空
  },

  async sherpaDownload(source = 'modelscope') {
      if (this.sherpaEventSource) this.sherpaEventSource.close()
      this.sherpaDownloading = true
      this.sherpaPercent = 0
      
      // 确保在 EventSource 实例化之前设置状态
      this.sherpaEventSource = null

      const es = new EventSource(`/sherpa-model/download/${source}`)
      this.sherpaEventSource = es
      
      // 监听消息流
      es.onmessage = e => {
          let data
          try {
              data = JSON.parse(e.data)
          } catch (error) {
              console.error('Failed to parse download progress data:', e.data, error)
              return
          }

          // --------------------------------------
          // 核心修复逻辑：处理多文件聚合进度
          // --------------------------------------
          
          // 1. 检查下载是否完成或失败
          if (data.status === 'complete') {
              es.close()
              this.sherpaDownloading = false
              this.sherpaPercent = 100
              this.sherpaModelStatus()
              showNotification(this.t('modelDownloadSuccess'))
              return
          }

          if (data.status === 'failed') {
              es.close()
              this.sherpaDownloading = false
              showNotification(this.t('modelDownloadFailed') + (data.error || ''), 'error')
              return
          }

          // 2. 聚合所有文件的进度
          let totalDone = 0
          let grandTotal = 0

          if (data.files && data.files.length > 0) {
              data.files.forEach(file => {
                  totalDone += file.done || 0
                  grandTotal += file.total || 0
                  // 检查是否有任何单个文件失败
                  if (file.failed) {
                      es.close()
                      this.sherpaDownloading = false
                      showNotification(this.t('modelDownloadFailed') + `: ${file.filename} 失败`, 'error')
                  }
              })
          }

          // 3. 计算整体百分比
          this.sherpaPercent = grandTotal > 0 ? Math.round((totalDone / grandTotal) * 100) : 0
      }
      
      // 监听错误
      es.onerror = () => {
          // 如果 EventSource 在没有收到 close 消息的情况下关闭，通常意味着错误
          es.close()
          this.sherpaDownloading = false
          showNotification(this.t('modelDownloadFailed'), 'error')
          this.sherpaModelStatus() // 再次检查状态，以防实际已下载完成
      }
  },

  async sherpaRemove() {
    try {
      const res = await fetch('/sherpa-model/remove', { method: 'DELETE' })
      if (!res.ok) throw new Error()
      showNotification(this.t('deleteSuccess'))
      this.sherpaModelStatus()
    } catch {
      showNotification(this.t('deleteFailed'),'error')
    }
  },

  async loadSherpaStatus() {
    await this.sherpaModelStatus()
  },

// 1. 获取 MOSS 模型状态
  async mossModelStatus() {
    try {
      const res = await fetch('/moss-model/status')
      if (!res.ok) return
      const data = await res.json()
      this.mossModelExists = data.exists
      
      // 同步后台下载状态（比如刷新页面后恢复 UI）
      if (data.downloading) {
        this.mossDownloading = true
        // 自动恢复轮询
        if (!this.mossPollInterval) this.startMossPolling()
      } else {
        this.mossDownloading = false
      }
    } catch (e) {
      console.error('Failed to get MOSS status:', e)
    }
  },

// 触发下载时把进度清零
  async mossDownload(source = 'modelscope') {
    this.mossDownloading = true
    this.mossDownloadSource = source
    this.mossPercent = 0 // 初始化为 0
    
    try {
      const res = await fetch(`/moss-model/download/${source}`, { method: 'POST' })
      if (!res.ok) throw new Error('Network error')
      this.startMossPolling()
    } catch (e) {
      this.mossDownloading = false
      showNotification(this.t('modelDownloadFailed') || '下载失败', 'error')
    }
  },

  startMossPolling() {
    if (this.mossPollInterval) clearInterval(this.mossPollInterval)
    
    this.mossPollInterval = setInterval(async () => {
      try {
        const statusRes = await fetch('/moss-model/status')
        const data = await statusRes.json()
        
        // 更新真实进度 (后台根据文件夹大小计算出的)
        if (data.percent !== undefined) {
          this.mossPercent = data.percent
        }
        
        if (!data.downloading) {
          clearInterval(this.mossPollInterval)
          this.mossPollInterval = null
          this.mossDownloading = false
          this.mossModelExists = data.exists
          
          if (data.exists) {
            this.mossPercent = 100 // 完成强制打满
            showNotification(this.t('modelDownloadSuccess') || 'MOSS 模型下载成功')
          } else if (data.download_error) {
            showNotification((this.t('modelDownloadFailed') || '下载失败: ') + data.download_error, 'error')
          }
        }
      } catch (err) {
        console.error('MOSS Polling error', err)
      }
    }, 1000) // 每 1 秒轮询一次，让进度条更顺滑
  },

  // 4. 删除 MOSS 模型
  async mossRemove() {
    try {
      const res = await fetch('/moss-model/remove', { method: 'DELETE' })
      if (!res.ok) throw new Error()
      showNotification(this.t('deleteSuccess') || '模型删除成功')
      this.mossModelExists = false
    } catch {
      showNotification(this.t('deleteFailed') || '模型删除失败', 'error')
    }
  },

  // 5. 在初始化时调用 (类似于 loadSherpaStatus)
  async loadMossStatus() {
    await this.mossModelStatus()
  },

    /**
     * 检查 MiniLM 模型状态 (是否存在)
     */
    async minilmModelStatus() {
        try {
            const res = await fetch('/minilm-model/status');
            if (!res.ok) throw new Error('Failed to fetch status');
            const data = await res.json();
            this.minilmModelExists = data.exists;
        } catch (error) {
            console.error("Error checking MiniLM model status:", error);
            this.minilmModelExists = false; // 假设网络错误导致无法检查，也视为不存在
        }
    },

    /**
     * 下载 MiniLM 模型
     * @param {string} source - 下载源: 'modelscope' 或 'huggingface'
     */
    async minilmDownload(source = 'modelscope') {
        if (this.minilmEventSource) this.minilmEventSource.close();
        
        this.minilmDownloading = true;
        this.minilmPercent = 0;
        this.minilmEventSource = null;

        const es = new EventSource(`/minilm-model/download/${source}`);
        this.minilmEventSource = es;
        
        // 监听消息流
        es.onmessage = async e => {
            let data;
            try {
                // 后端会发送 JSON 格式的进度数据
                data = JSON.parse(e.data);
            } catch (error) {
                // 后端可能会发送 'close' 这样的非 JSON 消息
                if (e.data === 'close') {
                    es.close();
                }
                console.error('Failed to parse download progress data:', e.data, error);
                return;
            }

            // 1. 检查下载是否完成或失败
            if (data.status === 'complete') {
                es.close();
                this.minilmDownloading = false;
                this.minilmPercent = 100;

                // 1. 通知后端热重载
                await fetch('/minilm/reload', { method: 'POST' });

                // 2. 再刷新一次存在状态（此时一定为 true）
                await this.minilmModelStatus();

                if (typeof showNotification === 'function') {
                    showNotification(this.t('modelDownloadSuccess'));
                }
                return;
            }

            if (data.status === 'failed') {
                es.close();
                this.minilmDownloading = false;
                // 尝试从 files 列表中提取具体的错误信息
                const firstError = data.files.find(f => f.failed)?.error || '';
                if (typeof showNotification === 'function') {
                    showNotification(this.t('modelDownloadFailed') + (firstError ? `: ${firstError}` : ''), 'error');
                }
                return;
            }

            // 2. 聚合所有文件的进度
            let totalDone = 0;
            let grandTotal = 0;

            if (data.files && data.files.length > 0) {
                let hasFailedFile = false;
                data.files.forEach(file => {
                    totalDone += file.done || 0;
                    grandTotal += file.total || 0;
                    
                    // 检查是否有任何单个文件失败 (后端已经在 status='failed' 中处理了，这里做冗余检查)
                    if (file.failed) {
                        hasFailedFile = true;
                    }
                });

                if (hasFailedFile) {
                      // 如果检测到文件失败，但 status 还没有被后端更新为 'failed'，则手动关闭和报错
                      es.close();
                      this.minilmDownloading = false;
                      const failedFile = data.files.find(f => f.failed);
                      if (typeof showNotification === 'function') {
                        showNotification(this.t('modelDownloadFailed') + `: ${failedFile.filename} 失败`, 'error');
                      }
                      return;
                }
            }

            // 3. 计算整体百分比
            this.minilmPercent = grandTotal > 0 ? Math.round((totalDone / grandTotal) * 100) : 0;
        };
        
        // 监听错误
        es.onerror = () => {
            // 如果 EventSource 在没有收到 close 消息的情况下关闭，通常意味着错误
            if (this.minilmEventSource) {
                this.minilmEventSource.close();
            }
            this.minilmDownloading = false;
            if (typeof showNotification === 'function') {
                showNotification(this.t('modelDownloadFailed') + ' (Network/Connection Error)', 'error');
            }
            this.minilmModelStatus(); // 再次检查状态，以防实际已下载完成
        };
    },

    /**
     * 删除本地 MiniLM 模型
     */
    async minilmRemove() {
        try {
            // 使用 Element Plus 确认对话框来增加安全性（如果可用）
            // 示例：await this.$confirm('确定删除 MiniLM 模型吗？', '警告', { type: 'warning' })

            const res = await fetch('/minilm-model/remove', { method: 'DELETE' });
            if (!res.ok) throw new Error();
            
            if (typeof showNotification === 'function') {
                showNotification(this.t('deleteSuccess'));
            }
            this.minilmModelStatus(); // 刷新模型存在状态
        } catch (error) {
            if (typeof showNotification === 'function') {
                showNotification(this.t('deleteFailed') + (error.message || ''), 'error');
            }
        }
    },

  async updatePlugin(plugin) {
    // 临时响应式标记
    plugin._updating = true // 发送更新请求
    try {
      const res = await fetch(`/api/extensions/${plugin.id}/update`, { method: 'PUT' })
      if (!res.ok) throw new Error(await res.text())
      showNotification(this.t('updateSuccess'))
      // 更新完后刷新本地列表，重新标 installed 状态
      this.fetchRemotePlugins();
    } catch (e) {
      showNotification(this.t('updateFailed') + ': ' + e.message, 'error')
    } finally {
      plugin._updating = false
    }
  },

    // 打开向量库交互主弹窗
    async openVectorDialog(mid) {
      this.vectorDialogVisible = true
      this.vectorDialogMemoryId = mid
      // 取 memory 名字只是为了标题展示
      this.vectorDialogMemoryName = this.memories.find(m => m.id === mid)?.name || mid
      await this.loadVectorTable(mid)
    },

    // 读取记忆内容
    async loadVectorTable(mid) {
      this.vectorLoading = true
      try {
        const res = await fetch(`/memory/${mid}`)
        if (!res.ok) throw new Error(await res.text())
        // 后端已平铺，直接赋值
        this.vectorTable = await res.json()
      } catch (e) {
        this.vectorTable = []
        console.error(e)
      } finally {
        this.vectorLoading = false
      }
    },

    // 新增记忆（C-5：此前为空 fetch 残壳=按钮静默必败，后端已补 POST /memory/{id}）
    async addVectorRow() {
      if (!this.newVectorText.trim()) return
      try {
        const mid = this.vectorDialogMemoryId
        const res = await fetch(`/memory/${mid}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: this.newVectorText.trim() })
        })
        if (!res.ok) throw new Error(await res.text())
        this.newVectorText = ''
        await this.loadVectorTable(mid)
      } catch (e) {
        showNotification(e.message, 'error')
      } finally {
        this.vectorLoading = false
      }
    },

  startEditRow(tableIndex) {
    const row = this.vectorTable[tableIndex]
    this.editRowIdx = row.idx
    this.editRowText = row.text
    this.editRowVisible = true
  },
  async submitEditRow() {
    if (!this.editRowText.trim()) return
    try {
      const mid = this.vectorDialogMemoryId
      const res = await fetch(`/memory/${mid}/${this.editRowIdx}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_text: this.editRowText.trim() })
      })
      if (!res.ok) throw new Error(await res.text())
      this.editRowVisible = false
      await this.loadVectorTable(mid)
    } catch (e) {
      showNotification(e.message, 'error')
    }
  },
  async deleteVectorRow(idx) {
    try {
      const mid = this.vectorDialogMemoryId
      const res = await fetch(`/memory/${mid}/${idx}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      await this.loadVectorTable(mid)
    } catch (e) {
      showNotification(e.message, 'error')
    }
  },
  /* 探针 */
  async probeNode() {
    const res = await fetch('/api/node/probe');
    const { installed } = await res.json();
    this.nodeInstalled = installed;
  },

    /* ===== uv 相关 ===== */
  async probeUv() {
    const res = await fetch('/api/uv/probe');
    const { installed } = await res.json();
    this.uvInstalled = installed;
  },

  async openLogDialog() {
    this.showLogDialog = true;
    await this.fetchLogs();
    // 自动滚动到底部
    this.$nextTick(() => {
      if (this.$refs.logContainer) {
        this.$refs.logContainer.scrollTop = this.$refs.logContainer.scrollHeight;
      }
    });
  },

  async fetchLogs() {
    if (window.electronAPI) {
      try {
        this.logContent = await window.electronAPI.getBackendLogs();
      } catch (e) {
        this.logContent = 'Failed to load logs: ' + e.message;
      }
    }
  },
  async fetchSystemVoices() {
      this.isLoadingSystemVoices = true;
      try {
        // 使用 fetch API 调用后端接口
        const response = await fetch('/system/voices'); // 请根据你的API前缀调整
        
        if (!response.ok) {
            // 处理 HTTP 错误状态（如 404, 500）
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data && data.voices) {
          this.systemVoices = data.voices;
          
          // 如果当前没有选中的音色，或者选中的音色不在列表里，默认选中第一个
          const currentVoiceValid = this.systemVoices.some(v => v.id === this.ttsSettings.systemVoiceName);
          if (!this.ttsSettings.systemVoiceName || !currentVoiceValid) {
             if (this.systemVoices.length > 0) {
               this.ttsSettings.systemVoiceName = this.systemVoices[0].id;
               this.autoSaveSettings(); // 保存默认选择
             }
          }
        }
      } catch (error) {
        console.error("获取系统音色失败:", error);
        if (this.$message) {
           this.$message.error(`获取系统音色列表失败: ${error.message}`);
        }
      } finally {
        this.isLoadingSystemVoices = false;
      }
    },

  addTableEnhancements() {
    this.$nextTick(() => {
      const tables = document.querySelectorAll('.markdown-body table');
      
      tables.forEach((table) => {
        if (table.parentElement.classList.contains('markdown-table-wrapper')) return;

        // 1. 创建容器
        const wrapper = document.createElement('div');
        wrapper.className = 'markdown-table-wrapper';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);

        // 2. 创建按钮
        const btn = document.createElement('button');
        btn.className = 'table-download-btn';
        // 使用 fa-file-excel 图标，更直观
        btn.innerHTML = '<i class="fa-solid fa-file-excel"></i> XLSX';
        btn.title = '导出为 Excel 文件';
        
        // 3. 绑定点击事件 (调用新的 exceljs 逻辑)
        btn.onclick = async (e) => {
          e.stopPropagation();
          // 添加加载状态反馈（可选）
          const originalText = btn.innerHTML;
          btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 导出中...';
          btn.disabled = true;
          
          try {
            await this.downloadTableAsXLSX(table);
          } catch (error) {
            console.error('Excel 导出失败:', error);
            this.$message?.error('导出失败，请重试');
          } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
          }
        };

        wrapper.appendChild(btn);
      });
    });
  },

  // 全局点击事件代理
  handleGlobalClick(event) {
    // 1. 检查点击的是否是 Excel 导出按钮
    // closest 处理用户可能点到图标 <i> 的情况
    const btn = event.target.closest('.download-xlsx-trigger');
    
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      
      // 找到同级的前一个兄弟元素 (即 table)
      // 根据上面 markdown-it 的结构: <table>...</table> <button>...</button>
      // 所以 button.previousElementSibling 就是 table
      const table = btn.previousElementSibling;
      
      if (table && table.tagName === 'TABLE') {
        this.exportTable(btn, table);
      }
    }
  },

    handleMessageLinkClick(event) {
        // 1. 如果你原有的 handleGlobalClick 有逻辑（比如点击空白处关闭菜单），在这里调用它
        this.handleGlobalClick(event); 

        if(isElectron){

          const link = event.target.closest('a');

          if (link && link.href) {
              const href = link.href;

              // 2. 过滤逻辑：只拦截 http/https 网络链接
              if (href.startsWith('http') || href.startsWith('https')) {
                  
                  // ★ 关键：同时调用 stopPropagation 和 preventDefault
                  event.preventDefault();  // 阻止链接默认跳转
                  event.stopPropagation(); // 阻止事件继续传播
                  
                  // 3. 打开内部浏览器
                  console.log('拦截到链接，正在内部浏览器打开:', href);
                  this.openUrlInNewTab(href);
              }
          }
        
        }

    },

  // 这里的逻辑跟您原来的 click 类似，只是参数变了
  async exportTable(btn, tableElement) {
    if (btn.disabled) return; // 防止重复点击

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 导出中...';
    btn.disabled = true;

    try {
      await this.downloadTableAsXLSX(tableElement);
    } catch (error) {
      console.error('导出失败', error);
      // 如果有 Element Plus
      if (this.$message) this.$message.error('导出失败');
    } finally {
      btn.innerHTML = originalHtml;
      btn.disabled = false;
    }
  },

  /**
   * 使用 ExcelJS 生成真正的 .xlsx 文件
   */
  async downloadTableAsXLSX(tableElement) {
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet('数据导出');

    // --- 1. 提取 HTML 表格数据 ---
    const rows = tableElement.querySelectorAll('tr');
    
    // 遍历 HTML 行
    rows.forEach((row, rowIndex) => {
      const cells = row.querySelectorAll('td, th');
      const rowData = [];
      
      cells.forEach(cell => {
        // 获取纯文本
        rowData.push(cell.innerText.trim());
      });
      
      // 添加到 Worksheet
      const excelRow = worksheet.addRow(rowData);
    });

    // --- 2. 美化 Excel 样式 (Pro 模式) ---
    
    // 2.1 设置表头样式 (第一行)
    const headerRow = worksheet.getRow(1);
    headerRow.font = { 
      name: '微软雅黑', 
      bold: true, 
      color: { argb: 'FFFFFFFF' } // 白字
    };
    headerRow.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF1E849B' } // 使用你的主题色 (深青色)
    };
    headerRow.alignment = { vertical: 'middle', horizontal: 'center' };

    // 2.2 自动计算列宽
    worksheet.columns.forEach(column => {
      let maxLength = 0;
      column.eachCell({ includeEmpty: true }, cell => {
        const columnLength = cell.value ? cell.value.toString().length : 10;
        if (columnLength > maxLength) maxLength = columnLength;
      });
      // 限制最大宽度，防止太宽
      column.width = maxLength < 10 ? 10 : (maxLength > 50 ? 50 : maxLength + 2);
    });

    // 2.3 添加边框
    worksheet.eachRow((row, rowNumber) => {
      row.eachCell((cell) => {
        cell.border = {
          top: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          left: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          bottom: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          right: { style: 'thin', color: { argb: 'FFDCDFE6' } }
        };
        // 内容垂直居中
        cell.alignment = { ...cell.alignment, vertical: 'middle', wrapText: true };
      });
    });

    // --- 3. 生成并下载文件 ---
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[-T:]/g, "");
    link.href = URL.createObjectURL(blob);
    link.download = `table_export_${timestamp}.xlsx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
  },

    // [A2UI 新增] 处理用户点击操作
    handleA2UIAction(msg) {
      console.log('A2UI Action Triggered:', msg);
      this.userInput = msg;
      this.sendMessage();
    },

    // [A2UI 新增] 拆分消息内容为 文本/UI 段
    splitMessageContent(content) {
      if (!content) return [];
      const segments = [];
      const regex = /```a2ui\s*([\s\S]*?)\s*```/g;
      
      let lastIndex = 0;
      let match;

      while ((match = regex.exec(content)) !== null) {
        if (match.index > lastIndex) {
          const textPart = content.slice(lastIndex, match.index);
          if (textPart) segments.push({ type: 'text', content: textPart });
        }

        try {
          const uiConfig = JSON.parse(match[1]);
          segments.push({ type: 'ui', content: uiConfig });
        } catch (e) {
          segments.push({ type: 'text', content: match[0] });
        }
        lastIndex = regex.lastIndex;
      }

      if (lastIndex < content.length) {
        segments.push({ type: 'text', content: content.slice(lastIndex) });
      }

      return segments;
    },

    async fetchTetosNewVoices(provider) {
        this.newTTSConfig.isFetchingVoices = true;
        this.newTTSConfig.tetosVoices = []; // 清空现有列表
        
        let config = {};
        const s = this.newTTSConfig;

        // 根据 provider 构建 config
        switch(provider) {
            case 'azure':
                config = { speech_key: s.azureSpeechKey, speech_region: s.azureRegion };
                break;
            case 'volcengine':
                config = { access_key: s.volcAccessKey, secret_key: s.volcSecretKey, app_key: s.volcAppKey };
                break;
            case 'baidu':
                config = { api_key: s.baiduApiKey, secret_key: s.baiduSecretKey };
                break;
            case 'minimax':
                config = { api_key: s.minimaxApiKey, group_id: s.minimaxGroupId };
                break;
            case 'xunfei':
                config = { app_id: s.xunfeiAppId, api_key: s.xunfeiApiKey, api_secret: s.xunfeiApiSecret };
                break;
            case 'fish':
                config = { api_key: s.fishApiKey };
                break;
            case 'google':
                // 尝试解析 JSON 字符串
                try {
                    if (s.googleServiceAccount) {
                         config = { service_account: JSON.parse(s.googleServiceAccount) };
                    }
                } catch (e) {
                    this.newTTSConfig.isFetchingVoices = false;
                    return;
                }
                break;
        }

        try {
            const response = await fetch('/tts/tetos/list_voices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: provider, config: config })
            });
            const result = await response.json();
            
            if (result.status === 'success') {
                this.newTTSConfig.tetosVoices = result.data;
            } else {
                console.error(result);
            }
        } catch (error) {
            console.error('Error fetching voices:', error);
        } finally {
            this.newTTSConfig.isFetchingVoices = false;
        }
    },

    async fetchTetosVoices(provider) {
        this.ttsSettings.isFetchingVoices = true;
        this.ttsSettings.tetosVoices = []; // 清空现有列表
        
        let config = {};
        const s = this.ttsSettings;

        // 根据 provider 构建 config
        switch(provider) {
            case 'azure':
                config = { speech_key: s.azureSpeechKey, speech_region: s.azureRegion };
                break;
            case 'volcengine':
                config = { access_key: s.volcAccessKey, secret_key: s.volcSecretKey, app_key: s.volcAppKey };
                break;
            case 'baidu':
                config = { api_key: s.baiduApiKey, secret_key: s.baiduSecretKey };
                break;
            case 'minimax':
                config = { api_key: s.minimaxApiKey, group_id: s.minimaxGroupId };
                break;
            case 'xunfei':
                config = { app_id: s.xunfeiAppId, api_key: s.xunfeiApiKey, api_secret: s.xunfeiApiSecret };
                break;
            case 'fish':
                config = { api_key: s.fishApiKey };
                break;
            case 'google':
                // 尝试解析 JSON 字符串
                try {
                    if (s.googleServiceAccount) {
                         config = { service_account: JSON.parse(s.googleServiceAccount) };
                    }
                } catch (e) {
                    this.ttsSettings.isFetchingVoices = false;
                    return;
                }
                break;
        }

        try {
            const response = await fetch('/tts/tetos/list_voices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider: provider, config: config })
            });
            const result = await response.json();
            
            if (result.status === 'success') {
                this.ttsSettings.tetosVoices = result.data;
            } else {
                console.error(result);
            }
        } catch (error) {
            console.error('Error fetching voices:', error);
        } finally {
            this.ttsSettings.isFetchingVoices = false;
        }
    },

    // 1. 获取音色显示名称 (Label)
    getVoiceLabel(v) {
        // 情况 A: 数据是纯字符串 (你刚才展示的情况)
        if (typeof v === 'string') return v;
        
        // 情况 B: 数据是对象 (Azure等)
        if (v && typeof v === 'object') {
            // 优先查找显示名称，如果没有则找 id 或 name
            return v.DisplayName || v.local_name || v.name || v.Name || v.id || v.Id || v.ShortName || 'Unknown Voice';
        }
        return 'Unknown';
    },

    // 2. 获取音色实际值 (Value - 传给后端的)
    getVoiceValue(v) {
        // 情况 A: 纯字符串
        if (typeof v === 'string') return v;
        
        // 情况 B: 对象
        if (v && typeof v === 'object') {
            return v.ShortName || v.id || v.Id || v.name || '';
        }
        return '';
    },

    // 3. 获取辅助信息 (显示在右侧的灰色小字，如语言)
    getVoiceDesc(v) {
        // 纯字符串没有额外信息，返回空
        if (typeof v === 'string') return '';
        
        // 对象可能包含语言信息
        if (v && typeof v === 'object') {
            const lang = v.Locale || v.locale || v.Language || v.language || (v.language_codes ? v.language_codes[0] : '');
            return lang ? `[${lang}]` : '';
        }
        return '';
    },


    // AI浏览器相关
    openUrlInNewTab(url) {
        // 如果 url 为空或者无效，可以做个判断，或者直接打开
        if (!url) return;

        const newTab = {
            id: Date.now(),
            title: 'Loading...',
            url: url,
            favicon: '',
            isLoading: true,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
        this.activeMenu = 'ai-browser';
    },

    // 切换标签
    switchTab(id) {
        this.currentTabId = id;
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) {
            // --- ✅ 修改此处 ---
            // 优先显示页面实际所在的 currentUrl，否则显示 tab.url
            this.urlInput = tab.currentUrl || tab.url;
            
            // 如果是欢迎页，清空地址栏显示
            if (!tab.url) this.urlInput = '';
        }
    },

    // 添加新标签
    addNewTab() {
        const newTab = {
            id: Date.now(),
            title: 'New Tab',
            url: '',
            favicon: '',
            isLoading: false,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
    },

    // 关闭标签
    closeTab(id, event) {
        if (event) event.stopPropagation(); // 防止触发点击切换
        
        const index = this.browserTabs.findIndex(t => t.id === id);
        if (index === -1) return;

        // 如果关闭的是当前标签，需要切换到另一个
        if (this.currentTabId === id) {
            if (this.browserTabs.length > 1) {
                // 优先切到右边，没右边切左边
                const nextTab = this.browserTabs[index + 1] || this.browserTabs[index - 1];
                this.currentTabId = nextTab.id;
                this.urlInput = nextTab.url;
            } else {
                // 如果只剩这一个，重置它而不是删除
                this.addNewTab(); // 加个新的
                this.browserTabs.splice(index, 1); // 删掉旧的
                return;
            }
        }
        
        this.browserTabs.splice(index, 1);
    },

    // 地址栏回车
    handleUrlEnter() {
        let val = this.urlInput.trim();
        if (!val) return;

        // 简单的 URL 补全逻辑
        if (!/^https?:\/\//i.test(val)) {
            // 如果看起来像域名
            if (/^([\w-]+\.)+[\w-]+/.test(val) && !val.includes(' ')) {
                val = 'https://' + val;
            } else {
                // 否则当做搜索
                if (this.searchEngine === 'google') {
                    val = `https://www.google.com/search?q=${encodeURIComponent(val)}`;
                } else if (this.searchEngine === 'bing') {
                    val = `https://www.bing.com/search?q=${encodeURIComponent(val)}`;
                } else {
                    if (this.chromeMCPSettings.enabled == false || this.chromeMCPSettings.type != 'internal') {
                        showNotification(this.t('notEnabledInternalBrowserBontrol'), 'error')
                    }
                    this.showBrowserChat = true;
                    this.userInput = val;
                    this.sendMessage();
                    return;
                }
            }
        }

        this.navigateTo(val);
    },

    getTabIdByIndex(index) {
        if (index >= 0 && index < this.browserTabs.length) {
            return this.browserTabs[index].id;
        }
        return null;
    },

    // 欢迎页搜索回车
    handleWelcomeSearch() {
        const query = this.welcomeSearchQuery.trim();
        this.welcomeSearchQuery = ''; // 清空输入框
        if (!query) return;

        // --- 新增逻辑：URL 检测与直接跳转 ---
        if (this.isUrl(query)) {
            let targetUrl = query;
            // 如果没有以 http:// 或 https:// 开头，默认补全 https://
            if (!/^https?:\/\//i.test(targetUrl)) {
                targetUrl = 'https://' + targetUrl;
            }
            this.navigateTo(targetUrl);
            return;
        }
        // ------------------------------------

        let searchUrl = '';
        if (this.searchEngine === 'google') {
            searchUrl = `https://www.google.com/search?q=${encodeURIComponent(query)}`;
        } else if (this.searchEngine === 'bing') {
            searchUrl = `https://www.bing.com/search?q=${encodeURIComponent(query)}`;
        } else {
            if (this.chromeMCPSettings.enabled == false || this.chromeMCPSettings.type != 'internal') {
                showNotification(this.t('notEnabledInternalBrowserBontrol'), 'error')
            }
            this.showBrowserChat = true;
            this.userInput = query;
            this.sendMessage();
            return;
        }

        this.navigateTo(searchUrl);
    },

    /**
     * 辅助函数：判断字符串是否为 URL
     * 规则：
     * 1. 以 http/https 开头
     * 2. 或者符合 域名.后缀 (如 google.com)
     * 3. 或者 localhost
     * 4. 或者 IP 地址
     * 5. 且不包含空格
     */
    isUrl(str) {
        // 简单判断：如果包含空格，通常是搜索词（除非是编码后的URL，但用户输入通常带空格）
        if (str.includes(' ')) return false;

        // 正则解释：
        // ^(https?:\/\/)?  -> 可选的 http:// 或 https://
        // (
        //   ([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}  -> 标准域名 (如 a.com, b.co.uk)
        //   | localhost                     -> 本地 localhost
        //   | (\d{1,3}\.){3}\d{1,3}         -> IP 地址 (如 192.168.1.1)
        // )
        // (:\d+)?          -> 可选端口号 (如 :8080)
        // (\/.*)?$         -> 可选路径
        const pattern = /^(https?:\/\/)?(([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}|localhost|(\d{1,3}\.){3}\d{1,3})(:\d+)?(\/.*)?$/i;
        
        return pattern.test(str);
    },

    // 核心导航方法
    navigateTo(url) {
        if (!this.currentTab) return;
        
        // 如果是刷新当前页面（URL 没变）
        // 注意：这里比较时最好也比较 currentUrl
        const activeUrl = this.currentTab.currentUrl || this.currentTab.url;
        
        if (activeUrl === url) {
            // ... (保持原有的 reload 逻辑)
            const wv = document.getElementById('webview-' + this.currentTabId);
            if (wv) wv.reload();
            return;
        }

        // 2. 如果是新 URL
        this.currentTab.url = url;      // 这会触发 :src 更新，开始加载
        this.currentTab.currentUrl = url; // 同步更新实际地址状态
        this.urlInput = url;
    },
    
    // 回到主页 (新标签页)
    goHome() {
        if(this.currentTab) {
            this.currentTab.url = '';
            this.currentTab.title = 'New Tab';
            this.currentTab.favicon = '';
            this.urlInput = '';
        }
    },

    // --- Webview 导航控制 ---
    getWebview(id) {
        const wv = document.getElementById('webview-' + (id || this.currentTabId));
        
        // 1. 基础非空检查
        if (!wv) {
            console.warn("getWebview: Element not found for ID", id || this.currentTabId);
            return null;
        }

        // 2. ★ 核心修改：检查元素是否真正连接在 DOM 树上
        // 如果元素存在但 isConnected 为 false，说明 Vue 正在销毁它或还没挂载好
        // 此时返回 null，让 Python 端捕获 "No active webview" 错误并触发重试
        if (!wv.isConnected) {
            console.warn("getWebview: Element found but detached from DOM (Zombie node).");
            return null;
        }

        // 3. (可选) 检查 Electron 内部状态
        // getWebContentsId 是 Electron webview 的原生方法，如果报错说明内部未初始化
        try {
            if (typeof wv.getWebContentsId !== 'function') {
                return null;
            }
        } catch (e) {
            return null;
        }

        return wv;
    },

    browserGoBack() {
        const wv = this.getWebview();
        if (wv && wv.canGoBack()) wv.goBack();
    },

    browserGoForward() {
        const wv = this.getWebview();
        if (wv && wv.canGoForward()) wv.goForward();
    },

    browserReload() {
        const wv = this.getWebview();
        if(!wv) return;
        if (this.currentTab.isLoading) {
            wv.stop();
        } else {
            wv.reload();
        }
    },

    // --- Webview 事件监听 ---
    // 注意：这些事件在 HTML 中通过 @did-start-loading="..." 绑定
    
    onDidStartLoading(id) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) tab.isLoading = true;
    },

    // 修改前
    onDidStopLoading(id) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) {
            tab.isLoading = false;
            const wv = document.getElementById('webview-' + id);
            if (wv) {
                tab.canGoBack = wv.canGoBack();
                tab.canGoForward = wv.canGoForward();
                
                // --- ✅ 修正后的代码 ---
                if (wv.getURL()) {
                    // 1. 将实际 URL 存入一个新字段，不触碰 tab.url (src)
                    tab.currentUrl = wv.getURL(); 
                    
                    // 2. 只更新顶部的地址栏 UI
                    if (this.currentTabId === id) {
                        this.urlInput = tab.currentUrl;
                    }
                }
            }
        }
    },

    onPageTitleUpdated(id, event) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab) tab.title = event.title;
    },

    onPageFaviconUpdated(id, event) {
        const tab = this.browserTabs.find(t => t.id === id);
        if (tab && event.favicons && event.favicons.length > 0) {
            tab.favicon = event.favicons[0];
        }
    },

    // 处理网页内部 window.open
    onNewWindow(id, event) {
        // 在应用内新建标签页打开，而不是弹出新窗口
        const { url } = event;
        const newTab = {
            id: Date.now(),
            title: 'Loading...',
            url: url,
            favicon: '',
            isLoading: true,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
    },
    
    // 在 methods 中添加或修改 onDomReady
    onDomReady(tabId) {
        const webview = document.getElementById('webview-' + tabId);
        if (!webview) return;

        webview.addEventListener('context-menu', (e) => {
            // ★★★ 关键调试点：打印出 Electron 传来的所有参数 ★★★
            console.log('Webview Context Menu Params:', e.params);
            
            const params = e.params;
            let menuType = 'default';
            let data = {};

            // 重新审视和调整判断逻辑的顺序，确保最具体的匹配优先
            if (params.mediaType === 'image' && params.srcURL && params.srcURL.length > 0) {
                menuType = 'image';
                data = { src: params.srcURL };
                console.log('Detected Image Context:', data); // 调试
            } else if (params.linkURL && params.linkURL.length > 0) {
                menuType = 'link';
                data = { 
                    url: params.linkURL, 
                    text: params.linkText || params.selectionText || '' 
                };
                console.log('Detected Link Context:', data); // 调试
            } else if (params.selectionText && params.selectionText.length > 0) {
                menuType = 'text';
                data = { text: params.selectionText };
                console.log('Detected Text Context:', data); // 调试
            } else {
                menuType = 'default';
                console.log('Detected Default Context'); // 调试
            }

            // 再次打印最终决定发送的类型和数据
            console.log(`Sending context menu request: Type = ${menuType}, Data =`, data);

            window.electronAPI.showContextMenu(menuType, data);
        });
        webview.send('set-i18n', {
            translate: this.t('translate') || '翻译',
            askAI: this.t('ask_ai') || '问 AI',
            read: this.t('read') || '朗读',
            copy: this.t('copy') || '复制'
        });
        //webview.openDevTools();
    },

    // 1. 修改 IPC 消息处理函数
    async handleWebviewIpcMessage(event) {
        if (event.channel === 'ai-toolbar-action') {
            const { action, text } = event.args[0];
            if (!text) return;

            // 获取 webview 实例，用于回传数据
            // 注意：event.target 就是 webview 元素
            const webview = event.target; 

            switch (action) {
                case 'translate':
                    // --- 1. 翻译/总结：直接调用后端 + 流式回传 ---
                    // 不打开侧边栏，直接在 webview 原地显示
                    this.streamTranslateInWebview(webview, text);
                    break;

                case 'ask':
                    // --- 2. 问 AI：保留原逻辑，去侧边栏 ---
                    this.showBrowserChat = true;
                    // 如果你想自动添加提示词：
                    this.userInput = `${text}`; 
                    // this.sendMessage(); // 也就是让用户自己点发送，或者你取消注释自动发
                    break;

                case 'read':
                    // --- 3. 朗读：调用 TTS ---
                    this.handleBrowserTTS(text);
                    break;
            }
        }
    },

    // 2. 新增：流式请求后端并发送给 Webview
    async streamTranslateInWebview(webview, text) {
        if (!webview) return;
        
        console.log('开始请求翻译:', text);
        webview.send('ai-stream-start');

        try {
            const host = window.electron?.server?.host || '127.0.0.1';
            const port = window.electron?.server?.port || 3456;
            const apiUrl = `http://${host}:${port}/simple_chat`;
            const targetLang = this.target_lang || 'Simplified Chinese';
            const sysPrompt = `You are a helpful translation assistant. Translate the following text to ${targetLang}. Only output the translated text.`;

            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    messages: [
                        { role: "system", content: sysPrompt },
                        { role: "user", content: text }
                    ],
                    stream: true
                })
            });

            if (!response.ok) throw new Error(`API Error: ${response.status}`);

            await iterateNdjsonLines(response, (data) => {
                    const content = data.choices?.[0]?.delta?.content;
                    
                    if (content) {
                        // console.log('Chunk:', content); 
                        webview.send('ai-stream-chunk', content);
                    }
            }, { stripDataPrefix: true });
            
            webview.send('ai-stream-end');
            console.log('流式传输结束');

        } catch (error) {
            console.error('Translation error:', error);
            webview.send('ai-stream-chunk', `\n[Error: ${error.message}]`);
        }
    },

    // 3. 修改：TTS 处理逻辑
    handleBrowserTTS(text) {
        // 停止之前的播放（如果有）
        this.stopTTSActivities();
        
        // 设置长文本内容
        this.readConfig.longText = text;
        
        // 稍微延迟确保状态更新，然后开始朗读
        setTimeout(() => {
            this.startRead();
            
            // 提示用户 (可选)
            // showNotification(this.t('tts_started'), 'success');
        }, 500);
    },

    // 切换引擎下拉
    toggleEngineDropdown() {
        this.showEngineDropdown = !this.showEngineDropdown;
    },

    // 设置引擎并关闭下拉
    setSearchEngine(engine) {
        this.searchEngine = engine;
        this.showEngineDropdown = false;
        // 如果想要切换后自动聚焦输入框
        this.$nextTick(() => {
            const input = document.querySelector('.ios-search-input');
            if(input) input.focus();
        });
    },

    // 搜索框失焦处理 (延迟关闭下拉，防止点击菜单项时菜单先消失)
    handleSearchBlur() {
        this.isSearchFocused = false;
        setTimeout(() => {
            this.showEngineDropdown = false;
        }, 200);
    },

    // 修改原有的 addNewTab，确保样式正确
    addNewTab() {
        const newTab = {
            id: Date.now(),
            title: 'New Tab',
            url: '',
            favicon: '',
            isLoading: false,
            canGoBack: false,
            canGoForward: false
        };
        this.browserTabs.push(newTab);
        this.switchTab(newTab.id);
        
        // 自动聚焦到欢迎页搜索框
        this.$nextTick(() => {
             const input = document.querySelector('.ios-search-input');
             if(input) input.focus();
        });
    },

    handleSelectorEnter() {
        if (this.dropdownTimer) clearTimeout(this.dropdownTimer);
        this.showEngineDropdown = true;
    },

    // 鼠标离开区域：延迟 200ms 关闭，给用户移动鼠标的时间
    handleSelectorLeave() {
        this.dropdownTimer = setTimeout(() => {
            this.showEngineDropdown = false;
        }, 200); // 200ms 延迟
    },

    // ★★★ 核心：处理边缘滚动 ★★★
    handleTabsMouseMove(e) {
      // 在 Options API 中，通过 this.$refs 访问 DOM
      const container = this.$refs.tabsContainerRef;
      
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const x = e.clientX - rect.left; // 鼠标相对于容器左侧的距离
      const width = rect.width;
      const threshold = 60; // 边缘触发滚动的范围 (px)
      const speed = 8;      // 滚动速度

      // 先清除可能存在的旧定时器
      this.stopEdgeScroll();

      // 定义滚动函数
      const scroll = (direction) => {
        if (direction === 'left') {
          container.scrollLeft -= speed;
        } else {
          container.scrollLeft += speed;
        }
        // 持续循环
        this.scrollInterval = requestAnimationFrame(() => scroll(direction));
      };

      // 判断鼠标位置
      if (x < threshold) {
        // 鼠标在左边缘 -> 向左滑
        scroll('left');
      } else if (x > width - threshold) {
        // 鼠标在右边缘 -> 向右滑
        scroll('right');
      } else {
        // 在中间 -> 停止滚动
        this.stopEdgeScroll();
      }
    },

    // 停止滚动
    stopEdgeScroll() {
      if (this.scrollInterval) {
        cancelAnimationFrame(this.scrollInterval);
        this.scrollInterval = null;
      }
    },


    controlDownload(id, action) {
        window.downloadAPI.controlDownload(id, action);
    },

    handleStopOrRemove(item) {
        if (item.state === 'progressing' || item.state === 'paused') {
            // 如果还在下载，就是取消
            this.controlDownload(item.id, 'cancel');
        } else {
            // 如果已完成或已取消，就是从列表中删除记录
            this.downloads = this.downloads.filter(d => d.id !== item.id);
        }
    },

    openFileFolder(path) {
        if(path) window.downloadAPI.showItemInFolder(path);
    },

    clearFinishedDownloads() {
        // 只保留正在下载的项目
        this.downloads = this.downloads.filter(d => d.state === 'progressing' || d.state === 'paused');
    },

    // 字节格式化工具
    formatBytes(bytes, decimals = 1) {
        if (!bytes) return '0 B';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    },
    handleDropdownEnter() {
        // 1. 如果有关闭的定时器正在倒计时，立刻取消它！
        if (this.dropdownTimer) {
            clearTimeout(this.dropdownTimer);
            this.dropdownTimer = null;
        }
        // 2. 显示面板
        this.showDownloadDropdown = true;
    },

    // ★ 鼠标离开
    handleDropdownLeave() {
        // 给用户 300ms 的反应时间
        this.dropdownTimer = setTimeout(() => {
            this.showDownloadDropdown = false;
            this.dropdownTimer = null;
        }, 300); 
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
    },
    // ===============================================
    // Python Agent 专用接口 (Electron API 桥接)
    // ===============================================

    // --- 基础信息与导航 ---





    // ===============================================
    // Python Agent 专用接口 (稳定 JS 注入版)
    // ===============================================











    
    getFaviconUrl(tab) {
      // 1. 浏览器已经给的就直接用
      if (tab.favicon) return tab.favicon;

      // 2. 用 Chrome 官方提供的“小彩蛋”API，0 成本
      //    注意：这个 API 不需要额外权限，也不会触发网络请求，只是读缓存
      if (chrome && chrome.tabs && typeof chrome.tabs.get === 'function') {
        // 同步读缓存，拿不到也不报错
        try {
          const url = new URL(tab.url);
          return `chrome://favicon/size/16@2x/${url.origin}`;
        } catch (_) {}
      }

      // 3. 兜底：拼一个最可能的地址
      try {
        const u = new URL(tab.url);
        return `${u.origin}/favicon.ico`;
      } catch (_) {}

      // 4. 实在没有就空字符串
      return '';
    },

    // 切换当前标签页的收藏状态
    toggleFavorite(tab) {
        if (!tab || !tab.url) return;

        const index = this.favorites.findIndex(f => f.url === tab.url);
        if (index !== -1) {
            // 已存在 -> 移除
            this.favorites.splice(index, 1);
            showNotification(this.t('favoriteRemoved') || 'Favorite removed', 'info');
        } else {
            // 不存在 -> 添加
            this.favorites.push({
                title: tab.title || 'New Tab',
                url: tab.url,
                favicon: this.getFaviconUrl(tab)
            });
            showNotification(this.t('favoriteAdded') || 'Favorite added', 'success');
        }
        this.saveFavorites();
    },

    // 从网格中移除特定收藏
    removeFavorite(url) {
        const index = this.favorites.findIndex(f => f.url === url);
        if (index !== -1) {
            this.favorites.splice(index, 1);
            this.saveFavorites();
        }
    },

    // 点击收藏图标时，在当前标签页加载 URL
    loadUrlInCurrentTab(url) {
        if (this.currentTab) {
            // 更新当前标签的 URL
            this.currentTab.url = url;
            // 更新地址栏输入框显示
            this.urlInput = url; 
            // 触发加载状态 (如果您的 webview逻辑依赖这个)
            this.currentTab.isLoading = true;
        } else {
            // 如果没有当前标签，创建一个新的
            this.addNewTab(url);
        }
    },

    // 持久化：保存收藏到本地存储
    saveFavorites() {
        try {
            localStorage.setItem('browser_favorites', JSON.stringify(this.favorites));
            // 保存显示状态配置
            localStorage.setItem('browser_show_favorites', JSON.stringify(this.showFavorites));
        } catch (e) {
            console.error('Failed to save favorites:', e);
        }
    },

    // 持久化：从本地存储加载
    loadFavorites() {
        try {
            const storedFavs = localStorage.getItem('browser_favorites');
            if (storedFavs) {
                this.favorites = JSON.parse(storedFavs);
            }
            
            const storedShow = localStorage.getItem('browser_show_favorites');
            if (storedShow !== null) {
                this.showFavorites = JSON.parse(storedShow);
            }
        } catch (e) {
            console.error('Failed to load favorites:', e);
        }
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

// Methods

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

// --- 增强原有的监听和初始化 ---

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
// 核心逻辑：判断并控制扩展页面的轮询
  handleExtensionsPolling(menu, sub) {
    if (menu === 'api-group' && sub === 'extension') {
      this.startExtensionsPolling();
    } else {
      this.stopExtensionsPolling();
    }
  },

  // 进入设置类页面时自动拉取原本需手动点「刷新」才加载的列表
  handleAutoLoadOnMenu(menu, sub) {
    if (menu === 'system') {
      this.loadBackupList();
    } else if (menu === 'deploy-bot' && sub === 'im_bot') {
      this.fetchBotConversations();
      this.fetchXmppCertPending();
    }
  },

  // 启动扩展轮询
  startExtensionsPolling() {
    if (this.extensionsPollingTimer) return;
    
    // 立即执行一次刷新
    this.scanExtensions(); 

    this.extensionsPollingTimer = setInterval(() => {
      console.log('正在轮询获取 Extensions...');
      this.scanExtensions();
    }, 5000);
  },

  // 停止扩展轮询
  stopExtensionsPolling() {
    if (this.extensionsPollingTimer) {
      clearInterval(this.extensionsPollingTimer);
      this.extensionsPollingTimer = null;
      console.log('已停止轮询 Extensions');
    }
  },

  // 刷新扩展列表，并在之后对比版本状态
  async scanExtensions() {
    try {
      const response = await fetch('/api/extensions/list');
      if (!response.ok) throw new Error('Fetch failed');
      const data = await response.json();
      this.extensions = data.extensions;
      
      // 同步本地与远程的“已安装”和“可更新”状态
      this.syncExtensionUpdateStatus();
    } catch (e) {
      console.error('刷新扩展列表失败', e);
    }
  },
  
  // 辅助方法：对比本地和远程，同步更新状态
  syncExtensionUpdateStatus() {
    if (!this.extensions || !this.remotePlugins) return;

    // 1. 遍历远程列表，标记 "installed" 和 "hasUpdate" 状态
    this.remotePlugins = this.remotePlugins.map(r => {
      const local = this.extensions.find(l => 
          (l.repository && r.repository && l.repository.trim().toLowerCase() === r.repository.trim().toLowerCase()) || 
          (l.id && r.id && l.id === r.id)
      );
      let installed = !!local;
      let hasUpdate = false;
      
      if (local && local.version && r.version) {
        if (this.compareVersions(local.version, r.version) < 0) {
          hasUpdate = true;
        }
      }
      return { ...r, installed, hasUpdate };
    });

    // 2. 遍历本地列表，标记 "hasUpdate" 状态
    this.extensions = this.extensions.map(l => {
      const remote = this.remotePlugins.find(r => 
          (l.repository && r.repository && l.repository.trim().toLowerCase() === r.repository.trim().toLowerCase()) || 
          (l.id && r.id && l.id === r.id)
      );
      let hasUpdate = false;
      if (remote && l.version && remote.version) {
        if (this.compareVersions(l.version, remote.version) < 0) {
          hasUpdate = true;
        }
      }
      return { ...l, hasUpdate };
    });
  },

  // 辅助方法：语义化版本比较
  compareVersions(v1, v2) {
    if (!v1 || !v2) return 0;
    const parts1 = v1.toString().replace(/[^0-9.]/g, '').split('.').map(Number);
    const parts2 = v2.toString().replace(/[^0-9.]/g, '').split('.').map(Number);
    for (let i = 0; i < Math.max(parts1.length, parts2.length); i++) {
      const num1 = parts1[i] || 0;
      const num2 = parts2[i] || 0;
      if (num1 < num2) return -1;
      if (num1 > num2) return 1;
    }
    return 0;
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
},

async handleRefreshSkills() {
  this.skillsLoading = true;
  try {
    // 假设你已定义了 fetchSkills 方法来获取列表
    await this.fetchSkills(); 
  } finally {
    this.skillsLoading = false;
  }
},

    // 打开编辑/新增对话框
    openBehaviorDialog(index) {
      this.currentBehaviorIndex = index;
      if (index === -1) {
        // 新增模式：创建默认模板的深拷贝
        this.tempBehavior = this.createDefaultBehavior();
      } else {
        // 编辑模式：创建现有数据的深拷贝（切断引用）
        // 假设您的数据在 behaviorSettings.behaviorList 中
        this.tempBehavior = JSON.parse(JSON.stringify(this.behaviorSettings.behaviorList[index]));
      }
      
      this.showBehaviorDialog = true;
    },

    // 创建默认行为模板
    createDefaultBehavior() {
      return {
        enabled: true,
        trigger: {
          type: 'time',
          time: { timeValue: '08:00:00', days: [1, 2, 3, 4, 5] },
          noInput: { latency: 60 },
          cycle: { cycleValue: '00:30:00', repeatNumber: 1, isInfiniteLoop: true }
        },
        action: {
          type: 'prompt',
          prompt: '',
          random: { type: 'random', events: [''] }
        },
        platforms: ["chat"],  // 新增多选渠道字段（字符串数组）
      };
    },

    // 关闭对话框后的清理
    resetBehaviorDialogState() {
      this.tempBehavior = null;
      this.currentBehaviorIndex = -1;
    },

    // 保存行为设置（新增或更新）
    saveBehavior() {
      if (!this.tempBehavior) return;

      // 1. 核心修复：确保 platforms 字段一定是数组且有值
      if (!Array.isArray(this.tempBehavior.platforms)) {
        // 如果没有数组，根据旧的单选字段转换，或者给默认值
        let oldVal = this.tempBehavior.platform || 'chat';
        this.tempBehavior.platforms = [oldVal];
      }
      
      // 如果用户一个都没选（空数组），强制给个 'chat'
      if (this.tempBehavior.platforms.length === 0) {
        this.tempBehavior.platforms = ['chat'];
      }

      // 2. 同步旧字段 platform，取数组第一个元素
      this.tempBehavior.platform = this.tempBehavior.platforms[0];

      // 3. 保存逻辑
      if (this.isEditingBehavior) {
        // 查找并替换旧项
        const idx = this.behaviorSettings.behaviorList.findIndex(b => b === this.editingItemOrigin);
        if (idx !== -1) {
          this.behaviorSettings.behaviorList[idx] = JSON.parse(JSON.stringify(this.tempBehavior));
        }
      } else {
        // 新增项
        this.behaviorSettings.behaviorList.push(JSON.parse(JSON.stringify(this.tempBehavior)));
      }

      this.showBehaviorDialog = false;
      
      // 4. 保存后刷新计时器
      this.$nextTick(() => {
        this.resetCycleTimers();
      });
    },

    // 确认删除行为
    confirmRemoveBehavior(index) {
      this.$confirm(
        this.t('confirmDeleteBehavior') || 'Are you sure you want to delete this behavior?',
        this.t('warning') || 'Warning',
        {
          confirmButtonText: this.t('confirm'),
          cancelButtonText: this.t('cancel'),
          type: 'warning',
        }
      ).then(() => {
        this.removeBehavior(index);
      }).catch(() => {});
    },

    // 执行删除
    removeBehavior(index) {
      this.behaviorSettings.behaviorList.splice(index, 1);
      this.resetCycleTimers();
      this.autoSaveSettings();
    },

    // 处理全局开关变化
    handleGlobalSwitchChange() {
      this.resetCycleTimers();
      this.autoSaveSettings();
    },

    // 处理单个行为开关变化
    handleBehaviorChange() {
      this.resetCycleTimers();
      this.autoSaveSettings();
    },

    // --- 弹窗内部的辅助方法 (Random Events) ---

    // 添加临时随机事件条目
    addTempEvent() {
      if (this.tempBehavior && this.tempBehavior.action.random) {
        this.tempBehavior.action.random.events.push('');
      }
    },

    // 删除临时随机事件条目
    removeTempEvent(eIdx) {
      if (this.tempBehavior && 
          this.tempBehavior.action.random && 
          this.tempBehavior.action.random.events.length > 1) {
        this.tempBehavior.action.random.events.splice(eIdx, 1);
      }
    },

    // --- UI 显示辅助方法 ---

    // 根据触发类型返回图标类名
    getTriggerIcon(type) {
      const map = {
        'time': 'fa-regular fa-clock',
        'noInput': 'fa-solid fa-hourglass-half',
        'cycle': 'fa-solid fa-arrows-spin'
      };
      return map[type] || 'fa-solid fa-bolt';
    },

    // 生成卡片上的摘要文本
    getBehaviorSummary(b) {
      if (!b || !b.trigger) return '';
      
      if (b.trigger.type === 'time') {
        const time = b.trigger.time.timeValue;
        const days = b.trigger.time.days.length;
        const daysText = this.t('repeatDays') || 'Days'; // 简单处理，实际根据你的 t 函数逻辑
        return `${time} (${daysText}: ${days})`;
      } else if (b.trigger.type === 'noInput') {
        return `${this.t('noInputLatency') || 'Latency'}: ${b.trigger.noInput.latency}s`;
      } else if (b.trigger.type === 'cycle') {
        const loopText = b.trigger.cycle.isInfiniteLoop ? '∞' : b.trigger.cycle.repeatNumber;
        return `${this.t('cycleValue') || 'Cycle'}: ${b.trigger.cycle.cycleValue} (x${loopText})`;
      }
      return '';
    },
  // 添加新事件行
  addTempEvent() {
    if (this.tempBehavior && this.tempBehavior.action.random) {
      this.tempBehavior.action.random.events.push(''); // 增加一个空字符串（即空输入框）
    }
  },

  // 删除指定行
  removeTempEvent(index) {
    if (this.tempBehavior && this.tempBehavior.action.random) {
      // 检查：如果只剩一个了，就不让删了（或者您可以去掉这个判断，允许删光）
      if (this.tempBehavior.action.random.events.length > 1) {
        this.tempBehavior.action.random.events.splice(index, 1);
      } else {
        // 如果只剩一个，清空内容而不是删除行
        this.tempBehavior.action.random.events[0] = '';
      }
    }
  },

    // 辅助工具：生成数字范围数组
    makeRange(start, end) {
      const result = [];
      for (let i = start; i <= end; i++) {
        result.push(i);
      }
      return result;
    },

    // 禁用小时
    disabledHours() {
      // 只有在最小值的小时大于 0 时才需要禁用
      // 如果最小是 00:00:01，则不禁用任何小时
      return this.makeRange(0, 23).filter(h => h < this.minLimit.h);
    },

    // 禁用分钟 (selectedHour 是当前转盘选中的小时)
    disabledMinutes(selectedHour) {
      // 只有当选中的小时等于最小值的小时时，才限制分钟
      if (selectedHour === this.minLimit.h) {
        return this.makeRange(0, 59).filter(m => m < this.minLimit.m);
      }
      return [];
    },

    // 禁用秒钟 (selectedHour 和 selectedMinute 是当前选中的时和分)
    disabledSeconds(selectedHour, selectedMinute) {
      // 只有当时和分都处于最小值临界点时，才限制秒钟
      if (selectedHour === this.minLimit.h && selectedMinute === this.minLimit.m) {
        return this.makeRange(0, 59).filter(s => s < this.minLimit.s);
      }
      return [];
    },

    async probeDocker() {
      try {
        const res = await fetch('/api/docker/probe');
        const data = await res.json();
        this.dockerInstalled = data.installed;
      } catch (error) {
        console.error("Docker 探测失败:", error);
        this.dockerInstalled = false;
      }
    },

    // 打开任务中心
    openTaskCenter() {
        this.activeSideView = 'tasks';
        this.sidePanelURL = ''; // 确保 iframe 关闭
        this.currentExtension = null;
        this.showExtensionsDialog = false; // 关闭对话框
        this.expandSidePanel();
        this.fetchTasks();
        // 开启轮询
        if (this.taskRefreshTimer) clearInterval(this.taskRefreshTimer);
        this.taskRefreshTimer = setInterval(this.fetchTasks, 3000);
    },
    openWorkspace() {
        this.activeSideView = 'workspace'
        this.sidePanelURL = ''; // 确保 iframe 关闭
        this.currentExtension = null;
        this.showExtensionsDialog = false; // 关闭对话框
        this.expandSidePanel();
    },
    // 关闭任务中心（返回列表）
    closeTaskCenter() {
        this.activeSideView = 'list';
        if (this.taskRefreshTimer) clearInterval(this.taskRefreshTimer);
    },

    // 获取任务列表
    async fetchTasks() {
        if (!this.hasWorkspacePath || !this.sidePanelOpen || this.activeSideView !== 'tasks') return;
        
        try {
            const res = await fetch(`/v1/tasks/list`);
            const data = await res.json();
            if (data.tasks) {
                this.taskList = data.tasks;
            }
        } catch (e) {
            console.error("Failed to fetch tasks", e);
        }
    },

    // 创建任务
    async submitCreateTask() {
        if (!this.newTaskForm.title || !this.newTaskForm.description) {
            showNotification(this.t('fillRequired'), 'error');
            return;
        }

        this.isCreatingTask = true;
        try {
            console.log(this.newTaskForm); // 打印表单数据
            const res = await fetch(`/v1/tasks/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: this.newTaskForm.title,
                    description: this.newTaskForm.description,
                    agent_type: this.newTaskForm.agent_type,
                    task_type: this.newTaskForm.task_type,
                    platforms: this.newTaskForm.platforms,
                    trigger_config: this.newTaskForm.trigger_config // 发送完整配置
                })
            });
            const data = await res.json();
            
            if (data.success) {
                showNotification(this.t('success'));
                this.showCreateTaskDialog = false;
                // 重置表单
                this.newTaskForm = { 
                    title: '', description: '', task_type: 'once', agent_type: 'default',
                    trigger_config: { timeValue: '09:00:00', days: [1,2,3,4,5], cycleValue: '01:00:00', repeatNumber: 1, isInfiniteLoop: true }
                };
                this.fetchTasks();
            } else {
                showNotification(data.error, 'error');
            }
        } catch (e) {
            showNotification(this.t('networkError'), 'error');
        } finally {
            this.isCreatingTask = false;
        }
    },


    // 取消任务
    async handleCancelTask(taskId) {
        try {
            await fetch(`/v1/tasks/cancel/${taskId}`, { method: 'POST' });
            showNotification(this.t('cancelSuccess') || '取消任务成功');
            this.fetchTasks();
        } catch (e) { console.error(e); }
    },

    // 删除任务
    async handleDeleteTask(taskId) {
        try {
            this.handleCancelTask(taskId);
            const res = await fetch(`/v1/tasks/${taskId}`, { 
                method: 'DELETE' 
            });
            
            if (res.ok) {
                showNotification(this.t('deleteSuccess') || '删除任务成功');
                this.fetchTasks(); // 刷新列表
            } else {
                console.error("Delete failed with status:", res.status);
            }
        } catch (e) { 
            console.error("Network error during delete:", e); 
        }
    },

    // 跳转设置
    jumpToCLIConfig() {
        this.activeMenu = 'toolkit';
        this.subMenu = 'CLI';
    },

    formatTaskTime(isoStr) {
        if (!isoStr) return '-';
        const date = new Date(isoStr);
        return date.toLocaleString();
    },

    getTaskStatusType(status) {
        const map = {
            'pending': 'info',
            'running': 'primary',
            'completed': 'success',
            'failed': 'danger',
            'cancelled': 'warning'
        };
        return map[status] || 'info';
    },
  // 打开任务结果弹窗
// 在 Vue 组件的 methods 中
openTaskResult(task) {
    this.selectedTaskTitle = task.title;
    
    // 1. 获取该任务的所有历史产出记录
    // 如果没有历史记录（比如旧任务），我们造一个包含当前结果的伪记录
    const rawHistory = task.context?.results_history || [];
    
    if (rawHistory.length === 0 && task.result) {
        this.selectedTaskHistory = [{
            time: task.updated_at || task.created_at,
            result: task.result
        }];
    } else {
        // 将历史记录倒序排列（最新的在最上面）
        this.selectedTaskHistory = [...rawHistory].reverse();
    }
    
    // 2. 默认选中第一项（即最新的一项）
    this.currentResultIdx = 0;
    
    // 3. 打开弹窗
    this.showTaskResultDialog = true;
},
    
    getModeIcon(type) {
        const iconMap = {
            'once': 'fa-solid fa-bolt-lightning',
            'time': 'fa-regular fa-clock',
            'cycle': 'fa-solid fa-arrows-rotate'
        };
        // 如果 type 为空或不在 map 中，返回默认图标
        return iconMap[type] || 'fa-solid fa-terminal';
    },


    // 重置表单到初始状态
    resetTaskForm() {
        this.newTaskForm = {
            title: '',
            description: '',
            task_type: 'once',
            platforms: [],
            agent_type: 'default',
            trigger_config: {
                timeValue: '09:00:00',
                days: [1, 2, 3, 4, 5],
                cycleValue: '01:00:00',
                repeatNumber: 1,
                isInfiniteLoop: true
            }
        };
        this.isEditing = false;
        this.editingTaskId = null;
    },

    // 打开新建窗口
    openCreateTaskDialog() {
        this.resetTaskForm(); // 确保每次新建前都干净
        this.showCreateTaskDialog = true;
    },

    openEditTaskDialog(task) {
        // 1. 先重置，清除上一次可能残留的状态
        this.resetTaskForm();
        
        // 2. 标记为编辑模式
        this.isEditing = true;
        this.editingTaskId = task.task_id;
        
        // 3. 填充基础数据
        this.newTaskForm.title = task.title;
        this.newTaskForm.description = task.description;
        this.newTaskForm.platforms = task.platforms || [];
        this.newTaskForm.agent_type = task.agent_type || 'default';
        this.newTaskForm.task_type = task.context?.task_type || task.task_type || 'once';
        
        // 4. 填充触发器配置
        const savedConfig = task.context?.trigger_config;
        if (savedConfig) {
            // 使用 assign 或 spread 确保响应式更新
            Object.assign(this.newTaskForm.trigger_config, JSON.parse(JSON.stringify(savedConfig)));
        }
        
        this.showCreateTaskDialog = true;
    },

    // 2. 统一的提交处理函数
    async submitTaskForm() {
        if (!this.newTaskForm.title || !this.newTaskForm.description) {
            showNotification(this.t('fillRequired'), 'error');
            return;
        }

        this.isCreatingTask = true;

        try {
            // 如果是编辑模式，先停止并删除旧任务
            if (this.isEditing && this.editingTaskId) {
                // A. 停止原有任务
                await fetch(`/v1/tasks/cancel/${this.editingTaskId}`, { method: 'POST' });
                // B. 删除原有任务
                await fetch(`/v1/tasks/${this.editingTaskId}`, { method: 'DELETE' });
                console.log(`Old task ${this.editingTaskId} removed for re-creation`);
            }

            // C. 创建新任务 (无论是新建还是编辑后的“重建”，都走这个接口)
            const res = await fetch(`/v1/tasks/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.newTaskForm)
            });
            const data = await res.json();
            
            if (data.success) {
                showNotification(this.t('success'));
                this.showCreateTaskDialog = false; // 关闭窗口
                this.resetTaskForm();             // ⭐ 提交成功后重置表单
                this.fetchTasks();                // 刷新列表
            } else {
                showNotification(data.error, 'error');
            }
        } catch (e) {
            showNotification(this.t('networkError'), 'error');
        } finally {
            this.isCreatingTask = false;
            // 提交完成后重置编辑状态
            this.isEditing = false;
            this.editingTaskId = null;
        }
    },

    // 3. 这里的 reset 函数在对话框关闭时调用 (el-dialog 的 @closed 事件)
    resetTaskForm() {
        this.isEditing = false;
        this.editingTaskId = null;
        this.newTaskForm = {
            title: '', description: '', task_type: 'once', agent_type: 'default',
            trigger_config: { timeValue: '09:00:00', days: [1,2,3,4,5], cycleValue: '01:00:00', repeatNumber: 1, isInfiniteLoop: true }
        };
    },
// 打开详情页
openTaskDetailView(task) {
    this.viewingTaskDetail = task;
},

// 关闭详情页回到列表
closeTaskDetail() {
    this.viewingTaskDetail = null;
},

// 修改 fetchTasks 方法，增加同步详情逻辑
async fetchTasks() {
    if (!this.hasWorkspacePath || !this.sidePanelOpen || this.activeSideView !== 'tasks') return;
    
    try {
        const res = await fetch(`/v1/tasks/list`);
        const data = await res.json();
        if (data.tasks) {
            this.taskList = data.tasks;
            
            // ⭐ 核心逻辑：如果当前正在看某个任务的详情，实时更新它
            if (this.viewingTaskDetail) {
                const updatedTask = data.tasks.find(t => t.task_id === this.viewingTaskDetail.task_id);
                if (updatedTask) {
                    this.viewingTaskDetail = updatedTask;
                }
            }
        }
    } catch (e) {
        console.error("Failed to fetch tasks", e);
    }
},

// 重置任务中心状态（关闭时调用）
closeTaskCenter() {
    this.activeSideView = 'list';
    this.viewingTaskDetail = null; // 清除详情状态
    if (this.taskRefreshTimer) clearInterval(this.taskRefreshTimer);
},

  // 处理启动开关的点击事件
  handleEnableToggle(newValue) {
    // 只有在用户试图“开启”开关时 (newValue === true) 才进行校验
    if (newValue === true) {
      // 检查 cc_path 是否为空
      if (!this.CLISettings.cc_path || this.CLISettings.cc_path.trim() === '') {
        
        // 1. 调用你提供的报错函数 
        // 这里的提示语使用了你模板里现成的 t('pleaseSelectWorkspaceFirst')
        const errorMsg = this.t ? this.t('pleaseSelectWorkspaceFirst') : '请先配置 Workspace 工作区路径';
        showNotification(errorMsg, 'error', 'Error');

        // 2. 强制把开关重置回关闭状态 (阻止启动)
        // 使用 $nextTick 确保 Vue 能正确更新 DOM
        this.$nextTick(() => {
          this.CLISettings.enabled = false;
        });

        // 3. 拦截执行，直接 return，不触发后续的保存
        return; 
      }
    }

    // 如果校验通过（或者用户只是在关闭开关），则正常执行原来的保存逻辑
    this.autoSaveSettings();
  },

  handleVisionControlEnableToggle(newValue){
    if (newValue === true && this.visionSettings.enabled === true) {
      this.visionSettings.enabled = false;
      showNotification(this.t('autoDisableVisionSettings'), 'warning');
    }
    this.autoSaveSettings();
  },
  handleVisionEnableToggle(newValue){
    if (newValue === true && this.visionControlSettings.enabled === true) {
      this.visionControlSettings.enabled = false;
      showNotification(this.t('autoDisableVisionControlSettings'), 'warning');
    }
    this.autoSaveSettings();
  },

  handleWebSearchToggle(newValue) {
    if (newValue === true) {
      const settings = this.webSearchSettings;
      let errorMsg = '';

      // --- 1. 校验搜索引擎配置 ---
      switch (settings.engine) {
        case 'searxng':
          if (!settings.searxng_url?.trim()) errorMsg = this.t('pleaseConfigSearxngUrl');
          break;
        case 'tavily':
          if (!settings.tavily_api_key?.trim()) errorMsg = this.t('pleaseConfigTavilyApiKey');
          break;
        case 'bing':
          if (!settings.bing_api_key?.trim()) errorMsg = this.t('pleaseConfigBingApiKey');
          else if (!settings.bing_search_url?.trim()) errorMsg = this.t('pleaseConfigBingSearchUrl');
          break;
        case 'google':
          if (!settings.google_api_key?.trim()) errorMsg = this.t('pleaseConfigGoogleApiKey');
          else if (!settings.google_cse_id?.trim()) errorMsg = this.t('pleaseConfigGoogleCseId');
          break;
        case 'brave':
          if (!settings.brave_api_key?.trim()) errorMsg = this.t('pleaseConfigBraveApiKey');
          break;
        case 'exa':
          if (!settings.exa_api_key?.trim()) errorMsg = this.t('pleaseConfigExaApiKey');
          break;
        case 'serper':
          if (!settings.serper_api_key?.trim()) errorMsg = this.t('pleaseConfigSerperApiKey');
          break;
        case 'bochaai':
          if (!settings.bochaai_api_key?.trim()) errorMsg = this.t('pleaseConfigBochaaiApiKey');
          break;
        // duckduckgo 无需强制配置，直接放行
      }

      // --- 2. 校验网页解析器配置 (前提是搜索引擎已经通过校验) ---
      if (!errorMsg) {
        switch (settings.crawler) {
          case 'crawl4ai':
            if (!settings.Crawl4Ai_url?.trim()) errorMsg = this.t('pleaseConfigCrawl4aiUrl');
            break;
          case 'firecrawl':
            if (!settings.firecrawl_url?.trim()) errorMsg = this.t('pleaseConfigFirecrawlUrl');
            // 如果你觉得 Firecrawl 的 API Key 也必须强制填写，可以解除下面这行的注释：
            // else if (!settings.firecrawl_api_key?.trim()) errorMsg = this.t('pleaseConfigFirecrawlApiKey');
            break;
          
          // 注意：jina API Key 是可选的，所以这里不写 case 'jina' 的报错逻辑，直接放行
          // simpleRequest 和 mdnew 也没有必填项，直接放行
        }
      }

      // --- 3. 拦截与报错 ---
      if (errorMsg) {
        // 报错提醒，标题也国际化
        const errorTitle = this.t ? this.t('configIncomplete') : 'Config Incomplete';
        showNotification(errorMsg, 'error', errorTitle);

        // 强制重置开关为关闭状态
        this.$nextTick(() => {
          this.webSearchSettings.enabled = false;
        });

        // 阻断执行，不触发保存
        return;
      }
    }

    // 校验全部通过，或者用户是主动关闭开关，则正常执行保存
    this.autoSaveSettings();
  },

  // 代码解释器启动开关的拦截处理
  handleInterpreterToggle(newValue) {
    if (newValue === true) {
      const settings = this.codeSettings;
      let errorMsg = '';

      // 根据选择的引擎校验必填项
      switch (settings.engine) {
        case 'e2b':
          if (!settings.e2b_api_key?.trim()) {
            errorMsg = this.t('pleaseConfigE2bApiKey');
          }
          break;
        case 'sandbox':
          if (!settings.sandbox_url?.trim()) {
            errorMsg = this.t('pleaseConfigSandboxUrl');
          }
          break;
      }

      // 如果有报错信息，进行拦截
      if (errorMsg) {
        // 报错提醒 (复用刚才加的 configIncomplete)
        const errorTitle = this.t ? this.t('configIncomplete') : 'Config Incomplete';
        showNotification(errorMsg, 'error', errorTitle);

        // 强制重置开关为关闭状态
        this.$nextTick(() => {
          this.codeSettings.enabled = false;
        });

        // 阻断执行，不触发保存
        return;
      }
    }

    // 校验通过或关闭开关，正常执行保存
    this.autoSaveSettings();
  },
// 1. 懒加载读取文件目录
  async loadWorkspaceNode(node, resolve) {
    // 顶层节点：加载工作区根目录
    if (node.level === 0) {
      if (!this.CLISettings || !this.CLISettings.cc_path) {
        return resolve([]); 
      }
      
      // ⚠️ 暴力触发：只要根节点加载，就立刻启动监听器！
      console.log('准备启动文件监听:', this.CLISettings.cc_path);
      this.setupWorkspaceWatcher(this.CLISettings.cc_path);

      try {
        const res = await window.electronAPI.readDirectory(this.CLISettings.cc_path);
        if (res.success) {
          return resolve(res.data);
        } else {
          this.$message?.error(this.t('readDirError') || '读取工作区目录失败: ' + res.error);
          return resolve([]);
        }
      } catch (error) {
        console.error(error);
        return resolve([]);
      }
    }

    // 子节点：加载被点击的子目录
    if (node.level > 0 && node.data.isDirectory) {
      try {
        const res = await window.electronAPI.readDirectory(node.data.path);
        if (res.success) {
          return resolve(res.data);
        } else {
          this.$message?.error(this.t('readDirError') || '读取子目录失败: ' + res.error);
          return resolve([]);
        }
      } catch (error) {
        console.error(error);
        return resolve([]);
      }
    }
    
    resolve([]);
  },

  // 2. 使用系统默认程序打开文件
  openWorkspaceFile(filePath) {
    if (window.electronAPI && window.electronAPI.openPath) {
      window.electronAPI.openPath(filePath);
    }
  },

  // 3. 删除文件/文件夹
  async deleteWorkspaceFile(data, node) {
    try {
      // 弹出确认框 (兼容 Element Plus 的 this.$confirm)
      await this.$confirm(
        (this.t('confirmDelete') || '确认将该文件放入回收站吗？') + `\n${data.name}`,
        this.t('warning') || '警告',
        { 
          confirmButtonText: this.t('confirm') || '确定', 
          cancelButtonText: this.t('cancel') || '取消', 
          type: 'warning' 
        }
      );
      
      const res = await window.electronAPI.deleteWorkspaceFile(data.path);
      if (res.success) {
        showNotification(this.t('deleteSuccess'),'success');
        // 从前端界面中动态移除该节点，避免重新读取整个目录树
        const parent = node.parent;
        const children = parent.data.children || parent.childNodes;
        const index = children.findIndex(d => d.data.path === data.path);
        if (index !== -1) {
          children.splice(index, 1);
        }
        
      } else {
        showNotification(this.t('deleteFailed'),'error');
      }
    } catch (error) {
      // 用户点击了取消，不做任何处理
    }
  },

  // 5. 刷新整个工作区树
  refreshWorkspaceTree() {
    // 改变 key 值会让 Vue 销毁并重建 el-tree，从而重新触发 load()
    this.workspaceTreeKey += 1;
  },

    // 核心上传逻辑
    async executeUpload(targetPath) {
        try {
            // 1. 调用选择文件对话框
            const result = await window.electronAPI.openFileDialog();
            
            if (result.canceled || result.filePaths.length === 0) return;

            // 2. 执行上传
            const uploadRes = await window.electronAPI.uploadToWorkspace(targetPath, result.filePaths);
            
            if (uploadRes.success) {
                showNotification(this.t('uploadSuccess'),'success');
                this.refreshWorkspaceTree(); // 刷新显示新文件
            } else {
                showNotification(this.t('uploadFailed'),'error');
            }
        } catch (err) {
            console.error('Upload Error:', err);
            this.$message.error('操作失败，请检查控制台日志');
        }
    },

    // 顶部按钮：上传到根目录
    handleRootUpload() {
        const rootPath = this.CLISettings.cc_path;
        if (!rootPath) {
            showNotification(this.t('pleaseConfigWorkspace'),'error');
            return;
        }
        this.executeUpload(rootPath);
    },

    // 文件夹按钮：上传到子目录
    handleFolderUpload(folderPath) {
        console.log("正在上传到子目录:", folderPath);
        this.executeUpload(folderPath);
    },

  // 添加好感度维度
  addLoveDimension() {
    if (!this.loveSettings.dimensions) {
      this.loveSettings.dimensions = [];
    }
    this.loveSettings.dimensions.push(""); // 压入一个空字符串
    this.autoSaveSettings();
  },

  // 删除好感度维度
  removeLoveDimension(idx) {
    if (this.loveSettings.dimensions && this.loveSettings.dimensions.length > 1) {
      this.loveSettings.dimensions.splice(idx, 1);
      this.autoSaveSettings();
    }
  },

  // ---------------- 羁绊系统：系统配置相关 ----------------
  addLoveDimension() {
    if (!this.loveSettings.dimensions) this.loveSettings.dimensions = [];
    this.loveSettings.dimensions.push("");
    this.autoSaveSettings();
  },
  removeLoveDimension(idx) {
    if (this.loveSettings.dimensions && this.loveSettings.dimensions.length > 1) {
      this.loveSettings.dimensions.splice(idx, 1);
      this.autoSaveSettings();
    }
  },

  // ---------------- 羁绊系统：数据管理相关 ----------------
  
  handleAffectionTabChange(tabName) {
    if (tabName === 'data') {
      this.fetchAffectionData();
    }
  },

  async fetchAffectionData() {
    try {
      // 请求我们刚才写的 FastAPI 路由
      const response = await fetch('/api/affection/get_data');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      
      this.affectionRawData = data || {};
      
      // 将 Object 转换为 Array，供 el-table 渲染
      this.affectionDataList = Object.keys(this.affectionRawData).map(userName => {
        return {
          userName: userName,
          ...this.affectionRawData[userName]
        };
      });
      
      console.log("✅ 羁绊数据加载成功:", this.affectionDataList); // 调试日志，按 F12 可以在控制台看到
    } catch (error) {
      console.error("❌ 获取羁绊数据失败:", error);
      if (this.$message) this.$message.error("无法加载羁绊数据，请检查后端是否正常运行");
    }
  },

  // 3. 将前端的修改同步保存到后端
  async syncAffectionDataToBackend() {
    try {
      // 将 Array 转回 Object 结构 {"小包": {love: 10}}
      const newData = {};
      this.affectionDataList.forEach(item => {
        const { userName, ...dimensionsData } = item;
        newData[userName] = dimensionsData;
      });

      this.affectionRawData = newData; // 更新本地缓存

      // 使用 fetch 发送 POST 请求
      const response = await fetch('/api/affection/save_data', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(newData)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      if (this.$message) this.$message.success("羁绊数据已同步");
    } catch (error) {
      console.error("❌ 保存羁绊数据失败:", error);
      if (this.$message) this.$message.error("羁绊数据保存失败");
    }
  },

  // 3. 打开新增/编辑对话框
  openAffectionDataDialog(row = null) {
    this.isEditingAffection = !!row; // 如果传了 row 说明是编辑
    
    if (row) {
      // 编辑：深拷贝当前行数据
      this.currentAffectionForm = JSON.parse(JSON.stringify(row));
    } else {
      // 新增：初始化表单，把所有维度默认设为 0
      const newForm = { userName: '' };
      if (this.loveSettings.dimensions) {
        this.loveSettings.dimensions.forEach(dim => {
          newForm[dim] = 0;
        });
      }
      this.currentAffectionForm = newForm;
    }
    
    this.showAffectionDataDialog = true;
  },

  // 4. 保存对话框表单
  saveAffectionData() {
    const form = this.currentAffectionForm;
    if (!form.userName) return;

    if (this.isEditingAffection) {
      // 寻找并替换
      const index = this.affectionDataList.findIndex(item => item.userName === form.userName);
      if (index !== -1) {
        this.affectionDataList.splice(index, 1, { ...form });
      }
    } else {
      // 查重：防止用户名重复
      const exists = this.affectionDataList.find(item => item.userName === form.userName);
      if (exists) {
        this.$message.warning("该用户名已存在！");
        return;
      }
      // 追加新用户
      this.affectionDataList.push({ ...form });
    }

    this.showAffectionDataDialog = false;
    this.syncAffectionDataToBackend(); // 触发网络请求同步到后端
  },

  // 5. 删除用户数据
  deleteAffectionData(userName) {
    this.$confirm(this.t('confirmDelete') || '确认删除该用户数据吗？', this.t('warning') || '警告', {
      confirmButtonText: this.t('confirm') || '确定',
      cancelButtonText: this.t('cancel') || '取消', 
      type: 'warning'
    }).then(() => {
      const index = this.affectionDataList.findIndex(item => item.userName === userName);
      if (index !== -1) {
        this.affectionDataList.splice(index, 1);
        this.syncAffectionDataToBackend(); // 触发网络请求同步到后端
      }
    }).catch(() => {});
  },

    // 处理单击文件自动添加 @ 快捷方式
    handleFileShortcut(fullPath) {
        if (!fullPath) return;

        // 1. 获取工作区根路径
        const rootPath = this.CLISettings.cc_path;
        let relativePath = fullPath;

        // 2. 将绝对路径转换为相对于工作区的路径
        if (rootPath && fullPath.startsWith(rootPath)) {
            // 截掉根目录部分，并去掉路径开头多余的斜杠
            relativePath = fullPath.substring(rootPath.length).replace(/^[/\\]+/, '');
        }

        // 3. 统一将路径分隔符替换为正斜杠 / (方便 AI 识别并保持跨平台一致性)
        relativePath = relativePath.replace(/\\/g, '/');

        // 4. 构造快捷指令字符串
        const shortcut = `@${relativePath} `;

        // 5. 将指令追加到输入框
        if (!this.userInput) {
            // 如果输入框是空的，直接赋值
            this.userInput = shortcut;
        } else if (this.userInput.endsWith(' ')) {
            // 如果末尾已经有空格，直接加内容
            this.userInput += shortcut;
        } else {
            // 如果末尾没有空格，先加个空格再加内容
            this.userInput += ' ' + shortcut;
        }

        // 6. (可选) 自动聚焦聊天输入框，让用户可以直接接着打字
        // 如果你的输入框组件设置了 ref="chatInput"
        this.$nextTick(() => {
            if (this.$refs.chatInput) {
                // 如果是 el-input 需要访问内部的 input 元素
                const inputEl = this.$refs.chatInput.$el.querySelector('input') || this.$refs.chatInput.$el.querySelector('textarea');
                if (inputEl) inputEl.focus();
                else this.$refs.chatInput.focus();
            }
        });
    },

    handleOmniTTSenabled(newValue){
      if (newValue === true && this.ttsSettings.enabled === true) {
        this.ttsSettings.enabled = false;
        showNotification(this.t('autoDisableTtsSettings'), 'warning');
      }
      this.autoSaveSettings();
    },

    async handleFullScreenChange(val) {
      if (!val) {
        // 如果开关变成 false（关闭全屏），主动调起选区界面
        await this.reselectRegion();
      } else {
        // 如果开关变成 true（开启全屏），直接保存设置
        this.autoSaveSettings();
      }
    },

    /**
     * 呼出边框让用户重新选择屏幕区域
     */
    async reselectRegion() {
      try {
        // 调用 preload 暴露的方法，传入 true 让主窗口暂时隐藏
        const rect = await window.electronAPI.showScreenshotOverlay(true);
        
        // 选区结束后，恢复显示主窗口
        window.electronAPI.windowAction('show');
        
        if (rect) {
          // 用户成功框选，记录选区：[x, y, 宽度, 高度]
          this.visionControlSettings.ScreenSize = [
            Math.floor(rect.x), 
            Math.floor(rect.y), 
            Math.floor(rect.width), 
            Math.floor(rect.height)
          ];
          this.visionControlSettings.isFullScreen = false;
        } else {
          // 如果 rect 为空（比如用户按 Esc 取消了截图），自动恢复为全屏模式
          this.visionControlSettings.isFullScreen = true;
        }
        
        // 触发自动保存
        this.autoSaveSettings();
        
      } catch (error) {
        console.error("选区失败:", error);
        // 如果发生错误，确保主窗口重新出现并恢复状态
        window.electronAPI.windowAction('show');
        this.visionControlSettings.isFullScreen = true;
        this.autoSaveSettings();
      }
    },

    // 开启工作区监控
    setupWorkspaceWatcher(path) {
      if (window.electronAPI && window.electronAPI.startWorkspaceWatch) {
        window.electronAPI.startWorkspaceWatch(path);
        
        window.electronAPI.onWorkspaceChanged((data) => {
          console.log('前端收到文件系统变化:', data.action, data.path);
          
          // ⚠️ 关键修复：使用原生定时器彻底解决 this 指向丢失的问题
          if (this.workspaceRefreshTimer) {
            clearTimeout(this.workspaceRefreshTimer);
          }
          
          this.workspaceRefreshTimer = setTimeout(() => {
            console.log('触发防抖更新 UI ...');
            this.refreshWorkspaceTreeKeepExpanded();
          }, 500);
        });
      }
    },

    // 刷新前保留展开状态
    refreshWorkspaceTreeKeepExpanded() {
      const treeRef = this.$refs.workspaceTreeRef;
      if (treeRef) {
        const store = treeRef.store;
        const expandedKeys = [];
        for (const key in store.nodesMap) {
          if (store.nodesMap[key].expanded) {
            expandedKeys.push(key);
          }
        }
        this.expandedNodeKeys = expandedKeys;
        console.log('当前记录的展开文件夹节点:', this.expandedNodeKeys);
      } else {
        console.warn('未找到 el-tree 的引用 (workspaceTreeRef)');
      }
      
      this.refreshWorkspaceTree();
    },

// 1. 修改后的流式随机话题生成逻辑
async generateRandomTopic() {
  if (this.isTopicGenerating) return;
  this.isTopicGenerating = true;
  
  // 开始前清空输入框，方便看到打字机效果
  this.userInput = ''; 

  try {
    const res = await fetch('/simple_chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.mainAgent,
        messages: [
          {
            role: 'system',
            content: '你是一个有趣的话题发起人。请根据当前热门技术、科幻、哲学或日常生活，生成一个简短、有趣、能引起讨论的对话开头或问题。只需要返回话题文字本身，不要有任何多余的修饰。'
          },
          {
            role: 'user',
            content: `给我一个有趣的话题，请使用${this.currentLanguage}语言。`
          }
        ],
        temperature: 1,
        stream: true // 开启流式
      })
    });

    if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);

            await iterateNdjsonLines(res, (data) => {
          const content = data.choices?.[0]?.delta?.content;
          if (content) {
        // 实时追加到 userInput，实现打字机效果
        this.userInput += content;
          }
            }, { stripDataPrefix: true });

  } catch (e) {
    console.error("生成话题失败", e);
    // 降级处理：直接显示一个随机话题
    const fallbackTopics = ["Will future AI have emotions?", "Recommend a book you've read recently", "If you could teleport instantly, where would you want to go?"];
    this.userInput = fallbackTopics[Math.floor(Math.random() * fallbackTopics.length)];
  } finally {
    this.isTopicGenerating = false;
  }
},

// 2. 仪表盘发送逻辑
handleDashboardSend() {
  if (!this.userInput.trim()) return;
  // 跳转到聊天页
  this.activeMenu = 'home';
  this.clearMessages();
  // 调用原本的发送方法
  this.$nextTick(() => {
    this.sendMessage();
  });
},

// 3. 万能智能体确认
confirmOmniAgent() {
  if (!this.CLISettings.cc_path) {
    showNotification(this.t('pleaseSelectWorkspaceFirst'), 'error');
    return;
  }
  // 开启 CLI
  this.CLISettings.enabled = true;
  this.handleEnableToggle(true);
  // 关闭弹窗并跳转
  this.showOmniAgentDialog = false;
  this.activeMenu = 'home';
  showNotification(this.t('omniAgentEnabled'));
},

// 4. 扩展收藏逻辑
toggleFavoriteExtension(ext) {
  const index = this.favoriteExtensionIds.indexOf(ext.id);
  if (index > -1) {
    this.favoriteExtensionIds.splice(index, 1);
  } else {
    this.favoriteExtensionIds.push(ext.id);
  }
  // 持久化存储
  localStorage.setItem('favorite_extensions', JSON.stringify(this.favoriteExtensionIds));
},

createNewTask(){
  this.activeMenu = 'home';
  this.expandSidePanel();
  this.activeSideView = 'tasks';

},
openAiBrowser(){
  this.activeMenu = 'ai-browser';
  this.chromeMCPSettings.type = 'internal';
  this.chromeMCPSettings.enabled = true;
  this.changeChromeMCPEnabled();
},

connectToChatApp(){
  this.activeMenu = 'deploy-bot';
  this.subMenu = 'im_bot';
},

startLiveStream(){
  this.activeMenu = 'deploy-bot';
  this.subMenu = 'live_stream';
},

gotoAddExtension(){
  this.activeMenu = 'api-group';
  this.subMenu = 'extension';
  this.openAddExtensionDialog();
},

  // 2. 添加这两个处理鼠标状态的方法
  handleExtMouseMove() {
    this.extButtonVisible = true;
    
    // 清除上一次的定时器
    if (this.extMouseTimer) {
      clearTimeout(this.extMouseTimer);
    }
    
    // 如果鼠标停止移动 1.5 秒，自动隐藏按钮
    this.extMouseTimer = setTimeout(() => {
      this.extButtonVisible = false;
    }, 1500);
  },
  
  hideExtButton() {
    this.extButtonVisible = false;
    if (this.extMouseTimer) {
      clearTimeout(this.extMouseTimer);
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
  },

  async checkAcpxStatus() {
    this.checkingAcpx = true
    try {
      const host = window.location.hostname || '127.0.0.1'
      const port = window.location.port || '3456'
      const res = await fetch(`http://${host}:${port}/api/acpx/status`)
      const data = await res.json()
      
      if (data.available) {
        this.acpxStatus = 'available'
        showNotification(`ACPM Ready - Environment: ${data.environment}`)
      } else {
        this.acpxStatus = 'unavailable'
        showNotification(`ACPM Not Found: ${data.error}`,'error')
      }
    } catch (err) {
      this.acpxStatus = 'unavailable'
      showNotification('Failed to check ACPX status','error')
    } finally {
      this.checkingAcpx = false
    }
  },

}
