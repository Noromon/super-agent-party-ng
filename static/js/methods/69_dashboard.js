// 批 3 F2：自 vue_methods.js 搬移的 dashboard 域（Object.assign 装配）。
Object.assign(vue_methods, {
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
}
});
