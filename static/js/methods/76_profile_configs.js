// 批 3 F2：自 vue_methods.js 搬移的 methods/76_profile_configs.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  NextPage() {
    if (this.longTextListIndex < this.readConfig.longTextList.length - 1) {
      this.longTextListIndex++;
      this.readConfig.longText = this.readConfig.longTextList[this.longTextListIndex];
    }
  },

  PrevPage() {
    if (this.longTextListIndex > 0) {
      this.longTextListIndex--;
      this.readConfig.longText = this.readConfig.longTextList[this.longTextListIndex];
    }
  },

  openAddTTSDialog() {
    this.newTTSConfig = {
      name: '',
      enabled: true,
      SampleText: 'super agent party链接一切！',
      engine: 'moss',
      edgettsLanguage: 'zh-CN',
      edgettsGender: 'Female',
      edgettsVoice: 'XiaoyiNeural',
      edgettsRate: 1.0,
      gsvServer: "http://127.0.0.1:9880",
      gsvTextLang: 'zh',
      gsvRate: 1.0,
      gsvPromptLang: 'zh',
      gsvPromptText: '',
      gsvRefAudioPath: '',
      gsvAudioOptions: [],
      selectedProvider: null,
      vendor: "OpenAI",
      model: "",
      base_url: "",
      api_key: "",
      openaiVoice:"alloy",
      openaiSpeed: 1.0,
      customTTSserver: "http://127.0.0.1:9880",
      customTTSspeaker: "",
      customTTSspeed: 1.0,
      mossVoice: 'Junhao',
      mossSpeed: 1.0,
    };
    this.showAddTTSDialog = true;
  },

  saveNewTTSConfig() {
    const name = this.newTTSConfig.name;
    if (!name) return;

    this.ttsSettings.newtts[name] = { ...this.newTTSConfig };
    this.showAddTTSDialog = false;
    this.autoSaveSettings();
  },

  deleteTTS(name) {
    delete this.ttsSettings.newtts[name];
  },

  editTTS(name) {
    this.newTTSConfig = { ...this.ttsSettings.newtts[name] };
    this.showAddTTSDialog = true;
  },

  openAddAppearanceDialog() {
    this.newAppearanceConfig = {
      name: '',
      windowWidth: 540,
      windowHeight: 960,
      selectedModelId: 'alice', // 默认选择Alice模型
      selectedMotionIds: [],
    };
    this.showAddAppearanceDialog = true;
  },

  editAppearance(name) {
    this.newAppearanceConfig = { ...this.VRMConfig.newVRM[name] };
    this.showAddAppearanceDialog = true;
  },

  deleteAppearance(name) {
    delete this.VRMConfig.newVRM[name];
  },

  saveNewAppearanceConfig() {
    const name = this.newAppearanceConfig.name;
    if (!name) return;

    this.VRMConfig.newVRM[name] = { ...this.newAppearanceConfig };
    this.showAddAppearanceDialog = false;
    this.autoSaveSettings();
  }
});
