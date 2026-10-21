// 批 3 F2：自 vue_methods.js 搬移的 methods/72_live_danmu.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  // 启动直播监听
  async startLive() {
    if (!this.isLiveConfigValid || this.isLiveRunning || this.isLiveStarting) {
      return;
    }

    this.isLiveStarting = true;
    
    try {
      // 发送启动请求到FastAPI后端
      const response = await fetch('/api/live/start', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          config: this.liveConfig
        })
      });

      const result = await response.json();
      
      if (result.success) {
        this.isLiveRunning = true;
        this.shouldReconnectWs = true; // 启动时允许重连
        this.connectLiveWebSocket();
        this.startDanmuProcessor(); // 启动弹幕处理器
        showNotification(result.message || this.t('live_started_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_start_live'), 'error');
      }
    } catch (error) {
      console.error('启动直播监听失败:', error);
      showNotification(this.t('failed_to_start_live'), 'error');
    } finally {
      this.isLiveStarting = false;
    }
  },

  // 停止直播监听
  async stopLive() {
    if (!this.isLiveRunning || this.isLiveStopping) {
      return;
    }

    this.isLiveStopping = true;
    
    try {
      // 先设置状态，阻止WebSocket重连
      this.shouldReconnectWs = false;
      this.isLiveRunning = false;
      
      // 停止弹幕处理器
      this.stopDanmuProcessor();
      
      // 关闭WebSocket连接
      this.disconnectLiveWebSocket();
      
      // 发送停止请求到FastAPI后端
      const response = await fetch('/api/live/stop', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        }
      });

      const result = await response.json();
      
      if (result.success) {
        this.danmu = []; // 清空弹幕数据
        showNotification(result.message || this.t('live_stopped_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_stop_live'), 'error');
        // 如果后端停止失败，恢复状态
        this.isLiveRunning = true;
        this.shouldReconnectWs = true;
        this.startDanmuProcessor(); // 重新启动弹幕处理器
      }
    } catch (error) {
      console.error('停止直播监听失败:', error);
      showNotification(this.t('failed_to_stop_live'), 'error');
      // 如果出错，恢复状态
      this.isLiveRunning = true;
      this.shouldReconnectWs = true;
      this.startDanmuProcessor(); // 重新启动弹幕处理器
    } finally {
      this.isLiveStopping = false;
    }
  },

  // 重载直播配置
  async reloadLiveConfig() {
    if (!this.isLiveRunning || this.isLiveReloading) {
      return;
    }

    this.isLiveReloading = true;
    
    try {
      const response = await fetch('/api/live/reload', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          config: this.liveConfig
        })
      });

      const result = await response.json();
      
      if (result.success) {
        // 重新连接WebSocket
        this.shouldReconnectWs = false; // 先阻止重连
        this.disconnectLiveWebSocket();
        
        setTimeout(() => {
          this.shouldReconnectWs = true; // 重新允许重连
          this.connectLiveWebSocket();
        }, 1000);
        
        showNotification(result.message || this.t('live_config_reloaded_successfully'));
      } else {
        showNotification(result.message || this.t('failed_to_reload_live_config'), 'error');
      }
    } catch (error) {
      console.error('重载直播配置失败:', error);
      showNotification(this.t('failed_to_reload_live_config'), 'error');
    } finally {
      this.isLiveReloading = false;
    }
  },

  // 启动弹幕处理器
  startDanmuProcessor() {
    console.log('启动弹幕处理器');
    
    // 如果已经有定时器在运行，先清除
    if (this.danmuProcessTimer) {
      clearInterval(this.danmuProcessTimer);
    }
    
    // 每秒检查一次弹幕队列
    this.danmuProcessTimer = setInterval(async () => {
      await this.processDanmuQueue();
    }, 1000);
  },

  // 停止弹幕处理器
  stopDanmuProcessor() {
    console.log('停止弹幕处理器');
    
    if (this.danmuProcessTimer) {
      clearInterval(this.danmuProcessTimer);
      this.danmuProcessTimer = null;
    }
    
    this.isProcessingDanmu = false;
  },

// 1. 拷贝 URL 方法
  copyDanmakuOverlayEndpoint() {
    const url = this.partyURL + '/danmaku_overlay';
    navigator.clipboard.writeText(url).then(() => {
      if(typeof showNotification === 'function') showNotification(this.t('copySuccess') || 'Copied!', 'success');
    }).catch(() => {
      if(typeof showNotification === 'function') showNotification('Copy failed', 'error');
    });
  },

copySubtitleOverlayEndpoint(){
  const url =  this.partyURL + '/subtitle_overlay';
  navigator.clipboard.writeText(url).then(() => {
    if(typeof showNotification === 'function') showNotification(this.t('copySuccess') || 'Copied!', 'success');
  }).catch(() => {
    if(typeof showNotification === 'function') showNotification('Copy failed', 'error');
  });
},

