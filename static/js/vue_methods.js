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








    changeImgHost(val) {
      this.BotConfig.img_host = val;
      this.autoSaveSettings()
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


    
    

      /* ==========================================
       滚动区域逻辑优化（支持内部区块跟随滚动）
       ========================================== */






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













    // 在 methods 中添加
    t(key) {
      const lang = this.translations[this.currentLanguage];
      const fallback = this.translations['en-US'];
      return (lang && lang[key]) || (fallback && fallback[key]) || key;
    },


















    
    
    


    

    


  






  // --- 企微方法 ---



















  































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





















  
  
  
  
  


    
  
  
  
  
  
  
 

  
  











  











/* 生命周期：读取场景列表 */
/* 选择场景后实时切换背景 */

/* 上传区域点击 */

/* 拖拽上传 */

/* 移除待上传文件 */

/* 真正上传 */

/* 取消上传 */

/* 删除用户场景 */









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


    // --- 辅助函数保持不变 ---
    












  removeBehavior(idx) {
    this.behaviorSettings.behaviorList[idx].enabled = false;
    this.behaviorSettings.behaviorList.splice(idx, 1);
    showNotification(this.t('deleteBehaviorSuccess'))
    this.autoSaveSettings();
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






    





    // --- Webview 事件监听 ---
    // 注意：这些事件在 HTML 中通过 @did-start-loading="..." 绑定
    




    







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












    // ===============================================
    // Python Agent 专用接口 (Electron API 桥接)
    // ===============================================

    // --- 基础信息与导航 ---





    // ===============================================
    // Python Agent 专用接口 (稳定 JS 注入版)
    // ===============================================











    







// Methods















// --- 增强原有的监听和初始化 ---







  // 刷新扩展列表，并在之后对比版本状态
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
  



async handleRefreshSkills() {
  this.skillsLoading = true;
  try {
    // 假设你已定义了 fetchSkills 方法来获取列表
    await this.fetchSkills(); 
  } finally {
    this.skillsLoading = false;
  }
},






    // 执行删除
    removeBehavior(index) {
      this.behaviorSettings.behaviorList.splice(index, 1);
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




    // 3. 这里的 reset 函数在对话框关闭时调用 (el-dialog 的 @closed 事件)
    resetTaskForm() {
        this.isEditing = false;
        this.editingTaskId = null;
        this.newTaskForm = {
            title: '', description: '', task_type: 'once', agent_type: 'default',
            trigger_config: { timeValue: '09:00:00', days: [1,2,3,4,5], cycleValue: '01:00:00', repeatNumber: 1, isInfiniteLoop: true }
        };
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
