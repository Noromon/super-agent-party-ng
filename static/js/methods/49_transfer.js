// S161：记忆/日记导出与跨角色卡导入（目标卡必选；覆盖策略双重确认）。
Object.assign(vue_methods, {
  async transferExport(scope, cardId) {
    try {
      let url = '/api/transfer/export?scope=' + encodeURIComponent(scope || 'all');
      if (cardId) url += '&card_id=' + encodeURIComponent(cardId);
      const res = await fetch(url);
      if (!res.ok) {
        showNotification(this.t('transferExportFailed'), 'error');
        return;
      }
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="?([^";]+)"?/);
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = m ? m[1] : 'sap-backup.json';
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      showNotification(this.t('transferExportDone'), 'success');
    } catch (e) {
      showNotification(this.t('transferExportFailed'), 'error');
    }
  },

  openTransferImport(prefillCard) {
    this.transferPayload = null;
    this.transferSources = [];
    this.transferSelected = {};
    this.transferTarget = prefillCard || '';
    this.transferTargetStats = null;
    this.transferStrategy = 'merge';
    this.transferBusy = false;
    this.transferImportOpen = true;
    if (prefillCard) this.transferTargetChanged();
  },

  handleTransferFile(event) {
    const f = event.target.files && event.target.files[0];
    event.target.value = '';
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const j = JSON.parse(reader.result);
        if (!j || j.sap_backup !== 1 || !Array.isArray(j.sources)) {
          throw new Error('bad pack');
        }
        this.transferPayload = j;
        this.transferSources = j.sources;
        const sel = {};
        j.sources.forEach(s => { sel[s.card_id] = true; });
        this.transferSelected = sel;
      } catch (e) {
        this.transferPayload = null;
        this.transferSources = [];
        showNotification(this.t('transferFileInvalid'), 'error');
      }
    };
    reader.readAsText(f);
  },

  async transferTargetChanged() {
    this.transferTargetStats = null;
    if (!this.transferTarget) return;
    try {
      const res = await fetch('/api/transfer/target_stats?card_id=' + encodeURIComponent(this.transferTarget));
      if (res.ok) this.transferTargetStats = await res.json();
    } catch (e) { /* 警示降级为通用文案 */ }
  },

  transferWarnText() {
    const st = this.transferTargetStats;
    if (st && st.memories >= 0) {
      return this.t('transferReplaceWarn')
        .replace('{name}', st.card_name || st.card_id)
        .replace('{mem}', st.memories)
        .replace('{diary}', st.diary);
    }
    return this.t('transferReplaceWarnGeneric');
  },

  async transferDoImport() {
    if (!this.transferPayload || !this.transferTarget) {
      showNotification(this.t('transferNeedFileTarget'), 'error');
      return;
    }
    if (this.transferStrategy === 'replace') {
      // 覆盖=破坏性操作：量化警示后再弹一次确认（用户双保险要求）
      try {
        await this.$confirm(this.transferWarnText(), this.t('transferReplaceConfirmTitle'), {
          type: 'warning', confirmButtonText: this.t('transferReplace'),
        });
      } catch (e) { return; }
    }
    const ids = this.transferSources
      .filter(s => this.transferSelected[s.card_id])
      .map(s => s.card_id);
    if (!ids.length) {
      showNotification(this.t('transferNeedSource'), 'error');
      return;
    }
    this.transferBusy = true;
    try {
      const res = await fetch('/api/transfer/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          payload: this.transferPayload,
          target_card: this.transferTarget,
          strategy: this.transferStrategy,
          source_ids: ids,
        }),
      });
      const json = await res.json().catch(() => ({}));
      if (res.ok && json.success) {
        showNotification(json.message || this.t('transferImportDone'), 'success');
        this.transferImportOpen = false;
      } else {
        showNotification(json.detail || json.message || this.t('transferImportFailed'), 'error');
      }
    } catch (e) {
      showNotification(this.t('transferImportFailed'), 'error');
    }
    this.transferBusy = false;
  },
});
