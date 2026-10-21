// 批 3 F2：自 vue_methods.js 搬移的 methods/62_backup.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
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
      this.backupNowRunning = true;
      try {
        const resp = await fetch('/api/backup/now', { method: 'POST' });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || data.ok === false) {
          throw new Error(data.reason || ('HTTP ' + resp.status));
        }
        this.$message?.success(this.t('dataGuardBackupOk') + ` (${data.files} ${this.t('dataGuardFiles')} / ${this.formatBackupBytes(data.bytes)})`);
        await this.loadBackupList();
      } catch (e) {
        this.$message?.error(this.t('dataGuardBackupFail') + ': ' + e.message);
      } finally {
        this.backupNowRunning = false;
      }
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
      if (n < 1024) return n + ' B';
      if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
      if (n < 1073741824) return (n / 1048576).toFixed(1) + ' MB';
      return (n / 1073741824).toFixed(2) + ' GB';
    }
});
