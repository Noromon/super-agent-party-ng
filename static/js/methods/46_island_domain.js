// S139(R6)：灵动岛域方法（Object.assign 装配，加载顺序在宿主之后、renderer 之前）。
// 自上游 vue_methods toggleDynamicIsland 终态逐字移植。
Object.assign(vue_methods, {
  // ========== Dynamic Island Methods ==========
  async toggleDynamicIsland() {
    if (!this.isDynamicIsland) {
      if (isElectron && window.electronAPI.openIslandWindow) {
        window.electronAPI.openIslandWindow();
        this.isDynamicIsland = true;
        if (window.electronAPI.onIslandWindowClosed) {
          window.electronAPI.onIslandWindowClosed(() => {
            this.isDynamicIsland = false;
          });
        }
      }
    } else {
      if (isElectron && window.electronAPI.closeIslandWindow) {
        window.electronAPI.closeIslandWindow();
      }
      this.isDynamicIsland = false;
    }
    this.sidePanelOpen = false;
  }
});
