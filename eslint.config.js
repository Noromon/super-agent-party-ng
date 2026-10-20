// M-2 静态检查（eslint flat config）：最小实用集 no-undef + no-unused-vars。
// 策略与 ruff 对称：CI 只对 git diff 涉及文件把关（存量 66k 行不阻塞历史），
// 基线豁免名单见本文件 legacyFiles（清除一个文件该类告警后从名单删除即重新收紧）。
"use strict";

const globals = require("globals");

const appGlobals = {
    Vue: "readonly",
    ElementPlus: "readonly",
    _VueOptions: "writable",
    chart: "writable",
    echarts: "readonly",
    marked: "readonly",
    DOMPurify: "readonly",
    Howl: "readonly",
    Howler: "readonly",
    html2canvas: "readonly",
    Chart: "readonly",
    dayjs: "readonly",
    screenfull: "readonly",
    Sortable: "readonly",
    vts: "writable",
    VRM: "writable",
    THREE: "readonly",
    GLTFLoader: "readonly",
    LicenseInfo: "readonly",
    DMGRest: "readonly",
    middleware: "readonly",
    loglevel: "readonly",
    WebsocketIP: "readonly",
    MD5: "readonly",
    ChartJS: "readonly",
    LocalForage: "readonly",
    showNotification: "readonly", // renderer.js 定义的全局通知函数
    // R1 专域排查确认的跨文件顶层真全局（script 加载顺序保证可见性；
    // R3 模块化时改 import 后逐项移出本表）：
    isElectron: "readonly",         // vue_data.js 顶层 const
    vue_data: "writable",           // vue_data.js 顶层 let
    vue_methods: "readonly",        // vue_methods.js 顶层 const
    backendURL: "readonly",         // vue_data.js 顶层 const
    translations: "readonly",       // locales.js 顶层 const
    md: "readonly",                 // vue_methods.js 顶层 const（markdown-it 实例）
    MAX_RENDERED_BLOCKS: "readonly",// renderer.js 顶层 const
    MAX_DISPLAY_LENGTH: "readonly", // renderer.js 顶层 const
    uuid: "readonly",               // libs/uuid.min.js
    hljs: "readonly",               // libs/highlight.min.js
    mermaid: "readonly",            // libs/mermaid.min.js
    morphdom: "readonly",           // libs/morphdom-umd.min.js
    ElementPlusIconsVue: "readonly",// libs/element-plus-icons.js
    QRCode: "readonly",             // libs/qrcode.min.js
    ExcelJS: "readonly",            // libs/exceljs.min.js
    vad: "readonly",                // libs/bundle.min.js（@ricky0123/vad-web）
    chrome: "readonly",             // Electron renderer 的 chrome.* API
};

module.exports = [
    {
        ignores: [
            "node_modules/**", "static/libs/**", "static/ext/**",
            "Git/**", "browsers/**", "tiktoken_cache/**", "release/**",
            "dist/**", "build/**", "vrm/**", "static/js/vrm.js",
        ],
    },
    {
        files: ["static/js/**/*.js", "main.js", "start.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script",
            globals: { ...globals.browser, ...globals.es2021, ...appGlobals },
        },
        linterOptions: { reportUnusedDisableDirectives: "off" },
        rules: {
            "no-undef": "error",
            "no-unused-vars": ["warn", { args: "none", varsIgnorePattern: "^_" }],
        },
    },
    {
        // Electron / preload 文件运行在 Node 环境
        files: ["main.js", "start.js", "static/js/webview-preload.js",
                "static/js/preload.js", "static/js/shotPreload.js"],
        languageOptions: {
            // CommonJS 顶层允许 return（main.js 存在该写法）
            sourceType: "commonjs",
            globals: { ...globals.node, ...appGlobals },
        },
    },
];
