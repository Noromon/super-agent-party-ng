// 批 3 F2：自 vue_methods.js 搬移的 methods/15_conversations.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    markConvDirty(convId) {
      if (convId === null || convId === undefined) return;
      if (!this._covsDirty) this._covsDirty = new Set();
      this._covsDirty.add(this.stringifyEntityId(convId));
    },

    // B2-2(16f079d4): 会话创建/刷新单点——发送首条消息时即分配 conversationId，
    // 保证长耗时流式回复（深度研究等）期间 30s 增量保存正常工作。
    // fork 决策：不带上游的 50 条会话裁剪（fork 为全量保留+行表增量策略）。
    ensureConversationCreated(titleMessages) {
      if (this.conversationId === null) {
        this.conversationId = uuid.v4();
        const newConv = {
          id: this.conversationId,
          title: this.generateConversationTitle(titleMessages || this.messages),
          mainAgent: this.mainAgent,
          groupId: this.activeConversationGroupId || this.draftConversationGroupId || 'default',
          timestamp: Date.now(),
          messages: this.messages,
          fileLinks: this.fileLinks,
          system_prompt: this.system_prompt,
        };
        this.conversations.unshift(newConv);
      } else {
        const conv = this.conversations.find(c => c.id === this.conversationId);
        if (conv) {
          conv.messages = this.messages;
          conv.timestamp = Date.now();
          conv.fileLinks = this.fileLinks;
          conv.groupId = conv.groupId || this.activeConversationGroupId || this.draftConversationGroupId || 'default';
          conv.system_prompt = this.system_prompt;
        }
      }
      this.markConvDirty(this.conversationId);
    },

    sanitizeConversationForSave(conv) {
      return {
        ...conv,
        messages: (conv.messages || []).map(msg => {
          const { audioChunks, omniAudioChunks, ttsQueue, isPlaying, cur_audioDatas, ...rest } = msg;
          return { ...rest, audioChunks: [], omniAudioChunks: [], currentChunk: 0, omniCurrentTime: 0, isPlaying: false };
        })
      };
    },

    flushDirtyConversations() {
      if (this._covsFlushing) return Promise.resolve();
      if (!this._covsDirty || this._covsDirty.size === 0) return Promise.resolve();
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return Promise.resolve();
      const ids = Array.from(this._covsDirty);
      const payload = [];
      for (const id of ids) {
        const conv = this.conversations.find(c => this.stringifyEntityId(c.id) === id);
        if (conv) payload.push(this.sanitizeConversationForSave(conv));
        this._covsDirty.delete(id);
      }
      if (!payload.length) return Promise.resolve();
      this._covsFlushing = true;
      const correlationId = uuid.v4();
      return new Promise((resolve) => {
        const finish = (acked) => {
          this._covsFlushing = false;
          try { this.ws.removeEventListener('message', handler); } catch (e) {}
          clearTimeout(timer);
          if (!acked) ids.forEach(id => this._covsDirty.add(id));
          if (this._covsDirty.size > 0) setTimeout(() => this.flushDirtyConversations(), 2000);
          resolve();
        };
        const handler = (event) => {
          let response; try { response = JSON.parse(event.data); } catch (e) { return; }
          if (response.type === 'conversations_delta_saved' && response.correlationId === correlationId) finish(true);
        };
        const timer = setTimeout(() => finish(false), 20000);
        this.ws.addEventListener('message', handler);
        try {
          this.ws.send(JSON.stringify({ type: 'save_conversations_delta', data: { conversations: payload }, correlationId }));
        } catch (e) { finish(false); }
      });
    },

    mergeRemoteConversations(remote) {
      const key = (id) => this.stringifyEntityId(id);
      if (!this._covsDirty) this._covsDirty = new Set();
      const localById = new Map(this.conversations.map(c => [key(c.id), c]));
      const remoteKeys = new Set(remote.map(c => key(c.id)));
      const merged = remote.map(rc => {
        const lc = localById.get(key(rc.id));
        if (lc && (this._covsDirty.has(key(rc.id)) || (lc.timestamp || 0) > (rc.timestamp || 0))) return lc;
        return rc;
      });
      for (const lc of this.conversations) {
        if (!remoteKeys.has(key(lc.id))) merged.unshift(lc);
      }
      this.conversations = merged;
      if (this._covsDirty.size > 0) this.flushDirtyConversations();
    },

    getSanitizedConversations() {
      // 使用 map 创建新数组，不影响原始的内存数据
      return this.conversations.map(conv => ({
        ...conv,
        // 清洗消息列表
        messages: conv.messages.map(msg => {
          // 使用解构赋值，排除掉不需要保存的大体积/临时属性
          const {
            audioChunks,      // 普通 TTS 的音频 Blob URL (保存了也没用)
            omniAudioChunks,  // PCM 流的巨大 Base64 数组 (核心清洗目标)
            ttsQueue,         // 运行时的 Set 队列
            isPlaying,        // 播放状态
            cur_audioDatas,   // 临时 Base64 数据
            ...rest           // 保留 role, content, pure_content, timestamp, fileLinks 等
          } = msg;

          // 返回一个干净的消息对象
          return {
            ...rest,
            // 明确将这些字段设为空，防止某些旧数据残留
            audioChunks: [],
            omniAudioChunks: [],
            currentChunk: 0,
            omniCurrentTime: 0,
            isPlaying: false
          };
        })
      }));
    },

    async saveConversations() {
      return new Promise((resolve, reject) => {
        const sanitizedConversations = this.getSanitizedConversations();

        const payload = {
          conversations: sanitizedConversations,
          conversationGroups: this.conversationGroups
        };
        const correlationId = uuid.v4();
        // 发送保存请求
        this.ws.send(JSON.stringify({
          type: 'save_conversations',
          data: payload,
          correlationId: correlationId // 添加唯一请求 ID
        }));
        // 设置响应监听器
        const handler = (event) => {
          const response = JSON.parse(event.data);
          
          // 匹配对应请求的确认消息
          if (response.type === 'conversations_saved' && 
              response.correlationId === correlationId) {
            this.ws.removeEventListener('message', handler);
            clearTimeout(timeout);
            if (this._covsDirty) this._covsDirty.clear();
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
    }
});
