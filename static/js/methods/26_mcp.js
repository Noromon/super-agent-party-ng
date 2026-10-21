// 批 3 F2：自 vue_methods.js 搬移的 methods/26_mcp.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    async getInternalIP() {
        try {
            const response = await fetch('/api/ip'); // 假设接口在同域名下
            const data = await response.json();
            return data.ip;
        } catch (error) {
            console.error("Failed to fetch internal IP:", error);
            return "127.0.0.1";
        }
    },

    async generateQRCode() {
      // 确保 partyURL 存在且 DOM 已渲染
      if (!this.partyURL) return;
      // 获取内网 IP
      const internalIP = await this.getInternalIP();

      // 替换 URL 中的 127.0.0.1 或 localhost，保留端口和路径
      const url = new URL(this.partyURL);
      if (url.hostname === '127.0.0.1' || url.hostname === 'localhost') {
        url.hostname = internalIP;
      }
      let qr_url = url.toString();
      const canvas = document.getElementById('qrcode');

      // 生成二维码
      QRCode.toCanvas(canvas, qr_url, function(error) {
            if (error) {
                console.error(error);
            } else {
                console.log("QR Code successfully generated!");
            }
        });
    },

    /**
     * 辅助方法：根据当前表单/JSON输入构建配置对象
     * 返回 { mcpId, serversObj, inputStr }
     */
    buildCurrentMCPConfig() {
      let mcpId = "mcp";
      let servers = {};
      let inputStr = "";

      if (this.mcpInputType === 'json') {
        const input = this.newMCPJson.trim();
        const parsed = JSON.parse(input.startsWith('{') ? input : `{${input}}`);
        const parsedServers = parsed.mcpServers || parsed;
        mcpId = Object.keys(parsedServers)[0];
        servers = parsedServers[mcpId];
        inputStr = input;
      } else {
        mcpId = this.newMCPFormData.name;
        
        if (this.newMCPType === 'stdio') {
          servers = { "command": this.newMCPFormData.command };
          
          // args
          let args = this.newMCPFormData.args;
          if (args) {
             servers['args'] = args.split('\n').map(arg => arg.trim()).filter(arg => arg);
          }
          
          // env
          let env = this.newMCPFormData.env;
          if (env) {
            servers['env'] = env.split('\n').map(e => e.trim()).filter(e => e).reduce((acc, cur) => {
              const parts = cur.split('=');
              if (parts.length >= 2) {
                  const key = parts[0].trim();
                  const value = parts.slice(1).join('=').trim();
                  acc[key] = value;
              }
              return acc;
            }, {});
          }
        } else {
          servers = { "url": this.newMCPFormData.url };
          let ContentType = 'application/json';
          if (this.newMCPType == 'sse') ContentType = 'text/event-stream';
          else if (this.newMCPType == 'ws') ContentType = 'text/plain';
          
          if (this.newMCPFormData.apiKey && this.newMCPFormData.apiKey.trim() != '') {
            servers['headers'] = {
              "Authorization": `Bearer ${this.newMCPFormData.apiKey.trim()}`,
              "Content-Type": ContentType
            }
          }
        }

        // 构建 input 字符串用于存储
        let inputObj = { "mcpServers": {} };
        inputObj.mcpServers[mcpId] = servers;
        inputStr = JSON.stringify(inputObj, null, 2);
      }

      return { mcpId, servers, inputStr };
    },

    /**
     * 修改后的添加方法：直接调用 buildCurrentMCPConfig
     */
    async addMCPServer() {
      try {
        const { mcpId, servers, inputStr } = this.buildCurrentMCPConfig();

        // 更新本地状态
        this.mcpServers = {
          ...this.mcpServers,
          [mcpId]: {
            ...servers, // 新的配置
            processingStatus: 'initializing',
            disabled: true,
            type: this.newMCPType,
            input: inputStr,
            // 如果是编辑模式调用 addMCPServer (即重启)，保留原有的 tools 以防万一，或者清空看需求
            // 这里为了UI不闪烁，如果ID相同，暂时保留旧tools，等ready了再覆盖
            tools: (this.mcpServers[mcpId] && this.mcpServers[mcpId].tools) || []
          }
        };

        this.isSubmitting = true;
        this.currentEditingMCPId = mcpId;
        
        await this.autoSaveSettings();

        // 触发后台创建
        await fetch(`/create_mcp`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ mcpId })
        });

        // 轮询状态
        await this.pollMCPStatus(mcpId); // 复用之前写的 poll 方法

        // 成功后切换模式
        this.isEditMode = true;
        this.activeDialogTab = 'tools';
      } catch (error) {
        console.error('MCP Add Error:', error);
        showNotification(error.message, 'error');
        if (this.currentEditingMCPId && this.mcpServers[this.currentEditingMCPId]) {
             this.mcpServers[this.currentEditingMCPId].processingStatus = 'server_error';
        }
      } finally {
        this.isSubmitting = false;
        await this.autoSaveSettings();
      }
    },

    /**
     * 更新配置逻辑：智能判断是否需要重启
     */
    async updateMCPServerConfig() {
      const currentId = this.currentEditingMCPId;
      const oldServer = this.mcpServers[currentId];
      
      if (!oldServer) return;

      // 1. 获取新表单对应的配置
      // 注意：这里我们只构建对象，暂时不写入 this.mcpServers
      let newConfigData;
      try {
        newConfigData = this.buildCurrentMCPConfig();
      } catch (e) {
        showNotification(this.t('invalidConfig'), 'error');
        return;
      }
      
      const { servers: newServersObj } = newConfigData;

      // 2. 比较关键字段是否变更 (Command, Args, Env, Url, Headers)
      // 忽略 tools, processingStatus, disabled 等状态字段
      const isConfigurationChanged = !this.isSameMCPConfig(oldServer, newServersObj);

      if (isConfigurationChanged) {
        // A. 如果配置变了 -> 走完整的重启流程 (即 addMCPServer)
        console.log("Configuration changed, restarting MCP...");
        await this.addMCPServer();
      } else {
        // B. 如果配置没变 (只是动了 Switch 或点了保存) -> 直接关闭
        console.log("Configuration identical, skipping restart.");
        showNotification(this.t('settingsSaved'), 'success');
        this.showAddMCPDialog = false;
      }
    },

    /**
     * 深度比较两个 MCP 配置对象 (仅比较核心连接参数)
     */
    isSameMCPConfig(oldSrv, newSrv) {
      // 比较辅助函数
      const jsonEq = (a, b) => JSON.stringify(a) === JSON.stringify(b);

      // 1. 比较基础类型
      // 注意：oldSrv 可能包含 extra 字段，newSrv 是纯净的配置对象
      // 我们只检查 newSrv 里有的字段
      
      // StdIO 检查
      if (newSrv.command !== oldSrv.command) return false;
      if (!jsonEq(newSrv.args, oldSrv.args)) return false;
      if (!jsonEq(newSrv.env, oldSrv.env)) return false;

      // HTTP/SSE/WS 检查
      if (newSrv.url !== oldSrv.url) return false;
      if (!jsonEq(newSrv.headers, oldSrv.headers)) return false;

      return true;
    },

    // 在methods中添加
    // 打开添加对话框的辅助函数
    openAddDialog() {
      this.showAddMCPDialog = true;
      this.activeDialogTab = 'config';
      this.isEditMode = false;
      this.isSubmitting = false;
      this.currentEditingMCPId = null;
      this.newMCPJson = '';
      this.newMCPFormData = { name: '', command: '', args: '', env: '', url: '', apiKey: '' };
      this.updateMCPExample();
    },

    // 重置弹窗状态
    resetDialogState() {
        this.newMCPJson = '';
        this.isSubmitting = false;
        // 注意：不要在这里设 showAddMCPDialog = false，因为这是 closed 事件
    },

    // 抽离轮询逻辑
    async pollMCPStatus(mcpId) {
       return new Promise((resolve, reject) => {
          let checkCount = 0;
          const maxChecks = 30; // 例如 60秒超时

          const interval = setInterval(async () => {
            checkCount++;
            try {
              const statusRes = await fetch(`/mcp_status/${mcpId}`);
              const data = await statusRes.json();
              const { status, tools } = data;

              if (status === 'ready') {
                clearInterval(interval);
                this.mcpServers[mcpId] = {
                  ...this.mcpServers[mcpId],
                  processingStatus: 'ready',
                  disabled: false,
                  tools: JSON.parse(tools)    
                };
                showNotification(this.t('mcpAdded'), 'success');
                resolve(true); // 成功
              } else if (status.startsWith('failed') || status === 'server_error') {
                clearInterval(interval);
                this.mcpServers[mcpId].processingStatus = 'server_error';
                showNotification(this.t('mcpCreationFailed'), 'error');
                resolve(false); // 虽然失败，但也算结束了轮询
              } else if (checkCount >= maxChecks) {
                clearInterval(interval);
                this.mcpServers[mcpId].processingStatus = 'server_error';
                reject(new Error("Timeout waiting for MCP server"));
              }
            } catch(e) {
               // 网络错误等
               clearInterval(interval);
               reject(e);
            }
          }, 2000);
       });
    },

    // 编辑已有服务器
    editMCPServer(name) {
      this.isEditMode = true;
      this.activeDialogTab = 'config';
      this.currentEditingMCPId = name;
      this.isSubmitting = false;

      const server = this.mcpServers[name];
      this.newMCPType = server.type || 'stdio'; // 默认回退
      this.newMCPJson = server.input;
      
      // 根据类型判断 inputType (如果有 input 且是 json 格式比较多，可能是 json，否则 form)
      // 简单起见，如果 editMCPServer 被调用，我们尝试填充 Form 数据
      this.mcpInputType = 'form'; // 或者根据是否有 input 字符串决定

      this.newMCPFormData = {
        name: name,
        command: server.command || '',
        args: server.args ? server.args.join('\n') : '',
        env: server.env ? Object.entries(server.env).map(([k, v]) => `${k}=${v}`).join('\n') : '',
        url: server.url || '',
        apiKey: server.headers?.Authorization?.split(' ')[1] || '',
      };
      
      this.showAddMCPDialog = true;
    },

    async restartMCPServer(name) {
       // 保持原有逻辑，或者也可以打开弹窗显示 loading
       // 这里简单复用原有逻辑，但加上 try catch
       this.mcpServers[name].processingStatus = 'initializing';
       // ... existing restart logic
       // 如果你想重启时也看弹窗状态，可以调用 editMCPServer(name) 然后 auto trigger logic
       // 但通常重启是卡片上的快捷操作，保持原样即可。
       // 只需要加上轮询更新:
       try {
         await fetch(`/create_mcp`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ mcpId: name })
            });
         this.pollMCPStatus(name); // 不 await，让它后台跑
       } catch(e) {
         console.error(e);
       }
    },

    async removeMCPServer(name) {
      this.deletingMCPName = name
      this.showMCPConfirm = true
    },

    // 新增确认方法
    async confirmDeleteMCP() {
      try {
        const response = await fetch(`/remove_mcp`, {
          method: 'DELETE',
          headers: {
              'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            serverName: this.deletingMCPName
          })
        });
        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail || '删除失败');
        }
        
        showNotification(this.t('mcpDeleted'), 'success')
      } catch (error) {
        console.error('Error:', error.message)
        showNotification(this.t('mcpDeleteFailed'), 'error')
      } finally {
        const name = this.deletingMCPName
        const newServers = { ...this.mcpServers }
        delete newServers[name]
        this.mcpServers = newServers
        
        this.$nextTick(async () => {
          await this.autoSaveSettings();
        })
        this.showMCPConfirm = false
      }
    }
});
