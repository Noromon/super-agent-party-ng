// 批 3 F2：自 vue_data.js 按行带搬移的状态域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    isMac: false,

    isWindows: false,

    partyURL:`${window.location.protocol}//${window.location.host}`,

    updateIcon: 'fa-solid fa-download',

    system_prompt: ' ',

    SystemPromptsList: [],          // 系统提示词数组,

    extensionsSystemPromptsDict: {}, // 扩展提示词字典,

    showPromptDialog: false,        // 对话框显隐,

    promptForm: {                   // 对话框绑定
      id: null,
      name: '',
      content: ''
    },

    selectSystemPromptId: null,    // 选择的系统提示词id,

    wakeWindowTimer: null,   // 计时器,

    withinWakeWindow: false, // 是否处于“免唤醒”30s 窗口,

    isdocker: false,

    isExpanded: true,

    isElectron: isElectron,

    isCollapse: true,

    isBtnCollapse: true,

    activeMenu: 'dashboard',

    activeLiveTab: 'live',

    isMaximized: false,

    hasUpdate: false,

    updateSuccess: false,

    audioCtx: null,          // WebAudio 上下文,

    activeSources: [],

    audioStartTime: 0,       // 下一帧应该开始的时间,

    omniQueue: [],        // [{idx, text, expressions, voice, pcmBase64}, ...],

    omniIdx: 0,           // 当前正在播的索引,

    isOmniPlaying: false, // 是否正在播放,

    settings: {
      model: '',
      base_url: '',
      api_key: '',
      temperature: 1,  // 默认温度值
      max_tokens: 8192,    // 默认最大输出长度
      max_rounds: 0,    // 默认最大轮数
      selectedProvider: null,
      top_p: 1,
      reasoning_effort: null,
      enableOmniTTS: false,// 是否启用omniTTS
      omniVoice: 'Cherry', // omniTTS的语音
      extra_params: [], // 额外参数
    },

    fastSettings: {
      enabled: false, // 默认不启用
      triggerMode: 'conditional', // 默认触发模式条件触发
      model: '',
      base_url: '',
      api_key: '',
      temperature: 1,  // 默认温度值
      max_tokens: 8192,    // 默认最大输出长度
      max_rounds: 0,    // 默认最大轮数
      selectedProvider: null,
      top_p: 1,
      reasoning_effort: null,
      enableOmniTTS: false,// 是否启用omniTTS
      omniVoice: 'Cherry', // omniTTS的语音
      extra_params: [], // 额外参数
      conditionMaxLen: 200,       // 默认字数限制，小于此字数才触发
      conditionNoNewline: true,   // 是否要求不能有换行才触发
      conditionNoFiles: true,     // 是否要求无图片/文件才触发
    },

    reasonerSettings: {
      enabled: false, // 默认不启用
      model: '',
      base_url: '',
      api_key: '',
      selectedProvider: null,
      temperature: 1,  // 默认温度值
      max_tokens: 4096,  // 默认最大输出长度
      stop_words: [',', '.', '，', '。'], // 停止词列表
      reasoning_effort: null,
    },

    target_lang: 'zh-CN',

    reasoningEfforts:[
      { value: null, label: 'reason-null' },
      { value: 'minimal', label: 'reason-minimal' },
      { value: 'low', label: 'reason-low' },
      { value: 'medium', label: 'reason-medium' },
      { value: 'high', label: 'reason-high' },
      { value: 'xhigh', label: 'reason-xhigh' },
      { value: 'max', label: 'reason-max' },
      { value: 'none', label: 'reason-none' },
    ],

    visionSettings: {
      enabled: false, // 默认不启用
      model: '',
      base_url: '',
      api_key: '',
      selectedProvider: null,
      temperature: 1,  // 默认温度值
      desktopVision: false,
      wakeWord: '看\nsee\nlook\n桌面\ndesktop',
      enableWakeWord: false,
    },

    paramTypes:[
      { value: 'string', label: 'string' },
      { value: 'integer', label: 'integer' },
      { value: 'float', label: 'float' },
      { value: 'boolean', label: 'boolean' },
      { value: 'json', label: 'JSON' } // 合并为一个
    ],

    ws: null,

    messages: [],

    cur_audioDatas: [],

    userInput: '',

    isTyping: false,

    currentMessage: '',

    conversationId: null, // 当前对话ID,

    conversations: [], // 对话历史记录,

    conversationGroups: [],

    collapsedConversationGroups: {},

    chatHistoryPanelOpen: true,

    chatHistoryPanelWidth: 320,

    draftConversationGroupId: 'default',

    activeConversationGroupId: 'default',

    showConversationGroupDialog: false,

    conversationGroupDialogMode: 'create',

    conversationGroupForm: {
      id: null,
      name: '',
      memoryEnabled: false,
    },

    showConversationRenameDialog: false,

    conversationRenameForm: {
      id: null,
      name: '',
    },

    showDeleteConversationDialog: false,

    deleteConversationForm: {
      id: null,
      title: '',
      deleteMemory: false,
    },

    showDeleteGroupDialog: false,

    deleteGroupForm: {
      id: null,
      name: '',
      conversationCount: 0,
    },

    showHistoryDialog: false,

    showLLMToolsDialog: false,

    showHttpToolDialog: false,

    showComfyUIDialog: false,

    showStickerPacksDialog: false,

    showGsvRefAudioPathDialog: false,

    showModelDialog: false,

    showLogoDialog: false,

    deletingConversationId: null, // 正在被删除的对话ID,

    jsonFile: null,

    models: [],

    modelsLoading: false,

    modelsError: null,

    isThinkOpen: false,

    showEditDialog: false,

    editContent: '',

    editType: 'system', // 或 'message',

    editIndex: null,

    asyncToolsID : [],

    TTSrunning:false,

    ASRrunning:false,

    isInputting: false,

    toolsSettings: {
      asyncTools: {
        enabled: false,
      },
      a2ui: {
        enabled: false,
      },
      time: {
        enabled: false,
        triggerMode: 'beforeThinking',
      },
      weather: {
        enabled: false
      },
      wikipedia: {
        enabled: false,
      },
      arxiv: {
        enabled: false,
      },
      hideToolResults: {
        enabled: false,
      },
      getFile: {
        enabled: false,
      },
      language: {
        enabled: false, // 默认不启用
        language: 'zh-CN',
        tone: 'normal',
      },
      inference: {
        enabled: false, // 默认不启用
      },
      deepsearch: {
        enabled: false, // 默认不启用
      },
      formula: {
        enabled: true
      },
      autoBehavior: {
        enabled: false
      },
      randomTopic: {
        enabled: false,
        baseURL:'https://topics-after-party.zeabur.app'
      },
    },

    toolForShowInfo: {"name": "", "description": ""},

    showToolInfoDialog: false,

    mcpServers: {},

    showAddMCPDialog: false,

    showMCPConfirm: false,

    deletingMCPName: null,

    newMCPJson: '',

    newMCPFormData: {
      name: 'mcp',
      command: '',
      args:'',
      env: '',
      url: '',
      apiKey: '',
    },

    newMCPType: 'stdio', // 新增类型字段,

    mcpInputType: 'form', // 默认为JSON，还可以是 'form',

    currentMCPExample: '',

    mcpURLDict: {
      stdio: 'http://127.0.0.1:8000/mcp',
      sse: 'http://127.0.0.1:8000/sse',
      ws: 'ws://127.0.0.1:8000/ws',
      streamablehttp: 'http://127.0.0.1:8000/mcp'
    },

    mcpExamples: {
      stdio: `{
  "mcpServers": {
    "echo-server": {
      "command": "node",
      "args": [
        "path/to/echo-mcp/build/index.js"
      ],
      "disabled": false
    }
  }
}`,
      sse: `{
  "mcpServers": {
    "sse-server": {
      "url": "http://127.0.0.1:8000/sse",
      "headers": {
        "Content-Type": "text/event-stream",
        "Authorization": "Bearer YOUR_API_KEY"
      },
      "disabled": false
    }
  }
}`,
      ws: `{
  "mcpServers": {
    "websocket-server": {
      "url": "ws://127.0.0.1:8000/ws",
      "disabled": false
    }
  }
}`,
    streamablehttp: `{
  "mcpServers": {
    "streamablehttp-server": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer YOUR_API_KEY"
      },
      "disabled": false
    }
  }
}`
    },

    activeKbTab: 'settings', // 默认激活的标签页,

    activeReadTab: 'full', // 默认激活的标签页,

    webSearchSettings: {
      enabled: false,
      engine: 'tavily',
      crawler: 'mdnew',
      when: 'after_thinking',
      duckduckgo_max_results: 10, // 默认值
      searxng_url: `http://127.0.0.1:8080`,
      searxng_engines: "baidu,bing,sogou,360search,quark",
      searxng_is_select:false,
      searxng_max_results: 10, // 默认值
      tavily_max_results: 10, // 默认值
      tavily_api_key: '',
      jina_api_key: '',
      Crawl4Ai_url: 'http://127.0.0.1:11235',
      Crawl4Ai_api_key: 'test_api_code',
      bing_max_results: 10, // 默认值
      bing_api_key: '',
      bing_search_url: 'https://api.bing.microsoft.com/v7.0/search',
      google_max_results: 10, // 默认值
      google_api_key: '',
      google_cse_id: '',
      brave_max_results: 10, // 默认值
      brave_api_key: '',
      exa_max_results:10,
      exa_api_key: '',
      serper_max_results:10,
      serper_api_key: '',
      bochaai_max_results:10,
      bochaai_api_key: '',
      firecrawl_url: 'https://api.firecrawl.dev/v2', // 官方API或自部署地址
      firecrawl_api_key: '',
      firecrawl_mode: 'scrape', 
    },

    codeSettings: {
      enabled: false,
      engine: 'e2b',
      e2b_api_key: '',
      sandbox_url: 'http://127.0.0.1:8080',
    },

    CLISettings: {
      enabled: false,
      visibilityScope: 'workspace',
      engine: 'local',
      cc_path: '',
      shortcut: true,
      max_iterations: 100,
      mode_change: false
    },

    visionControlSettings:{
      enabled: false,
      mouse:true,
      keyboard:true,
      desktopVision: true,
      onlyNewScreen: true,
      isEnableGrid: true, // 是否启用网格
      isFullScreen: true, // 是否全屏
      ScreenSize : [0,0,1280,720], // 非全屏时，截取x1 y1 x2 y2
    },

    ccSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
      permissionMode: 'default',
    },

    qcSettings: {
      enabled: false,
      selectedProvider: null,
      base_url:'',
      api_key:'',
      model:'',
      permissionMode: 'default',
    },

    dsSettings: {
      enabled: false,
      permissionMode: 'default',
    }
});
