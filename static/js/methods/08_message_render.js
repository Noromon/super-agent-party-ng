// 批 3 F2：自 vue_methods.js 搬移的消息渲染与编辑域（Object.assign 装配）。
Object.assign(vue_methods, {
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
              // B4(上游 on* 剥离): 合法标签名保留但事件属性一律剥除，防 XSS
              const safeAttrs = attrs.replace(/\s+on\w+\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]*)/gi, '');
              return `<${slash}${tagName}${safeAttrs}>`;
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

  stringifyEntityId(value) {
    if (value === null || value === undefined || value === '') {
      return null;
    }
    return String(value);
  }
});
