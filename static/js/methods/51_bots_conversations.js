// 批 3 F2：自 vue_methods.js 搬移的 methods/51_bots_conversations.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
async fetchBotConversations() {
  try {
    const res = await fetch('/bot_conversations');
    const json = await res.json();
    this.xmppBotSessions = json.conversations || [];
  } catch (e) {
    this.xmppBotSessions = [];
  }
},

async openBotConversation(c) {
  try {
    const res = await fetch('/bot_conversation?id=' + encodeURIComponent(c.conv_id));
    const json = await res.json();
    if (json.success) {
      this.xmppSessionDetail = json.messages || [];
      this.xmppSessionTitle = c.peer || c.conv_id;
      this.xmppSessionOpen = true;
    } else {
      showNotification(json.message || '会话读取失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误：会话读取失败', 'error');
  }
},

async clearBotConversation(id) {
  if (!window.confirm('清空该 bot 会话的历史记录？')) return;
  try {
    const res = await fetch('/bot_conversation/clear', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id })
    });
    const json = await res.json();
    if (json.success) {
      showNotification('会话已清空', 'success');
      if (this.xmppSessionTitle && ('bot:xmpp:' + this.xmppSessionTitle) === id) {
        this.xmppSessionDetail = [];
      }
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '清空失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},

async deleteBotConversation(id) {
  if (!window.confirm('删除该 bot 会话？（不可恢复）')) return;
  try {
    const res = await fetch('/bot_conversation?id=' + encodeURIComponent(id), { method: 'DELETE' });
    const json = await res.json();
    if (json.success) {
      showNotification('会话已删除', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '删除失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},

async newBotConversation(row) {
  if (!window.confirm('归档当前会话并开启新会话？下一条入站消息将从空白开始（旧会话保留在归档中）。')) return;
  try {
    const res = await fetch('/bot_conversation/new', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: row.conv_id })
    });
    const json = await res.json();
    if (json.success) {
      showNotification(json.archive_id ? '已归档，下一条消息开启新会话' : '会话已是空白，无需归档', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '操作失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},

async activateBotConversation(row) {
  if (!window.confirm('将该归档会话置为 live？当前进行中的同对端会话会被归档，下一条入站消息接续此会话。')) return;
  try {
    const res = await fetch('/bot_conversation/activate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: row.conv_id, into: `bot:${row.channel}:${row.peer}` })
    });
    const json = await res.json();
    if (json.success) {
      showNotification('已置为 live，下一条入站消息将接续该会话', 'success');
      this.fetchBotConversations();
    } else {
      showNotification(json.message || '操作失败', 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  }
},

formatBotTime(ts) {
  if (!ts) return '';
  try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return String(ts); }
},

botMsgText(msg) {
  const c = msg && msg.content;
  if (typeof c === 'string') return c.length > 800 ? c.slice(0, 800) + '…' : c;
  if (Array.isArray(c)) {
    return c.map(p => (p && p.type === 'text' ? p.text
      : (p && p.type === 'image_url' ? '[图片]' : ''))).filter(Boolean).join(' ');
  }
  return '';
}
});
