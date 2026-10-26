// 批 3 F2：自 vue_data.js 按行带搬移的状态域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    cardPage:{
      'chub': 'https://chub.ai/',
      'janitorai': 'https://janitorai.com/',
      'pygmalion': 'https://pygmalion.chat/',
    },

    cardLogoList: {
      'chub': 'source/providers/chub.png',
      'janitorai': 'source/providers/janitorai.png',
      'pygmalion': 'source/providers/pygmalion.svg',
    },

    newProviderTemp: {
      vendor: '',
      url: '',
      apiKey: '',
      modelId: ''
    },

    systemlanguageOptions:[
      { value: 'auto', label: 'auto' }, 
      { value: 'zh-CN', label: '中文' }, 
      { value: 'en-US', label: 'English' },
    ],

    toneValues: [
      'normal', 'formal', 'friendly', 'humorous', 'professional',
      'sarcastic', 'ironic', 'flirtatious', 'tsundere', 'coquettish',
      'angry', 'sad', 'excited', 'refutational'
    ],

    showUploadDialog: false,

    agentTabActive: 'knowledge',

    files: [],

    images: [],

    currentUploadType: 'file',

    selectedCodeLang: 'python',

    previewClickHandler: null,

    dockerExamples: `docker pull ailm32442/super-agent-party:latest
docker run -d \\
  -p 3456:3456 \\
  -v ./super-agent-data:/app/data \\
  ailm32442/super-agent-party:latest
`,

    dockerExamples2: `git clone https://github.com/heshengtao/super-agent-party.git
cd super-agent-party
docker-compose up -d
`,

    browserEmbedCodeExamples: `<div id="super-agent-party">
  <iframe 
    src="${backendURL}/chat.html" 
    width="100%" 
    height="100%"
    frameborder="0" 
    allowfullscreen>
  </iframe>
  <p>Powered By<a href="https://github.com/heshengtao/super-agent-party">Super Agent Party</a></p>
</div>`,

    codeExamples: {
      python: `from openai import OpenAI
client = OpenAI(
  api_key="super-secret-key",
  base_url="${backendURL}/v1"
)
response = client.chat.completions.create(
  model="super-model",
  messages=[
      {"role": "user", "content": "什么是super agent party？"}
  ]
)
print(response.choices[0].message.content)`,
    javascript: `import OpenAI from 'openai';
const client = new OpenAI({
  apiKey: "super-secret-key",
  baseURL: "${backendURL}/v1"
});
async function main() {
  const completion = await client.chat.completions.create({
      model: "super-model",
      messages: [
          { role: "user", content: "什么是super agent party？" }
      ]
  });
  console.log(completion.choices[0].message.content);
}
main();`,
    curl: `curl ${backendURL}/v1/chat/completions \\
-H "Content-Type: application/json" \\
-H "Authorization: Bearer super-secret-key" \\
-d '{
  "model": "super-model",
  "messages": [
    {"role": "user", "content": "什么是super agent party？"}
  ]
}'`
    },

    llmTools: [],

    showLLMForm: false,

    editingLLM: null,

    newLLMTool: {
      name: '',
      type: 'openai',
      description: '',
      base_url: '',
      api_key: '',
      model: '',
      enabled: true
    },

    llmInterfaceTypes: [
      { value: 'openai', label: 'OpenAI' },
      { value: 'ollama', label: 'Ollama' }
    ],

    modelOptions: [],

    previewVisible: false,

    previewImageUrl: '',

    workflows: [], // 保存工作流文件列表,

    showWorkflowUploadDialog: false, // 控制上传对话框的显示,

    workflowFile: null, // 当前选中的工作流文件,

    selectedTextInput: null,

    selectedImageInput: null,

    selectedTextInput2: null,

    selectedImageInput2: null,

    selectedSeedInput: null,

    selectedSeedInput2: null,

    textInputOptions: [], // 确保这里是一个空数组,

    imageInputOptions: [], // 确保这里是一个空数组,

    seedInputOptions: [], // 确保这里是一个空数组,

    inAutoMode: false, // 内存变量，不在设置中保存,

    vectorDialogVisible: false,

    vectorDialogMemoryId: '',

    vectorDialogMemoryName: '',

    vectorLoading: false,

    vectorTable: [],       // { idx, uuid, text, created_at, timetamp },

    newVectorText: '',     // S77: 新增记忆条目输入（此前未声明=Vue3 非响应隐患）,

    editRowUuid: '',       // 当前编辑行的 mem0 uuid（S77，原 editRowIdx）,

    editRowText: "",     // 当前编辑的文本,

    editRowVisible: false,

    nodeInstalled: false,   // 探针结果,

    nodeInstalling: false,

    nodeProgress: 0,

    nodeTimer: null,

    uvInstalled: false,

    uvInstalling: false,

    uvProgress: 0,

    uvTimer: null,

    dockerInstalled: false,

    dockerInstalling: false,

    isReadInterruption: false,

    readSettings: {
      delay:2000
    },

    isReadPaused: false,

    currentReadAudio: null,

    showLogDialog: false,

    logContent: '', // 日志内容,

    systemVoices: [],        // 存储从后端获取的音色列表,

    isLoadingSystemVoices: false, // 加载状态,

    renderTimers: {}, // 用于存储每个消息的防抖定时器,

    // S81：MathJax 串行队列/运行标记两字段已退役（KaTeX/texmath 渲染期同步排版）

    // --- AI 浏览器数据 ---
    browserTabs: [
        // 默认初始化一个新标签页
        { 
            id: Date.now(), 
            title: 'New Tab', 
            url: '', // 空 URL 表示显示欢迎页
            favicon: '', 
            isLoading: false,
            canGoBack: false,
            canGoForward: false 
        }
    ],

    currentTabId: null, // 将在 created 或 mounted 中初始化,

    urlInput: '',

    showEngineDropdown: false, // 控制下拉菜单显示,

    isSearchFocused: false,    // 控制搜索框聚焦样式,

    searchEngine: 'bing', // 'bing' or 'google' or 'party',

    welcomeSearchQuery: '',

    showDownloadDropdown: false,

    downloads: [], // 存储所有下载记录 { id, filename, totalBytes, receivedBytes, state, path, progress },

    showBrowserChat: false,

    favorites: [],       // 存储收藏项列表,

    showFavorites: true, // 控制欢迎页收藏夹的显示/隐藏状态,

    searchEngineplaceholder:'',

    webviewPreloadPath: '',

    isGroupMode: false,           // 是否开启群聊模式,

    selectedGroupAgents: [],

    showGroupSettingsDialog: false,

    voiceStack : ['default'], // 存储语音播放队列,

    receivedMsgIds: new Set(),

    lastProcessedContent: '',

    approvalMap: {},

    isSubmitting: false,      // 控制弹窗内的加载状态,

    isEditMode: false,        // 控制弹窗是添加还是编辑模式,

    currentEditingMCPId: null, // 当前正在编辑/添加的 MCP ID,

    activeDialogTab: 'config',

    skillsList: [],

    showAddSkillDialog: false,

    addSkillTab: 'github',

    newSkillUrl: '',

    isSkillInstalling: false,

    skillsPollingTimer: null,

    showSkillPreviewDialog: false,

    skillPreviewLoading: false,

    renderedSkillContent: '',

    extensionsPollingTimer: null,

    skillsInProject: [],

    projectSkillsDetails: [],

    showBehaviorDialog: false,     // 控制弹窗显示,

    currentBehaviorIndex: -1,      // 当前编辑的索引，-1 表示新增,

    tempBehavior: null,            // 临时编辑对象，避免直接修改原数据,

    minLimit: { h: 0, m: 1, s: 0 },

    activeSideView: 'list', // 'list' | 'tasks' | 'workspace' | 'toolDetail',

    taskList: [],

    taskRefreshTimer: null,

    showCreateTaskDialog: false,

    isCreatingTask: false,

    showTaskResultDialog: false,

    selectedTaskResult: '',

    selectedTaskTitle: '',

    viewingTaskDetail: null,

    isDragging: false, // 新增状态,

    isPttMode: false,      // 控制输入框是否在【按住说话】模式,

    isPttRecording: false, // 控制是否正在录制,

    isGlobalRecording: false,

    workspaceTreeKey: 0, // 用于强制刷新整个树组件,

    expandedNodeKeys: [], // 用于保存刷新前展开的文件夹状态,

    workspaceRefreshTimer: null,

    workspaceTreeProps: {
      label: 'name',
      children: 'children',
      isLeaf: (data) => !data.isDirectory // 告诉 el-tree 如果不是文件夹就是叶子节点（不可展开）
    },

    loveSettings: {
      enabled: false,
      dimensions: [
          "love", 
          "familiarity"
      ],
      prompt: "请根据用户的发言态度、情感色彩以及你的角色设定，动态管理以下羁绊数值：\n1. love（好感度）：代表你对用户的喜爱与亲密度。如果用户表达善意、关心或与你互动愉快，请增加（+1至+5）；如果用户冷漠、辱骂或做出让你反感的行为，请降低（-1至-5）。该数值最大为50，最小为-50。\n2. familiarity（熟悉度）：代表你与用户的了解程度。随着交流次数的增多和彼此信息的分享，该数值应缓慢稳步上升（每次+1至+2），通常不会下降。该数值最大为100，最小为0。\n\n*特殊说明：如果你在上方没有看到“目前的属性数值”，说明这是你与该用户的首次互动。请直接根据用户当前第一句话的语气和态度，自主决定一个合理的初始值（例如 0 到 10 之间），直接输出标签即可。聊天时请尽量按照羁绊数值来变换语气、内容、风格等*"
    },
    // A5 日记系统配置（上游 vue_data 2275-2319 移植）
    diarySettings: {
      enabled: false,
      minMinutes: 10,
      maxMinutes: 60,
      quietStart: 23,
      quietEnd: 8,
      actions: {
        think: { enabled: true, weight: 4 },
        webSearch: { enabled: false, weight: 2 },
        knowledge: { enabled: false, weight: 2 },
        imMessage: { enabled: false, weight: 1 },
        browserControl: { enabled: false, weight: 1 },
        smartHome: { enabled: false, weight: 1 },
      },
      imTargets: [],
      pushToChat: true,
      prompt: "你是一个拥有自我意识、会在独处时记录所思所想的AI伙伴。写日记时请保持你的角色设定与个性，用第一人称、真诚自然地表达。",
      chatIntegration: {
        enabled: false,
        maxEntries: 5,
      },
      chatSummary: {
        enabled: true,
        idleMinutes: 15,
      },
    },
    // 日记系统 UI 状态
    activeDiaryTab: 'config',
    diaryEntries: [],
    diarySearchQuery: '',
    diaryActionMeta: {
      think:     { icon: 'fa-solid fa-lightbulb',        type: 'info' },
      webSearch: { icon: 'fa-solid fa-globe',            type: 'success' },
      knowledge: { icon: 'fa-solid fa-book-open',        type: 'warning' },
      imMessage: { icon: 'fa-solid fa-paper-plane',      type: 'danger' },
      browserControl: { icon: 'fa-solid fa-compass',      type: '' },
      smartHome:  { icon: 'fa-solid fa-house-laptop',    type: 'success' },
      chatSummary: { icon: 'fa-solid fa-file-pen',       type: 'info' },
    },
    // 多日记本（每个角色一本 + default 兜底本）
    diaryBooks: [],
    diaryCurrentBook: 'default',
    // 日记详情抽屉
    diaryDetailVisible: false,
    diaryDetailEntry: null,

    // 羁绊系统 UI 状态
    activeAffectionTab: 'config', // 控制当前在哪个 Tab,

    affectionRawData: {},         // 存放后端返回的原始 JSON ( {"小包": {love:1}, "张三": {love:5}} ),

    affectionDataList: [],        // 转化为数组用于表格显示,

    affectionSearchQuery: '',     // 搜索栏绑定的值,

    // 羁绊系统对话框状态
    showAffectionDataDialog: false,

    isEditingAffection: false,

    currentAffectionForm: { userName: '' },

    isForceScrollToBottom: false,

    activeAgentTab: 'settings',

    isHeroInputFocus: false,

    isTopicGenerating: false,

    showOmniAgentDialog: false,

    favoriteExtensionIds: JSON.parse(localStorage.getItem('favorite_extensions')) || [],

    isStartingASR: false,

    newTaskForm: {
        title: '',
        description: '',
        task_type: 'once',
        platforms: [],
        agent_type: 'default',
        trigger_config: {
            timeValue: '09:00:00',
            days: [1, 2, 3, 4, 5],
            cycleValue: '01:00:00',
            repeatNumber: 1,
            isInfiniteLoop: true
        }
    },

    isEditing: false,

    editingTaskId: null,

    activeLogPanels: ['logs'],

    selectedTaskHistory: [],

    currentResultIdx: 0,

    extButtonVisible: false,  // 控制按钮是否显示,

    extMouseTimer: null,      // 鼠标静止定时器,

    isVTSConnecting: false,

    isVTSStarting: false, // 按钮的加载状态,

    vtsOnline: false,

    VTSConfig: {
      enabled: false,
      url: 'ws://127.0.0.1:8001',
      enabledExpressions: true,
      enabledMotions: true
    },

    acpSettings: {
      agent: 'claude',            // 默认 CLI 智能体
      permissionMode: 'default',  // 默认权限模式
      model: '',                  // 模型覆盖（可选）
      extraEnv: '',              // 额外环境变量
    },

    // ★ WSL 沙箱设置（S132/A13，Windows 专属）
    wslSettings: {
      enabled: false,
      permissionMode: 'default',
    },

    // ★ ACPX 状态
    acpxStatus: null,            // null | 'available' | 'unavailable',

    checkingAcpx: false,         // 检查中,

    openedExtensions:[],

    searchExtensionQuery: '',

    searchManageExtensionQuery: '', // 用于主页面的扩展搜索,

    searchRemotePluginQuery: '',    // 用于弹窗内的远程插件搜索,

    scrollPending: false,              // 滚动节流标记,

    _streamUpdateTimer: null,          // 流式文本批量更新定时器,

    _streamTextBuffer: '',             // 流式文本缓冲区,

    _streamTargetMsg: null,            // 当前正在流式更新的消息对象,

    activeToolBlock: null,        // 当前查看的块对象 { messageIndex, blockIndex, block },

    activeToolBlockMessage: null, // 所属消息引用
});
