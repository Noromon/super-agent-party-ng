// 批 3 F2：自 vue_methods.js 搬移的 methods/62_backup.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
// S280/S281：备份内容项目录与后端 py/data_backup.py BACKUP_ITEM_IDS 严格同序同集。
const BACKUP_ITEM_IDS = ["settings", "appdb", "convdb", "txtidx", "memory_cache",
                         "agents", "kb", "diary", "ext", "uploads"];
Object.assign(vue_methods, {
    // --- 数据安全网（M4-lite 快照备份 UI）---
    async loadBackupList() {
      this.backupListLoading = true;
      try {
        const resp = await fetch('/api/backup/list');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.backupSnapshots = (data.snapshots || []).slice().reverse();
      } catch (e) {
        this.$message?.error(this.t('dataGuardLoadFail') + ': ' + e.message);
      } finally {
        this.backupListLoading = false;
      }
    },

    async backupNow() {
      if (this.backupNowRunning) return;
      // S281：按"本次手动"勾选构成上传 include；未打开面板（未初始化）= 后端缺省全选
      const inc = (Array.isArray(this.backupSelManual) && this.backupSelManual.length)
        ? this.backupSelManual.filter(i => BACKUP_ITEM_IDS.includes(i)) : null;
      if (Array.isArray(this.backupSelManual) && this.backupSelManual.length === 0 && this.backupEstimate) {
        this.$message?.warning(this.t('dataGuardSelEmpty'));
        return;
      }
      this.backupNowRunning = true;
      try {
        const resp = await fetch('/api/backup/now', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(inc ? { include: inc } : {}),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data.ok === false) {
          throw new Error(data.reason || data.detail || ('HTTP ' + resp.status));
        }
        this.$message?.success(this.t('dataGuardBackupOk') + ` (${data.files} ${this.t('dataGuardFiles')} / ${this.formatBackupBytes(data.bytes)})`);
        await this.loadBackupList();
      } catch (e) {
        this.$message?.error(this.t('dataGuardBackupFail') + ': ' + e.message);
      } finally {
        this.backupNowRunning = false;
      }
    },

    // --- S281：内容构成与容量面板 ---
    backupItemLabel(id) {
      const s = this.t('backupItem_' + id);
      return s || id;
    },

    // 自动备份构成缺省推导：显式 backupAutoItems 优先；否则按遗留开关
    //（backupIncludeUploads===false → 排除 uploads；其余一律全选）
    backupItemDefaultAuto() {
      const saved = this.systemSettings && this.systemSettings.backupAutoItems;
      if (Array.isArray(saved) && saved.length) {
        return BACKUP_ITEM_IDS.filter(i => saved.includes(i));
      }
      return (this.systemSettings && this.systemSettings.backupIncludeUploads === false)
        ? BACKUP_ITEM_IDS.filter(i => i !== 'uploads')
        : BACKUP_ITEM_IDS.slice();
    },

    async loadBackupEstimate() {
      if (this.backupEstimateLoading) return;
      this.backupEstimateLoading = true;
      try {
        const resp = await fetch('/api/backup/estimate');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        this.backupEstimate = await resp.json();
        if (!this.backupSelAuto.length) this.backupSelAuto = this.backupItemDefaultAuto();
        if (!this.backupSelInit) {
          this.backupSelManual = BACKUP_ITEM_IDS.slice();
          this.backupSelInit = true;
        }
      } catch (e) {
        this.$message?.error(this.t('dataGuardEstFail') + ': ' + e.message);
      } finally {
        this.backupEstimateLoading = false;
      }
    },

    setBackupSel(which, id, on) {
      const arr = which === 'auto' ? this.backupSelAuto : this.backupSelManual;
      const i = arr.indexOf(id);
      if (on && i < 0) arr.push(id);
      if (!on && i >= 0) arr.splice(i, 1);
      if (which === 'auto') this.saveBackupAutoItems();
    },

    async saveBackupAutoItems() {
      try {
        // 全选时回落 null=交后端按遗留语义缺省，避免把目录写死挡住未来新增项
        const sel = BACKUP_ITEM_IDS.filter(i => this.backupSelAuto.includes(i));
        this.systemSettings.backupAutoItems = (sel.length === BACKUP_ITEM_IDS.length) ? null : sel;
        await this.autoSaveSettings();
      } catch (e) {}
    },

    async verifyBackup(name) {
      this.verifyBackupName = name;
      try {
        const resp = await fetch('/api/backup/verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.detail || ('HTTP ' + resp.status));
        if (data.ok) this.$message?.success(`${name}: ` + this.t('dataGuardVerifyOk'));
        else this.$message?.error(`${name}: ` + this.t('dataGuardVerifyFail'));
      } catch (e) {
        this.$message?.error(this.t('dataGuardVerifyFail') + ': ' + e.message);
      } finally {
        this.verifyBackupName = '';
      }
    },

    formatBackupBytes(n) {
      n = Number(n) || 0;
      if (n < 0) return '--';
      if (n < 1024) return n + ' B';
      if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
      if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
      return (n / 1073741824).toFixed(2) + ' GB';
    }
});
