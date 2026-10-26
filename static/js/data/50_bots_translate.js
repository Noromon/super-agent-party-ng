// 批 3 F2：自 vue_data.js 按行带搬移的状态域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    deployTiles: [
      { id: 'table_pet', title: 'tablePet', icon: "fa-solid fa-user-ninja"},
      { id: 'THA_pet', title: 'THAPet', icon: "fa-solid fa-hat-wizard"},
      { id: 'Soulx_pet', title: 'SoulXFlashHead', icon: "fa-solid fa-face-smile"},
      { id: 'vts_config', title: 'vtsbot', icon: "fa-solid fa-child"},
      { id: 'live_stream', title: 'live_stream_bot', icon: "fa-solid fa-video"},
      { id: 'im_bot', title: 'imBot', icon: 'fa-solid fa-comment' },
      { id: 'read_bot', title: 'readBot', icon: "fa-solid fa-book-open-reader"}, 
      { id: 'translate_bot', title: 'translateBot', icon: "fa-solid fa-language"}, 
    ],

    activeImBotTab: 'qq',

    sourceText: '',

    translatedText: '',

    isTranslating: false,

    targetLangSelected: 'system',   //“系统默认”,

    readConfig: {
      longText: "",
      longTextList: [],
    },

    longTextListIndex: 0,

    selectedFile: null,

    isReadStarting: false,

    isReadStopping: false,

    isReadRunning: false,

    readState: {
      ttsChunks: [],
      audioChunks: [],
      chunks_voice: [], 
      ttsQueue: new Set(),
      currentChunk: 0,
      isPlaying: false
    },

    segmentEditBuffer: '',  // 单个段落临时编辑区,

    segmentVoiceEditBuffer: [],  // 单个段落临时编辑区,

    activeSegmentIdx: -1,    // 当前手动编辑的段落索引,

    _curAudio: null,        // 当前 Audio 实例,

    isReadingOnetext: false,

    liveConfig: {
      filterMode: 'danmaku_only',
      danmakuQueueLimit: 5,
      wakeWord: '',
      bilibili_enabled: false,
      bilibili_type: 'open_live',
      bilibili_room_id: '',
      bilibili_sessdata: '',
      bilibili_ACCESS_KEY_ID: '',
      bilibili_ACCESS_KEY_SECRET: '',
      bilibili_APP_ID: '',
      bilibili_ROOM_OWNER_AUTH_CODE: '',
      youtube_enabled: false,
      youtube_vedio_id:  "",
      youtube_api_key:  "",
      twitch_enabled: false,
      twitch_channel: "",
      twitch_access_token: "",
      danmakuVoice:"default",
      enableDanmakuTTS: false,
    },

    WXBotConfig: {
      WXAgent:'super-model',
      memoryLimit: 30,
      separators: ["。", "\n", "？", "！"],
      reasoningVisible: false,
      quickRestart: true,
      nickNameList: [],
      wakeWord: '小派',
    },

    isSlackBotRunning: false,

    isSlackStarting: false,

    isSlackStopping: false,

    isSlackReloading: false,

    // Slack 配置对象
    slackBotConfig: {
      auto_connect: false,
      bot_token: '',      // Slack 的 xoxb token
      app_token: '',      // Slack 的 xapp token (Socket Mode)
      llm_model: 'super-model',
      memory_limit: 30,
      separators: ['。', '\n', '？', '！'],
      reasoning_visible: true,
      quick_restart: true,
      enable_tts: false,
      wakeWord: '',
      behaviorTargetChatIds: [],
    },

    danmu: [], // 弹幕列表,

    bilibiliWs: null, // WebSocket连接,

    danmuProcessTimer: null, // 弹幕处理定时器,

    isProcessingDanmu: false, // 是否正在处理弹幕,

    shouldReconnectWs :false,

    isLiveRunning: false,

    isLiveStarting: false,

    isLiveStopping: false,

    isLiveReloading: false,

    isWXStarting: false,

    isWXStopping: false,

    isWXReloading: false,

    isWXBotRunning: false,

    stickerPacks: [],

    showStickerDialog: false,

    newStickerPack: {
      name: '',
      stickers: [],
      tags: []
    },

    dialogVisible: false,

    imageUrl: '',

    uploadedStickers: [], // 格式: { uid: string, url: string, tags: string[] },

    isQQBotRunning: false, // QQ机器人状态,

    isStarting: false,      // 启动中状态,

    isStopping: false,      // 停止中状态,

    isReloading: false,     // 重载中状态,

    activeMemoryTab: 'config',

    activeBehaviorTab: 'config',

    activeMemoryTabName: 'autoUpdateSetting',

    activeMCPTab: 'config',

    quickCreatePrompt: '',

    isGenerating: false, // 是否正在生成,

    quickCreateSystemPrompt: '',

    isSystemPromptGenerating: false, // 是否正在生成,

    isQuickGenerating: false, // 是否正在生成,

    memories: [],

    newMemory: {
      id: null,
      name: '',
      infer: false,
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
    },

    firstMes: '',

    alternateGreetings: [],

    showAddMemoryDialog: false,

    showMemoryDialog: false,

    memorySettings: {
      selectedMemory: null,
      is_memory: false,
      memoryLimit: 10,
      userName:'user',
      genericSystemPrompt: '{{char}}必须使用{{user}}使用的语言与之交流，例如：当{{user}}使用中文时，你也必须尽可能地使用中文！当{{user}}使用英文时，你也必须尽可能地使用英文！包括交代旁白等文字也是同理！',
    },

    llmGuardSettings: {
      enabled: true,
      debounceSeconds: 20,
    },

    textFiles: [],

    imageFiles: [],

    videoFiles: [],

    selectedFiles: [],      // 存 unique_filename,

    selectedImages: [],

    allImagesChecked: false,

    indeterminateImages: false,

    selectedVideos: [],

    allVideosChecked: false,

    indeterminateVideos: false,

    subMenu: '', // 新增子菜单状态,

    isWorldviewSettingsExpanded: true,

    isRandomSettingsExpanded: true,

    isBasicCharacterExpanded: true,

    text2imgSettings: {
      enabled: false,
      engine: 'pollinations',
      pollinations_model: 'flux',
      pollinations_width: 512,
      pollinations_height: 512,
      selectedProvider: null,
      vendor: 'OpenAI',
      model: '',
      base_url: '',
      api_key: '',
      size: '1024x1024',
    },

    agentTiles: [
      { 
        id: 'agents',
        title: 'agentSnapshot',
        icon: 'fa-solid fa-robot'
      },
      {
        id: 'mcp',
        title: 'mcpServers', 
        icon: 'fa-solid fa-server'
      },
      {
        id: 'a2a',
        title: 'a2aServers',
        icon: 'fa-solid fa-plug'
      },
      {
        id: 'llmTool',
        title: 'llmTools',
        icon: 'fa-solid fa-network-wired'
      },
      {
        id: 'customHttpTool',
        title: 'customHttpTool',
        icon: 'fa-solid fa-wifi'
      },
      {
        id: 'comfyui',
        title: 'ComfyUI',
        icon: 'fa-solid fa-palette'
      },
    ],

    comfyuiServers: ['http://127.0.0.1:8188'], // 默认服务器,

    comfyuiAPIkey: '',

    workflowDescription: "",

    activeComfyUIUrl: '',

    isConnecting: false,

    customHttpTools: [],  // 用于存储自定义HTTP工具的数组,

    showCustomHttpToolForm: false,

    isInputExpanded: false,

    sidebarVisible: false,

    isMobile: false,

    isMinimalMode: false, // S135(minimal)

    isDynamicIsland: false, // S139(R6/灵动岛)

    searchKeyword: '',

    newCustomHttpTool: {
      enabled: true,
      name: '',
      description: '',
      url: '',
      method: 'GET',
      headers: '',
      body: ''
    },

    editingCustomHttpTool: false,

    searchQuery: '', // 搜索框的值,

    activeCategory: 'all', // 当前选中的分类：'all' | 'local' | 'cloud',

    // 定义属于本地/自建的供应商列表
    localVendors:[
      'llama.cpp','Ollama', 'Vllm', 'LMstudio','SGLang', 'xinference', 
      'LocalAI', 'ttswebui', 'Dify', 'newapi'
    ],

    vendorValues: [
      'custom','customAnthropic','OpenAIResponses', 'OpenAI','Anthropic', 'Gemini','Grok',
      'llama.cpp', 'Ollama','Vllm','LMstudio','SGLang','xinference','Dify','newapi',
      'LocalAI','ttswebui', 'Deepseek', 'Volcano','302.AI',
      'siliconflow', 'aliyun', 'ZhipuAI', 'moonshot', 'minimax', 
       'mistral', 'lingyi','baichuan', 'qianfan', 'hunyuan', 'stepfun', 'Github', 
      'openrouter','together', 'fireworks', '360', 'Nvidia',
      'jina', 'gitee', 'perplexity', 'infini',
      'modelscope', 'tencent', 'MiMo','longcat'
    ],

    vendorLogoList: {
      'custom': 'source/providers/logo.png',
      'customAnthropic': 'source/providers/logo.png',
      'OpenAI': 'source/providers/openai.jpeg',
      'SGLang': 'source/providers/sglang.svg',      
      'llama.cpp': 'source/providers/llamacpp.png', 
      'Ollama': 'source/providers/ollama.png',
      'Vllm': 'source/providers/vllm.png',
      'LMstudio': 'source/providers/lmstudio.png',
      'xinference': 'source/providers/xinference.png',
      'Dify': 'source/providers/dify.png',
      'newapi': 'source/providers/newapi.png',
      'LocalAI': 'source/providers/localai.png',
      'ttswebui': 'source/providers/ttswebui.jpeg',
      'Deepseek': 'source/providers/deepseek.png',
      'Volcano': 'source/providers/volcengine.png',
      'siliconflow': 'source/providers/silicon.png',
      '302.AI': 'source/providers/302.png',
      'aliyun': 'source/providers/bailian.png',
      'ZhipuAI': 'source/providers/zhipu.png',
      'moonshot': 'source/providers/moonshot.png',
      'minimax': 'source/providers/minimax.png',
      'MiMo': 'source/providers/mimo.png',
      'longcat': 'source/providers/longcat.png',
      'Gemini': 'source/providers/gemini.png',
      'Anthropic': 'source/providers/anthropic.png',
      'Grok': 'source/providers/grok.png',
      'mistral': 'source/providers/mistral.png',
      'lingyi': 'source/providers/zero-one.png',
      'baichuan': 'source/providers/baichuan.png',
      'qianfan': 'source/providers/baidu-cloud.svg',
      'hunyuan': 'source/providers/hunyuan.png',
      'stepfun': 'source/providers/step.png',
      'Github': 'source/providers/github.png',
      'openrouter': 'source/providers/openrouter.png',
      'together': 'source/providers/together.png',
      'fireworks': 'source/providers/fireworks.png',
      '360': 'source/providers/360.png',
      'Nvidia': 'source/providers/nvidia.png',
      'jina': 'source/providers/jina.png',
      'gitee': 'source/providers/gitee-ai.png',
      'perplexity': 'source/providers/perplexity.png',
      'infini': 'source/providers/infini.png',
      'modelscope': 'source/providers/modelscope.png',
      'tencent': 'source/providers/tencent-cloud-ti.png',
    },

    vendorAPIpage: {
      'OpenAI': 'https://platform.openai.com/api-keys',
      'Ollama': 'https://ollama.com/',
      'Vllm': 'https://docs.vllm.ai/en/latest/',      
      'LMstudio': 'https://lmstudio.ai/docs/app',
      'xinference': 'https://inference.readthedocs.io/zh-cn/latest/index.html',
      'SGLang': 'https://github.com/sgl-project/sglang',    
      'llama.cpp': 'https://github.com/ggerganov/llama.cpp', 
      'Dify': 'http://localhost/apps',
      'newapi': 'https://github.com/QuantumNous/new-api',
      'LocalAI': 'https://github.com/mudler/LocalAI',
      'ttswebui': 'https://github.com/rsxdalv/TTS-WebUI',
      'Deepseek': 'https://platform.deepseek.com/api_keys',
      'Volcano': 'https://www.volcengine.com/experience/ark',
      'siliconflow': 'https://cloud.siliconflow.cn/i/yGxrNlGb',
      '302.AI': 'https://share.302.ai/Mtahd4',
      'aliyun': 'https://bailian.console.aliyun.com/?tab=model#/api-key',
      'ZhipuAI': 'https://open.bigmodel.cn/usercenter/apikeys',
      'moonshot': 'https://platform.moonshot.cn/console/api-keys',
      'minimax': 'https://platform.minimaxi.com/user-center/basic-information/interface-key',
      'MiMo': 'https://platform.xiaomimimo.com/#/console/api-keys',
      'longcat': 'https://longcat.chat/platform/api_keys',
      'Gemini': 'https://aistudio.google.com/app/apikey',
      'Anthropic': 'https://console.anthropic.com/settings/keys',
      'Grok': 'https://console.x.ai/',
      'mistral': 'https://console.mistral.ai/api-keys/',
      'lingyi': 'https://platform.lingyiwanwu.com/apikeys',
      'baichuan': 'https://platform.baichuan-ai.com/console/apikey',
      'qianfan': 'https://console.bce.baidu.com/iam/#/iam/apikey/list',
      'hunyuan': 'https://console.cloud.tencent.com/hunyuan/api-key',
      'stepfun': 'https://platform.stepfun.com/interface-key',
      'Github': 'https://github.com/settings/tokens',
      'openrouter': 'https://openrouter.ai/settings/keys',
      'together': 'https://api.together.ai/settings/api-keys',
      'fireworks': 'https://fireworks.ai/account/api-keys',
      '360': 'https://ai.360.com/platform/keys',
      'Nvidia': 'https://build.nvidia.com/meta/llama-3_1-405b-instruct',
      'jina': 'https://jina.ai/api-dashboard',
      'gitee': 'https://ai.gitee.com/dashboard/settings/tokens',
      'perplexity': 'https://www.perplexity.ai/settings/api',
      'infini': 'https://cloud.infini-ai.com/iam/secret/key',
      'modelscope': 'https://modelscope.cn/my/myaccesstoken',
      'tencent': 'https://console.cloud.tencent.com/lkeap/api',
    },

    MCPvendorValues:['MCP','awesome','docker'],

    MCPpage:{
      'MCP': 'https://github.com/modelcontextprotocol/servers',
      'awesome': 'https://github.com/punkpeye/awesome-mcp-servers',
      'docker': 'https://hub.docker.com/mcp'
    },

    MCPvendorLogoList: {
      'MCP': 'source/providers/mcp.png',
      'awesome': 'source/providers/github.png',
      'docker': 'source/providers/docker.png'
    },

    promptValues:['awesome', 'aiTool','leaked'],

    promptPage:{
      'awesome': 'https://github.com/f/awesome-chatgpt-prompts',
      'aiTool': 'https://github.com/x1xhlol/system-prompts-and-models-of-ai-tools',
      'leaked': 'https://github.com/linexjlin/GPTs',
    },

    promptLogoList: {
      'awesome': 'source/providers/github.png',
      'aiTool': 'source/providers/github.png',
      'leaked': 'source/providers/github.png',
    },

    cardValues: ['chub', 'janitorai','pygmalion']
});
