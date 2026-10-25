// R2-5 vendor_params 簇：供应商推荐参数一键添加（Object.assign 装配，
// 数据源=static/js/vendor_params.js 的 window.vendorSuggestedParams）。
Object.assign(vue_methods, {
    // 从建议参数中添加（主模型）
    async addMainSuggestedParam(param) {
      if (this.paramExistsInMain(param.name)) return;
      this.settings.extra_params.push({
        name: param.name,
        type: param.type,
        value: param.default !== undefined ? param.default : (param.type === 'boolean' ? false : (param.type === 'json' ? '{}' : (param.type === 'integer' || param.type === 'float' ? 0 : '')))
      });
      await this.autoSaveSettings();
    },
    // 从建议参数中添加（快速应答模型）
    async addFastSuggestedParam(param) {
      if (this.paramExistsInFast(param.name)) return;
      this.fastSettings.extra_params.push({
        name: param.name,
        type: param.type,
        value: param.default !== undefined ? param.default : (param.type === 'boolean' ? false : (param.type === 'json' ? '{}' : (param.type === 'integer' || param.type === 'float' ? 0 : '')))
      });
      await this.autoSaveSettings();
    },
    paramExistsInMain(name) {
      return this.settings.extra_params.some(p => p.name === name);
    },
    paramExistsInFast(name) {
      return this.fastSettings.extra_params.some(p => p.name === name);
    },
    formatVendorName(name) {
      if (!name) return '';
      const first = name.charAt(0);
      if (first >= 'a' && first <= 'z') return first.toUpperCase() + name.slice(1);
      return name;
    },
});
