// 批 3 F2：自 vue_methods.js 搬移的 methods/84_quickgen.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
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
  }
});
