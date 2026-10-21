// 批 3 F2：自 vue_data.js 按行带搬移的状态域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    localEnvSettings: {
      enabled: false,
      permissionMode: 'default',
    },

    ocSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
      permissionMode: 'default',
    },

    prefrontalCortexSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
    },

    NeocortexSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
    },

    LimbicSystemSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
    },

    ReptilianBrainSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
    },

    showBrainEditDialog: false, // 控制模态框显示,

    currentEditingKey: '',      // 当前正在编辑哪个脑区 (例如 'prefrontalCortex'),

    HASettings: {
      enabled: false,
      api_key: '',
      url: 'http://127.0.0.1:8123',
    },

    chromeMCPSettings: {
      enabled: false,
      mcpName: 'browser-mcp', // browser-mcp or playwright-mcp
      type:"external", // external or internal
      CDPport:9222
    },

    sqlSettings:{
      enabled: false,
      engine: "sqlite",
      user: "",
      password: "",
      host:"",
      port:5432,
      dbname: "",
      dbpath: "",
    },

    knowledgeBases: [],

    KBSettings: {
      when: 'after_thinking',
      is_rerank: false,
      selectedProvider: null,
      model: '',
      base_url: '',
      api_key: '',
      top_n: 5,
    },

    showAddKbDialog: false,

    showKnowledgeDialog: false,

    showMCPServerDialog: false,

    a2aServers: {},

    showA2AServerDialog: false,

    showAddA2ADialog: false,

    newA2AUrl: '',

    activeCollapse: [],

    newKb: {
      name: '',
      introduction: '',
      providerId: null,
      model: '',
      base_url: '',
      api_key: '',
      chunk_size: 2048,
      chunk_overlap: 512,
      chunk_k: 5,
      weight: 0.5,
      processingStatus: 'processing',
    },

    newKbFiles: [],

    systemSettings: {
      language: 'auto',
      theme: 'light',
      network:"local",
      proxy: 'http://127.0.0.1:7890',
      proxyMode: 'system', //system or manual or none
      isChinaProxy: false,
      backupIncludeUploads: false,
    },

    // --- 数据安全网（M4-lite 快照备份 UI）---
    backupSnapshots: [],

    backupNowRunning: false,

    backupListLoading: false,

    verifyBackupName: '',

    networkOptions:[
      { value: 'local', label: 'local' }, 
      { value: 'global', label: 'allDevicesVisible' },
    ],

    imgHostOptions:[
      { value: 'easyImage2', label: 'easyImage2' }
    ],

    showRestartDialog: false,

    showCDPRestartDialog: false,

    agents: {},

    showAgentForm: false,

    showAgentDialog: false,

    mainAgent: 'super-model',

    newAgent: {
      id: '',
      name: '',
      system_prompt: ''
    },

    currentLanguage: 'zh-CN',

    translations: translations,

    themeValues: ['light', 'dark','midnight','desert','neon','marshmallow','ink','party',"rainbow"],

    isBrowserOpening: false,

    expandedSections: {
      settingsBase: true,
      reasonerConfig: true,
      language: true,
      superapi: true,
      webSearchConfig: true,
      duckduckgoConfig: true,
      searxngConfig: true,
      tavilyConfig: true,
      jinaConfig: true,
      Crawl4AiConfig: true,
      settingsAdvanced: true,
      reasonerAdvanced: true,
      knowledgeAdvanced: false,
    },

    abortController: null, // 用于中断请求的控制器,

    isSending: false, // 是否正在发送,

    contextStats: {},

    ctxPanelVisible: false,

    ctxHover: false,

    ctxPopStyle: {},

    todoStats: {},

    todoHover: false,

    todoPopStyle: {},

    todoPanelPinned: false,

    showAddDialog: false,

    modelProviders: [],

    fileLinks: [],

    audioContext: null,

    mediaStream: null,

    mediaRecorder: null,

    audioChunks: [],

    isRecording: false,

    vad: null,

    speechTimeout: null,

    currentAudioChunks: [],

    currentTranscriptionId: null,

    speechStartTime: null,

    recognition: null,

    sherpaModelExists: false,             // 模型是否已存在,

    sherpaDownloading: false,             // 是否正在下载,

    sherpaPercent: 0,                     // 实时进度 0-100,

    sherpaEventSource: null,               // 当前 SSE 实例,

    sherpaModelName: '',                 // 模型名称,

    minilmModelExists: false,       // 模型是否已存在,

    minilmDownloading: false,       // 是否正在下载,

    minilmPercent: 0,               // 实时进度 0-100,

    minilmEventSource: null,        // 当前 SSE 实例,

    mossModelExists: false,

    mossDownloading: false,

    mossDownloadSource: '',

    mossPollInterval: null,

    mossPercent: 0, // 新增：真实进度条百分比,

    asrSettings: {
      enabled: false,
      engine: 'sherpa',
      selectedProvider: null,
      webSpeechLanguage: 'auto',
      vendor: "OpenAI",
      model: "",
      base_url: "",
      api_key: "",
      funasr_ws_url: "ws://127.0.0.1:10095",
      funasr_mode: "offline",
      interactionMethod: "auto",
      hotkey : "Alt",
      wakeWord: "小派",
      endWord: "结束对话",
      hotwords: "小派 80\nagent party 60\n结束对话 80",
    },

    supportedLanguages: [
      { code: 'zh-CN', name: '中文' },
      { code: 'en-US', name: 'English' },
      { code: 'ja-JP', name: '日本語' },
      { code: 'ko-KR', name: '한국어' },
      { code: 'es-ES', name: 'Español' },
      { code: 'fr-FR', name: 'Français' },
      { code: 'de-DE', name: 'Deutsch' },
      { code: 'ru-RU', name: 'Русский' },
    ],

    userInputBuffer: '',

    sidePanelOpen: false,

    sidePanelHTML: '',

    chatAreaOpen: true,        // 对话区域是否展开,

    chatAreaWidth: 50,         // 对话区域宽度百分比,

    sidePanelWidth: 50,        // 侧边栏宽度百分比,

    isResizing: false,         // 是否正在调整大小,

    isHistoryPanelResizing: false,

    minPanelWidth: 25,         // 最小面板宽度百分比,

    extensions: [],              // 所有发现的扩展,

    currentExtension: null,      // 当前加载的扩展,

    sidePanelURL: '',            // 侧边栏中显示的扩展URL,

    showExtensionsDialog: false, // 控制扩展选择对话框的显示,

    showExtensionForm: false, // 控制扩展表单的显示,

    newExtensionUrl: '',   // 绑定输入框,

    remotePlugins: [], // 远程插件列表,

    installedPlugins: [], // 本地已安装,

    installLoading: false,

    refreshing: false,

    refreshButtonText: "",

    showHistorySidebar: false,

    ttsSettings: {
      enabled: false,
      engine: 'edgetts',
      separators:["。", "\n", "？", "！", "，","～","!","?",",","~"],
      maxConcurrency: 2,
      enabledInterruption: false,
      bufferWordList: [],
      SampleText: 'super agent party链接一切！',
      edgettsLanguage: 'zh-CN',
      edgettsGender: 'Female',
      edgettsVoice: 'XiaoyiNeural',
      edgettsRate: 1.0,
      gsvServer: "http://127.0.0.1:9880",
      gsvTextLang: 'zh',
      gsvRate: 1.0,
      gsvPromptLang: 'zh',
      gsvPromptText: '',
      gsvSample_steps: 4,
      gsvRefAudioPath: '',
      gsvAudioOptions: [],
      selectedProvider: null,
      vendor: "OpenAI",
      model: "",
      base_url: "",
      api_key: "",
      openaiVoice:"alloy",
      openaiStream: false,
      openaiSpeed: 1.0,
      customTTSserver: "http://127.0.0.1:9880",
      customTTSspeaker: "",
      customTTSspeed: 1.0,
      customStream: false,
      customTTSKeyText: 'text',
      customTTSKeySpeaker: 'speaker',
      customTTSKeySpeed: 'speed',
      systemVoiceName: null,
      systemRate: 200,
      // Tetos 通用音色列表缓存 (当切换引擎时刷新)
      tetosVoices: [],
      isFetchingVoices: false,

      // Azure
      azureSpeechKey: '',
      azureRegion: '',
      azureVoice: '',

      // Volcengine
      volcAppId: '',
      volcAccessKey: '',
      volcResourceId: 'seed-tts-2.0', // 默认公共资源ID
      volcVoice: 'zh_female_vv_uranus_bigtts', // 默认大模型音色
      volcRate: 1.0,

      // Baidu
      baiduApiKey: '',
      baiduSecretKey: '',
      baiduVoice: '',

      // Minimax
      minimaxApiKey: '',
      minimaxGroupId: '',
      minimaxVoice: '',

      // Xunfei
      xunfeiAppId: '',
      xunfeiApiKey: '',
      xunfeiApiSecret: '',
      xunfeiVoice: '',

      // Fish Audio
      fishApiKey: '',
      fishVoice: '',

      // Google
      googleServiceAccount: '', // JSON 字符串
      googleVoice: '',
      newtts:{},


      // elevenLabs
      elevenLabsApiKey: '',
      elevenLabsVoice: 'JBFqnCBsd6RMkjVDRZzb',
      elevenLabsModel: 'eleven_multilingual_v2',
      elevenLabsRate: 1.0,


      // moss
      mossVoice: 'Junhao',
      mossSpeed: 1.0,
    },

    volcResourceOptions: [
        { value: 'volc_tts_release', label: '旧版/标准版 (Standard)' },
        // 豆包 1.0
        { value: 'seed-tts-1.0', label: '豆包模型1.0 (字符版)' },
        { value: 'volc.service_type.10029', label: '豆包1.0 (字符版-ServiceType)' },
        { value: 'seed-tts-1.0-concurr', label: '豆包模型1.0 (并发版)' },
        { value: 'volc.service_type.10048', label: '豆包1.0 (并发版-ServiceType)' },
        // 豆包 2.0
        { value: 'seed-tts-2.0', label: '豆包模型2.0 (字符版)' },
        // 声音复刻
        { value: 'seed-icl-1.0', label: '声音复刻1.0 (字符版)' },
        { value: 'seed-icl-1.0-concurr', label: '声音复刻1.0 (并发版)' },
        { value: 'seed-icl-2.0', label: '声音复刻2.0 (字符版)' }
    ],

    activeTTSTab: 'default', // 控制 TTS 标签页切换,

    showAddTTSDialog: false, // 控制添加 TTS 的对话框显示
});
