// 批 3 F2：自 vue_methods.js 搬移的 methods/12_context_todos.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // ==========================================
    // 1. 用户动作入口与调度函数（可直接替换）
    // ==========================================
    updateTodoStats(evt) {
      const k = this.stringifyEntityId(this.conversationId ?? 'draft');
      this.todoStats = { ...this.todoStats, [k]: evt };
    },

    todoUsage() {
      return this.todoStats[this.stringifyEntityId(this.conversationId ?? 'draft')] || null;
    },

    todoColorClass() {
      const u = this.todoUsage();
      if (!u || !u.total) return 'ctx-green';
      const r = u.done / u.total;
      return r >= 1 ? 'ctx-green' : 'ctx-orange';
    },

    updateContextStats(evt) {
      const k = this.stringifyEntityId(this.conversationId ?? 'draft');
      this.contextStats = { ...this.contextStats, [k]: { ...evt, ts: Date.now() } };
      if ((this.conversationId ?? null) === null && evt) {
        const draft = this.contextStats.draft;
        delete this.contextStats.draft;
        this.contextStats = { ...this.contextStats };
        if (draft) setTimeout(() => {
          const k2 = this.stringifyEntityId(this.conversationId);
          if (k2 && !this.contextStats[k2]) { this.contextStats = { ...this.contextStats, [k2]: draft }; }
        }, 500);
      }
    },

    ctxUsage() {
      return this.contextStats[this.stringifyEntityId(this.conversationId ?? 'draft')] || null;
    },

    fmtTk(n) {
      if (n === null || n === undefined) return '-';
      return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n);
    },

    ctxPct() {
      const u = this.ctxUsage();
      if (!u || !u.window) return 0;
      const used = u.prompt_tokens || u.est_total || 0;
      return Math.min(100, Math.round(used / u.window * 100));
    },

    ctxColorClass() {
      const p = this.ctxPct();
      return p >= 85 ? 'ctx-red' : (p >= 60 ? 'ctx-orange' : 'ctx-green');
    },

    showCtxHover(e) {
      const r = e.currentTarget.getBoundingClientRect();
      this.ctxPopStyle = {
        position: 'fixed',
        bottom: (window.innerHeight - r.top + 8) + 'px',
        right: (window.innerWidth - r.right) + 'px',
        zIndex: 3000,
      };
      this.ctxHover = true;
    },

    showTodoHover(e) {
      const r = e.currentTarget.getBoundingClientRect();
      this.todoPopStyle = {
        position: 'fixed',
        bottom: (window.innerHeight - r.top + 8) + 'px',
        right: (window.innerWidth - r.right) + 'px',
        zIndex: 3000,
      };
      this.todoHover = true;
    },

    compactNow() {
      this.ctxPanelVisible = false;
      this.handleCompactCommand(false);
    },

    applyContextCompact(evt) {
      // 上下文压缩落账：system + 摘要卡 + 最近若干条展示消息
      const sysMsg = this.messages.find(m => m.role === 'system');
      const nonSys = this.messages.filter(m => m.role !== 'system');
      const kept = nonSys.slice(-6);
      const summaryText = evt.summary || '';
      const summaryMsg = {
        id: Date.now() + Math.random(),
        role: 'assistant',
        content: `🗜️ ${this.t('compact_card') || '上下文已压缩'} (${evt.compacted_count || 0})\n\n${summaryText}`,
        is_compact_summary: true,
        backend_content: [{
          role: 'user',
          content: `【对话摘要·已压缩】\n${summaryText}\n（以上为本会话早前内容的压缩摘要，视为已发生且已确认的事实；不要重做其中已完成的动作，直接基于它继续当前任务。）`
        }]
      };
      const rebuilt = [];
      if (sysMsg) rebuilt.push(sysMsg);
      rebuilt.push(summaryMsg, ...kept);
      this.messages = rebuilt;
      this.$nextTick(() => this.requestScrollToBottom());
      this.markConvDirty(this.conversationId);
      this.flushDirtyConversations();
    },

    async handleCompactCommand(focus) {
      const backendMsgs = [];
      for (const msg of this.messages) {
        if (msg.role === 'system') {
          backendMsgs.push({ role: 'system', content: String(msg.pure_content ?? msg.content ?? '') });
          continue;
        }
        if (msg.role === 'assistant' && msg.backend_content && msg.backend_content.length > 0) {
          const startIdx = backendMsgs.length;
          for (const m of msg.backend_content) {
            if ((m.content && String(m.content).trim() !== '') || (m.tool_calls && m.tool_calls.length > 0) || m.role === 'tool') {
              backendMsgs.push({ role: m.role, content: m.content, tool_calls: m.tool_calls, tool_call_id: m.tool_call_id, name: m.name });
            }
          }
          if (backendMsgs.length === startIdx) {
            const body = String((msg.pure_content ?? msg.content ?? '') + (msg.fileLinks_content ?? ''));
            if (body.trim()) backendMsgs.push({ role: 'assistant', content: body });
          }
          continue;
        }
        const text = (msg.pure_content ?? msg.content ?? '') + (msg.fileLinks_content ?? '');
        if (String(text).trim()) {
          backendMsgs.push({ role: msg.role === 'assistant' ? 'assistant' : 'user', content: text });
        }
      }
      if (backendMsgs.length < 6) {
        showNotification(this.t('compact_no_need') || '当前会话较短，无需压缩', 'info');
        return;
      }
      showNotification(this.t('compact_running') || '正在压缩上下文…', 'info');
      try {
        const resp = await fetch('/api/compact', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ messages: backendMsgs, focus: focus || '', conversation_id: this.conversationId })
        });
        const data = await resp.json();
        if (data.ok) {
          this.applyContextCompact(data);
          showNotification(`${this.t('compact_done') || '上下文已压缩'} (${data.compacted_count})`, 'success');
        } else {
          showNotification(this.t('compact_no_need') || '当前会话较短，无需压缩', 'info');
        }
      } catch (e) {
        showNotification(`${this.t('compact_failed') || '压缩失败'}: ${e.message}`, 'error');
      }
    }
});
