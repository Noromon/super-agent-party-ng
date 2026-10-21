// 批 3 F2：自 vue_methods.js 搬移的 methods/74_read_aloud.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  async confirmClearAll() {
    await this.clearAllHistoryRecords();
  },

  async keepLastWeek() {
    try {
      await this.$confirm(this.t('confirmKeepLastWeek'), this.t('warning'), {
        confirmButtonText: this.t('confirm'),
        cancelButtonText: this.t('cancel'),
        type: 'warning'
      });

      const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
      this.conversations = this.conversations.filter(conv => 
        conv.timestamp && conv.timestamp >= oneWeekAgo
      );
      if (this.conversations.length === 0){
        this.conversationId = null; // 清空当前对话ID
      }
      
      await this.saveConversations();
    } catch (error) {
      // 用户取消操作
    }
  },

    /* ===============  朗读主流程  =============== */
toggleRead() {
  if (this.isReadRunning) {
    if (this.isReadPaused) {
      this.resumeRead();
    } else {
      this.pauseRead();
    }
  } else {
    this.startRead();
  }
},

// 修改后的startRead方法
async startRead() {
  if (!this.readConfig.longText.trim()) return;
  
  this.stopSegmentTTS();
  this.readState.currentChunk = 0;
  this.isReadStarting = true;
  this.isReadRunning  = true;
  this.isReadPaused   = false;  // 重置暂停状态
  this.isReadStopping = false;

  /* 清空上一次的残留 */
  this.readState.ttsChunks  = [];
  this.readState.audioChunks = [];
  this.readState.currentChunk = 0;
  this.readState.isPlaying = false;
  this.readState.chunks_voice = [];
  this.cur_voice = 'default';
  
  /* 重置音频计数状态 */
  this.audioChunksCount = 0;
  this.totalChunksCount = 0;

  /* 分段处理逻辑（保持原有） */
  const {
    chunks,
    chunks_voice,
    remaining,
    remaining_voice
  } = this.splitTTSBuffer(this.readConfig.longText);

  if (remaining) {
    chunks.push(remaining);
    chunks_voice.push(remaining_voice);
  }

  /* 去标签 + 去空白并同步删除 */
  const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());
  const finalChunks = [];
  const finalChunksVoice = [];

  cleanedChunks.forEach((txt, idx) => {
    if (txt) {
      finalChunks.push(txt);
      finalChunksVoice.push(chunks_voice[idx]);
    }
  });

  if (!finalChunks.length) {
    this.isReadRunning  = false;
    this.isReadStarting = false;
    return;
  }

  this.readState.ttsChunks   = finalChunks;
  this.readState.chunks_voice = finalChunksVoice;
  this.totalChunksCount = finalChunks.length;

  /* 通知 VRM 开始朗读 */
  this.sendTTSStatusToVRM('ttsStarted', {
    totalChunks: this.readState.ttsChunks.length
  });

  this.isReadStarting = false;

  /* 并发 TTS */
  this.isAudioSynthesizing = true;
  await this.startReadTTSProcess();
},

// 新增：暂停朗读
pauseRead() {
  if (!this.isReadRunning || this.isReadPaused) return;
  
  this.isReadPaused = true;
  
  // 暂停当前音频
  if (this.currentReadAudio) {
    this.currentReadAudio.pause();
  }
  
  // 通知 VRM 暂停
  this.sendTTSStatusToVRM('pauseSpeaking', {});
},

