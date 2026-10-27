// S145：IM 对端名录域（Object.assign 装配，加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_methods, {
    imPeerRows() {
      const plat = (this.imPeerSettings.roster || {})[this.imPeerPlatform] || {};
      return Object.keys(plat).map(id => ({ id, e: plat[id] }));
    },
    imPeerChanged() {
      this.autoSaveSettings();
    },
    _imPeerEnsurePlat() {
      if (!this.imPeerSettings.roster) this.imPeerSettings.roster = {};
      const r = this.imPeerSettings.roster;
      if (!r[this.imPeerPlatform]) r[this.imPeerPlatform] = {};
      return r[this.imPeerPlatform];
    },
    imPeerAdd() {
      const id = (this.imPeerNewId || '').trim();
      if (!id) return;
      const plat = this._imPeerEnsurePlat();
      if (!plat[id]) plat[id] = { alias: '', roleDesc: '', approver: false, notes: '' };
      this.imPeerNewId = '';
      this.autoSaveSettings();
    },
    imPeerQuickAdd(id) {
      this._imPeerEnsurePlat()[id] = { alias: '', roleDesc: '', approver: false, notes: '' };
      this.autoSaveSettings();
    },
    imPeerRemove(id) {
      delete this._imPeerEnsurePlat()[id];
      this.autoSaveSettings();
    },
    imPeerSeenUnlisted() {
      const seen = (this.imPeersSeen || {})[this.imPeerPlatform] || {};
      const reg = (this.imPeerSettings.roster || {})[this.imPeerPlatform] || {};
      return Object.keys(seen).filter(k => !reg[k])
        .sort((a, b) => ((seen[b] || {}).last_seen || 0) - ((seen[a] || {}).last_seen || 0));
    },
    async imPeerLoadSeen() {
      try {
        const r = await fetch('/api/peers-seen');
        this.imPeersSeen = await r.json();
      } catch (e) {
        // 静默：seen 仅为便捷提示，失败不影响名录编辑
      }
    },
});