// 处理弹幕队列 - 新版
  async processDanmuQueue() {
    try {
      // 基础检查 (保持不变)
      if (!this.isLiveRunning || this.danmu.length === 0 || this.isTyping || 
          (this.TTSrunning && this.ttsSettings.enabled) || this.isProcessingDanmu) {
        return;
      }

      this.isProcessingDanmu = true;
      const oldestDanmu = this.danmu[this.danmu.length - 1];
      
      if (oldestDanmu && oldestDanmu.content) {
        if (this.lastProcessedContent === oldestDanmu.content) {
            this.danmu.pop();
            this.isProcessingDanmu = false;
            return;
        }

        console.log('开始处理弹幕:', oldestDanmu.content);
        this.lastProcessedContent = oldestDanmu.content;
        
        // 【关键修复点 1】：将弹幕存入临时变量，准备注入 TTS 队列
        this.pendingDanmakuToRead = oldestDanmu.content;

        // 设置 LLM 的输入
        this.userInput = oldestDanmu.content;
        
        // 触发 OBS 弹窗显示 (调用后端 API)
        try {
            fetch('/api/overlay/danmaku', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(oldestDanmu)
            }).catch(()=>{});
        } catch(e) {}

        // 发送消息，启动 AI 生成流程
        await this.sendMessage();
        
        this.danmu.pop(); 
      }
    } catch (error) {
      console.error('处理弹幕出错:', error);
      this.danmu.pop(); 
    } finally {
      this.isProcessingDanmu = false;
    }
  },

  // 连接WebSocket
  connectLiveWebSocket() {
    try {
      // 根据当前协议选择ws或wss
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${protocol}//${window.location.host}/ws/live/danmu`;
      
      this.bilibiliWs = new WebSocket(wsUrl);
      
      this.bilibiliWs.onopen = (event) => {
        console.log('WebSocket连接已建立');
      };
      
      this.bilibiliWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleDanmuMessage(data);
        } catch (error) {
          console.error('解析WebSocket消息失败:', error);
        }
      };
      
      this.bilibiliWs.onclose = (event) => {
        console.log('WebSocket连接已关闭');
        
        // 只有在允许重连且直播还在运行时才重连
        if (this.shouldReconnectWs && this.isLiveRunning) {
          console.log('准备重连WebSocket...');
          setTimeout(() => {
            // 再次检查状态，确保仍然需要重连
            if (this.shouldReconnectWs && this.isLiveRunning) {
              console.log('开始重连WebSocket');
              this.connectLiveWebSocket();
            } else {
              console.log('取消重连WebSocket');
            }
          }, 3000);
        } else {
          console.log('不需要重连WebSocket');
        }
      };
      
      this.bilibiliWs.onerror = (error) => {
        console.error('WebSocket连接错误:', error);
      };
    } catch (error) {
      console.error('创建WebSocket连接失败:', error);
    }
  },

  // 断开WebSocket连接
  disconnectLiveWebSocket() {
    console.log('断开WebSocket连接');
    
    if (this.bilibiliWs) {
      // 先设置为null，避免onclose事件中的重连逻辑
      const ws = this.bilibiliWs;
      this.bilibiliWs = null;
      
      // 然后关闭连接
      ws.close();
    }
  },

  async checkLiveStatus() {
    try {
      const response = await fetch('/api/live/status');
      const result = await response.json();
      
      // 更新状态
      this.isLiveRunning = result.is_running;

      // 关键点：如果后台正在运行，前端刷新后需要重新挂载 WebSocket 和处理器
      if (this.isLiveRunning) {
        console.log('检测到后台直播监听正在运行，正在恢复连接...');
        this.shouldReconnectWs = true;
        
        // 重新连接 WebSocket 接收弹幕
        this.connectLiveWebSocket();
        
        // 重新启动弹幕队列处理定时器
        this.startDanmuProcessor();
      }
    } catch (error) {
      console.error('检查直播状态失败:', error);
    }
  },

  // 处理弹幕消息
  handleDanmuMessage(data) {
    if (data.type !== 'message') {
      if (data.type === 'error') showNotification(data.message, 'error');
      return;
    }

    // --- 1. ID 级去重 ---
    if (data.id) {
      if (this.receivedMsgIds.has(data.id)) return;
      this.receivedMsgIds.add(data.id);
      if (this.receivedMsgIds.size > 500) {
        const firstVal = this.receivedMsgIds.values().next().value;
        this.receivedMsgIds.delete(firstVal);
      }
    }

    // --- 2. 统一定义消息属性 ---
    const danmuType = data.danmu_type; // danmaku, super_chat, gift, buy_guard, enter_room, follow, like
    const isDanmaku = (danmuType === "danmaku" || danmuType === "super_chat");
    const isPaid = (danmuType === "gift" || danmuType === "buy_guard" || danmuType === "super_chat");
    const isInteraction = (danmuType === "enter_room" || danmuType === "follow" || danmuType === "like");

    // --- 3. 模式过滤判断 ---
    let modePass = false;
    const mode = this.liveConfig.filterMode || 'all';

    if (mode === 'all') {
      modePass = true;
    } else if (mode === 'danmaku_paid') {
      modePass = (isDanmaku || isPaid);
    } else if (mode === 'danmaku_only') {
      modePass = isDanmaku;
    }

    if (!modePass) return;

    // --- 4. 唤醒词校验 (仅针对文本类消息) ---
    const wakeStr = this.liveConfig.wakeWord || "";
    const wakeKeywords = wakeStr.split(/[\r\n]+/).map(k => k.trim()).filter(k => k.length > 0);
    
    const isMatchWakeWord = (text) => {
      if (wakeKeywords.length === 0) return true;
      return wakeKeywords.some(keyword => text.includes(keyword));
    };

    let shouldAdd = false;
    if (isDanmaku) {
      // 弹幕和 SC 必须匹配唤醒词
      if (isMatchWakeWord(data.content)) shouldAdd = true;
    } else {
      // 礼物、舰长、关注等互动，直接放行 (不被唤醒词拦截)
      shouldAdd = true;
    }

    // --- 5. 入队 ---
    if (shouldAdd) {
      const danmuItem = {
        id: data.id,
        content: data.content,
        type: danmuType,
        platform: data.platform || 'bilibili',
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false })
      };

      // 连续重复内容防刷屏
      if (this.danmu.length > 0 && this.danmu[0].content === danmuItem.content) return;

      this.danmu.unshift(danmuItem);
      if (this.danmu.length > this.liveConfig.danmakuQueueLimit) {
        this.danmu = this.danmu.slice(0, this.liveConfig.danmakuQueueLimit);
      }
    }
  }
});