// 新增：恢复朗读
resumeRead() {
  if (!this.isReadRunning || !this.isReadPaused) return;
  
  this.isReadPaused = false;
  
  // 恢复当前音频播放
  if (this.currentReadAudio) {
    this.currentReadAudio.play().catch(console.error);
  }
  
  // 通知 VRM 恢复
  this.sendTTSStatusToVRM('resumeSpeaking', {});
  
  // 尝试继续播放后续音频
  this.checkReadAudioPlayback();
},

    // 修改 processReadTTSChunk 方法
    async processReadTTSChunk(index) {
      try {
        const chunk = this.readState.ttsChunks[index];
        const voice = this.readState.chunks_voice[index];
        const cachedAudio = this.readState.audioChunks[index];

        // 检查缓存是否命中
        if (cachedAudio?.url && cachedAudio?.base64 && cachedAudio?.text === chunk && cachedAudio?.voice === voice) {
          this.cur_audioDatas[index] = cachedAudio.base64;
        }
        else{
          /* —— 与对话版完全一致的文本清洗 —— */
          let chunk_text = chunk;
          let  chunk_expressions = [];
          if (chunk.indexOf('<') !== -1) {
              const tagReg = /<[^>]+>/g;
              chunk_expressions = (chunk.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
              chunk_text = chunk.replace(tagReg, '').trim();
          }

          const res = await fetch('/tts', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ttsSettings: this.ttsSettings,
              text: chunk_text,
              index,
              voice
            })
          });

          if (!res.ok) throw new Error('TTS failed');

          const blob = await res.blob();
          const url  = URL.createObjectURL(blob);

          /* Base64 给 VRM */
          const base64 = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload  = () => resolve(reader.result.split(',')[1]);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
          });
          this.cur_audioDatas[index] = `data:${blob.type};base64,${base64}`;
          /* 缓存两样东西 */
          this.readState.audioChunks[index] = {
            url,                       // 本地播放用
            expressions: chunk_expressions,
            base64: this.cur_audioDatas[index], // VRM 播放用
            text: chunk_text,
            index,
            voice
          };
        }

        /* 新增: 增加已生成片段计数 */
        this.audioChunksCount++;
        
        /* 新增: 检查是否全部合成完成 */
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }

        /* 立刻尝试播放 */
        this.checkReadAudioPlayback();
      } catch (e) {
        console.error(`Read TTS chunk ${index} error`, e);
        // chunk_text/chunk_expressions 声明在 try 的 else 块内，catch 不可见：
        // 错误槽位直接用原始 chunk 回填（url:null 不会被缓存命中）
        this.readState.audioChunks[index] = { url: null, expressions: [], text: this.readState.ttsChunks[index] ?? "", index };
        this.cur_audioDatas[index] = null;
        
        /* 新增: 处理错误时也增加计数 */
        this.audioChunksCount++;
        
        /* 新增: 检查是否全部合成完成 */
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
        
        this.checkReadAudioPlayback();
      }
    },

    async ClickToListen(SampleText,voice='default') {
      if (!SampleText) {
        SampleText ='super agent party链接一切！'
      }

    try {
      // 创建副本，避免直接修改 this.ttsSettings
      let Settings = { ...this.ttsSettings };

      if (this.showAddTTSDialog) {
        Settings = { ...Settings, ...this.newTTSConfig };
      } else if (voice !== 'default' && this.ttsSettings.newtts && this.ttsSettings.newtts[voice]) {
        // 从角色语音卡片调用：合并角色配置
        Settings = { ...Settings, ...this.ttsSettings.newtts[voice] };
      }

      // ★ 关键修复：附带 modelProviders，供后端查找 API Key
      // 后端逻辑：如果角色配置缺少api_key但有selectedProvider，会从这里查找
      if (this.modelProviders && Array.isArray(this.modelProviders)) {
        Settings.modelProviders = this.modelProviders;
      }

        const res = await fetch('/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ttsSettings: Settings,
            text: SampleText,
            index: 0,          // 随便给个 index，后端不关心
            voice: voice || 'default'
          })
        });
        if (!res.ok) throw new Error('TTS failed');

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);

        /* 直接播放 */
        const audio = new Audio(url);
        audio.play().catch(console.error);

        /* 播放完清掉内存 */
        audio.onended = () => URL.revokeObjectURL(url);
      } catch (e) {
        console.error('ClickToListen error', e);
      }
    },

    // 2. 重写 createCombinedAudio：核心修改是“自动识别真实格式”
    async createCombinedAudio(chunks) {
      if (!chunks || chunks.length === 0) return;

      showNotification(this.t('audioProcessingStarted') || '正在处理音频...');

      try {
        // ================= 关键步骤：探测真实格式 =================
        // 先 Fetch 第一个片段，查看 HTTP 头或 Blob 类型，以此为准
        const firstResponse = await fetch(chunks[0].url);
        const firstBlob = await firstResponse.blob();
        
        // 获取真实的 MIME (例如: "audio/ogg; codecs=opus" -> "audio/ogg")
        const realMimeType = firstBlob.type.split(';')[0]; 
        
        console.log('Detected Real Audio Format:', realMimeType);

        // 根据真实 MIME 推导后缀名和处理逻辑
        let extension = 'mp3'; // 默认
        let isWav = false;

        if (realMimeType.includes('wav')) {
          extension = 'wav';
          isWav = true;
        } else if (realMimeType.includes('ogg')) {
          extension = 'ogg';
        } else if (realMimeType.includes('aac')) {
          extension = 'aac';
        } else if (realMimeType.includes('flac')) {
          extension = 'flac';
        } else if (realMimeType.includes('webm')) {
          extension = 'webm';
        } else if (realMimeType.includes('mp4') || realMimeType.includes('m4a')) {
          extension = 'm4a';
        }

        // ================= 开始获取所有数据 =================
        // 重用第一个 Blob，减少一次请求
        const firstBuffer = await firstBlob.arrayBuffer();
        
        // 并发获取剩余片段
        const restPromises = chunks.slice(1).map(async (chunk) => {
          const response = await fetch(chunk.url);
          return response.arrayBuffer();
        });
        
        const restBuffers = await Promise.all(restPromises);
        const allBuffers = [firstBuffer, ...restBuffers];

        // ================= 根据真实格式合并 =================
        let combinedBuffer;

        if (isWav) {
          // WAV 专用处理：去头
          combinedBuffer = this.mergeWavBuffers(allBuffers);
        } else {
          // 其他格式（MP3, OGG等）：直接拼接
          // 注意：OGG 直接拼接在浏览器中播放可能只能听第一句（Chained Ogg），
          // 但下载后用本地播放器（VLC/PotPlayer）是完整的。这是无损拼接的特性。
          combinedBuffer = this.mergeGeneralBuffers(allBuffers);
        }

        // ================= 下载文件 =================
        const blob = new Blob([combinedBuffer], { type: realMimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-');
        
        a.href = url;
        // 使用探测到的真实后缀名
        a.download = `tts-merged-${timestamp}.${extension}`; 
        
        document.body.appendChild(a);
        a.click();
        
        // 清理
        setTimeout(() => {
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }, 100);
        
        showNotification(this.t('audioDownloadStarted'));

      } catch (error) {
        console.error('Audio merging failed:', error);
        showNotification(this.t('audioMergeFailed'));
      }
    },

    // 通用拼接 (MP3/OGG/AAC)
    mergeGeneralBuffers(buffers) {
      const totalLength = buffers.reduce((acc, buffer) => acc + buffer.byteLength, 0);
      const result = new Uint8Array(totalLength);
      
      let offset = 0;
      buffers.forEach(buffer => {
        result.set(new Uint8Array(buffer), offset);
        offset += buffer.byteLength;
      });
      
      return result;
    },

    // WAV 专用拼接
    mergeWavBuffers(buffers) {
      if (buffers.length === 0) return new Uint8Array(0);
      if (buffers.length === 1) return new Uint8Array(buffers[0]);

      const HEADER_SIZE = 44; 
      let totalDataLength = 0;
      
      buffers.forEach((buffer, index) => {
        if (index === 0) totalDataLength += buffer.byteLength;
        else totalDataLength += Math.max(0, buffer.byteLength - HEADER_SIZE);
      });

      const result = new Uint8Array(totalDataLength);
      
      // 写入第一个文件（含头）
      result.set(new Uint8Array(buffers[0]), 0);
      let offset = buffers[0].byteLength;

      // 写入后续文件（去头）
      for (let i = 1; i < buffers.length; i++) {
        const buffer = new Uint8Array(buffers[i]);
        if (buffer.byteLength > HEADER_SIZE) {
            const dataChunk = buffer.subarray(HEADER_SIZE);
            result.set(dataChunk, offset);
            offset += dataChunk.byteLength;
        }
      }

      // 修正 WAV 头
      const view = new DataView(result.buffer);
      view.setUint32(4, result.byteLength - 8, true); 
      view.setUint32(40, result.byteLength - HEADER_SIZE, true);

      return result;
    },

// 修改 stopRead 方法
stopRead() {
  if (!this.isReadRunning) return;
  
  this.isReadStopping = true;
  this.isReadRunning  = false;
  this.isReadPaused   = false;  // 重置暂停状态
  this.readState.isPlaying = false;

  /* 停掉当前音频 */
  if (this.currentReadAudio) {
    this.currentReadAudio.pause();
    this.currentReadAudio = null;
  }
  
  this.sendTTSStatusToVRM('stopSpeaking', {});
  
  /* 重置音频计数状态 */
  this.isAudioSynthesizing = false;
  this.audioChunksCount = 0;
  this.totalChunksCount = 0;
  
  this.isReadStopping = false;
},

// 修改 stopTTSActivities 方法
stopTTSActivities() {
  // 停止朗读流程
  if (this.isReadRunning) {
    this.isReadStopping = true;
    this.isReadRunning = false;
    this.isReadPaused = false;  // 重置暂停状态
    this.readState.isPlaying = false;
    
    /* 停掉当前音频 */
    if (this.currentReadAudio) {
      this.currentReadAudio.pause();
      this.currentReadAudio = null;
    }
    this.sendTTSStatusToVRM('stopSpeaking', {});
    
    /* 重置音频计数状态 */
    this.isAudioSynthesizing = false;
    
    this.isReadStopping = false;
  }
  
  // 停止音频转换流程（保持原有）
  if (this.isConvertingAudio) {
    this.isConvertStopping = true;
    this.isConvertingAudio = false;
    this.isAudioSynthesizing = false;
    showNotification(this.t('audioConversionStopped'));
    this.isConvertStopping = false;
  }
},

  /* ===============  复用 / 微调 TTS 流程  =============== */
  async startReadTTSProcess() {
    let max_concurrency = this.ttsSettings.maxConcurrency || 1;
    let nextIndex = 0;

    /* 与对话版唯一区别：readState 代替 messages[last] */
    while (this.isReadRunning) {
      while (
        this.readState.ttsQueue.size < max_concurrency &&
        nextIndex < this.readState.ttsChunks.length
      ) {
        if (!this.isReadRunning) break;

        const index = nextIndex++;
        this.readState.ttsQueue.add(index);

        this.processReadTTSChunk(index).finally(() => {
          this.readState.ttsQueue.delete(index);
        });

        /* 首包加速 */
        if (index === 0) await new Promise(r => setTimeout(r, 800));
      }
      await new Promise(r => setTimeout(r, 10));
    }
    console.log('Read TTS queue processing completed');
  },

  // 修改后的 convertAudioOnly 方法
  async convertAudioOnly() {
    if (!this.readConfig.longText.trim()) {
      showNotification(this.t('noTextToConvert'));
      return;
    }

    this.isConvertingAudio = true;
    
    try {
      // 1. 清空上一次的残留
      this.readState.ttsChunks = [];
      this.readState.audioChunks = [];
      this.readState.chunks_voice = [];
      this.audioChunksCount = 0;
      this.totalChunksCount = 0;

  /* 2. 分段 */
      const {
        chunks,
        chunks_voice,
        remaining,
        remaining_voice
      } = this.splitTTSBuffer(this.readConfig.longText);

      // 追加 remaining
      if (remaining) {
        chunks.push(remaining);
        chunks_voice.push(remaining_voice);
      }

      /* ================= 新增：去标签 + 去空白并同步删除 ================= */
      // 1. 去 HTML 标签
      const cleanedChunks = chunks.map(txt => txt.replace(/<\/?[^>]+>/g, '').trim());

      // 2. 过滤空白并同步删除 chunks_voice 对应项
      const finalChunks       = [];
      const finalChunksVoice  = [];

      cleanedChunks.forEach((txt, idx) => {
        if (txt) {                      // 非空才保留
          finalChunks.push(txt);
          finalChunksVoice.push(chunks_voice[idx]);
        }
      });

      // 3. 覆盖原来的数组
      chunks.length       = 0;
      chunks_voice.length = 0;
      chunks.push(...finalChunks);
      chunks_voice.push(...finalChunksVoice);
      /* ================================================================ */
      
      if (!chunks.length) {
        this.isConvertingAudio = false;
        return;
      }
      
      this.readState.ttsChunks = chunks;
      this.readState.chunks_voice = chunks_voice;
      this.totalChunksCount = chunks.length;

      // 3. 开始转换（复用 processReadTTSChunk 但禁用播放）
      this.isAudioSynthesizing = true;
      
      // 使用并发控制处理所有片段
      const maxConcurrency = this.ttsSettings.maxConcurrency || 1;
      let nextIndex = 0;
      const activeTasks = new Set();
      
      // 使用 Promise 来等待所有任务完成
      await new Promise((resolve) => {
        const processNext = async () => {
          // 检查是否被用户停止
          if (!this.isConvertingAudio) {
            resolve();
            return;
          }
          
          // 所有任务完成
          if (nextIndex >= chunks.length && activeTasks.size === 0) {
            resolve();
            return;
          }
          
          // 添加新任务（如果有空位且还有任务）
          while (activeTasks.size < maxConcurrency && nextIndex < chunks.length) {
            const index = nextIndex++;
            activeTasks.add(index);
            
            this.processTTSChunkWithoutPlayback(index)
              .finally(() => {
                activeTasks.delete(index);
                processNext(); // 检查是否可添加新任务
              });
          }
        };
        
        processNext();
      });
      
      // 只有在没有被停止的情况下才显示完成通知
      if (this.isConvertingAudio) {
        this.isAudioSynthesizing = false;
        showNotification(this.t('audioConversionCompleted', { count: chunks.length }));
      }
      
    } catch (error) {
      console.error('Audio conversion failed:', error);
      showNotification(this.t('audioConversionFailed'));
    } finally {
      this.isConvertingAudio = false;
    }
  },

    // 处理TTS片段但不播放
    async processTTSChunkWithoutPlayback(index) {
      const chunk = this.readState.ttsChunks[index];
      const voice = this.readState.chunks_voice[index];
      console.log(`Processing TTS chunk ${index}`);
      // 文本清洗
      let chunk_text = chunk;
      let chunk_expressions =[];
      if (chunk.indexOf('<') !== -1) {
        const tagReg = /<[^>]+>/g;
        chunk_expressions = (chunk.match(tagReg) || []).map(t => t.slice(1, -1)); // 去掉两端的 <>
        chunk_text = chunk.replace(tagReg, '').trim(); // 把标签从正文里删掉
      }

      try {
        const res = await fetch('/tts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ttsSettings: this.ttsSettings,
            text: chunk_text,
            index,
            voice
          })
        });

        if (!res.ok) throw new Error('TTS failed');

        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        /* Base64 给 VRM */
        const base64 = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload  = () => resolve(reader.result.split(',')[1]);
          reader.onerror = reject;
          reader.readAsDataURL(blob);
        });
        this.cur_audioDatas[index] = `data:${blob.type};base64,${base64}`;
        /* 缓存两样东西 */
        this.readState.audioChunks[index] = {
          url,                       // 本地播放用
          expressions: chunk_expressions,
          base64: this.cur_audioDatas[index], // VRM 播放用
          text: chunk_text,
          index,
          voice
        };
        // 增加计数
        this.audioChunksCount++;
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
      } catch (e) {
        console.error(`TTS chunk ${index} error`, e);
        this.readState.audioChunks[index] = { 
          url: null, 
          expressions: chunk_expressions, 
          text: chunk_text, 
          index 
        };
        
        // 错误时也增加计数
        this.audioChunksCount++;
        if (this.audioChunksCount >= this.totalChunksCount) {
          this.isAudioSynthesizing = false;
          this.audioChunksCount = this.totalChunksCount; // 重置计数
        }
      }
    },

  /* ===============  播放监控  =============== */
  async startReadAudioPlayProcess() {
    /* 与对话版的 startAudioPlayProcess 完全一致，只是把 readState 替换掉 */
    this.readState.currentChunk = 0;
    this.readState.isPlaying   = false;
    this.audioPlayQueue = [];
  },

  async checkReadAudioPlayback() {
    if (this.isReadPaused) return;
    if (!this.isReadRunning || this.readState.isPlaying) return;

    const curIdx = this.readState.currentChunk;
    const total  = this.readState.ttsChunks.length;
    if (curIdx >= total) {
      /* 全部读完 */
      console.log('All read audio chunks played');
      this.readState.currentChunk = 0;
      this.isReadRunning = false;
      this.cur_audioDatas = [];
      this.sendTTSStatusToVRM('allChunksCompleted', {});
      return;
    }

    const audioChunk = this.readState.audioChunks[curIdx];
    if (!audioChunk) return;

    /* 开始播放这一块 */
    this.readState.isPlaying = true;
    console.log(`Playing read audio chunk ${curIdx}`);
    this.scrollToCurrentChunk(curIdx);
    try {
      this.currentReadAudio = new Audio(audioChunk.url);
      this.currentReadAudio.volume = this.vrmOnline ? 0.0000001 : 1; // VRM在线时静音
      this.sendTTSStatusToVRM('startSpeaking', {
        audioDataUrl: this.cur_audioDatas[curIdx],
        chunkIndex: curIdx,
        totalChunks: total,
        text: audioChunk.text,
        expressions: audioChunk.expressions,
        voice: this.readState.chunks_voice[curIdx]
      });

      await new Promise(resolve => {
        this.currentReadAudio.onended = () => {
          this.sendTTSStatusToVRM('chunkEnded', { chunkIndex: curIdx });
          resolve();
        };
        this.currentReadAudio.onerror = resolve;
        this.currentReadAudio.play().catch(console.error);
      });
    } catch (e) {
      console.error('Read playback error', e);
    } finally {
      this.readState.currentChunk++;
      this.readState.isPlaying = false;
      setTimeout(() => this.checkReadAudioPlayback(), 0);
    }
  },

    async parseSelectedFile() {
        this.readConfig.longText = '';
        this.readConfig.longTextList = [];
        this.longTextListIndex = 0;
        // 根据选择的文件unique_filename在textFiles中查找对应的文件信息
        const selectedFile = this.textFiles.find(file => file.unique_filename === this.selectedFile);
        try {
          if (selectedFile) {
            // 构建完整的请求URL
            const url = `/get_file_content?file_url=${selectedFile.unique_filename}`;
            
            // 发送请求获取文件内容
            const response = await fetch(url, {
              method: 'GET',
              headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (selectedFile.unique_filename.toLowerCase().endsWith('.epub')){
              // data.content转成字典
              let data_json = JSON.parse(data.content);
              this.readConfig.longTextList = data_json.chapters || [];
              if (this.readConfig.longTextList.length > 0){
                this.longTextListIndex = 0;
                this.readConfig.longText = this.readConfig.longTextList[0];
              }else{
                this.readConfig.longText = data.content;
              }
            }else{
              this.readConfig.longText = data.content;
            }
            // 如果this.readConfig.longText太长了，就只取前100000个
            // if (this.readConfig.longText.length > 100000) {
            //   this.readConfig.longText = this.readConfig.longText.substring(0, 100000);
            //   showNotification(this.t('contentTooLong'))
            // }
          }
        }
        catch (error) {
          console.error('Error:', error);
        }
    }
});
