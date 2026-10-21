// 批 3 F2：自 vue_methods.js 搬移的 methods/79_prompt_crud.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
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
  }
});
