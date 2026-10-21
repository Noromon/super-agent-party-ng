// 批 3 F2：自 vue_methods.js 搬移的 methods/92_model_downloads.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  async sherpaModelStatus() {
    const res = await fetch('/sherpa-model/status')
    if (!res.ok) return
    const { exists, model } = await res.json()
    this.sherpaModelExists = exists
    this.sherpaModelName  = model ?? ''   // 后端没返回时留空
  },

  async sherpaDownload(source = 'modelscope') {
      if (this.sherpaEventSource) this.sherpaEventSource.close()
      this.sherpaDownloading = true
      this.sherpaPercent = 0
      
      // 确保在 EventSource 实例化之前设置状态
      this.sherpaEventSource = null

      const es = new EventSource(`/sherpa-model/download/${source}`)
      this.sherpaEventSource = es
      
      // 监听消息流
      es.onmessage = e => {
          let data
          try {
              data = JSON.parse(e.data)
          } catch (error) {
              console.error('Failed to parse download progress data:', e.data, error)
              return
          }

          // --------------------------------------
          // 核心修复逻辑：处理多文件聚合进度
          // --------------------------------------
          
          // 1. 检查下载是否完成或失败
          if (data.status === 'complete') {
              es.close()
              this.sherpaDownloading = false
              this.sherpaPercent = 100
              this.sherpaModelStatus()
              showNotification(this.t('modelDownloadSuccess'))
              return
          }

          if (data.status === 'failed') {
              es.close()
              this.sherpaDownloading = false
              showNotification(this.t('modelDownloadFailed') + (data.error || ''), 'error')
              return
          }

          // 2. 聚合所有文件的进度
          let totalDone = 0
          let grandTotal = 0

          if (data.files && data.files.length > 0) {
              data.files.forEach(file => {
                  totalDone += file.done || 0
                  grandTotal += file.total || 0
                  // 检查是否有任何单个文件失败
                  if (file.failed) {
                      es.close()
                      this.sherpaDownloading = false
                      showNotification(this.t('modelDownloadFailed') + `: ${file.filename} 失败`, 'error')
                  }
              })
          }

          // 3. 计算整体百分比
          this.sherpaPercent = grandTotal > 0 ? Math.round((totalDone / grandTotal) * 100) : 0
      }
      
      // 监听错误
      es.onerror = () => {
          // 如果 EventSource 在没有收到 close 消息的情况下关闭，通常意味着错误
          es.close()
          this.sherpaDownloading = false
          showNotification(this.t('modelDownloadFailed'), 'error')
          this.sherpaModelStatus() // 再次检查状态，以防实际已下载完成
      }
  },

  async sherpaRemove() {
    try {
      const res = await fetch('/sherpa-model/remove', { method: 'DELETE' })
      if (!res.ok) throw new Error()
      showNotification(this.t('deleteSuccess'))
      this.sherpaModelStatus()
    } catch {
      showNotification(this.t('deleteFailed'),'error')
    }
  },

  async loadSherpaStatus() {
    await this.sherpaModelStatus()
  },

// 1. 获取 MOSS 模型状态
  async mossModelStatus() {
    try {
      const res = await fetch('/moss-model/status')
      if (!res.ok) return
      const data = await res.json()
      this.mossModelExists = data.exists
      
      // 同步后台下载状态（比如刷新页面后恢复 UI）
      if (data.downloading) {
        this.mossDownloading = true
        // 自动恢复轮询
        if (!this.mossPollInterval) this.startMossPolling()
      } else {
        this.mossDownloading = false
      }
    } catch (e) {
      console.error('Failed to get MOSS status:', e)
    }
  },

