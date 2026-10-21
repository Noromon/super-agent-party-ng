// 批 3 F2：自 vue_methods.js 搬移的 methods/50_bots_lifecycle.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  // 启动QQ机器人
  async startQQBot() {
    this.isStarting = true;
    
    try {
      // 显示连接中的提示
      showNotification('正在连接QQ机器人...', 'info');
      
      const response = await fetch(`/start_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.qqBotConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        this.isQQBotRunning = true;
        showNotification('QQ机器人已成功启动并就绪', 'success');
      } else {
        // 显示具体错误信息
        const errorMessage = result.message || '启动失败，请检查配置';
        showNotification(`启动失败: ${errorMessage}`, 'error');
        
        // 如果是超时错误，给出更具体的提示
        if (errorMessage.includes('超时')) {
          showNotification('提示：请检查网络连接和机器人配置是否正确', 'warning');
        }
      }
    } catch (error) {
      console.error('启动QQ机器人时出错:', error);
      showNotification('启动QQ机器人失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isStarting = false;
    }
  },

  // 停止QQ机器人
  async stopQQBot() {
    this.isStopping = true;
    
    try {
      const response = await fetch(`/stop_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
      });

      const result = await response.json();
      
      if (result.success) {
        this.isQQBotRunning = false;
        showNotification('QQ机器人已成功停止', 'success');
      } else {
        const errorMessage = result.message || '停止失败';
        showNotification(`停止失败: ${errorMessage}`, 'error');
      }
    } catch (error) {
      console.error('停止QQ机器人时出错:', error);
      showNotification('停止QQ机器人失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isStopping = false;
    }
  },

  // 重载QQ机器人配置
  async reloadQQBotConfig() {
    this.isReloading = true;
    
    try {
      const response = await fetch(`/reload_qq_bot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.qqBotConfig)
      });

      const result = await response.json();
      
      if (result.success) {
        if (result.config_changed) {
          showNotification('QQ机器人配置已重载并重新启动', 'success');
        } else {
          showNotification('QQ机器人配置已更新', 'success');
        }
      } else {
        const errorMessage = result.message || '重载失败';
        showNotification(`重载失败: ${errorMessage}`, 'error');
      }
    } catch (error) {
      console.error('重载QQ机器人配置时出错:', error);
      showNotification('重载QQ机器人配置失败: 网络错误或服务器未响应', 'error');
    } finally {
      this.isReloading = false;
    }
  },

  // 添加状态检查方法
  async checkQQBotStatus() {
    try {
      const response = await fetch(`/qq_bot_status`);
      const status = await response.json();
      
      // 更新机器人运行状态
      this.isQQBotRunning = status.is_running;
      
      // 如果机器人正在运行但前端状态不一致，更新状态
      if (status.is_running && !this.isQQBotRunning) {
        this.isQQBotRunning = true;
      }
    } catch (error) {
      console.error('检查机器人状态失败:', error);
    }
  },

    // 新增的方法：供主进程请求关闭机器人
    async requestStopQQBotIfRunning() {
      try {
        const response = await fetch(`/qq_bot_status`)
        const status = await response.json()

        if (status.is_running) {
          // 调用 stopQQBot 来关闭机器人
          await this.stopQQBot()
          console.log('机器人已关闭')
        }
      } catch (error) {
        console.error('检查或停止机器人失败:', error)
      }
    },

 async requestFeishuBotStopIfRunning(){
      try {
        const response = await fetch(`/feishu_bot_status`)
        const status = await response.json()

        if (status.is_running) {
          // 调用 stopQQBot 来关闭机器人
          await this.stopFeishuBot()
          console.log('机器人已关闭')
        }
      } catch (error) {
        console.error('检查或停止机器人失败:', error)
      }
 },

async startFeishuBot() {
  this.isFeishuStarting = true;
  try {
    showNotification('正在连接飞书机器人...', 'info');
    const res = await fetch('/start_feishu_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.feishuBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isFeishuBotRunning = true;
      showNotification('飞书机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuStarting = false;
  }
},

async stopFeishuBot() {
  this.isFeishuStopping = true;
  try {
    const res = await fetch('/stop_feishu_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isFeishuBotRunning = false;
      showNotification('飞书机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuStopping = false;
  }
},

async reloadfeishuBotConfig() {
  this.isFeishuReloading = true;
  try {
    const res = await fetch('/reload_feishu_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.feishuBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('飞书机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isFeishuReloading = false;
  }
},

async checkFeishuBotStatus() {
  try {
    const res = await fetch('/feishu_bot_status');
    const st = await res.json();
    this.isFeishuBotRunning = st.is_running;
  } catch (e) {
    console.error('检查飞书机器人状态失败', e);
  }
},

handleCreateFeishuSeparator(val) {
  this.feishuBotConfig.separators.push(val);
},

async requestWechatBotStopIfRunning() {
  try {
    const res = await fetch(`/wechat_bot_status`)
    const status = await res.json()
    if (status.is_running) {
      await this.stopWechatBot()
    }
  } catch (error) { console.error('检查或停止微信机器人失败:', error) }
},

async startWechatBot() {
  this.isWechatStarting = true;
  this.showWechatQR = false; // 隐藏旧的弹窗
  this.wechatQRCodeBase64 = null; // 清空旧的二维码
  try {
    showNotification('正在启动微信机器人服务...', 'info');
    const res = await fetch('/start_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.wechatBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isWechatBotRunning = true;
      // 启动成功后，开启 1.5 秒一次的高频轮询，去抓后台的 Base64 图片
      if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
      this.wechatStatusTimer = setInterval(() => {
        this.checkWechatBotStatus();
      }, 1500);
      
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isWechatStarting = false;
  }
},

async stopWechatBot() {
  this.isWechatStopping = true;
  if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
  try {
    const res = await fetch('/stop_wechat_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isWechatBotRunning = false;
      showNotification('微信机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatStopping = false;
  }
},

async reloadWechatBotConfig() {
  this.isWechatReloading = true;
  try {
    const res = await fetch('/reload_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.wechatBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('微信机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatReloading = false;
  }
},

async checkWechatBotStatus() {
  try {
    const res = await fetch('/wechat_bot_status');
    const st = await res.json();
    this.isWechatBotRunning = st.is_running;
    
    // 弹出二维码：如果后端有二维码，并且和当前界面的不一样
    if (st.qr_base64 && this.wechatQRCodeBase64 !== st.qr_base64) {
      this.wechatQRCodeBase64 = st.qr_base64;
      this.showWechatQR = true; 
    }

    // --- 核心修复：触发自动秒关弹窗的逻辑 ---
    // 条件1: 后端识别到登录成功的特征 (st.is_logged_in)
    // 条件2: 原本正在显示二维码，但下一秒发现后端的 qr_base64 变成了 null (被系统清除了)
    if (st.is_logged_in || (this.showWechatQR && !st.qr_base64 && this.wechatQRCodeBase64)) {
        this.showWechatQR = false;         // 瞬间关闭弹窗
        this.wechatQRCodeBase64 = null;    // 清空本地图片缓存
        showNotification('✅ 微信已成功登录，机器人开始工作！', 'success');
        
        // 扫码成功后，取消极速轮询定时器，减轻服务器压力
        if (this.wechatStatusTimer) {
            clearInterval(this.wechatStatusTimer);
            this.wechatStatusTimer = null;
        }
    }

    // 意外停止时的清理逻辑
    if (!st.is_running && this.wechatStatusTimer) {
       clearInterval(this.wechatStatusTimer);
       this.wechatStatusTimer = null;
    }
  } catch (e) {
    console.error('检查微信状态失败', e);
  }
},

handleCreateWechatSeparator(val) {
  this.wechatBotConfig.separators.push(val);
},

async forceReLoginWechatBot() {
  // 1. 如果当前正在运行，先停止它，释放被占用的凭证文件
  if (this.isWechatBotRunning) {
    showNotification('正在关闭当前实例并物理粉碎凭证缓存...', 'info');
    await this.stopWechatBot();
    
    // 关键：强制等待 2.5 秒，给操作系统足够的时间释放文件句柄和销毁底层线程
    await new Promise(resolve => setTimeout(resolve, 2500));
  }
  
  this.isWechatStarting = true;
  this.showWechatQR = false; 
  this.wechatQRCodeBase64 = null; 
  
  try {
    showNotification('强制获取全新二维码中，请稍候...', 'info');
    // 在 payload 中追加强制标识，后端检测到就会先执行物理删除
    const payload = { ...this.wechatBotConfig, force_relogin: true };
    
    const res = await fetch('/start_wechat_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const json = await res.json();
    
    if (json.success) {
      this.isWechatBotRunning = true;
      if (this.wechatStatusTimer) clearInterval(this.wechatStatusTimer);
      
      // 开启极速轮询，一旦后端生成了新二维码就会自动弹窗
      this.wechatStatusTimer = setInterval(() => {
        this.checkWechatBotStatus();
      }, 1500);
    } else {
      showNotification(`拉取新二维码失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isWechatStarting = false;
  }
},

  async requestWeComBotStopIfRunning() {
    try {
      const response = await fetch(`/wecom_bot_status`);
      const status = await response.json();

      if (status.is_running) {
        // 调用 stopWeComBot 来关闭机器人
        await this.stopWeComBot();
        console.log('机器人已关闭');
      }
    } catch (error) {
      console.error('检查或停止机器人失败:', error)
    }
  },

  async startWeComBot() {
    this.isWeComStarting = true;
    try {
      showNotification('正在连接企微机器人...', 'info');
      const res = await fetch('/start_wecom_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.weComBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        this.isWeComBotRunning = true;
        showNotification('企微机器人启动成功', 'success');
      } else {
        showNotification(`启动失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误或服务器未响应', 'error');
    } finally {
      this.isWeComStarting = false;
    }
  },

  async stopWeComBot() {
    this.isWeComStopping = true;
    try {
      const res = await fetch('/stop_wecom_bot', { method: 'POST' });
      const json = await res.json();
      if (json.success) {
        this.isWeComBotRunning = false;
        showNotification('企微机器人已停止', 'success');
      } else {
        showNotification(`停止失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isWeComStopping = false;
    }
  },

  async reloadWeComBotConfig() {
    this.isWeComReloading = true;
    try {
      const res = await fetch('/reload_wecom_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.weComBotConfig),
      });
      const json = await res.json();
      if (json.success) showNotification('企微机器人已重载', 'success');
      else showNotification(`重载失败：${json.message}`, 'error');
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isWeComReloading = false;
    }
  },

  async checkWeComBotStatus() {
    try {
      const res = await fetch('/wecom_bot_status');
      const st = await res.json();
      this.isWeComBotRunning = st.is_running;
    } catch (e) { }
  },

async requestTelegramBotStopIfRunning() {
  try {
    const res = await fetch('/telegram_bot_status');
    const st = await res.json();
    if (st.is_running) await this.stopTelegramBot();
  } catch (e) {
    console.error('检查或停止 Telegram 机器人失败:', e);
  }
},

  // 1. 启动钉钉机器人
  async startDingtalkBot() {
    this.isDingtalkStarting = true;
    try {
      showNotification('正在建立钉钉 Stream 连接...', 'info');
      const res = await fetch('/start_dingtalk_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.dingtalkBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        this.isDingtalkBotRunning = true;
        showNotification('钉钉机器人启动成功 (Stream模式)', 'success');
      } else {
        showNotification(`启动失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误：钉钉服务未响应', 'error');
    } finally {
      this.isDingtalkStarting = false;
    }
  },

  // 2. 停止钉钉机器人
  async stopDingtalkBot() {
    this.isDingtalkStopping = true;
    try {
      const res = await fetch('/stop_dingtalk_bot', { method: 'POST' });
      const json = await res.json();
      if (json.success) {
        this.isDingtalkBotRunning = false;
        showNotification('钉钉机器人连接已断开', 'success');
      } else {
        showNotification(`停止失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isDingtalkStopping = false;
    }
  },

  // 3. 重载钉钉机器人配置
  async reloadDingtalkBot() {
    this.isDingtalkReloading = true;
    try {
      const res = await fetch('/reload_dingtalk_bot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(this.dingtalkBotConfig),
      });
      const json = await res.json();
      if (json.success) {
        showNotification('钉钉机器人配置已实时重载', 'success');
      } else {
        showNotification(`重载失败：${json.message}`, 'error');
      }
    } catch (e) {
      showNotification('网络错误', 'error');
    } finally {
      this.isDingtalkReloading = false;
    }
  },

  // 4. 检查钉钉机器人状态 (常用于 mounted 钩子)
  async checkDingtalkBotStatus() {
    try {
      const res = await fetch('/dingtalk_bot_status');
      const st = await res.json();
      this.isDingtalkBotRunning = st.is_running;
    } catch (e) {
      console.error('检查钉钉机器人状态失败', e);
    }
  },

  // 其他辅助方法
  handleCreateDingtalkSeparator(val) {
    if (!this.dingtalkBotConfig.separators) this.dingtalkBotConfig.separators = [];
    this.dingtalkBotConfig.separators.push(val);
  },

  // 联动停止：当其他机器人启动时，确保停止当前的钉钉机器人
  async requestDingtalkBotStopIfRunning() {
    try {
      const res = await fetch('/dingtalk_bot_status');
      const st = await res.json();
      if (st.is_running) await this.stopDingtalkBot();
    } catch (e) {
      console.error('停止钉钉机器人失败:', e);
    }
  },

async startTelegramBot() {
  this.isTelegramStarting = true;
  try {
    showNotification('正在连接 Telegram 机器人...', 'info');
    const res = await fetch('/start_telegram_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.telegramBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      this.isTelegramBotRunning = true;
      showNotification('Telegram 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramStarting = false;
  }
},

async stopTelegramBot() {
  this.isTelegramStopping = true;
  try {
    const res = await fetch('/stop_telegram_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isTelegramBotRunning = false;
      showNotification('Telegram 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramStopping = false;
  }
},

async reloadTelegramBotConfig() {
  this.isTelegramReloading = true;
  try {
    const res = await fetch('/reload_telegram_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.telegramBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Telegram 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isTelegramReloading = false;
  }
},

async checkTelegramBotStatus() {
  try {
    const res = await fetch('/telegram_bot_status');
    const st = await res.json();
    this.isTelegramBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Telegram 机器人状态失败', e);
  }
},

handleCreateTelegramSeparator(val) {
  this.telegramBotConfig.separators.push(val);
},

/* ------- XMPP 机器人（收编版第九通道） ------- */
async startXmppBot() {
  this.isXmppStarting = true;
  try {
    showNotification('正在连接 XMPP 服务器...', 'info');
    const res = await fetch('/start_xmpp_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.xmppBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      this.isXmppBotRunning = true;
      showNotification('XMPP 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppStarting = false;
    this.fetchXmppCertPending();
  }
},

async stopXmppBot() {
  this.isXmppStopping = true;
  try {
    const res = await fetch('/stop_xmpp_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isXmppBotRunning = false;
      showNotification('XMPP 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppStopping = false;
    this.fetchXmppCertPending();
  }
},

async reloadXmppBotConfig() {
  this.isXmppReloading = true;
  try {
    const res = await fetch('/reload_xmpp_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.xmppBotConfig)
    });
    const json = await res.json();
    if (json.success) {
      showNotification('XMPP 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isXmppReloading = false;
    this.fetchXmppCertPending();
  }
},

async checkXmppBotStatus() {
  try {
    const res = await fetch('/xmpp_bot_status');
    const st = await res.json();
    this.isXmppBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 XMPP 机器人状态失败', e);
  }
},

async requestXmppBotStopIfRunning() {
  try {
    const res = await fetch('/xmpp_bot_status');
    const st = await res.json();
    if (st.is_running) await this.stopXmppBot();
  } catch (e) {
    console.error('检查或停止 XMPP 机器人失败:', e);
  }
},

handleCreateXmppSeparator(val) {
  this.xmppBotConfig.separators.push(val);
},

/* ------- Discord 机器人 ------- */
async startDiscordBot() {
  this.isDiscordStarting = true;
  try {
    showNotification('正在连接 Discord 机器人...', 'info');
    const res = await fetch('/start_discord_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.discordBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      this.isDiscordBotRunning = true;
      showNotification('Discord 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordStarting = false;
  }
},

async stopDiscordBot() {
  this.isDiscordStopping = true;
  try {
    const res = await fetch('/stop_discord_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isDiscordBotRunning = false;
      showNotification('Discord 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordStopping = false;
  }
},

async reloadDiscordBot() {
  this.isDiscordReloading = true;
  try {
    const res = await fetch('/reload_discord_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.discordBotConfig),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Discord 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isDiscordReloading = false;
  }
},

async checkDiscordBotStatus() {
  try {
    const res = await fetch('/discord_bot_status');
    const st = await res.json();
    this.isDiscordBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Discord 机器人状态失败', e);
  }
},

handleCreateDiscordSeparator(val) {
  this.discordBotConfig.separators.push(val);
},

async requestSlackBotStopIfRunning() {
    try {
      // 1. 先从后端确认 Slack 机器人的真实运行状态
      const response = await fetch(`/slack_bot_status`);
      const status = await response.json();

      // 2. 如果后端返回正在运行 (is_running 为 true)
      if (status.is_running) {
        // 3. 调用你之前在 methods 里写好的 stopSlackBot 方法
        // 该方法包含了停止逻辑、Loading 状态切换以及 showNotification 通知
        await this.stopSlackBot();
        console.log('Slack 机器人已应系统请求成功关闭');
      }
    } catch (error) {
      // 捕获网络错误或后端未启动的情况
      console.error('检查或停止 Slack 机器人失败:', error);
    }
  },

/* ------- Slack 机器人 ------- */
async startSlackBot() {
  this.isSlackStarting = true;
  try {
    showNotification('正在连接 Slack 机器人...', 'info');
    // 注意：这里发送的是 slackBotConfig，但后端会自动处理共用的 memorySettings 状态
    const res = await fetch('/start_slack_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...this.slackBotConfig,
        // 显式传一下 memory 配置，确保后端能拿到最新的
        memory_settings: this.memorySettings 
      }),
    });
    const json = await res.json();
    if (json.success) {
      this.isSlackBotRunning = true;
      showNotification('Slack 机器人启动成功', 'success');
    } else {
      showNotification(`启动失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误或服务器未响应', 'error');
  } finally {
    this.isSlackStarting = false;
  }
},

async stopSlackBot() {
  this.isSlackStopping = true;
  try {
    const res = await fetch('/stop_slack_bot', { method: 'POST' });
    const json = await res.json();
    if (json.success) {
      this.isSlackBotRunning = false;
      showNotification('Slack 机器人已停止', 'success');
    } else {
      showNotification(`停止失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isSlackStopping = false;
  }
},

async reloadSlackBot() {
  this.isSlackReloading = true;
  try {
    const res = await fetch('/reload_slack_bot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...this.slackBotConfig,
        memory_settings: this.memorySettings
      }),
    });
    const json = await res.json();
    if (json.success) {
      showNotification('Slack 机器人已重载', 'success');
    } else {
      showNotification(`重载失败：${json.message}`, 'error');
    }
  } catch (e) {
    showNotification('网络错误', 'error');
  } finally {
    this.isSlackReloading = false;
  }
},

async checkSlackBotStatus() {
  try {
    const res = await fetch('/slack_bot_status');
    const st = await res.json();
    this.isSlackBotRunning = st.is_running;
  } catch (e) {
    console.error('检查 Slack 状态失败', e);
  }
},

handleCreateSlackSeparator(val) {
  this.slackBotConfig.separators.push(val);
},

    async handleSeparatorChange(val) {
      this.qqBotConfig.separators = val.map(s => 
        s.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
      );
      await this.autoSaveSettings();
    },

    formatSeparator(s) {
      return s.replace(/\n/g, '\\n')
              .replace(/\t/g, '\\t')
              .replace(/\r/g, '\\r');
    },

    // 新增创建分隔符处理方法
    async handleCreateSeparator(newSeparator) {
      const processed = this.escapeSeparator(newSeparator)
      if (!this.qqBotConfig.separators.includes(processed)) {
        this.qqBotConfig.separators.push(processed)
        await this.autoSaveSettings()
      }
    },

    escapeSeparator(s) {
      return s.replace(/\\n/g, '\n').replace(/\\t/g, '\t')
    },

async fetchXmppCertPending() {
  try {
    const res = await fetch('/xmpp_cert_pending');
    const json = await res.json();
    this.xmppCertPending = json.pending || [];
  } catch (e) {
    this.xmppCertPending = [];
  }
},

async xmppCertDecision(key, decision) {
  try {
    const res = await fetch('/xmpp_cert_decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ key, decision })
    });
    const json = await res.json();
    if (!json.success) {
      showNotification(`证书决策失败：${json.message}`, 'error');
      return;
    }
    await this.fetchXmppCertPending();
    if (decision === 'once') showNotification('本次运行内信任该证书（重启后需重新确认）', 'info');
    if (decision === 'always') showNotification('已永久信任该证书，正在重新启动机器人...', 'success');
    if (decision !== 'reject') {
      await this.startXmppBot();
      await this.fetchXmppCertPending();
    } else {
      showNotification('已拒绝该证书', 'info');
    }
  } catch (e) {
    showNotification('网络错误：证书决策未送达', 'error');
  }
}
});
