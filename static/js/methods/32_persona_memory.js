// 批 3 F2：自 vue_methods.js 搬移的 methods/32_persona_memory.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    selectMemoryProvider(providerId) {
      if (providerId == 'paraphrase-multilingual-MiniLM-L12-v2'){
        this.newMemory.model = providerId;
        this.newMemory.base_url = `${backendURL}/minilm`
        this.newMemory.api_key = 'MiniLM';
        return;
      }

      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.newMemory.model = provider.modelId;
        this.newMemory.base_url = provider.url;
        this.newMemory.api_key = provider.apiKey;
      }
    },

    // 世界书条目清空
    clearBook(idx) {
      this.newMemory.characterBook[idx].keysRaw = '';
      this.newMemory.characterBook[idx].content = '';
    },

    /* 世界书 */
    addBook() {
      this.newMemory.characterBook.push({ keysRaw: '', content: '' });
    },

    removeBook(idx) {
      this.newMemory.characterBook.splice(idx, 1);
    },

    clearGreeting(idx) {
      this.newMemory.alternateGreetings[idx] = '';
    },

    clearFirstMes() {
      this.newMemory.firstMes = '';
    },

    /* 删除 alternate greeting */
    removeGreeting(idx) {
      this.newMemory.alternateGreetings.splice(idx, 1);
    },

    /* 新增 alternate greeting */
    addGreeting() {
      this.newMemory.alternateGreetings.push('');
    },

    async addMemory() {
      this.selectMemoryProvider(this.newMemory.providerId);

      /* ---- 0. 备份旧数据（更新场景用） ---- */
      const oldMemory = this.newMemory.id
        ? this.memories.find(m => m.id === this.newMemory.id)
        : 1024;

      /* ---- 1. 立即生成内存对象（用户可瞬间看到） ---- */
      const build = (dims = 1024) => ({
        id: this.newMemory.id || uuid.v4(),
        name: this.newMemory.name,
        infer: this.newMemory.infer,
        providerId: this.newMemory.providerId,
        model: this.newMemory.model,
        api_key: this.newMemory.api_key,
        base_url: this.newMemory.base_url,
        embedding_dims: dims,
        vendor: this.newMemory.providerId
          ? this.modelProviders.find(p => p.id === this.newMemory.providerId)?.vendor || ''
          : '',
        description: this.newMemory.description,
        avatar: this.newMemory.avatar,
        personality: this.newMemory.personality,
        mesExample: this.newMemory.mesExample,
        systemPrompt: this.newMemory.systemPrompt,
        firstMes: this.newMemory.firstMes,
        alternateGreetings: this.newMemory.alternateGreetings.filter(Boolean),
        characterBook: this.newMemory.characterBook.filter(e => e.keysRaw.trim() || e.content.trim())
      });

      let memory;
      let insertIdx = -1;          // 用于更新场景
      if (this.newMemory.id === null) {
        memory = build();
        this.memories.push(memory);
        if (this.memorySettings.selectedMemory === null) {
          this.memorySettings.selectedMemory = memory.id;
        }
      } else {
        insertIdx = this.memories.findIndex(m => m.id === this.newMemory.id);
        if (insertIdx === -1) return;
        memory = build(oldMemory?.embedding_dims ?? 1024);
        this.memories.splice(insertIdx, 1, memory);
      }
      this.showAddMemoryDialog = false;
      if (this.newMemory.providerId != null){
        /* ---- 2. 异步探测维度（失败则回滚） ---- */
        try {
          const resp = await fetch('/api/embedding_dims', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              api_key:  this.newMemory.api_key,
              base_url: this.newMemory.base_url,
              model:    this.newMemory.model
            })
          });

          // ******** 关键点 ********
          if (!resp.ok) {                           // 4xx/5xx 都进这里
            const txt = await resp.text();
            throw new Error(`Embedding 接口异常 ${resp.status}: ${txt}`);
          }

          const { dims } = await resp.json();
          memory.embedding_dims = dims;
          await this.autoSaveSettings();          // 真正落盘
        } catch (e) {
          /* ---- 3. 回滚 & 提示 ---- */
          if (this.newMemory.id === null) {
            // 新增：直接 pop
            this.memories.pop();
            if (this.memorySettings.selectedMemory === memory.id) {
              this.memorySettings.selectedMemory = null;
            }
          } else {
            // 更新：把旧记忆写回去
            if (oldMemory) this.memories.splice(insertIdx, 1, oldMemory);
          }
          // 保证能拿到 t 函数
          showNotification(this.t('EmbeddingFailed'), 'error');
          console.error('[addMemory] 探测维度失败', e);
          return;   // 不再继续
        }
      }

      /* ---- 4. 收尾 ---- */
      this.resetNewMemory();
      this.changeMemory();
    },

    async removeMemory(id) {
      this.memories = this.memories.filter(m => m.id !== id);
      if (this.memorySettings.selectedMemory === id){
        this.memorySettings.selectedMemory = null;
      }
      try {
        // 向/delete_file发送请求
        const response = await fetch(`/remove_memory`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ memoryId: id })
        });
        // 处理响应
        if (response.ok) {
          console.log('memory deleted successfully');
          showNotification(this.t('memoryDeleted'), 'success');
        }
      } catch (error) {
        console.error('Error:', error);
        showNotification(this.t('memoryDeleteFailed'), 'error');
      }
      await this.autoSaveSettings();
    },

    editMemory(id) {
      const memory = this.memories.find(m => m.id === id);
      if (memory) {
        this.newMemory = { ...memory };
        if (this.newMemory.characterBook.length === 0){
          this.newMemory.characterBook = [{ keysRaw: '', content: '' }];
        }
        this.showAddMemoryDialog = true;
      }
    },

    getVendorName(providerId) {
      if (providerId == 'paraphrase-multilingual-MiniLM-L12-v2'){
        return `${this.t("model")}:${providerId}`;
      }
      const provider = this.modelProviders.find(p => p.id === providerId);
      return provider ? `${this.t("model")}:${provider.modelId}` : this.t("NoLongTermMemory");
    },

    // 处理回车键冲突
    handleEnter(e) {
      if (e.target.value) {
        e.stopPropagation()
      }
    },

    // 一键重置
    resetNewMemory() {
      this.newMemory = {
        id: null,
        name: '',
        infer:false,
        providerId: null,
        model: '',
        base_url: '',
        api_key: '',
        vendor: '',
        description: '',
        avatar: '',
        personality: '',
        mesExample: '',
        systemPrompt: '',
        firstMes: '',
        alternateGreetings: [],
        characterBook: [{ keysRaw: '', content: '' }]
      };
    },

    copyExistingMemoryData(selectedId) {
      const src = this.memories.find(m => m.id === selectedId);
      if (src) {
        /* 把旧字段映射到新字段，没有的就给默认值 */
        this.newMemory = {
          id: null,
          name: src.name || '',
          infer: src.infer || false,
          providerId: src.providerId || null,
          model: src.model || '',
          base_url: src.base_url || '',
          api_key: src.api_key || '',
          vendor: src.vendor || '',

          /* 旧→新 */
          description: src.basic_character || src.description || '',
          avatar: src.avatar || '',
          personality: src.personality || '',
          mesExample: src.mesExample || '',
          systemPrompt: src.systemPrompt || '',
          firstMes: src.firstMes || (Array.isArray(src.random) ? src.random[0]?.value : ''),
          alternateGreetings:
            Array.isArray(src.alternateGreetings)
              ? src.alternateGreetings
              : (src.random || []).slice(1).map(r => r.value),
          characterBook:
            Array.isArray(src.characterBook)
              ? src.characterBook
              : (src.lorebook || []).map(l => ({
                  keysRaw: l.name,
                  content: l.value
                }))  
        };
           if (this.newMemory.characterBook.length == 0 ){
              this.newMemory.characterBook = [{ keysRaw: '', content: '' }]
           }   
      } else {
        /* 新建：直接给空模板 */
        this.resetNewMemory();
      }
    }
});
