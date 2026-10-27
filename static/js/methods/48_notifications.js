// S151：通知中心域——顶栏铃铛、抽屉面板、分类筛选与 IM 挂起审批的双向批复。
Object.assign(vue_methods, {
  async openNotificationsPanel() {
    this.notificationsOpen = true;
    await this.fetchNotifications();
    // 打开即视为已读（未读角标清零；待审批仍单独计数）
    this.notifMarkAllRead();
  },

  closeNotificationsPanel() {
    this.notificationsOpen = false;
  },

  async fetchNotifications() {
    this.notifLoading = true;
    try {
      const res = await fetch('/api/notifications?limit=100');
      const json = await res.json();
      this.notificationItems = Array.isArray(json.items) ? json.items : [];
    } catch (e) {
      console.error('获取通知失败', e);
    }
    this.notifLoading = false;
  },

  onWsNotification(rec) {
    if (!rec || !rec.id) return;
    if (this.notificationItems.some(d => d.id === rec.id)) return;
    this.notificationItems.unshift(rec);
    if (this.notificationItems.length > 200) this.notificationItems.splice(200);
  },

  notifFilteredItems() {
    if (!this.notificationFilter) return this.notificationItems;
    return this.notificationItems.filter(d => d.category === this.notificationFilter);
  },

  // pending 判定：approval 挂起事件尚未被同 pending_key 的决策事件销账
  notifIsPending(item) {
    const ex = item.extra || {};
    if (item.category !== 'approval' || ex.status !== 'pending') return false;
    const key = ex.pending_key || '';
    return !this.notificationItems.some(d => {
      const e2 = d.extra || {};
      return e2.status === 'resolved' && (e2.pending_key || '') === key && key !== '';
    });
  },

  notifBadgeCount() {
    let n = 0;
    for (const d of this.notificationItems) {
      if (this.notifIsPending(d)) { n += 1; continue; }
      if (!d.read) n += 1;
    }
    return n;
  },

  notifCatLabel(item) {
    const m = {
      approval: 'notifCatApproval', generation: 'notifCatGeneration',
      bot: 'notifCatBot', error: 'notifCatError', system: 'notifCatSystem',
    };
    const k = m[item.category];
    return k ? this.t(k) : item.category;
  },

  notifTime(item) {
    try { return new Date((item.ts || 0) * 1000).toLocaleString(); } catch (e) { return ''; }
  },

  async notifMarkAllRead() {
    this.notificationItems.forEach(d => { d.read = true; });
    try {
      await fetch('/api/notifications/read', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: null }),
      });
    } catch (e) { /* 下次打开面板兜底 */ }
  },

  async notifClearAll() {
    try {
      await fetch('/api/notifications/clear', { method: 'POST' });
    } catch (e) { /* ignore */ }
    this.notificationItems = [];
  },

  async notifDecision(item, decision) {
    const ex = item.extra || {};
    if (ex.source !== 'im') { this.notifGoChat(); return; }
    try {
      const res = await fetch('/api/notifications/im_decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approval_id: ex.approval_id || ex.pending_key, decision, note: '' }),
      });
      const json = await res.json();
      showNotification(json.message || (json.success ? this.t('notifDecided') : this.t('notifDecideFailed')),
        json.success ? 'success' : 'error');
    } catch (e) {
      showNotification(this.t('notifDecideFailed'), 'error');
    }
    await this.fetchNotifications();
  },

  // Web 来源挂起审批：引导回会话审批卡处理（唯一能正确回写会话历史的路径）
  notifGoChat() {
    this.notificationsOpen = false;
    this.activeMenu = 'home';
  },
});
