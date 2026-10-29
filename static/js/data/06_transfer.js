// S161：记忆/日记导入导出（跨角色卡移植）状态域（Object.assign 装配）。
Object.assign(vue_data, {
    transferImportOpen: false,

    transferPayload: null,

    transferSources: [],

    transferSelected: {},

    transferTarget: '',

    transferTargetStats: null,

    transferStrategy: 'merge',

    transferBusy: false,
});
