// 批 3 F2：自 vue_methods.js 搬移的 methods/22_providers.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 修改后的fetchModels方法
    async fetchModels() {
      this.modelsLoading = true;
      try {
        const response = await fetch(`/v1/models`);
        const result = await response.json();
        
        // 双重解构获取数据
        const { data } = result;
        
        this.models = data.map(item => ({
          id: item.id,
          created: new Date(item.created * 1000).toLocaleDateString(),
        }));
        
      } catch (error) {
        console.error('获取模型数据失败:', error);
        this.modelsError = error.message;
        this.models = []; // 确保清空数据
      } finally {
        this.modelsLoading = false;
      }
    },

    async addProvider() {
      this.modelProviders.push({
        id: Date.now(),
        vendor: this.newProviderTemp.vendor,
        url: this.newProviderTemp.url,
        apiKey: '',
        modelId: '',
        isNew: true
      });
      this.newProviderTemp = { vendor: '', url: '', apiKey: '', modelId: '' };
      await this.autoSaveSettings();
    },

    async fetchModelsForProvider(provider) {
      try {
        const response = await fetch(`/v1/providers/models`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            url: provider.url,
            api_key: provider.apiKey
          })
        });
        if (!response.ok) {
          throw new Error('Failed to fetch models');
        }
        const data = await response.json();
        provider.models = data.data;
        showNotification(this.t('fetch_models_success'));
      } catch (error) {
        showNotification(this.t('fetch_models_failed'), 'error');
      }
    },

    // 找到原有的 removeProvider 方法，替换为以下代码
    async removeProvider(index) {
      // 获取被删除的供应商信息
      const removedProvider = this.modelProviders[index];
      
      // 从供应商列表中移除
      this.modelProviders.splice(index, 1);

      // 清理所有相关配置中的引用
      const providerId = removedProvider.id;
      
      // 主模型配置清理
      if (this.settings.selectedProvider === providerId) {
        this.settings.selectedProvider = null;
        this.settings.model = '';
        this.settings.base_url = '';
        this.settings.api_key = '';
      }

      // 推理模型配置清理
      if (this.reasonerSettings.selectedProvider === providerId) {
        this.reasonerSettings.selectedProvider = null;
        this.reasonerSettings.model = '';
        this.reasonerSettings.base_url = '';
        this.reasonerSettings.api_key = '';
      }

      // 触发自动保存
      await this.autoSaveSettings();
    },

    confirmAddProvider() {
      if (!this.newProviderTemp.vendor) {
        showNotification(this.t('vendor_required'), 'warning')
        return
      }
      
      const newProvider = {
        id: Date.now(),
        vendor: this.newProviderTemp.vendor,
        url: this.newProviderTemp.url,
        apiKey: this.newProviderTemp.apiKey || '',
        modelId: this.newProviderTemp.modelId || '',
        models: []
      }
      
      this.modelProviders.push(newProvider)
      this.showAddDialog = false
      this.newProviderTemp = { vendor: '', url: '', apiKey: '', modelId: '' }
      this.autoSaveSettings()
    },

    handleVendorChange(value) {
      const defaultUrls = {
        'OpenAI': 'https://api.openai.com/v1',
        'Deepseek': 'https://api.deepseek.com/v1',
        'aliyun': 'https://dashscope.aliyuncs.com/compatible-mode/v1',
        'ZhipuAI': 'https://open.bigmodel.cn/api/paas/v4',
        'Volcano': 'https://ark.cn-beijing.volces.com/api/v3',
        'moonshot': 'https://api.moonshot.cn/v1',
        'minimax': 'https://api.minimaxi.com/v1',
        'MiMo': 'https://api.xiaomimimo.com/v1',
        'longcat':'https://api.longcat.chat/openai/v1',
        'Ollama': this.isdocker ? 'http://host.docker.internal:11434/v1' : 'http://127.0.0.1:11434/v1',
        'Vllm': this.isdocker ? 'http://host.docker.internal:8000/v1' :'http://127.0.0.1:8000/v1',
        'LMstudio': this.isdocker ? 'http://host.docker.internal:1234/v1' :'http://127.0.0.1:1234/v1',
        'xinference': this.isdocker ? 'http://host.docker.internal:9997/v1' :'http://127.0.0.1:9997/v1',
        'Dify': this.isdocker ? 'http://host.docker.internal/v1' :'http://127.0.0.1/v1',
        'newapi': this.isdocker ? 'http://host.docker.internal:3000/v1' : 'http://127.0.0.1:3000/v1',
        'LocalAI': this.isdocker ? 'http://host.docker.internal:8080/v1' : 'http://127.0.0.1:8080/v1',
        'ttswebui': this.isdocker ? 'http://host.docker.internal:7778/v1' : 'http://127.0.0.1:7778/v1',
        'SGLang': this.isdocker ? 'http://host.docker.internal:3000/v1' : 'http://127.0.0.1:3000/v1', 
        'llama.cpp': this.isdocker ? 'http://host.docker.internal:8080/v1' : 'http://127.0.0.1:8080/v1',
        'Gemini': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'Anthropic': 'https://api.anthropic.com/v1',
        'Grok': 'https://api.groq.com/openai/v1',
        'mistral': 'https://api.mistral.ai/v1',
        'lingyi': 'https://api.lingyiwanwu.com/v1',
        'baichuan': 'https://api.baichuan-ai.com/v1',
        'qianfan': 'https://qianfan.baidubce.com/v2',
        'hunyuan': 'https://api.hunyuan.cloud.tencent.com/v1',
        'siliconflow': 'https://api.siliconflow.cn/v1',
        '302.AI': 'https://api.302ai.cn/v1',
        'stepfun': 'https://api.stepfun.com/v1',
        'o3': 'https://api.o3.fan/v1',
        'aihubmix': 'https://aihubmix.com/v1',
        'ocoolai': 'https://api.ocoolai.com/v1',
        'Github': 'https://models.github.ai/inference',
        'dmxapi': 'https://www.dmxapi.cn/v1',
        'openrouter': 'https://openrouter.ai/api/v1',
        'together': 'https://api.together.xyz/v1',
        'fireworks': 'https://api.fireworks.ai/inference/v1',
        '360': 'https://api.360.cn/v1',
        'Nvidia': 'https://integrate.api.nvidia.com/v1',
        'hyperbolic': 'https://api.hyperbolic.xyz/v1',
        'jina': 'https://api.jina.ai/v1',
        'gitee': 'https://ai.gitee.com/v1',
        'ppinfra': 'https://api.ppinfra.com/v3/openai/v1',
        'perplexity': 'https://api.perplexity.ai',
        'infini': 'https://cloud.infini-ai.com/maas/v1',
        'modelscope': 'https://api-inference.modelscope.cn/v1',
        'tencent': 'https://api.lkeap.cloud.tencent.com/v1',
      }
      
      if (value !== 'custom' && value !== 'customAnthropic' ) {
        this.newProviderTemp.url = defaultUrls[value] || ''
      }
      if (value === 'Ollama') {
        this.newProviderTemp.apiKey = 'ollama'
      }
      if (value === 'Vllm') {
        this.newProviderTemp.apiKey = 'Vllm'
      }
      if (value === 'LMstudio') {
        this.newProviderTemp.apiKey = 'LMstudio'
      }
      if (value === 'xinference') {
        this.newProviderTemp.apiKey = 'xinference'
      }
      if (value === 'Dify') {
        this.newProviderTemp.modelId = 'dify'
      }
      if (value === 'SGLang') {
        this.newProviderTemp.apiKey = 'SGLang' // 新增
      }
      if (value === 'llama.cpp') {
        this.newProviderTemp.apiKey = 'llamacpp' // 新增
      }
    },

    // rerank供应商
    async selectRankProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.KBSettings.model = provider.modelId;
        this.KBSettings.base_url = provider.url;
        this.KBSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    // 主模型供应商选择
    async selectMainProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      console.log(provider)
      if (provider) {
        console.log("provider")
        this.settings.model = provider.modelId;
        this.settings.base_url = provider.url;
        this.settings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectFastProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      console.log(provider)
      if (provider) {
        console.log("provider")
        this.fastSettings.model = provider.modelId;
        this.fastSettings.base_url = provider.url;
        this.fastSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    // Claude code 供应商选择
    async selectCCProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      let vendor_list = {
        "Anthropic": "https://api.anthropic.com/",
        "Deepseek": "https://api.deepseek.com/anthropic/",
        "siliconflow": "https://api.siliconflow.cn/",
        "ZhipuAI":"https://open.bigmodel.cn/api/anthropic/",
        "moonshot":"https://api.moonshot.cn/anthropic/",
        "aliyun": "https://dashscope.aliyuncs.com/apps/anthropic/",
        "modelscope":"https://api-inference.modelscope.cn/",
        "302.AI":"https://api.302.ai/cc/"
      };

      let cc_url = vendor_list[provider.vendor] || provider.url;

      if (provider) {
        this.ccSettings.model = provider.modelId;
        this.ccSettings.base_url = cc_url;
        this.ccSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectQCProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.qcSettings.model = provider.modelId;
        this.qcSettings.base_url = provider.url;
        this.qcSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectOCProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.ocSettings.model = provider.modelId;
        this.ocSettings.base_url = provider.url;
        this.ocSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectBrainProvider(providerId) {
      // 1. 在供应商列表中查找详细信息
      const provider = this.modelProviders.find(p => p.id === providerId);

      // 2. 校验：确保找到了供应商，且当前有正在编辑的脑区配置
      if (provider && this.currentBrainSettings) {
        // 3. 将供应商的详细信息 (model, url, key) 同步到当前脑区的设置中
        this.currentBrainSettings.model = provider.modelId;
        this.currentBrainSettings.base_url = provider.url;
        this.currentBrainSettings.api_key = provider.apiKey;

        // 4. 打印日志方便调试
        console.log(`[${this.currentEditingKey}] 切换模型为: ${provider.modelId}`);

        // 5. 自动保存
        if (typeof this.autoSaveSettings === 'function') {
          await this.autoSaveSettings();
        }
      }
    },

    // 推理模型供应商选择
    async selectReasonerProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.reasonerSettings.model = provider.modelId;
        this.reasonerSettings.base_url = provider.url;
        this.reasonerSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectVisionProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.visionSettings.model = provider.modelId;
        this.visionSettings.base_url = provider.url;
        this.visionSettings.api_key = provider.apiKey;
        await this.autoSaveSettings();
      }
    },

    async selectText2imgProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.text2imgSettings.model = provider.modelId;
        this.text2imgSettings.base_url = provider.url;
        this.text2imgSettings.api_key = provider.apiKey;
        this.text2imgSettings.vendor = provider.vendor;
        if (this.text2imgSettings.vendor === 'siliconflow') {
          this.text2imgSettings.size = '1024x1024';
        }
        else {
          this.text2imgSettings.size = 'auto';
        }
        await this.autoSaveSettings();
      }
    },

    async selectAsrProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.asrSettings.model = provider.modelId;
        this.asrSettings.base_url = provider.url;
        this.asrSettings.api_key = provider.apiKey;
        this.asrSettings.vendor = provider.vendor;
        await this.autoSaveSettings();
      }
    },

    async selectTTSProvider(providerId) {
      const provider = this.modelProviders.find(p => p.id === providerId);
      if (provider) {
        this.ttsSettings.model = provider.modelId;
        this.ttsSettings.base_url = provider.url;
        this.ttsSettings.api_key = provider.apiKey;
        this.ttsSettings.vendor = provider.vendor;
        await this.autoSaveSettings();
      }
    },

    handleTTSProviderVisibleChange(visible) {
      if (!visible) {
        this.selectTTSProvider(this.ttsSettings.selectedProvider);
      }
    },

    handleAsrProviderVisibleChange(visible) {
      if (!visible) {
        this.selectAsrProvider(this.asrSettings.selectedProvider);
      }
    },

    handleText2imgProviderVisibleChange(visible) {
      if (!visible) {
        this.selectText2imgProvider(this.text2imgSettings.selectedProvider);
      }
    },

    handleRankProviderVisibleChange(visible) {
      if (!visible) {
        this.selectRankProvider(this.KBSettings.selectedProvider);
      }
    },

    // 在methods中添加
    handleMainProviderVisibleChange(visible) {
      if (!visible) {
        this.selectMainProvider(this.settings.selectedProvider);
      }
    },

    handleFastProviderVisibleChange(visible) {
      if (!visible) {
        this.selectFastProvider(this.fastSettings.selectedProvider);
      }
    },

    handleCCProviderVisibleChange(visible) {
      if (!visible) {
        this.selectCCProvider(this.ccSettings.selectedProvider);
      }
    },

    handleQCProviderVisibleChange(visible) {
      if (!visible) {
        this.selectQCProvider(this.qcSettings.selectedProvider);
      }
    },

    handleOCProviderVisibleChange(visible) {
      if (!visible) {
        this.selectOCProvider(this.ocSettings.selectedProvider);
      }
    },

    handleReasonerProviderVisibleChange(visible) {
      if (!visible) {
        this.selectReasonerProvider(this.reasonerSettings.selectedProvider);
      }
    },

    handleVisionProviderVisibleChange(visible) {
      if (!visible) {
        this.selectVisionProvider(this.visionSettings.selectedProvider);
      }
    },

    handleBrainProviderVisibleChange(visible) {
      // 当下拉框关闭 (!visible) 且当前有选中的供应商 ID 时
      if (!visible && this.currentBrainSettings && this.currentBrainSettings.selectedProvider) {
        this.selectBrainProvider(this.currentBrainSettings.selectedProvider);
      }
    }
});
