// S160 潜龙勿用：EOS 防御开关 + 存量隔离巡检/执行/灌回。
// 后端对破坏性动作强制两段式确认（scan/plan 发一次性 confirm_token），
// 这里在点击链路上再展示“即将发生的变更 + 警告”并寻求确认。
Object.assign(vue_methods, {
    async eosGuardInit() {
      try {
        const resp = await fetch('/api/eos_guard/status');
        if (!resp.ok) return;
        const data = await resp.json();
        if (data && data.eosGuard) {
          this.eosGuardSettings.enabled = !!data.eosGuard.enabled;
          this.eosGuardSettings.sanitize = data.eosGuard.sanitize !== false;
          this.eosGuardSettings.softBias = (data.eosGuard.softBias === undefined || data.eosGuard.softBias === null)
            ? -30 : data.eosGuard.softBias;
          const ids = Array.isArray(data.eosGuard.eosTokenIds) ? data.eosGuard.eosTokenIds : [];
          this.eosGuardSettings.eosTokenIds = ids;
          this.eosPatrol.idsText = ids.join(', ');
        }
        this.eosPatrol.sanitizeActive = !!data.sanitizeActive;
        if (data.lastScan) this.eosPatrol.report = data.lastScan;
      } catch (e) {
        console.error('eos_guard status failed:', e);
      }
    },

    eosGuardIdsChanged() {
      const ids = String(this.eosPatrol.idsText || '')
        .split(/[\s,;]+/)
        .map(x => parseInt(x, 10))
        .filter(x => Number.isInteger(x) && x >= 0);
      this.eosGuardSettings.eosTokenIds = ids;
      this.eosPatrol.idsText = ids.join(', ');
      this.autoSaveSettings();
    },

    async eosGuardScan() {
      this.eosPatrol.scanning = true;
      try {
        const resp = await fetch('/api/eos_guard/scan', { method: 'POST' });
        if (!resp.ok) throw new Error('scan HTTP ' + resp.status);
        const data = await resp.json();
        this.eosPatrol.report = data.report;
        this.eosPatrol.confirmToken = data.confirm_token || '';
      } catch (e) {
        console.error(e);
        if (this.$message) this.$message.error(this.t('eosGuardFailScan') || '巡检失败');
      } finally {
        this.eosPatrol.scanning = false;
      }
    },

    eosGuardApply() {
      const rep = this.eosPatrol.report;
      if (!rep || !rep.total || !this.eosPatrol.confirmToken) return;
      const summary = (this.t('eosGuardConfirmApply') || 'About to quarantine {total} contaminated entries (backup first, originals kept for review).')
        .replace('{total}', rep.total)
        .replace('{stores}', Object.keys(rep.stores || {}).length);
      this.$confirm(summary, this.t('eosGuardDangerTitle') || '危险操作确认', {
        type: 'error',
        confirmButtonText: this.t('confirm') || '确定',
        cancelButtonText: this.t('cancel') || '取消'
      }).then(async () => {
        this.eosPatrol.applying = true;
        try {
          const resp = await fetch('/api/eos_guard/apply', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_token: this.eosPatrol.confirmToken })
          });
          if (resp.status === 409) {
            const d = await resp.json().catch(() => ({}));
            if (d.detail && d.detail.report) {
              this.eosPatrol.report = d.detail.report;
            }
            this.eosPatrol.confirmToken = '';
            await this.eosGuardScan();
            if (this.$message) this.$message.warning(this.t('eosGuardDrift') || '数据已变化，请按最新巡检结果重新确认');
            return;
          }
          if (!resp.ok) throw new Error('apply HTTP ' + resp.status);
          const data = await resp.json();
          const rec = (data.result && data.result.records) || 0;
          if (this.$message) this.$message.success((this.t('eosGuardDoneApply') || '隔离完成') + ': ' + rec);
          this.eosPatrol.confirmToken = '';
          this.eosPatrol.report = null;
          await this.eosGuardScan();
          await this.eosGuardLoadQuarantine();
        } catch (e) {
          console.error(e);
          if (this.$message) this.$message.error(this.t('eosGuardFailApply') || '隔离执行失败');
        } finally {
          this.eosPatrol.applying = false;
        }
      }).catch(() => {});
    },

    eosRowKind(k) {
      const s = String(k || '');
      if (s.indexOf('report-only') >= 0) return 'report';
      if (s.indexOf('backups/') === 0 || s.indexOf('backups\\') === 0) return 'snapshot';
      return 'live';
    },

    eosReportOnlyCount() {
      const st = (this.eosPatrol.report && this.eosPatrol.report.stores) || {};
      let n = 0;
      for (const k in st) {
        if (this.eosRowKind(k) === 'report') n += (st[k][0] || 0) + (st[k][1] || 0);
      }
      return n;
    },

    async eosGuardLoadQuarantine() {
      try {
        const resp = await fetch('/api/eos_guard/quarantine');
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const data = await resp.json();
        this.eosPatrol.backups = data.backups || [];
        this.eosPatrol.quarantineFiles = data.quarantine_files || [];
      } catch (e) {
        console.error(e);
        if (this.$message) this.$message.error(this.t('eosGuardFailInv') || '隔离区清点失败');
      }
    },

    eosGuardRestore(ts) {
      this.eosGuardRestorePlanAndConfirm(ts);
    },

    async eosGuardRestorePlanAndConfirm(ts) {
      try {
        const resp = await fetch('/api/eos_guard/restore/plan', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ backup_ts: ts })
        });
        if (!resp.ok) throw new Error('plan HTTP ' + resp.status);
        const data = await resp.json();
        const p = data.plan || {};
        const summary = (this.t('eosGuardConfirmRestore') || 'About to write back {rows} rows and {files} files, overwriting current data. The current versions will first be snapshotted.')
          .replace('{rows}', p.total_rows || 0)
          .replace('{files}', p.total_files || 0);
        await this.$confirm(summary + ' ' + (this.t('eosGuardRestoreDanger') || '灌回会把已脱敏文本原样写回持久层，仅在明确需要时使用。'),
          this.t('eosGuardDangerTitle') || '危险操作确认', {
            type: 'error',
            confirmButtonText: this.t('confirm') || '确定',
            cancelButtonText: this.t('cancel') || '取消'
          });
        this.eosPatrol.restoring = true;
        try {
          const exec = await fetch('/api/eos_guard/restore', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ confirm_token: data.confirm_token })
          });
          if (!exec.ok) throw new Error('restore HTTP ' + exec.status);
          const out = await exec.json();
          const r = out.result || {};
          if (this.$message) this.$message.success((this.t('eosGuardDoneRestore') || '灌回完成') + `: rows=${r.rows_restored || 0} files=${r.files_restored || 0}`);
          await this.eosGuardScan();
        } finally {
          this.eosPatrol.restoring = false;
        }
      } catch (e) {
        if (e === 'cancel' || e === 'close') return;
        console.error(e);
        if (this.$message) this.$message.error(this.t('eosGuardFailRestore') || '灌回失败');
      }
    }
});
