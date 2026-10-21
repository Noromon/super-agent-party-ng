// 批 3 F2：vue_data 存量重复键（7 对）按原行序整体保留在本末位分片，
// last-wins 语义与原文件一致；加载顺序必须在所有 data 分片之后。
Object.assign(vue_data, {
    downloadProgress: 0,

    updateDownloaded: false,

    updateAvailable: false,

    updateInfo: null,

    editingAgent: null,

    editingAgent: false,

    // 更新相关
    updateAvailable: false,

    updateInfo: null,

    updateDownloaded: false,

    downloadProgress: 0,

    activeCLITab: 'config',

    dropdownTimer: null, // 新增定时器变量,

    dropdownTimer: null,

    activeCLITab: 'config', // 确保这个已存在
});
