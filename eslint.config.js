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
    {
        // legacy：跨文件顶层 var（isElectron 等浏览器实际可见但 eslint 静态不可见）
        // 与可疑未定义引用（url/uuid/fileName/data...）暂整体豁免；
        // 后续专域批次逐个排查修复后从本名单移除即重新收紧（对齐 ruff per-file-ignores 策略）
        files: ["static/js/vue_data.js", "static/js/vue_methods.js", "static/js/renderer.js"],
        rules: { "no-undef": "off" },
    },
];
