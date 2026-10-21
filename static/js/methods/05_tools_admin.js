// 批 3 F2：自 vue_methods.js 搬移的 methods/05_tools_admin.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    async addParam() {
      this.settings.extra_params.push({
        name: '',
        type: 'string',  // 默认类型
        value: ''        // 根据类型自动初始化
      });
      await this.autoSaveSettings();
    },

    async addFastParam() {
      this.fastSettings.extra_params.push({
        name: '',
        type: 'string',  // 默认类型
        value: ''        // 根据类型自动初始化
      });
      await this.autoSaveSettings();
    },

    isInvalidJson(param) {
      // 如果不是 json 类型，不需要进行 JSON 校验
      if (param.type !== 'json') return false;
      
      // 为空或纯空格视为无效
      if (!param.value || param.value.trim() === '') return true; 

      try {
        const parsed = JSON.parse(param.value);
        
        // 既然单独选了 json 类型，通常排除了基础类型(string/integer/boolean)。
        // 这里我们限制它解析后必须是 对象({}) 或 数组([])，且不能是 null
        if (typeof parsed !== 'object' || parsed === null) {
          return true;
        }
        
        return false; // 解析成功且是对象/数组，校验通过
      } catch (e) {
        return true; // JSON 语法错误，校验失败
      }
    },

  getParamPlaceholder(type) {
    if (type === 'dict') return '{"type": "enabled"}';
    if (type === 'list') return '["item1", "item2"]';
    return this.t('paramValue'); // 默认使用翻译
  },

    async updateParamType(index) {
      const param = this.settings.extra_params[index];
      switch(param.type) {
        case 'json':
          param.value = '{}'; // 默认给一个对象，用户需要数组自己改成[] 即可
          break;
        case 'boolean':
          param.value = false;
          break;
        case 'integer':
        case 'float':
          param.value = 0;
          break;
        default:
          param.value = '';
      }
      await this.autoSaveSettings();
    },

    async updateFastParamType(index) {
      const param = this.fastSettings.extra_params[index];
      // 根据类型初始化值
      switch(param.type) {
        case 'json':
          param.value = '{}'; // 默认给一个对象，用户需要数组自己改成[] 即可
          break;
        case 'boolean':
          param.value = false;
          break;
        case 'integer':
        case 'float':
          param.value = 0;
          break;
        default:
          param.value = '';
      }
      await this.autoSaveSettings();
    },

    async removeParam(index) {
      this.settings.extra_params.splice(index, 1);
      await this.autoSaveSettings();
    },

    async removeFastParam(index) {
      this.fastSettings.extra_params.splice(index, 1);
      await this.autoSaveSettings();
    },

    cancelLLMTool() {
      this.showLLMForm = false
      this.resetForm()
    },

    handleTypeChange(val) {
      this.newLLMTool.base_url = this.defaultBaseURL
      this.newLLMTool.api_key = this.defaultApikey
      this.fetchModelsForType(val)
    },

    // 获取模型列表
    async fetchModelsForType(type) {
      try {
        // C-4: /llm_models 后端从不存在（调用必 404 被 catch 吞）=改用真实端点
        const response = await fetch(`/v1/providers/models`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            type: type,
            url: this.newLLMTool.base_url,
            api_key: this.newLLMTool.api_key
          })
        })
        
        const { data } = await response.json()
        this.modelOptions = data.models || []
      } catch (error) {
        console.error('Failed to fetch models:', error)
      }
    },

    // 保存工具
    saveLLMTool() {
      const tool = { ...this.newLLMTool }
      // 添加工具ID
      tool.id = uuid.v4();
      if (this.editingLLM) {
        this.llmTools[this.editingLLM] = tool
      } else {
        this.llmTools.push(tool)
      }
      this.showLLMForm = false
      this.resetForm()
      this.autoSaveSettings()
    },

    // 删除工具
    removeLLMTool(index) {
      this.llmTools.splice(index, 1)
      this.autoSaveSettings()
    },

    // 重置表单
    resetForm() {
      this.newLLMTool = {
        name: '',
        type: 'openai',
        description: '',
        base_url: '',
        api_key: '',
        model: '',
        enabled: true
      }
      this.editingLLM = null
    },

    // 类型标签转换
    toolTypeLabel(type) {
      const found = this.llmInterfaceTypes.find(t => t.value === type)
      return found ? found.label : type
    }
});
