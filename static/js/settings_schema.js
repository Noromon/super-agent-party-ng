// 设置读写单一事实源（批 0-④）：autoSaveSettings 的 payload 构造与
// initWebSocket 'settings' 恢复共用本表，杜绝“每键写三遍”的清单漂移。
// wire  = 传输层键名（save payload / 恢复消息 data.data 的键）
// state = Vue 实例字段名（this.X）
// 历史别名（wire≠state，协议兼容不可改名）：tools/reasoner/fast/vision/
// webSearch/custom_http 五对，已在表内显式声明。
//
// 不走本表的特例（语义特殊，保留在 vue_methods 手写并在此登记）：
//   settings 展开字段     —— 恢复需逐字段默认值，见 SETTINGS_DEFAULTS
//   conversations 三元组  —— 恢复带重连保护/合并（isReconnect）
//   isdocker              —— 恢复默认 false 而非保留现值
//   large/smallMoreButtonDict —— 恢复为按 name 合并 enabled 的算法
(function () {
  'use strict';

  // [wire, state]；顺序即原 autoSaveSettings 手写清单顺序（审阅对照用）
  const PAIRS = [
    ['showHistorySidebar', 'showHistorySidebar'],
    ['system_prompt', 'system_prompt'],
    ['SystemPromptsList', 'SystemPromptsList'],
    ['agents', 'agents'],
    ['mainAgent', 'mainAgent'],
    ['qqBotConfig', 'qqBotConfig'],
    ['feishuBotConfig', 'feishuBotConfig'],
    ['wechatBotConfig', 'wechatBotConfig'],
    ['weComBotConfig', 'weComBotConfig'],
    ['dingtalkBotConfig', 'dingtalkBotConfig'],
    ['discordBotConfig', 'discordBotConfig'],
    ['slackBotConfig', 'slackBotConfig'],
    ['telegramBotConfig', 'telegramBotConfig'],
    ['xmppBotConfig', 'xmppBotConfig'],
    ['targetLangSelected', 'targetLangSelected'],
    ['allBriefly', 'allBriefly'],
    ['isForceScrollToBottom', 'isForceScrollToBottom'],
    ['BotConfig', 'BotConfig'],
    ['liveConfig', 'liveConfig'],
    ['WXBotConfig', 'WXBotConfig'],
    ['stickerPacks', 'stickerPacks'],
    ['tools', 'toolsSettings'],
    ['llmTools', 'llmTools'],
    ['conversationId', 'conversationId'],
    ['conversationGroups', 'conversationGroups'],
    ['reasoner', 'reasonerSettings'],
    ['fast', 'fastSettings'],
    ['isBtnCollapse', 'isBtnCollapse'],
    ['vision', 'visionSettings'],
    ['webSearch', 'webSearchSettings'],
    ['codeSettings', 'codeSettings'],
    ['CLISettings', 'CLISettings'],
    ['acpSettings', 'acpSettings'],
    ['visionControlSettings', 'visionControlSettings'],
    ['loveSettings', 'loveSettings'],
    ['diarySettings', 'diarySettings'],
    ['ccSettings', 'ccSettings'],
    ['qcSettings', 'qcSettings'],
    ['dsSettings', 'dsSettings'],
    ['wslSettings', 'wslSettings'],
    ['localEnvSettings', 'localEnvSettings'],
    ['ocSettings', 'ocSettings'],
    ['HASettings', 'HASettings'],
    ['chromeMCPSettings', 'chromeMCPSettings'],
    ['sqlSettings', 'sqlSettings'],
    ['KBSettings', 'KBSettings'],
    ['textFiles', 'textFiles'],
    ['imageFiles', 'imageFiles'],
    ['videoFiles', 'videoFiles'],
    ['knowledgeBases', 'knowledgeBases'],
    ['modelProviders', 'modelProviders'],
    ['systemSettings', 'systemSettings'],
    ['largeMoreButtonDict', 'largeMoreButtonDict'],
    ['smallMoreButtonDict', 'smallMoreButtonDict'],
    ['currentLanguage', 'currentLanguage'],
    ['mcpServers', 'mcpServers'],
    ['a2aServers', 'a2aServers'],
    ['isdocker', 'isdocker'],
    ['memories', 'memories'],
    ['memorySettings', 'memorySettings'],
    ['llmGuardSettings', 'llmGuardSettings'],
    ['text2imgSettings', 'text2imgSettings'],
    ['asrSettings', 'asrSettings'],
    ['ttsSettings', 'ttsSettings'],
    ['behaviorSettings', 'behaviorSettings'],
    ['VRMConfig', 'VRMConfig'],
    ['THAConfig', 'THAConfig'],
    ['comfyuiServers', 'comfyuiServers'],
    ['comfyuiAPIkey', 'comfyuiAPIkey'],
    ['workflows', 'workflows'],
    ['custom_http', 'customHttpTools'],
    ['showBrowserChat', 'showBrowserChat'],
    ['searchEngine', 'searchEngine'],
    ['isGroupMode', 'isGroupMode'],
    ['selectedGroupAgents', 'selectedGroupAgents']
  ];

  // 恢复侧由 vue_methods 特例代码处理的 wire 键（保存仍走本表）
  const RESTORE_SPECIAL = new Set([
    'conversationId',
    'conversationGroups',
    'largeMoreButtonDict',
    'smallMoreButtonDict',
    'isdocker'
  ]);

  // settings 展开字段恢复默认值（对象/数组默认用函数产出新实例）
  const SETTINGS_DEFAULTS = {
    model: '',
    base_url: '',
    api_key: '',
    temperature: 0.7,
    max_tokens: 4096,
    max_rounds: 0,
    contextManagement: function () {
      return { enabled: true, contextWindow: 32000, compactRatio: 0.8, keepRecentTools: 4, keepRecentDialog: 12, autoAgentCompact: true };
    },
    networkAccessSettings: function () {
      return { allowLocalEquivalentUrls: false, allowLanUrls: false };
    },
    selectedProvider: '',
    top_p: 1,
    reasoning_effort: null,
    enableOmniTTS: false,
    omniVoice: 'Cherry',
    mcpCallTimeout: 180,
    extra_params: function () { return []; }
  };

  // 保存：构造 save_settings payload（等价原 71 对手写清单 + ...this.settings）
  function buildSettingsPayload(vm) {
    const payload = Object.assign({}, vm.settings);
    for (let i = 0; i < PAIRS.length; i++) {
      payload[PAIRS[i][0]] = vm[PAIRS[i][1]];
    }
    return payload;
  }

  // 恢复：常规对赋值，truthy 才覆盖（等价原 `data.data.X || this.X`）
  function applySettingsPayload(vm, d) {
    for (let i = 0; i < PAIRS.length; i++) {
      const wire = PAIRS[i][0];
      if (RESTORE_SPECIAL.has(wire)) continue;
      if (d[wire]) vm[PAIRS[i][1]] = d[wire];
    }
  }

  // 恢复：重建 settings 展开对象（等价原逐字段 `data.data.X || 默认`）
  function buildSettingsFromWire(d) {
    const out = {};
    Object.keys(SETTINGS_DEFAULTS).forEach(function (key) {
      const dft = SETTINGS_DEFAULTS[key];
      out[key] = d[key] || (typeof dft === 'function' ? dft() : dft);
    });
    return out;
  }

  window.SETTINGS_SCHEMA = {
    PAIRS: PAIRS,
    RESTORE_SPECIAL: RESTORE_SPECIAL,
    SETTINGS_DEFAULTS: SETTINGS_DEFAULTS,
    buildSettingsPayload: buildSettingsPayload,
    applySettingsPayload: applySettingsPayload,
    buildSettingsFromWire: buildSettingsFromWire
  };
})();
