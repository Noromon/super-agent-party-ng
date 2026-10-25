// 批 3 F2：自 vue_methods.js 搬移的 methods/90_panel_resize.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  startChatHistoryResize(e) {
    if (this.isMobile || !this.chatHistoryPanelOpen) return;

    const container = this.$refs.chatWrapperRef;
    const panel = this.$refs.chatHistoryPanelRef;
    if (!container || !panel) return;

    this.isHistoryPanelResizing = true;
    const containerRect = container.getBoundingClientRect();
    const minWidth = 220;
    const maxWidth = Math.max(minWidth, Math.min(520, containerRect.width - 320));

    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (event) => {
      if (!this.isHistoryPanelResizing) return;
      const nextWidth = Math.max(minWidth, Math.min(event.clientX - containerRect.left, maxWidth));
      this.chatHistoryPanelWidth = nextWidth;
    };

    const handleMouseUp = () => {
      this.isHistoryPanelResizing = false;
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  },

  // 开始拖拽调整大小
  startResize(e) {
    if (!this.chatAreaOpen || !this.sidePanelOpen) return;
    
    const container = this.$refs.chatWrapperRef;
    // 获取当前历史侧边栏是否可见并获取宽度
    const historySidebar = container.querySelector('.chat-history-sidebar');
    const isSidebarVisible = this.showHistorySidebar && !this.isMobile;
    const sidebarWidth = isSidebarVisible ? historySidebar.offsetWidth : 0;

    this.isResizing = true;
    const containerRect = container.getBoundingClientRect();
    const availableWidth = containerRect.width - sidebarWidth; // 减去历史栏宽度
    
    container.classList.add('resizing');

    const handleMouseMove = (e) => {
      if (!this.isResizing) return;
      
      // 这里的 mouseX 必须相对于聊天区的左边缘
      const mouseXInChat = e.clientX - (containerRect.left + sidebarWidth);
      const clampedMouseX = Math.max(0, Math.min(mouseXInChat, availableWidth));
      
      const leftWidth = clampedMouseX;
      const rightWidth = availableWidth - clampedMouseX - 10; // 10 是分割条宽
      
      const leftPercent = (leftWidth / availableWidth) * 100;
      const rightPercent = (rightWidth / availableWidth) * 100;
      
      if (leftPercent < this.minPanelWidth) {
        this.collapseChatArea();
        handleMouseUp();
        return;
      }
      
      if (rightPercent < this.minPanelWidth) {
        this.collapseSidePanel();
        handleMouseUp();
        return;
      }
      
      this.updatePanelWidthsWithPixels(leftWidth, rightWidth);
    };

    const handleMouseUp = () => {
      this.isResizing = false;
      container.classList.remove('resizing');
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
      document.body.style.cursor = '';
      this.recalculatePercentages(availableWidth);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  },

  handleHistoryToggle() {
      this.showHistorySidebar = !this.showHistorySidebar;
      console.log('showHistorySidebar:',this.showHistorySidebar)
      // 强制触发一次 recalculate，让右侧聊天区重新适应剩余宽度
      this.$nextTick(() => {
          this.handleResize(); 
      });
      this.autoSaveSettings();
  },

  // 使用像素宽度更新面板
  updatePanelWidthsWithPixels(leftWidth, rightWidth) {
    this.$nextTick(() => {
      const chatArea = this.$refs.chatAreaRef;
      const sidePanel = this.$refs.sidePanelRef;
      
      if (!chatArea || !sidePanel) {
        return;
      }
      
      if (this.chatAreaOpen && this.sidePanelOpen) {
        chatArea.style.width = `${leftWidth}px`;
        sidePanel.style.width = `${rightWidth}px`;
      }
    });
  },

  // 重新计算百分比（用于保存状态和响应式）
  recalculatePercentages(providedAvailableWidth) {
    const container = this.$refs.chatWrapperRef;
    const historySidebar = container?.querySelector('.chat-history-sidebar');
    const sidebarWidth = (historySidebar && !this.isMobile) ? historySidebar.offsetWidth : 0;
    
    // 如果没有传入宽度，则实时计算
    const availableWidth = providedAvailableWidth || (container.offsetWidth - sidebarWidth);
    
    const chatArea = this.$refs.chatAreaRef;
    const sidePanel = this.$refs.sidePanelRef;
    
    if (chatArea && sidePanel && this.chatAreaOpen && this.sidePanelOpen) {
      const chatAreaWidthPx = chatArea.offsetWidth;
      const sidePanelWidthPx = sidePanel.offsetWidth;
      
      // 基于可用宽度计算比例
      this.chatAreaWidth = (chatAreaWidthPx / availableWidth) * 100;
      this.sidePanelWidth = (sidePanelWidthPx / availableWidth) * 100;
    }
  },

  // 处理分割条点击
  handleResizerClick(e) {
    if (e.target.closest('.expand-chat-btn') || e.target.closest('.expand-side-btn')) {
      return;
    }
    
    // 双击重置为50:50
    if (e.detail === 2) {
      this.resetPanelSizes();
    }
  },

  // 收起对话区域
// 收起左侧对话区域（让右侧面板向左填充）
collapseChatArea() {
  const sidePanel = this.$refs.sidePanelRef;
  const chatArea = this.$refs.chatAreaRef;

  // 1. 核心修复：在隐藏左侧前，先清除右侧的像素限制
  if (sidePanel) sidePanel.style.width = '';
  if (chatArea) chatArea.style.width = '';

  // 2. 更新状态
  this.chatAreaOpen = false;
  this.sidePanelOpen = true; 
  this.sidePanelWidth = 100;
  this.chatAreaWidth = 0;

  // 3. 应用百分比布局
  this.updatePanelWidths();
},

// 收起右侧侧边栏（让左侧对话区向右填充）
collapseSidePanel() {
  const chatArea = this.$refs.chatAreaRef;
  const sidePanel = this.$refs.sidePanelRef;

  if (chatArea) chatArea.style.width = '';
  if (sidePanel) sidePanel.style.width = '';

  if (!this.isResizing && this.sidePanelWidth > 0 && this.sidePanelWidth < 100) {
    this.savedSidePanelWidth = this.sidePanelWidth;
  }
  if (this.isResizing) {
    this.savedSidePanelWidth = null;
  }

  this.sidePanelOpen = false;
  this.chatAreaOpen = true;
  this.chatAreaWidth = 100;
  this.sidePanelWidth = 0;

  this.updatePanelWidths();
},

// 顶栏按钮：右侧面板开合切换（R2 ④）
toggleSidePanel() {
  if (this.sidePanelOpen) {
    this.collapseSidePanel();
  } else {
    this.expandSidePanel();
  }
},

  // 展开对话区域
  expandChatArea() {
    this.chatAreaOpen = true;
    this.chatAreaWidth = 50;
    this.sidePanelWidth = 50;
    this.updatePanelWidths();
  },

  // 展开侧边栏
  expandSidePanel() {
    this.sidePanelOpen = true;
    const saved = this.savedSidePanelWidth;
    if (saved && saved > 0 && saved < 100) {
      this.sidePanelWidth = saved;
      this.chatAreaWidth = 100 - saved;
    } else {
      this.chatAreaWidth = 50;
      this.sidePanelWidth = 50;
    }
    this.updatePanelWidths();
  },

  // 重置面板大小
  resetPanelSizes() {
    this.chatAreaWidth = 50;
    this.sidePanelWidth = 50;
    this.savedSidePanelWidth = null;
    this.chatAreaOpen = true;
    this.sidePanelOpen = true;
    this.updatePanelWidths();
  },

  // 更新面板宽度样式
  updatePanelWidths() {
    this.$nextTick(() => {
      const chatArea = this.$refs.chatAreaRef;
      const sidePanel = this.$refs.sidePanelRef;
      
      if (!chatArea || !sidePanel) return;
      
      // ✨ 清除之前可能遗留的 px 宽度
      chatArea.style.width = '';
      sidePanel.style.width = '';
      
      if (this.chatAreaOpen && this.sidePanelOpen) {
        chatArea.style.width = `${this.chatAreaWidth}%`;
        sidePanel.style.width = `${this.sidePanelWidth}%`;
      } else if (this.chatAreaOpen) {
        chatArea.style.width = '100%';
      } else if (this.sidePanelOpen) {
        sidePanel.style.width = '100%';
      }
      
      // 🔧 关键修复：强制浏览器重排（读取布局属性）
      sidePanel.offsetWidth;   // 或者 chatArea.offsetWidth
    });
  },

  // 处理窗口大小变化
  handleResize() {
    if (this.chatAreaOpen && this.sidePanelOpen) {
      this.updatePanelWidths();
    }
  }
});
