// R2-1 外观包：保存背景图弹窗的临时态（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。
Object.assign(vue_data, {
    saveBgDialogVisible: false,
    newBgName: '',
    isChatInputActive: false,
});