// 触发下载时把进度清零
  async mossDownload(source = 'modelscope') {
    this.mossDownloading = true
    this.mossDownloadSource = source
    this.mossPercent = 0 // 初始化为 0
    
    try {
      const res = await fetch(`/moss-model/download/${source}`, { method: 'POST' })
      if (!res.ok) throw new Error('Network error')
      this.startMossPolling()
    } catch (e) {
      this.mossDownloading = false
      showNotification(this.t('modelDownloadFailed') || '下载失败', 'error')
    }
  },

  startMossPolling() {
    if (this.mossPollInterval) clearInterval(this.mossPollInterval)
    
    this.mossPollInterval = setInterval(async () => {
      try {
        const statusRes = await fetch('/moss-model/status')
        const data = await statusRes.json()
        
        // 更新真实进度 (后台根据文件夹大小计算出的)
        if (data.percent !== undefined) {
          this.mossPercent = data.percent
        }
        
        if (!data.downloading) {
          clearInterval(this.mossPollInterval)
          this.mossPollInterval = null
          this.mossDownloading = false
          this.mossModelExists = data.exists
          
          if (data.exists) {
            this.mossPercent = 100 // 完成强制打满
            showNotification(this.t('modelDownloadSuccess') || 'MOSS 模型下载成功')
          } else if (data.download_error) {
            showNotification((this.t('modelDownloadFailed') || '下载失败: ') + data.download_error, 'error')
          }
        }
      } catch (err) {
        console.error('MOSS Polling error', err)
      }
    }, 1000) // 每 1 秒轮询一次，让进度条更顺滑
  },

  // 4. 删除 MOSS 模型
  async mossRemove() {
    try {
      const res = await fetch('/moss-model/remove', { method: 'DELETE' })
      if (!res.ok) throw new Error()
      showNotification(this.t('deleteSuccess') || '模型删除成功')
      this.mossModelExists = false
    } catch {
      showNotification(this.t('deleteFailed') || '模型删除失败', 'error')
    }
  },

  // 5. 在初始化时调用 (类似于 loadSherpaStatus)
  async loadMossStatus() {
    await this.mossModelStatus()
  },

    /**
     * 检查 MiniLM 模型状态 (是否存在)
     */
    async minilmModelStatus() {
        try {
            const res = await fetch('/minilm-model/status');
            if (!res.ok) throw new Error('Failed to fetch status');
            const data = await res.json();
            this.minilmModelExists = data.exists;
        } catch (error) {
            console.error("Error checking MiniLM model status:", error);
            this.minilmModelExists = false; // 假设网络错误导致无法检查，也视为不存在
        }
    },

    /**
     * 下载 MiniLM 模型
     * @param {string} source - 下载源: 'modelscope' 或 'huggingface'
     */
    async minilmDownload(source = 'modelscope') {
        if (this.minilmEventSource) this.minilmEventSource.close();
        
        this.minilmDownloading = true;
        this.minilmPercent = 0;
        this.minilmEventSource = null;

        const es = new EventSource(`/minilm-model/download/${source}`);
        this.minilmEventSource = es;
        
        // 监听消息流
        es.onmessage = async e => {
            let data;
            try {
                // 后端会发送 JSON 格式的进度数据
                data = JSON.parse(e.data);
            } catch (error) {
                // 后端可能会发送 'close' 这样的非 JSON 消息
                if (e.data === 'close') {
                    es.close();
                }
                console.error('Failed to parse download progress data:', e.data, error);
                return;
            }

            // 1. 检查下载是否完成或失败
            if (data.status === 'complete') {
                es.close();
                this.minilmDownloading = false;
                this.minilmPercent = 100;

                // 1. 通知后端热重载
                await fetch('/minilm/reload', { method: 'POST' });

                // 2. 再刷新一次存在状态（此时一定为 true）
                await this.minilmModelStatus();

                if (typeof showNotification === 'function') {
                    showNotification(this.t('modelDownloadSuccess'));
                }
                return;
            }

            if (data.status === 'failed') {
                es.close();
                this.minilmDownloading = false;
                // 尝试从 files 列表中提取具体的错误信息
                const firstError = data.files.find(f => f.failed)?.error || '';
                if (typeof showNotification === 'function') {
                    showNotification(this.t('modelDownloadFailed') + (firstError ? `: ${firstError}` : ''), 'error');
                }
                return;
            }

            // 2. 聚合所有文件的进度
            let totalDone = 0;
            let grandTotal = 0;

            if (data.files && data.files.length > 0) {
                let hasFailedFile = false;
                data.files.forEach(file => {
                    totalDone += file.done || 0;
                    grandTotal += file.total || 0;
                    
                    // 检查是否有任何单个文件失败 (后端已经在 status='failed' 中处理了，这里做冗余检查)
                    if (file.failed) {
                        hasFailedFile = true;
                    }
                });

                if (hasFailedFile) {
                      // 如果检测到文件失败，但 status 还没有被后端更新为 'failed'，则手动关闭和报错
                      es.close();
                      this.minilmDownloading = false;
                      const failedFile = data.files.find(f => f.failed);
                      if (typeof showNotification === 'function') {
                        showNotification(this.t('modelDownloadFailed') + `: ${failedFile.filename} 失败`, 'error');
                      }
                      return;
                }
            }

            // 3. 计算整体百分比
            this.minilmPercent = grandTotal > 0 ? Math.round((totalDone / grandTotal) * 100) : 0;
        };
        
        // 监听错误
        es.onerror = () => {
            // 如果 EventSource 在没有收到 close 消息的情况下关闭，通常意味着错误
            if (this.minilmEventSource) {
                this.minilmEventSource.close();
            }
            this.minilmDownloading = false;
            if (typeof showNotification === 'function') {
                showNotification(this.t('modelDownloadFailed') + ' (Network/Connection Error)', 'error');
            }
            this.minilmModelStatus(); // 再次检查状态，以防实际已下载完成
        };
    },

    /**
     * 删除本地 MiniLM 模型
     */
    async minilmRemove() {
        try {
            // 使用 Element Plus 确认对话框来增加安全性（如果可用）
            // 示例：await this.$confirm('确定删除 MiniLM 模型吗？', '警告', { type: 'warning' })

            const res = await fetch('/minilm-model/remove', { method: 'DELETE' });
            if (!res.ok) throw new Error();
            
            if (typeof showNotification === 'function') {
                showNotification(this.t('deleteSuccess'));
            }
            this.minilmModelStatus(); // 刷新模型存在状态
        } catch (error) {
            if (typeof showNotification === 'function') {
                showNotification(this.t('deleteFailed') + (error.message || ''), 'error');
            }
        }
    },

  /* 探针 */
  async probeNode() {
    const res = await fetch('/api/node/probe');
    const { installed } = await res.json();
    this.nodeInstalled = installed;
  },

    /* ===== uv 相关 ===== */
  async probeUv() {
    const res = await fetch('/api/uv/probe');
    const { installed } = await res.json();
    this.uvInstalled = installed;
  }
});
