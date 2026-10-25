// 批 3 F2：自 vue_methods.js 搬移的扩展桥接域（Object.assign 装配）。
Object.assign(vue_methods, {
    // 新增：发送当前消息列表到所有连接的客户端
    sendMessagesToExtension(force) {
      const now = Date.now();
      if (!force && now - (this._lastExtSendTime || 0) < 500) return; // 流式期间节流：最多每 500ms 序列化一次
      const wsOpen = this.ws && this.ws.readyState === WebSocket.OPEN;
      // S103: 通道断开且已有待发快照 → 直接跳过（重连补发旧快照即可，
      // 不必每分钟把全历史 stringify 两下）
      if (!wsOpen && this._pendingExtensionMessage) return;
      this._lastExtSendTime = now;
      // S103: toRaw 快照。JSON.stringify 走响应式代理 = 逐属性过 Proxy get，
      // 全历史含 displayBlocks 可达数 MB → 单次秒级长任务（LongFrame 主嫌疑）。
      // toRaw 拿原始对象图，序列化原生速度，数据形状不变。
      const rawMessages = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(this.messages) : this.messages;
      const payload = JSON.stringify({
        type: 'broadcast_messages',
        data: {
          messages: rawMessages,
          conversationId: this.conversationId
        }
      });
      if (wsOpen) {
        try {
          this.ws.send(payload);
        } catch (e) {
          console.error('Failed to send messages to extension:', e);
          // 发送失败也暂存，等重连后补发
          this._pendingExtensionMessage = payload;
        }
      } else {
        // WS 未连接，暂存消息，等重连后补发
        this._pendingExtensionMessage = payload;
      }
    },

    async syncSystemPromptToMessages(newPrompt) {
      // 情况 1: 新提示词为空
      if (!newPrompt) {
        if (this.messages.length > 0 && this.messages[0].role === 'system') {
          this.messages.splice(0, 1); // 删除系统消息
        }
        return;
      }
  
      // 情况 2: 已有系统消息
      if (this.messages[0]?.role === 'system') {
        // 更新系统消息内容
        this.messages[0].content = newPrompt;
        console.log('Updated system message:', this.messages[0]);
        return;
      }
  
      // 情况 3: 没有系统消息
      this.messages.unshift({
        id: Date.now() + Math.random(), // 添加唯一ID
        role: 'system',
        content: newPrompt
      });
      console.log('Added system message:', this.messages[0]);
      await this.autoSaveSettings();
    },

    // 敏感路径检测函数
    isDangerousPath(path) {
        if (!path) return false;

        // 1. 规范化路径：统一斜杠，转小写，去掉末尾斜杠
        let normalized = path.trim().replace(/\\/g, '/').toLowerCase();
        if (normalized.length > 1 && normalized.endsWith('/')) {
            normalized = normalized.slice(0, -1);
        }

        // --- A. 绝对禁止的磁盘/系统根目录 ---
        // 匹配: "c:", "d:", "/"
        const winRootRegex = /^[a-z]:$/;
        if (winRootRegex.test(normalized) || normalized === '/' || normalized === '') {
            return true; 
        }

        // --- B. 仅禁止目录本身，但允许其子目录 (User Containers) ---
        // 比如禁止选择 "C:/Users"，但允许 "C:/Users/YourName/Documents"
        const userContainers = [
            'c:/users',
            '/users',
            '/home'
        ];
        if (userContainers.includes(normalized)) {
            return true;
        }

        // --- C. 禁止该目录及其所有子目录 (System Core) ---
        // 这些地方无论如何都不该让本地引擎去跑
        const strictSystemPaths = [
            'c:/windows',
            'c:/program files',
            'c:/program files (x86)',
            'c:/boot',
            'c:/recovery',
            'c:/system volume information',
            '/bin', '/boot', '/dev', '/etc', '/lib', '/lib64', '/proc', 
            '/root', '/run', '/sbin', '/sys', '/usr', '/var', '/opt',
            '/system', '/library', '/volumes'
        ];

        return strictSystemPaths.some(prefix => {
            // 只有在匹配系统核心目录或其子路径时才拦截
            return normalized === prefix || normalized.startsWith(prefix + '/');
        });
    }
});
