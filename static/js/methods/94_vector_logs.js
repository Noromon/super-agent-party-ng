// 批 3 F2：自 vue_methods.js 搬移的 methods/94_vector_logs.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 打开向量库交互主弹窗
    async openVectorDialog(mid) {
      this.vectorDialogVisible = true
      this.vectorDialogMemoryId = mid
      // 取 memory 名字只是为了标题展示
      this.vectorDialogMemoryName = this.memories.find(m => m.id === mid)?.name || mid
      await this.loadVectorTable(mid)
    },

    // 读取记忆内容
    async loadVectorTable(mid) {
      this.vectorLoading = true
      try {
        const res = await fetch(`/memory/${mid}`)
        if (!res.ok) throw new Error(await res.text())
        // 后端已平铺，直接赋值
        this.vectorTable = await res.json()
      } catch (e) {
        this.vectorTable = []
        console.error(e)
      } finally {
        this.vectorLoading = false
      }
    },

    // 新增记忆（S77：上游终态 new_text 主字段；trim 防御=b6a0cd30）
    async addVectorRow() {
      if (!(this.newVectorText || '').trim()) return
      try {
        const mid = this.vectorDialogMemoryId
        const res = await fetch(`/memory/${mid}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_text: this.newVectorText.trim() })
        })
        if (!res.ok) throw new Error(await res.text())
        this.newVectorText = ''
        await this.loadVectorTable(mid)
      } catch (e) {
        showNotification(e.message, 'error')
      } finally {
        this.vectorLoading = false
      }
    },

  startEditRow(tableIndex) {
    const row = this.vectorTable[tableIndex]
    this.editRowUuid = row.uuid
    this.editRowText = row.text
    this.editRowVisible = true
  },

  async submitEditRow() {
    if (!this.editRowText.trim()) return
    try {
      const mid = this.vectorDialogMemoryId
      const res = await fetch(`/memory/${mid}/${this.editRowUuid}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ new_text: this.editRowText.trim() })
      })
      if (!res.ok) throw new Error(await res.text())
      this.editRowVisible = false
      await this.loadVectorTable(mid)
    } catch (e) {
      showNotification(e.message, 'error')
    }
  },

  async deleteVectorRow(tableIndex) {
    try {
      const mid = this.vectorDialogMemoryId
      const row = this.vectorTable[tableIndex]
      const res = await fetch(`/memory/${mid}/${row.uuid}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(await res.text())
      await this.loadVectorTable(mid)
    } catch (e) {
      showNotification(e.message, 'error')
    }
  },

  async openLogDialog() {
    this.showLogDialog = true;
    await this.fetchLogs();
    // 自动滚动到底部
    this.$nextTick(() => {
      if (this.$refs.logContainer) {
        this.$refs.logContainer.scrollTop = this.$refs.logContainer.scrollHeight;
      }
    });
  },

  async fetchLogs() {
    if (window.electronAPI) {
      try {
        this.logContent = await window.electronAPI.getBackendLogs();
      } catch (e) {
        this.logContent = 'Failed to load logs: ' + e.message;
      }
    }
  }
});
