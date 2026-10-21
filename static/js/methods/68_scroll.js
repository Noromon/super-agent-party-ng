// 批 3 F2：自 vue_methods.js 搬移的 methods/68_scroll.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 滚动到最新消息
    /* 判断元素是否接近底部 */
    isElemNearBottom(el, threshold = 300) {
      if (!el) return true;               // 元素不存在就默认“需要滚底”
      return el.scrollHeight - el.scrollTop - el.clientHeight <= threshold;
    },

    scrollToBottom() {
      this.$nextTick(() => {
        const container = this.$refs.messagesContainer;
        if (container) {
          // 1. 滚动外层主容器
          if (this.isElemNearBottom(container) || this.isForceScrollToBottom) {
            container.scrollTop = container.scrollHeight;
          }
          
          // 2. 滚动内层带有滚动条的区块 (工具代码块、思考过程块)
          const innerBlocks = container.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              // 同样复用 isElemNearBottom 判断，如果用户没故意往上翻，就自动贴底
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
      
      this.scrollPanelToBottom();
      // 兼容你原有的写法
      if (typeof isElectron !== 'undefined' ? isElectron : this.isElectron) {
        this.browserPanelToBottom();
      }
    },

    /* 侧边栏滚动 */
    scrollPanelToBottom() {
      this.$nextTick(() => {
        const panel = this.$refs.messagesPanel;
        if (panel) {
          // 1. 滚动侧边栏外层容器
          if (this.isElemNearBottom(panel) || this.isForceScrollToBottom) {
            panel.scrollTop = panel.scrollHeight;
          }

          // 2. 滚动侧边栏内层区块
          const innerBlocks = panel.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
    },

    /* 独立浏览器面板滚动 */
    browserPanelToBottom() {
      this.$nextTick(() => {
        const panel = this.$refs.browserMessagesContainer;
        if (panel) {
          // 1. 滚动独立面板外层容器
          if (this.isElemNearBottom(panel) || this.isForceScrollToBottom) {
            panel.scrollTop = panel.scrollHeight;
          }

          // 2. 滚动独立面板内层区块
          const innerBlocks = panel.querySelectorAll('.sp-code, .type-reasoning .sp-content');
          innerBlocks.forEach(block => {
            if (block.scrollHeight > block.clientHeight) {
              if (this.isElemNearBottom(block) || this.isForceScrollToBottom) {
                block.scrollTop = block.scrollHeight;
              }
            }
          });
        }
      });
    }
});
