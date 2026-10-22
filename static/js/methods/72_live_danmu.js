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
  /**
   * S80(9a30de93) 队列裁剪：保留最新 N 条，但**永不丢弃扩展推来的请求**
   * （source === 'director'）。导演请求 push 到队尾（=下一个被处理），而裁剪
   * slice(0, limit) 保留队首砍队尾——不豁免的话一条观众弹幕就能把导演请求挤掉。
   */
  trimDanmuQueue() {
    const limit = this.liveConfig.danmakuQueueLimit || 5;
    if (this.danmu.length <= limit) return;
    const keep = this.danmu.slice(0, limit);
    const pinned = this.danmu.slice(limit).filter((d) => d && d.source === 'director');
    this.danmu = keep.concat(pinned);
  },

  /**
   * S80(9a30de93) 按引用删队列里**指定的那一条**，不是 pop()。
   * sendMessage 期间队列还会变（观众弹幕 unshift 队首、扩展请求 push 队尾），
   * pop() 删的「当前最后一条」可能根本不是刚处理完的那条（上游真机实锤：
   * 处理 A 时 B 入队尾，A 跑完 pop 把 B 删了，B 凭空消失）。
   */
  removeDanmuItem(item) {
    if (!item) return;
    const i = this.danmu.indexOf(item);
    if (i >= 0) this.danmu.splice(i, 1);
  },

  /**
   * S80(9a30de93) 扩展（如 sap-snack-director）经 /ws live_enqueue 推来的请求：
   * **进弹幕队列**，不直接 sendMessage()。
   * 为什么不走 trigger_send_message：sendMessage() 会 stopAllAudioPlayback()+清
   * TTSrunning ⇒ 打断正在播报的语音；且开头 if (this.isTyping) return ⇒ 正在
   * 生成时**静默丢弃**。进队列后由 processDanmuQueue 闸门串行调度，忙时排队。
   * 队列里至多留一条导演请求：新请求替换旧请求（游戏状态已变，旧问题过期）。
   */
  enqueueLiveRequest(payload) {
    const text = String((payload && payload.text) || '').trim();
    if (!text) return;

    this.danmu = this.danmu.filter((d) => !d || d.source !== 'director');
    this.danmu.push({
      id: (payload && payload.id) || ('director-' + Date.now()),
      content: text,
      type: (payload && payload.source) || 'director',
      platform: (payload && payload.platform) || 'director',
      source: 'director',
      // 默认不上 OBS 弹幕叠加层（这是一大段提示词）
      silent: payload ? payload.silent !== false : true,
      timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false })
    });
    this.trimDanmuQueue();

    // 没开直播面板时 danmuProcessTimer 可能不存在，这里保证它被挂上
    this.startDanmuProcessor();
    // 若当前空闲，别等下一个 1s tick；忙的话闸门会挡住，下一 tick 再来
    this.processDanmuQueue();
  },

  async processDanmuQueue() {
    let processing = null;
    try {
      // S80(f49f267f)：陈旧 TTS 锁检测——锁为真但没有任何真实播放在跑，
      // 直接释放，否则弹幕队列被一把假锁永久卡死
      const hasStaleTTSLock = this.TTSrunning &&
          this.ttsSettings.enabled &&
          !this.hasActiveTTSPlayback();
      if (hasStaleTTSLock) {
        console.warn('Detected stale TTS lock before processing danmu queue; releasing it.');
        this.TTSrunning = false;
      }

      /**
       * S80(9a30de93) 基础闸门：**正在生成 / 正在播报 / 正在处理** 时一律不取队列——
       * 这正是「扩展的请求不会打断 LLM 说话」的机制：它排队，不抢麦。
       * isLiveRunning 只该拦**观众弹幕**；导演请求即使没开直播面板也必须处理，
       * 否则整个导演功能会被「没开直播」卡死。
       */
      if ((!this.isLiveRunning && !this.danmu.some((d) => d && d.source === 'director')) ||
          this.danmu.length === 0 || this.isTyping ||
          (this.TTSrunning && this.ttsSettings.enabled) || this.isProcessingDanmu) {
        return;
      }

      this.isProcessingDanmu = true;
      const oldestDanmu = this.danmu[this.danmu.length - 1];

      if (oldestDanmu && oldestDanmu.content) {
        processing = oldestDanmu;
        // S80(9a30de93)：导演请求带唯一 id 且游戏没变化时正文会重复，
        // 连续重复内容去重**只对观众弹幕**生效
        if (oldestDanmu.source !== 'director' && this.lastProcessedContent === oldestDanmu.content) {
            this.removeDanmuItem(processing);
            this.isProcessingDanmu = false;
            return;
        }

        console.log('开始处理弹幕:', oldestDanmu.content);
        this.lastProcessedContent = oldestDanmu.content;
        
        // 【关键修复点 1】：将弹幕存入临时变量，准备注入 TTS 队列
        this.pendingDanmakuToRead = oldestDanmu.content;

        // 设置 LLM 的输入
        this.userInput = oldestDanmu.content;
        
        // 触发 OBS 弹窗显示 (调用后端 API)。
        // S80(9a30de93)：扩展的请求标了 silent，不上画面——它是一大段提示词
        if (!oldestDanmu.silent) {
          try {
              fetch('/api/overlay/danmaku', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify(oldestDanmu)
              }).catch(()=>{});
          } catch(e) {}
        }

        // 发送消息，启动 AI 生成流程
        await this.sendMessage();
        
        this.removeDanmuItem(processing);
      }
    } catch (error) {
      console.error('处理弹幕出错:', error);
      this.removeDanmuItem(processing);
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
      this.trimDanmuQueue();  // S80(9a30de93): 裁剪单点（director 豁免）
    }
  },

startLiveStream(){
  this.activeMenu = 'deploy-bot';
  this.subMenu = 'live_stream';
}
});
