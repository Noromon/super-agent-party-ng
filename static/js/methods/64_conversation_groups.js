// 批 3 F2：自 vue_methods.js 搬移的 methods/64_conversation_groups.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
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
      // S81(A8)：切换会话不再手动 MathJax typeset——KaTeX 输出即普通 HTML，morphdom 自然 diff

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
    }
});
