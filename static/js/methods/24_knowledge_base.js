// 批 3 F2：自 vue_methods.js 搬移的 methods/24_knowledge_base.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 创建知识库
    async createKnowledgeBase() {
      try {
        // 上传文件
        let uploadedFiles = [];
        if (this.newKbFiles.length > 0) {
          if (!this.isElectron) {
            // 浏览器环境：通过 FormData 上传
            const formData = new FormData();
            for (const file of this.newKbFiles) {
              if (file.file instanceof Blob) {
                formData.append('files', file.file, file.name);
              } else {
                console.error("Invalid file object:", file);
                showNotification(this.t('invalid_file'), 'error');
                return;
              }
            }
  
            try {
              console.log('Uploading files...');
              const response = await fetch(`/load_file`, {
                method: 'POST',
                body: formData
              });
  
              if (!response.ok) {
                const errorText = await response.text();
                console.error('Server responded with an error:', errorText);
                showNotification(this.t('file_upload_failed'), 'error');
                return;
              }
  
              const data = await response.json();
              if (data.success) {
                uploadedFiles = data.fileLinks; // 获取上传后的文件链接
                // data.textFiles 添加到 this.textFiles
                this.textFiles = [...this.textFiles, ...data.textFiles];
                await this.autoSaveSettings();
              } else {
                showNotification(this.t('file_upload_failed'), 'error');
                return;
              }
            } catch (error) {
              console.error('Error during file upload:', error);
              showNotification(this.t('file_upload_failed'), 'error');
              return;
            }
          } else {
            // Electron 环境：通过 JSON 上传
            try {
              console.log('Uploading Electron files...');
              const response = await fetch(`/load_file`, {
                method: 'POST',
                headers: {
                  'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                  files: this.newKbFiles.map(file => ({
                    path: file.path,
                    name: file.name
                  }))
                })
              });
  
              if (!response.ok) {
                const errorText = await response.text();
                console.error('Server error:', errorText);
                showNotification(this.t('file_upload_failed'), 'error');
                return;
              }
  
              const data = await response.json();
              if (data.success) {
                uploadedFiles = data.fileLinks; // 获取上传后的文件链接
                // data.textFiles 添加到 this.textFiles
                this.textFiles = [...this.textFiles, ...data.textFiles];
                await this.autoSaveSettings();
              } else {
                showNotification(this.t('file_upload_failed'), 'error');
                return;
              }
            } catch (error) {
              console.error('上传错误:', error);
              showNotification(this.t('file_upload_failed'), 'error');
              return;
            }
          }
        }
  
        // 生成唯一的 ID
        const kbId = uuid.v4();
  
        // 构建新的知识库对象，使用上传后的文件链接
        const newKb = {
          id: kbId,
          name: this.newKb.name,
          introduction: this.newKb.introduction,
          providerId: this.newKb.providerId,
          model: this.newKb.model,
          base_url: this.newKb.base_url,
          api_key: this.newKb.api_key,
          enabled: true, // 默认启用
          chunk_size: this.newKb.chunk_size,
          chunk_overlap: this.newKb.chunk_overlap,
          chunk_k: this.newKb.chunk_k,
          weight: this.newKb.weight,
          files: uploadedFiles.map(file => ({ // 使用服务器返回的文件链接
            name: file.name,
            path: file.path,
          })),
          processingStatus: 'processing', // 设置处理状态为 processing
        };
  
        // 更新 settings 中的 knowledgeBases
        this.knowledgeBases = [...(this.knowledgeBases || []), newKb];
        //手动触发modelProviders更新，从而能够实时与后端同步
        this.modelProviders = this.modelProviders
        // 保存 settings
        await this.autoSaveSettings();
        // post kbId to 后端的create_kb端口
        try {
          // 1. 触发任务
          const startResponse = await fetch(`/create_kb`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ kbId }),
          });
          
          if (!startResponse.ok) throw new Error('启动失败');
          // 2. 轮询状态
          const checkStatus = async () => {
            try {
              const statusResponse = await fetch(`/kb_status/${kbId}`);
              
              // 处理 HTTP 错误状态
              if (!statusResponse.ok) {
                console.error('状态检查失败:', statusResponse.status);
                return 'failed'; // 返回明确的失败状态
              }
              const data = await statusResponse.json();
              return data.status || 'unknown'; // 防止 undefined
            } catch (error) {
              console.error('状态检查异常:', error);
              return 'failed';
            }
          };
          // 修改轮询逻辑
          const interval = setInterval(async () => {
            try {
              const status = await checkStatus() || ''; // 确保有默认值
              
              const targetKb = this.knowledgeBases.find(k => k.id === kbId);
              if (!targetKb) {
                clearInterval(interval);
                return;
              }
              // 安全的状态判断
              if (status === 'completed') {
                clearInterval(interval);
                targetKb.processingStatus = 'completed';
                showNotification(this.t('kb_created_successfully'), 'success');
                await this.autoSaveSettings();
              } else if (typeof status === 'string' && status.startsWith('failed')) { // 安全判断
                clearInterval(interval);
                this.knowledgeBases = this.knowledgeBases.filter(k => k.id !== kbId);
                showNotification(this.t('kb_creation_failed'), 'error');
                await this.autoSaveSettings();
              }
            } catch (error) {
              console.error('轮询异常:', error);
              clearInterval(interval);
            }
          }, 2000);
        } catch (error) {
          console.error('知识库创建失败:', error);
          showNotification(this.t('kb_creation_failed'), 'error');
        }      
        this.showAddKbDialog = false;
        this.newKb = { 
          name: '', 
          introduction: '',
          providerId: null, 
          model: '', 
          base_url: '', 
          api_key: '',
          chunk_size: 1024,
          chunk_overlap: 256,
          chunk_k: 5,
          weight: 0.5,
        };
        this.newKbFiles = [];
      } catch (error) {
        console.error('知识库创建失败:', error);
        showNotification(this.t('kb_creation_failed'), 'error');
      }
    },

    // 删除知识库
    async removeKnowledgeBase(kb) {
      try {
        // 从 settings 中过滤掉要删除的 knowledgeBase
        this.knowledgeBases = this.knowledgeBases.filter(
          item => item.id !== kb.id
        );
        let kbId = kb.id
        //手动触发modelProviders更新，从而能够实时与后端同步
        this.modelProviders = this.modelProviders
        const Response = await fetch(`/remove_kb`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ kbId }),
        });

        if (!Response.ok) throw new Error('删除失败');

        // 保存 settings
        await this.autoSaveSettings();

        showNotification(this.t('kb_deleted_successfully'), 'success');
      } catch (error) {
        console.error('知识库删除失败:', error);
        showNotification(this.t('kb_deletion_failed'), 'error');
      }
    },

    // 切换知识库启用状态
    async toggleKbEnabled(kb) {
      try {
        // 更新 knowledgeBase 的 enabled 状态
        const kbToUpdateIndex = this.knowledgeBases.findIndex(
          item => item.id === kb.id
        );

        if (kbToUpdateIndex !== -1) {
          this.knowledgeBases[kbToUpdateIndex].enabled = kb.enabled;
          //手动触发modelProviders更新，从而能够实时与后端同步
          this.modelProviders = this.modelProviders
          // 保存 settings
          await this.autoSaveSettings();
          showNotification(this.t('kb')+` ${kb.name} ${kb.enabled ? this.t('enabled')  : this.t('disabled')}`, 'success');
        }
      } catch (error) {
        console.error('切换知识库状态失败:', error);
        showNotification(this.t('kb_status_change_failed'), 'error');
      }
    },

    // 选择供应商
    selectKbProvider(providerId) {
      if (providerId == 'paraphrase-multilingual-MiniLM-L12-v2'){
        this.newKb.model = providerId;
        this.newKb.base_url = `${backendURL}/minilm`
        this.newKb.api_key = 'MiniLM';
        return;
      }

      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.newKb.model = provider.modelId;
        this.newKb.base_url = provider.url;
        this.newKb.api_key = provider.apiKey;
      }
    },

    // 文件上传相关方法
    async browseKbFiles() {
        if (!this.isElectron) {
          const input = document.createElement('input')
          input.type = 'file'
          input.multiple = true
          input.accept = ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')
          
          input.onchange = (e) => {
            const files = Array.from(e.target.files)
            const validFiles = files.filter(this.isValidFileType)
            this.handleKbFiles(validFiles)
          }
          input.click()
        } else {
          const result = await window.electronAPI.openFileDialog();
          if (!result.canceled) {
            const validPaths = result.filePaths
              .filter(path => {
                const ext = path.split('.').pop()?.toLowerCase() || ''
                return ALLOWED_EXTENSIONS.includes(ext)
              })
            this.handleKbFiles(validPaths)
          }
        }
    },

    handleKbFiles(files) {
        if (files.length > 0) {
          this.addKbFiles(files)
        } else {
          this.showErrorAlert()
        }
    },

      // 添加文件到列表
    addKbFiles(files) {
      const newFiles = files.map(file => {
        if (typeof file === 'string') { // Electron路径
          return {
            path: file,
            name: file.split(/[\\/]/).pop()
          }
        }
        return { // 浏览器File对象
          path: URL.createObjectURL(file),// 生成临时URL
          name: file.name,
          file: file
        }
      });
      
      this.newKbFiles = [...this.newKbFiles, ...newFiles];
    },

    async handleKbDrop(event) {
      event.preventDefault();
      const files = Array.from(event.dataTransfer.files)
        .filter(this.isValidFileType);
      this.handleKbFiles(files);
    },

    removeKbFile(index) {
      this.newKbFiles.splice(index, 1);
    },

    switchToKnowledgePage() {
      this.activeMenu = 'toolkit';  // 根据你的菜单项配置的实际值设置
      this.subMenu = 'document';   // 根据你的子菜单项配置的实际值设置
    },

    switchToKnowledgeConfig(){
      this.activeMenu = 'toolkit';  // 根据你的菜单项配置的实际值设置
      this.subMenu = 'document';   // 根据你的子菜单项配置的实际值设置
      this.activeKbTab='settings';
      this.showAddKbDialog=false;
    },

    switchToMemoryConfig(){
      this.activeMenu = 'role';  // 根据你的菜单项配置的实际值设置
      this.subMenu = 'memory';   // 根据你的子菜单项配置的实际值设置
      this.activeMemoryTab='config';
      this.showAddMemoryDialog=false;
    },

    switchToMemory(){
      this.activeMenu = 'role';
      this.subMenu = 'memory'; 
    }
});
