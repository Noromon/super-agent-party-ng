// 批 3 F2：自 vue_methods.js 搬移的 methods/70_memory_io.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // S77(1c33bc74)：移除破坏 JSON/API 传输的控制字符（保留换行、回车、制表符）
    _sanitizeCardText(raw, maxLen = 100 * 1024) {
      if (typeof raw !== 'string') return raw || '';
      let cleaned = raw.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
      if (cleaned.length > maxLen) {
        console.warn(`[_sanitizeCardText] 字段过长 ${cleaned.length} > ${maxLen}，已截断`);
        cleaned = cleaned.substring(0, maxLen);
      }
      return cleaned;
    },

    downloadMemory(memory) {
      // 仅导出酒馆 V3 所需字段，敏感信息全部剔除
      const card = {
        spec: 'chara_card_v3',
        spec_version: '3.0',
        name: memory.name,
        description: memory.description || '',
        avatar: memory.avatar || '',
        personality: memory.personality || '',
        mes_example: memory.mesExample || '',
        first_mes: memory.firstMes || '',
        system_prompt: memory.systemPrompt || '',
        alternate_greetings: Array.isArray(memory.alternateGreetings)
          ? memory.alternateGreetings.filter(Boolean)
          : [],
        character_book: {
          name: memory.name,
          entries: Array.isArray(memory.characterBook)
            ? memory.characterBook
                .filter(e => e.keysRaw?.trim() && e.content?.trim())
                .map((e, idx) => ({
                  id: idx,
                  keys: e.keysRaw
                    .split(/\r?\n/)
                    .map(k => k.trim())
                    .filter(Boolean),
                  secondary_keys: [],
                  content: e.content,
                  comment: '',
                  constant: false,
                  selective: true,
                  insertion_order: 100,
                  enabled: true,
                  position: 'before_char',
                  use_regex: true,
                  extensions: {}
                }))
            : []
        }
        // 其余字段如 avatar、tags、scenario…按需补空
      };

      const blob = new Blob([JSON.stringify(card, null, 2)], {
        type: 'application/json'
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${memory.name}_v3.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    },

    changeMemory() {
      if (this.memorySettings.is_memory){
        // 根据selectedMemory获取当前的memories中的对应的记忆
        let curMemory = this.memories.find(memory => memory.id === this.memorySettings.selectedMemory);
        this.firstMes = curMemory.firstMes;
        this.alternateGreetings= curMemory.alternateGreetings;
      }
      else{
        this.firstMes = '';
        this.alternateGreetings = [];
      }
      this.randomGreetings();
      this.autoSaveSettings(); // 保存设置
    },

    randomGreetings() {
      let greetings = [this.firstMes, ...this.alternateGreetings];
      // 过滤掉空字符串
      greetings = greetings.filter(greeting => greeting.trim() !== '');
      // 替换掉开场白中的所有的{{user}}为this.memorySettings.userName
      greetings = greetings.map(greeting => greeting.replace(/{{user}}/g, this.memorySettings.userName));
      // 根据selectedMemory获取当前的memories中的对应的记忆
      let curMemory = this.memories.find(memory => memory.id === this.memorySettings.selectedMemory);
      // 替换掉开场白中的所有的{{char}}为curMemory.name
      greetings = greetings.map(greeting => greeting.replace(/{{char}}/g, curMemory.name));
      if (greetings.length > 0) {
        let randomIndex = Math.floor(Math.random() * greetings.length);
        // 将随机的开场白立刻加入的this.messages中
        // 如果this.messages中第二个元素是开场白，则替换，否则在第一个元素之后插入
        if (this.messages.length > 1 && this.messages[1].role === 'assistant') {
          this.messages[1].content = greetings[randomIndex];
          this.messages[1].pure_content = greetings[randomIndex];
        } else {
          this.messages.splice(1, 0, {
            role: 'assistant',
            content: greetings[randomIndex],
            pure_content: greetings[randomIndex],
          });
        }
      } 
      else{
        // 如果this.messages中第二个元素是开场白，则移除
        if (this.messages.length > 1 && this.messages[1].role === 'assistant') {
          this.messages.splice(1, 1);
        }
      }
    },

    browseJsonFile() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json,.png';          // 关键：多给一个 png
      input.onchange = (event) => {
        const file = event.target.files[0];
        if (!file) return;
        if (file.name.toLowerCase().endsWith('.png')) {
          this.handlePngAsJson(file);        // 新增分支
        } else {
          this.handleFileUpload(file);       // 原 JSON 分支
        }
      };
      input.click();
    },

    handleJsonDrop(event) {
      const file = event.dataTransfer.files[0];
      if (!file) return;
      const isPng = file.type === 'image/png' ||
                    file.name.toLowerCase().endsWith('.png');
      const isJson = file.type === 'application/json' ||
                    file.name.toLowerCase().endsWith('.json');

      if (isPng) {
        this.handlePngAsJson(file);
      } else if (isJson) {
        this.handleFileUpload(file);
      } else {
        showNotification('Please upload a valid JSON or PNG character card.', 'error');
      }
    },

    async handlePngAsJson(file) {
      // 1. 把 PNG 当成普通图片先上传，拿外链
      const formData = new FormData();
      formData.append('files', file);   // 字段名跟 /load_file 接口保持一致

      let imageUrl;
      try {
        const up = await fetch('/load_file', { method: 'POST', body: formData });
        if (!up.ok) throw new Error('upload failed');
        const res = await up.json();
        if (!res.success || !res.fileLinks || !res.fileLinks[0])
          throw new Error('no url returned');
        imageUrl = res.fileLinks[0].path;          // 后端返回的完整 URL
        // 可选：把这张图片也塞进 imageFiles 列表，保持界面同步
        this.imageFiles = [...this.imageFiles, ...res.imageFiles];
      } catch (e) {
        console.error(e);
        showNotification('PNG upload failed', 'error');
        return;
      }

      // 2. 拆包拿 JSON
      const jsonText = await this.extractJsonFromPng(file);
      if (!jsonText) return;   // 通知已在内部弹过

      // 3. 把 avatar 换成刚上传的 URL
      let jsonData;
      try {
        jsonData = JSON.parse(jsonText);
      } catch {
        showNotification('Invalid JSON inside PNG', 'error');
        return;
      }
      // 兼容 V2/V3
      const target = jsonData.data || jsonData;
      target.avatar = imageUrl;   // 直接覆盖

      // 4. 走现有逻辑回填表单
      this.importMemoryData(jsonData);
      this.jsonFile = file;       // 保留文件对象，方便移除按钮
      showNotification('Character card imported from PNG', 'success');
    },

    async extractJsonFromPng(file) {
      const buffer = await file.arrayBuffer();
      const png = new Uint8Array(buffer);
      const sign = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
      if (!sign.every((b, i) => b === png[i])) {
        showNotification('Not a valid PNG file', 'error');
        return null;
      }

      let pos = 8;
      const view = new DataView(buffer);
      let jsonText = null;

      while (pos < png.length) {
        const len  = view.getUint32(pos);
        const type = String.fromCharCode(...png.slice(pos + 4, pos + 8));
        const start = pos + 8;
        const end   = start + len;

        if (type === 'tEXt') {
          const data = png.slice(start, end);
          const zero = data.indexOf(0);
          if (zero > 0) {
            const key = new TextDecoder().decode(data.slice(0, zero)).toLowerCase();
            if (key === 'chara' || key === 'ccv3') {
              const b64 = new TextDecoder().decode(data.slice(zero + 1));
              try {
                jsonText = new TextDecoder().decode(
                  Uint8Array.from(atob(b64), c => c.charCodeAt(0))
                );
                if (key === 'ccv3') break;
              } catch {}
            }
          }
        }
        if (type === 'IEND') break;
        pos = end + 4; // 跳过 CRC
      }

      if (!jsonText) showNotification('No character data found in PNG', 'error');
      return jsonText;
    },

    importMemoryData(jsonData) {
      // 兼容 V2/V3：统一抽出 data
      const data = jsonData.data || jsonData;

      const s = this._sanitizeCardText.bind(this);   // S77: 导入清洗
      this.newMemory = {
        ...this.newMemory,                      // 保持 providerId 等旧字段
        name: s(data.name).substring(0, 512),   // 名称限制 512 字符
        description: s(data.description),
        avatar: data.avatar || '',
        personality: s(data.personality),
        mesExample: s(data.mes_example),
        systemPrompt: s(data.system_prompt),
        firstMes: s(data.first_mes),
        alternateGreetings: Array.isArray(data.alternate_greetings)
          ? data.alternate_greetings
          : [''],
        characterBook:
          Array.isArray(data.character_book?.entries) &&
          data.character_book.entries.length
            ? data.character_book.entries.map(e => ({
                keysRaw: (e.keys || []).join('\n'),
                content: e.content || ''
              }))
            : [{ keysRaw: '', content: '' }]
      };
    }
});
