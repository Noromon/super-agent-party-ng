// 批 3 F2：自 vue_methods.js 搬移的 methods/82_translate_panel.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
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

      let result = '';
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
  }
});
