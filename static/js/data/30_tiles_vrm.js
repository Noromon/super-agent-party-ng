// 批 3 F2：自 vue_data.js 按行带搬移的状态域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    newTTSConfig: {
      name: '',
      enabled: false,
      SampleText: 'super agent party链接一切！',
      engine: 'edgetts',
      edgettsLanguage: 'zh-CN',
      edgettsGender: 'Female',
      edgettsVoice: 'XiaoyiNeural',
      edgettsRate: 1.0,
      gsvServer: "http://127.0.0.1:9880",
      gsvTextLang: 'zh',
      gsvRate: 1.0,
      gsvSample_steps: 4,
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

      mossVoice: 'Junhao',
      mossSpeed: 1.0,

      newtts:{}
    },

    cur_voice :'default',

    openaiVoices:['alloy', 'ash', 'ballad', 'coral', 'echo', 'sage', 'shimmer', 'verse'],

    showMoreButtonDialog: false,

    isAssistantMode: false,

    isCapsuleMode: false,

    isFixedWindow: false,

    MoreButtonDict: [
      {"name": "brieflyButton", "enabled": true},
      {"name": "forceScrollButton", "enabled": true},
      {"name": "expandButton", "enabled": true},
      {"name": "fileButton", "enabled": true},
      {"name": "fastResponseButton", "enabled": true},
      {"name": "reasonerButton", "enabled": true},
      {"name": "deepSearchButton", "enabled": false},
      {"name": "visionButton", "enabled": false},
      {"name": "screenshotButton", "enabled": true},
      {"name": "desktopVisionButton", "enabled": false},
      {"name": "text2imgButton", "enabled": false},
      {"name": "asrButton", "enabled": true},
      {"name": "ttsButton", "enabled": true},
      {"name": "knowledgeBaseButton", "enabled": true},
      {"name": "webSearchButton", "enabled": true},
      {"name": "memoryButton", "enabled": true},
      {"name": "uiButton", "enabled": true},
      {"name": "codeButton", "enabled": false},
      {"name": "CLIButton", "enabled": false},
      {"name": "visionControl", "enabled": false},
      {"name": "stickerButton", "enabled": false},
      {"name": "haButton", "enabled": false},
      {"name": "chromeButton", "enabled": false},
      {"name": "sqlButton", "enabled": false},
      {"name": "agentButton", "enabled": false},
      {"name": "llmButton", "enabled": false},
      {"name": "mcpButton", "enabled": true},
      {"name": "a2aButton", "enabled": false},
      {"name": "httpButton", "enabled": false},
      {"name": "comfyuiButton", "enabled": false},
      {"name": "vrmButton", "enabled": true},
      {"name": "thaButton", "enabled": true},
      {"name": "soulxButton", "enabled": true},
      {"name": "behaviorBotton", "enabled": false},
      {"name": "groupChatBotton", "enabled": true},
    ],

    largeMoreButtonDict:[
      {"name": "brieflyButton", "enabled": true},
      {"name": "forceScrollButton", "enabled": true},
      {"name": "expandButton", "enabled": true},
      {"name": "fileButton", "enabled": true},
      {"name": "fastResponseButton", "enabled": true},
      {"name": "reasonerButton", "enabled": true},
      {"name": "deepSearchButton", "enabled": false},
      {"name": "visionButton", "enabled": false},
      {"name": "desktopVisionButton", "enabled": false},
      {"name": "screenshotButton", "enabled": true},
      {"name": "text2imgButton", "enabled": false},
      {"name": "asrButton", "enabled": true},
      {"name": "ttsButton", "enabled": true},
      {"name": "knowledgeBaseButton", "enabled": true},
      {"name": "webSearchButton", "enabled": true},
      {"name": "memoryButton", "enabled": true},
      {"name": "uiButton", "enabled": true},
      {"name": "codeButton", "enabled": false},
      {"name": "CLIButton", "enabled": false},
      {"name": "visionControl", "enabled": false},
      {"name": "stickerButton", "enabled": false},
      {"name": "haButton", "enabled": false},
      {"name": "chromeButton", "enabled": false},
      {"name": "sqlButton", "enabled": false},
      {"name": "agentButton", "enabled": false},
      {"name": "llmButton", "enabled": false},
      {"name": "mcpButton", "enabled": true},
      {"name": "a2aButton", "enabled": false},
      {"name": "httpButton", "enabled": false},
      {"name": "comfyuiButton", "enabled": false},
      {"name": "vrmButton", "enabled": true},
      {"name": "thaButton", "enabled": true},
      {"name": "soulxButton", "enabled": true},
      {"name": "behaviorBotton", "enabled": false},
      {"name": "groupChatBotton", "enabled": true},
    ],

    smallMoreButtonDict:[
      {"name": "brieflyButton", "enabled": false},
      {"name": "forceScrollButton", "enabled": false},
      {"name": "expandButton", "enabled": false},
      {"name": "fileButton", "enabled": false},
      {"name": "fastResponseButton", "enabled": false},
      {"name": "reasonerButton", "enabled": false},
      {"name": "deepSearchButton", "enabled": false},
      {"name": "visionButton", "enabled": false},
      {"name": "desktopVisionButton", "enabled": true},
      {"name": "screenshotButton", "enabled": true},
      {"name": "text2imgButton", "enabled": false},
      {"name": "asrButton", "enabled": false},
      {"name": "ttsButton", "enabled": false},
      {"name": "knowledgeBaseButton", "enabled": false},
      {"name": "webSearchButton", "enabled": false},
      {"name": "memoryButton", "enabled": false},
      {"name": "uiButton", "enabled": false},
      {"name": "codeButton", "enabled": false},
      {"name": "CLIButton", "enabled": false},
      {"name": "visionControl", "enabled": false},
      {"name": "stickerButton", "enabled": false},
      {"name": "haButton", "enabled": false},
      {"name": "chromeButton", "enabled": false},
      {"name": "sqlButton", "enabled": false},
      {"name": "agentButton", "enabled": false},
      {"name": "llmButton", "enabled": false},
      {"name": "mcpButton", "enabled": false},
      {"name": "a2aButton", "enabled": false},
      {"name": "httpButton", "enabled": false},
      {"name": "comfyuiButton", "enabled": false},
      {"name": "vrmButton", "enabled": true},
      {"name": "thaButton", "enabled": true},
      {"name": "soulxButton", "enabled": true},
      {"name": "behaviorBotton", "enabled": false},
      {"name": "groupChatBotton", "enabled": false},
    ],

    showVrmModelDialog: false,

    vrmOnline: false,   // 新增,

    vrmPollTimer: null, // 新增,

    newVrmModel: {
      name: '',
      displayName: '',
      file: null
    },

    showGaussSceneDialog: false, // GAUSS,

    newGaussScene: { name: '', displayName: '' }, // GAUSS,

    VRMConfig: {
      name: 'default',
      enabledExpressions: false,
      enabledMotions: false,
      selectedModelId: 'alice', // 默认选择Alice模型
      windowWidth: 540,
      windowHeight: 960,
      defaultModels: [], // 存储默认模型
      userModels: [],     // 存储用户上传的模型
      defaultMotions: [], // 存储默认动作
      userMotions: [],     // 存储用户上传的动作
      selectedMotionIds: [],
      selectedNewModelId: 'alice',
      selectedNewMotionIds: [],
      newVRM:{},
      gaussDefaultScenes: [],   // GAUSS
      gaussUserScenes: [],      // GAUSS
      selectedGaussSceneId: '',
    },

    // S91(THA)：桌宠配置（随上游终态）
    THAConfig: {
      name: 'default',
      enabledEmotions: false,
      enabledFineControl: false,
      enabledMouthSync: false,
      srMode: 'cnnx2vl',
      selectedModelId: 'Lyra',
      windowWidth: 540,
      windowHeight: 540,
      defaultModels: [],
      userModels: []
    },
    showThaModelDialog: false,
    newThaModel: {
      file: null,
      name: '',
      displayName: ''
    },

    // S136(SoulX)：真人伴侣配置（随上游终态；FlashHead GPU 服务另行部署）
    SoulxConfig: {
      name: 'default',
      enabled: false,
      serverUrl: 'ws://127.0.0.1:8765',
      condImage: '',
      selectedImageId: '',
      images: [],
      transparentBg: true,
      windowWidth: 512,
      windowHeight: 512
    },
    showSoulxImageDialog: false,
    newSoulxImage: {
      file: null,
      name: '',
      displayName: ''
    },

    newAppearanceConfig: {
      name: '',
      windowWidth: 540,
      windowHeight: 960,
      selectedModelId: 'alice', // 默认选择Alice模型
      selectedMotionIds: [],
    },

    showAddAppearanceDialog: false,

    showVrmaMotionDialog: false,

    showFileDialog: false,

    newVrmaMotion: {
      name: '',
      displayName: '',
      file: null
    },

    expressionMap : [
      '<happy>', 
      '<angry>', 
      '<sad>',
      '<neutral>',
      '<surprised>', 
      '<relaxed>'],

    newGsvAudio: {
      name: '',
      path: '',
      text: '',
    },

    startTime: null,

    elapsedTime: 0,

    gsvTextLangs:["zh", "en" , "yue","ja","ko","auto","auto_yue"],

    audioPlayQueue: [],

    currentAudio: null,

    edgettsLanguage: 'zh-CN',

    edgettsGender: 'Female'
});
