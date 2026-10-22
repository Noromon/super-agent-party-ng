// 批 3 F2：自 vue_methods.js 搬移的 methods/14_ws_client.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // WebSocket相关
    initWebSocket() {
      const http_protocol = window.location.protocol;
      const ws_protocol = http_protocol === 'https:' ? 'wss:' : 'ws:';
      const ws_url = `${ws_protocol}//${window.location.host}/ws`;

      // 【重连保护】如果已有旧连接，说明是重连而非首次连接
      const isReconnect = !!this.ws;
      if (isReconnect) {
        this._isWsReconnect = true;
        console.log('[WS] 检测到重连，将保护当前对话状态不被覆盖');
      }

      this.ws = new WebSocket(ws_url);

      // 设置心跳间隔和重连间隔（单位：毫秒）
      const HEARTBEAT_INTERVAL = 10000; // 每10秒发送一次 ping
      const RECONNECT_INTERVAL = 5000;  // 断开后每5秒尝试重连一次

      let heartbeatTimer = null;
      let reconnectTimer = null;

      const startHeartbeat = () => {
        heartbeatTimer = setInterval(() => {
          if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            try {
              this.ws.send(JSON.stringify({ type: 'ping' })); // 发送心跳包
            } catch (e) {
              console.error('Failed to send ping:', e);
            }
          }
        }, HEARTBEAT_INTERVAL);
      };

      const stopHeartbeat = () => {
        if (heartbeatTimer) {
          clearInterval(heartbeatTimer);
          heartbeatTimer = null;
        }
      };

      const scheduleReconnect = () => {
        stopHeartbeat();
        if (!reconnectTimer) {
          reconnectTimer = setTimeout(() => {
            console.log('Reconnecting WebSocket...');
            this.initWebSocket(); // 重新初始化
            reconnectTimer = null;
          }, RECONNECT_INTERVAL);
        }
      };

      // WebSocket 打开事件
      this.ws.onopen = () => {
        console.log('WebSocket connection established');
        stopHeartbeat(); // 防止重复心跳
        startHeartbeat();
        if (!this._covsSaveTimer) {
          this._covsSaveTimer = setInterval(() => { this.flushDirtyConversations(); }, 30000);
        }
      };

      // 接收消息
      this.ws.onmessage = async (event) => {
        let data;
        try {
          data = JSON.parse(event.data);
        } catch (e) {
          console.log('Message from server:', event.data);
          return;
        }

      if (data.type === 'pong') {
        // 可以在这里处理 pong 回复，比如记录状态
        console.log('Received pong from server.');
      } 
      else if (data.type === 'settings_update') {
          // 增量广播：payload 为 settings 子集，schema 驱动恢复自动跳过未推送键
          // （批 0-④：原手写清单缺 agents/systemSettings 等键，推送被静默忽略，已并入单源）
          this.settings = window.SETTINGS_SCHEMA.buildSettingsFromWire(data.data);
          window.SETTINGS_SCHEMA.applySettingsPayload(this, data.data);
      }
      else if (data.type === 'settings') {
          // 【重连保护】如果是重连，保护当前对话状态不被服务端全量覆盖
          const isReconnect = this._isWsReconnect;
          if (isReconnect) {
            console.log('[WS] 重连模式：保护当前对话状态，仅同步非对话配置');
            this._isWsReconnect = false;
            // 【修复】重连后补发被缓存的扩展消息，确保插件收到完整回复
            if (this._pendingExtensionMessage) {
              setTimeout(() => {
                if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                  try {
                    this.ws.send(this._pendingExtensionMessage);
                    this._pendingExtensionMessage = null;
                    console.log('[WS] 重连后已补发缓存的扩展消息');
                  } catch (e) {
                    console.error('[WS] 补发缓存消息失败:', e);
                  }
                }
              }, 500); // 延迟500ms确保连接稳定
            }
          }
          this.ensureConversationGroups();
          this.isdocker = data.data.isdocker || false;
          // settings 展开字段与常规设置对均由 settings_schema.js 单一事实源驱动（批 0-④）
          this.settings = window.SETTINGS_SCHEMA.buildSettingsFromWire(data.data);
          // 【重连保护】重连时不覆盖对话数据，避免丢失正在进行的对话
          if (!isReconnect) {
            this.conversations = data.data.conversations || this.conversations;
            this.conversationGroups = data.data.conversationGroups || this.conversationGroups;
            this.conversationId = data.data.conversationId || this.conversationId;
          } else if (Array.isArray(data.data.conversations)) {
            // 重连：与服务器副本按 id+timestamp 双向合并，本地未落盘的会话保留并补推
            this.mergeRemoteConversations(data.data.conversations);
          }
          // 常规设置对恢复（truthy 覆盖），清单在 settings_schema.js 单源维护
          window.SETTINGS_SCHEMA.applySettingsPayload(this, data.data);
          if (data.data.largeMoreButtonDict) {
            this.largeMoreButtonDict = this.largeMoreButtonDict.map(existingButton => {
              const newButton = data.data.largeMoreButtonDict.find(button => button.name === existingButton.name);
              if (newButton) {
                return { ...existingButton, enabled: newButton.enabled };
              }
              return existingButton;
            });
          }
          if (data.data.smallMoreButtonDict) {
            this.smallMoreButtonDict = this.smallMoreButtonDict.map(existingButton => {
              const newButton = data.data.smallMoreButtonDict.find(button => button.name === existingButton.name);
              if (newButton) {
                return { ...existingButton, enabled: newButton.enabled };
              }
              return existingButton;
            });
          }
          // 【重连保护】重连时不重新加载对话，避免覆盖正在进行的 SSE 流消息
          if (!isReconnect) {
            this.loadConversation(this.conversationId);
          }
          // 初始化时确保数据一致性
          this.edgettsLanguage = this.ttsSettings.edgettsLanguage;
          this.edgettsGender = this.ttsSettings.edgettsGender;
          this.handleSystemLanguageChange(this.systemSettings.language);
          this.refreshButtonText = this.t('refreshList');
          if (this.HASettings.enabled) {
            this.changeHAEnabled();
          };
          await this.initChromeMCPSettings();
          if (this.chromeMCPSettings.enabled){
            this.changeChromeMCPEnabled();
          }
          if (this.sqlSettings.enabled){
            this.changeSqlEnabled();
          }
          this.changeMemory();
          // this.target_lang改成navigator.language || navigator.userLanguage;
          this.target_lang = this.targetLangSelected!="system"? this.targetLangSelected: navigator.language || navigator.userLanguage || 'zh-CN';
          this.loadDefaultModels();
          this.loadDefaultMotions();
          this.loadGaussScenes();
          this.checkMobile();
          this.checkQQBotStatus(); 
          this.checkFeishuBotStatus();
          this.checkTelegramBotStatus();
          this.checkXmppBotStatus();
          this.checkDiscordBotStatus();
          this.checkLiveStatus();
          this.fetchRemotePlugins();
          this.fetchSkills();
          this.fetchTetosVoices(this.ttsSettings.engine);
          if (this.asrSettings.enabled && this.asrSettings.interactionMethod != 'globalKeyTriggered' && this.asrSettings.interactionMethod != 'keyTriggered') {
            this.startASR();
          }
          if (this.activeMenu === 'home') this.startDriverGuide();
        } 
          // 在 initWebSocket() 的 onmessage 逻辑中添加
          else if (data.type === 'task_notification') {
              // 调用前端的弹窗提醒
              showNotification(`${data.data.title}\n${this.t('intask')}`, 'success');
          }
        // A5 日记：后端推送的日记条目（上游 vue_methods 同型分支）
        else if (data.type === 'diary_entry') {
          if (data.data && data.data.content) {
            if (data.data.actionType === 'system_notify') {
              const title = data.data.title || this.t('DiarySystem') || '日记系统';
              showNotification(title + ': ' + data.data.content, 'warning');
            } else {
              this.pushDiaryToChat(data.data.content, data.data.actionType);
            }
          }
        }
        else if (data.type === 'diary_im_targets') {
          this.applyDiaryImTargetOptions(data);
        }
        else if (data.type === 'settings_saved') {
          if (!data.success) {
            showNotification(this.t('settings_save_failed'), 'error');
          }
        }
        // 新增：处理用户输入更新
        else if (data.type === 'update_user_input') {
          this.userInput = data.data.text;
          // [XMPP Bridge] 接收扩展注入的图片附件（已上传到 uploaded_files，形如 [{path, name, type}]）
          const extImages = Array.isArray(data.data.images) ? data.data.images : [];
          if (extImages.length > 0) {
            this.extensionImageLinks = [...(this.extensionImageLinks || []), ...extImages];
          }
        }
        // 更新或添加提示词
        else if (data.type === 'update_system_prompt') {
            const id = data.data.id;
            const text = data.data.text;
            this.extensionsSystemPromptsDict[id] = text; 
        }
        
        // 移除提示词 (对应后端 finally 中的逻辑)
        else if (data.type === 'remove_system_prompt') {
            const id = data.data.id;
            
            if (this.extensionsSystemPromptsDict[id]) {
                delete this.extensionsSystemPromptsDict[id];
            }
        }
        // 新增：处理工具输入
        else if (data.type === 'update_tool_input') {
          this.userInput = data.data.text;
          this.sendMessage('system')
        }
        // 新增：处理TTS输入
        else if (data.type === 'start_tts') {
          this.readConfig.longText = data.data.text;
          // 等待0.5s
          setTimeout(() => {
            this.startRead();
          }, 500);
        }
        // 新增：停止TTS
        else if (data.type === 'stop_tts') {
          this.stopTTSActivities();
          this.readConfig.longText = '';
        }
        // 新增：处理关闭扩展侧边栏
        else if (data.type === 'trigger_close_extension') {
          console.log('关闭侧边栏')
          this.resetToDefaultView();
        }
        // 新增：处理触发发送消息
        else if (data.type === 'trigger_send_message') {
          this.sendMessage();
        }
        // S80(B6/9a30de93)：扩展推的请求进弹幕队列串行调度（见 enqueueLiveRequest 注释）
        else if (data.type === 'live_enqueue') {
          this.enqueueLiveRequest(data.data);
        }
        // 新增：清空消息列表
        else if (data.type === "trigger_clear_message" ){
          this.clearMessages();
        }
        // 新增：响应请求消息列表
        else if (data.type === 'request_messages') {
          // 发送当前消息列表给请求方
          this.sendMessagesToExtension();
        }
      };

      // WebSocket 关闭事件
      this.ws.onclose = (event) => {
        console.log('WebSocket connection closed:', event.reason);
        stopHeartbeat();
        scheduleReconnect();
      };

      // WebSocket 错误事件
      this.ws.onerror = (error) => {
        console.error('WebSocket error:', error);
        this.ws.close(); // 主动关闭连接，触发 onclose 事件
      };
    }
});
