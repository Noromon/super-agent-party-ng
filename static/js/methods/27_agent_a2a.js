// 批 3 F2：自 vue_methods.js 搬移的 methods/27_agent_a2a.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    /**
     * 监听输入方式切换 (Form <-> JSON)
     */
    handleInputMethodChange(val) {
      if (val === 'json') {
        // 刚才在 Form 模式，切去 JSON -> 把表单转为 JSON
        this.syncFormToJson();
      } else {
        // 刚才在 JSON 模式，切去 Form -> 把 JSON 解析进表单
        this.syncJsonToForm();
      }
    },

    /**
     * 将表单数据同步到 JSON 字符串
     */
    syncFormToJson() {
      // 如果表单名字都没填，可能还没开始编辑，就不覆盖 JSON 了
      if (!this.newMCPFormData.name) return;

      try {
        // 复用之前写过的构建配置对象的逻辑 (如果之前封装了 buildCurrentMCPConfig 可以复用，这里为了独立性单独写)
        const mcpId = this.newMCPFormData.name;
        let servers = {};
        
        if (this.newMCPType === 'stdio') {
          servers = { "command": this.newMCPFormData.command };
          if (this.newMCPFormData.args) {
             servers['args'] = this.newMCPFormData.args.split('\n').map(arg => arg.trim()).filter(arg => arg);
          }
          if (this.newMCPFormData.env) {
            servers['env'] = this.newMCPFormData.env.split('\n').map(e => e.trim()).filter(e => e).reduce((acc, cur) => {
              const parts = cur.split('=');
              if (parts.length >= 2) acc[parts[0].trim()] = parts.slice(1).join('=').trim();
              return acc;
            }, {});
          }
        } else {
          servers = { "url": this.newMCPFormData.url };
          // 构建 Headers
          if (this.newMCPFormData.apiKey) {
            servers['headers'] = { "Authorization": `Bearer ${this.newMCPFormData.apiKey.trim()}` };
          }
        }

        const fullConfig = { mcpServers: { [mcpId]: servers } };
        this.newMCPJson = JSON.stringify(fullConfig, null, 2);
      } catch (e) {
        console.error("Sync Form to JSON failed:", e);
      }
    },

    /**
     * 将 JSON 字符串同步到表单数据
     */
    syncJsonToForm() {
      if (!this.newMCPJson || !this.newMCPJson.trim()) return;

      try {
        const input = this.newMCPJson.trim();
        // 容错处理：支持纯对象内容或完整 mcpServers 结构
        const parsed = JSON.parse(input.startsWith('{') ? input : `{${input}}`);
        const serversMap = parsed.mcpServers || parsed;
        const names = Object.keys(serversMap);
        
        if (names.length === 0) return;

        const name = names[0]; // 取第一个服务器
        const config = serversMap[name];

        // 1. 填充名字
        this.newMCPFormData.name = name;

        // 2. 判断类型并填充字段
        if (config.command) {
          // 是 Stdio 类型
          this.newMCPType = 'stdio';
          this.newMCPFormData.command = config.command;
          this.newMCPFormData.args = Array.isArray(config.args) ? config.args.join('\n') : '';
          this.newMCPFormData.env = config.env ? Object.entries(config.env).map(([k, v]) => `${k}=${v}`).join('\n') : '';
        } else if (config.url) {
          // 是 HTTP/SSE/WS 类型
          // 如果当前 newMCPType 还是 stdio，就切成 sse，否则保留用户选择的 (ws/streamablehttp)
          if (this.newMCPType === 'stdio') {
             this.newMCPType = 'sse'; 
          }
          this.newMCPFormData.url = config.url;
          
          // 尝试提取 API Key
          if (config.headers && config.headers.Authorization) {
            this.newMCPFormData.apiKey = config.headers.Authorization.replace('Bearer ', '');
          } else {
            this.newMCPFormData.apiKey = '';
          }
        }
      } catch (e) {
        console.warn("JSON parse failed during sync:", e);
        // JSON 格式可能有误，暂不强制覆盖表单，以免用户数据丢失
      }
    },

      // 保存智能体
    truncatePrompt(text) {
      return text.length > 100 ? text.substring(0, 100) + '...' : text;
    },

    async saveAgent() {
      const payload = {
        type: 'save_agent',
        data: {
          name: this.newAgent.name,
          system_prompt: this.newAgent.system_prompt
        }
      };
      this.ws.send(JSON.stringify(payload));
      this.showAgentForm = false;
      this.newAgent = {
        id: '',
        name: '',
        system_prompt: ''
      };
    },

    copyAgentId(id) {
      navigator.clipboard.writeText(id)
      showNotification(`Agent ID: ${id} copyed`, 'success');
    },

    copyAgentName(name) {
      navigator.clipboard.writeText(name)
      showNotification(`Agent Name: ${name} copyed`, 'success');
    },

    async removeAgent(id) {
      if (this.agents.hasOwnProperty(id)) {
        delete this.agents[id]
        this.agents = { ...this.agents }
        try {
          // 向/delete_file发送请求
          const response = await fetch(`/remove_agent`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ agentId: id })
          });
          // 处理响应
          if (response.ok) {
            console.log('Agent deleted successfully');
            showNotification(this.t('AgentDeleted'), 'success');
          }
        } catch (error) {
          console.error('Error:', error);
          showNotification(this.t('AgentDeleteFailed'), 'error');
        }
      }
      await this.autoSaveSettings();
    },

    isValidUrl(url) {
      try {
        new URL(url);
        return true;
      } catch {
        return false;
      }
    },

    async addA2AServer() {
      // newurl 必须声明在 try 之前：catch 的失败清理分支需要可见（原声明在 try 体内=
      // 初始化失败时 catch 抛 ReferenceError，清理与报错提示双双失效）
      const newurl = this.newA2AUrl;
      try {
        this.showAddA2ADialog = false;
        this.newA2AUrl = '';
        this.a2aServers = {
          ...this.a2aServers,
          [newurl]: {
            status: 'initializing',
          }
        };
        await this.autoSaveSettings();
        const response = await fetch(`/a2a`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: newurl })
        });
        
        const data = await response.json();
        this.a2aServers[newurl] = {
          ...this.a2aServers[newurl],
          ...data
        }

        await this.autoSaveSettings();
      } catch (error) {
        console.error('A2A初始化失败:', error);
        this.a2aServers = Object.fromEntries(Object.entries(this.a2aServers).filter(([k]) => k !== newurl));
        await this.autoSaveSettings();
        showNotification(this.t('a2aInitFailed'), 'error');
      }
    },

    async removeA2AServer(url) {
      this.a2aServers = Object.fromEntries(Object.entries(this.a2aServers).filter(([k]) => k !== url));
      await this.autoSaveSettings();
    }
});
