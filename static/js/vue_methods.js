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


// S81(A8)：KaTeX 引擎 + markdown-it-texmath（上游终态：md 渲染期同步排版，替代 MathJax 异步 typeset）
if (window.texmath) {
    md.use(window.texmath, {
        engine: window.katex, // 指定渲染引擎为 katex
        delims: 'dollars',    // 指定使用 $...$ 和 $$...$$ 语法
        katexOptions: {
            throwOnError: false,
            output: 'html'    // 强制输出 HTML，对流式渲染最友好
        }
    });
} else {
    console.warn('KaTeX/texmath 未加载，$ 公式将按普通文本渲染。');
}

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
  




















  

  
  




}
