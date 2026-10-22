// A5 日记系统：自上游 vue_methods.js(20458-20671) 移植（S65）。
Object.assign(vue_methods, {
    handleDiaryTabChange(tabName) {
      if (tabName === 'data') {
        this.refreshDiaryView();
      }
    },

    // 刷新整个日记本视图（先拉本子列表，再拉当前本子内容）
    async refreshDiaryView() {
      await this.fetchDiaryBooks();
      await this.fetchDiaryData();
    },

    async fetchDiaryBooks() {
      try {
        const response = await fetch('/api/diary/books');
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        this.diaryBooks = (data && Array.isArray(data.books)) ? data.books : [];
        // 当前选中的本子若已不存在，回落到 default
        if (!this.diaryBooks.some(b => b.bookId === this.diaryCurrentBook)) {
          this.diaryCurrentBook = 'default';
        }
      } catch (error) {
        console.error("获取日记本列表失败:", error);
      }
    },

    async fetchDiaryData() {
      try {
        const bookId = this.diaryCurrentBook || 'default';
        const response = await fetch(`/api/diary/get_data?book_id=${encodeURIComponent(bookId)}`);
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        const data = await response.json();
        this.diaryEntries = (data && Array.isArray(data.entries)) ? data.entries : [];
      } catch (error) {
        console.error("获取日记数据失败:", error);
        if (this.$message) this.$message.error("无法加载日记数据，请检查后端是否正常运行");
      }
    },

    // 切换查看的日记本
    switchDiaryBook(bookId) {
      if (!bookId || bookId === this.diaryCurrentBook) return;
      this.diaryCurrentBook = bookId;
      this.diaryEntries = [];
      this.fetchDiaryData();
    },

    // 日记本的显示名称：优先用角色卡当前名，其次本子里存的名字，default 用兜底文案
    diaryBookLabel(book) {
      if (!book) return '';
      if (book.isDefault || book.bookId === 'default') {
        return this.t('diaryDefaultBook') || '默认日记本';
      }
      const mem = (this.memories || []).find(m => String(m.id) === String(book.characterId || book.bookId));
      if (mem && mem.name) return mem.name;
      if (book.characterName) return book.characterName;
      return this.t('diaryUnknownRole') || '未知角色';
    },

    // 日记本头像：从角色卡解析，没有则用默认头像
    diaryBookAvatar(book) {
      if (!book || book.isDefault || book.bookId === 'default') return '';
      const mem = (this.memories || []).find(m => String(m.id) === String(book.characterId || book.bookId));
      if (mem && mem.avatar) return mem.avatar;
      return '';
    },

    openDiaryDetail(entry) {
      this.diaryDetailEntry = entry;
      this.diaryDetailVisible = true;
    },

    closeDiaryDetail() {
      this.diaryDetailVisible = false;
      this.diaryDetailEntry = null;
    },

    deleteDiaryEntryById(id) {
      this.$confirm(this.t('confirmDelete') || '确认删除这篇日记吗？', this.t('warning') || '警告', {
        confirmButtonText: this.t('confirm') || '确定',
        cancelButtonText: this.t('cancel') || '取消',
        type: 'warning'
      }).then(async () => {
        try {
          const response = await fetch('/api/diary/delete', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id, book_id: this.diaryCurrentBook || 'default' })
          });
          if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
          this.diaryEntries = this.diaryEntries.filter(e => e.id !== id);
          if (this.diaryDetailEntry && this.diaryDetailEntry.id === id) this.closeDiaryDetail();
          this.fetchDiaryBooks();
          if (this.$message) this.$message.success(this.t('deleted') || '已删除');
        } catch (error) {
          console.error("删除日记失败:", error);
          if (this.$message) this.$message.error("删除日记失败");
        }
      }).catch(() => {});
    },

    // 用户手动切换日记动作开关时，自动开启对应的底层工具
    async onDiaryActionToggle(key) {
      const enabled = this.diarySettings.actions[key].enabled;
      // 先保存日记配置
      await this.autoSaveSettings();

      if (!enabled) return;

      try {
        switch (key) {
          case 'webSearch':
            this.webSearchSettings.enabled = true;
            await this.autoSaveSettings();
            showNotification(this.t('diaryAutoTool_webSearch') || '联网搜索工具已被自动开启', 'success');
            break;

          case 'knowledge':
            if (!this.knowledgeBases || this.knowledgeBases.length === 0) {
              showNotification(this.t('diaryAutoTool_noKb') || '没有已配置的知识库，请先在知识库设置中添加', 'warning');
              break;
            }
            if (!this.knowledgeBases.some(kb => kb.enabled)) {
              this.knowledgeBases[0].enabled = true;
            }
            await this.autoSaveSettings();
            showNotification(this.t('diaryAutoTool_knowledge') || '知识库工具已被自动开启', 'success');
            break;

          case 'browserControl':
            this.chromeMCPSettings.enabled = true;
            this.chromeMCPSettings.type = 'internal';
            if (this.isElectron && window.electronAPI) {
              const cdpInfo = await window.electronAPI.getInternalCDPInfo();
              if (cdpInfo.active) {
                this.chromeMCPSettings.CDPport = cdpInfo.port;
              }
            }
            await this.autoSaveSettings();
            showNotification(this.t('diaryAutoTool_browser') || '浏览器控制工具（内建 CDP）已被自动开启', 'success');
            break;

          case 'smartHome':
            if (!this.HASettings.api_key) {
              showNotification(this.t('diaryAutoTool_noHaKey') || '未配置 Home Assistant API Key，请先在智能家居设置中填写', 'warning');
              this.diarySettings.actions[key].enabled = false;
              await this.autoSaveSettings();
              break;
            }
            this.HASettings.enabled = true;
            await this.autoSaveSettings();
            const haResp = await fetch('/start_HA', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ data: this.HASettings })
            });
            if (haResp.ok) {
              showNotification(this.t('diaryAutoTool_smartHome') || '智能家居工具已被自动开启', 'success');
            } else {
              this.HASettings.enabled = false;
              this.diarySettings.actions[key].enabled = false;
              await this.autoSaveSettings();
              const errText = await haResp.text().catch(() => '');
              showNotification(this.t('diaryAutoTool_smartHomeFail') || ('智能家居工具开启失败：' + (errText || '请检查 HA 配置')), 'error');
            }
            break;
        }
      } catch (e) {
        console.error('[Diary] 自动开启工具失败:', e);
        showNotification(this.t('diaryAutoTool_error') || ('开启对应工具失败: ' + (e.message || '未知错误')), 'error');
      }
    },

    // 动作类型的图标/标签颜色（供模板使用）
    diaryMeta(type) {
      return (this.diaryActionMeta && this.diaryActionMeta[type]) || { icon: 'fa-solid fa-book', type: 'info' };
    },

    // 将后端推送的日记原样展示到当前对话
    pushDiaryToChat(content, actionType) {
      // 若正在查看日记本，顺手刷新一下列表
      if (this.subMenu === 'diary' && this.activeDiaryTab === 'data') {
        this.refreshDiaryView();
      }
      if (!Array.isArray(this.messages)) return;
      const diaryContent = content || '';
      const entry = {
        id: Date.now() + Math.random(),
        role: 'assistant',
        agentName: (this.t('DiarySystem') || '日记'),
        content: diaryContent,
        pure_content: diaryContent,
        // 使用标准新架构 displayBlocks，与普通助手消息一致
        displayBlocks: [{ type: 'text', content: diaryContent, segments: [{ type: 'text', content: diaryContent }] }],
        segments: [{ type: 'text', content: diaryContent }],
        isDiary: true,
        diaryType: actionType || 'think',
        generationFinished: true,
        timestamp: Date.now()
      };
      this.messages.push(entry);
      // 同步回当前对话，确保持久化与主对话界面正确显示
      const conv = this.conversations.find(c => c.id === this.conversationId);
      if (conv) {
        conv.messages = this.messages;
      }
      if (typeof this.saveConversations === 'function') {
        this.saveConversations();
      }
      this.$nextTick(() => { if (typeof this.scrollToBottom === 'function') this.scrollToBottom(); });
    },

    // ---- S71：日记主动推送目标（imTargetMap {platform:[ids]}；空/缺省 = 自动取触发时主会话）----
    diaryTargetPlatformsList() {
      const list = this.diarySettings && this.diarySettings.imTargets;
      if (!Array.isArray(list)) return [];
      const seen = new Set();
      const out = [];
      for (const tgt of list) {
        const p = typeof tgt === 'string' ? tgt : (tgt && tgt.platform);
        if (p && p !== 'chat' && !seen.has(p)) { seen.add(p); out.push(p); }
      }
      return out;
    },

    diaryPlatformLabel(p) {
      const map = {
        wechat: '微信', feishu: '飞书', dingtalk: '钉钉', wecom: '企业微信',
        telegram: 'Telegram', discord: 'Discord', slack: 'Slack', xmpp: 'XMPP',
      };
      return map[p] || p;
    },

    diaryImTargetOptionLabel(o) {
      if (!o || !o.id) return '';
      let label = o.id;
      if (o.is_main) {
        label += this.t('diaryImTargetMainSuffix') || '（当前激活主会话）';
      } else if (o.last_active) {
        const d = new Date(o.last_active * 1000);
        label += ' · ' + String(d.getHours()).padStart(2, '0') + ':'
          + String(d.getMinutes()).padStart(2, '0');
      }
      return label;
    },

    async onDiaryImTargetsChange() {
      // 移除未再勾选渠道的目标残留，避免无效配置常驻 settings
      const keep = new Set(this.diaryTargetPlatformsList());
      const map = this.diarySettings.imTargetMap || (this.diarySettings.imTargetMap = {});
      for (const p of Object.keys(map)) {
        if (!keep.has(p)) delete map[p];
      }
      if (keep.size) this.requestDiaryImTargets();
      await this.autoSaveSettings();
    },

    onDiaryImTargetChange(platform, ids) {
      if (!this.diarySettings.imTargetMap) this.diarySettings.imTargetMap = {};
      this.diarySettings.imTargetMap[platform] = Array.isArray(ids) ? ids : [];
      this.autoSaveSettings();
    },

    requestDiaryImTargets() {
      if (this.ws && this.ws.readyState === 1) {
        this.ws.send(JSON.stringify({ type: 'get_diary_im_targets' }));
      }
    },

    applyDiaryImTargetOptions(payload) {
      this.diaryImTargetOptions = (payload && payload.targets) || {};
    },

    // 处理单击文件自动添加 @ 快捷方式
});
