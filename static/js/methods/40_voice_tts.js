// 批 3 F2：自 vue_methods.js 搬移的 methods/40_voice_tts.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // WAV转换函数保持不变
    async audioToWav(audioData) {
      try {
        // 音频参数配置
        const sampleRate = 16000; // 采样率 16kHz，适合语音识别
        const numChannels = 1;    // 单声道
        const bitsPerSample = 16; // 16位采样深度
        
        // 将Float32Array转换为Int16Array (16位PCM)
        const int16Array = new Int16Array(audioData.length);
        for (let i = 0; i < audioData.length; i++) {
          // 将[-1.0, 1.0]范围的浮点数转换为[-32768, 32767]范围的整数
          const sample = Math.max(-1, Math.min(1, audioData[i])); // 限制范围
          int16Array[i] = sample < 0 ? sample * 32768 : sample * 32767;
        }
        
        // 计算文件大小
        const byteLength = int16Array.length * 2; // 每个样本2字节
        const buffer = new ArrayBuffer(44 + byteLength); // WAV头部44字节 + 音频数据
        const view = new DataView(buffer);
        
        // 写入WAV文件头
        const writeString = (offset, string) => {
          for (let i = 0; i < string.length; i++) {
            view.setUint8(offset + i, string.charCodeAt(i));
          }
        };
        
        // RIFF chunk descriptor
        writeString(0, 'RIFF');
        view.setUint32(4, 36 + byteLength, true); // 文件大小-8
        writeString(8, 'WAVE');
        
        // fmt sub-chunk
        writeString(12, 'fmt ');
        view.setUint32(16, 16, true); // fmt chunk大小
        view.setUint16(20, 1, true);  // 音频格式 (PCM)
        view.setUint16(22, numChannels, true); // 声道数
        view.setUint32(24, sampleRate, true);  // 采样率
        view.setUint32(28, sampleRate * numChannels * bitsPerSample / 8, true); // 字节率
        view.setUint16(32, numChannels * bitsPerSample / 8, true); // 块对齐
        view.setUint16(34, bitsPerSample, true); // 位深度
        
        // data sub-chunk
        writeString(36, 'data');
        view.setUint32(40, byteLength, true); // 数据大小
        
        // 写入音频数据
        const offset = 44;
        for (let i = 0; i < int16Array.length; i++) {
          view.setInt16(offset + i * 2, int16Array[i], true);
        }
        
        // 创建Blob并返回File对象
        const blob = new Blob([buffer], { type: 'audio/wav' });
        const file = new File([blob], 'audio.wav', { type: 'audio/wav' });
        
        return file;
        
      } catch (error) {
        console.error('Audio conversion error:', error);
        throw new Error('Failed to convert audio to WAV format');
      }
    },

    // 自动判断下载源的工具函数
    async getAutoSource() {
      try {
        // 1. 检查时区
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        const isMainlandChinaTimezone = [
          'Asia/Shanghai', 
          'Asia/Chongqing', 
          'Asia/Harbin', 
          'Asia/Urumqi'
        ].includes(timezone);

        // 2. 检查语言
        const isChineseLanguage = navigator.language.startsWith('zh');

        if (isMainlandChinaTimezone || isChineseLanguage) {
          return 'modelscope';
        }
      } catch (e) {
        console.error('Failed to detect locale', e);
      }
      return 'huggingface'; // 默认源
    },

    async changeTTSstatus() {
      if (!this.ttsSettings.enabled) {
        this.TTSrunning = false;
      }
      if (this.ttsSettings.enabled === true && this.settings.enableOmniTTS === true) {
        this.settings.enableOmniTTS = false;
        showNotification(this.t('autoDisableOmniControlSettings'), 'warning');
      }else if (this.ttsSettings.enabled === true && this.ttsSettings.engine === 'moss'){
        if (!this.mossModelExists){
          showNotification(this.t('autoDownloadModel'), 'info');
          this.ttsSettings.enabled = false;
          let source = await this.getAutoSource();
          await this.mossDownload(source);
        }
      }
      await this.autoSaveSettings();
    },

    /**
     * 按分隔符 + <voice> 标签 拆分 buffer
     * @returns {
     *   chunks: string[]        // 纯文本块（已去标签、已清理）
     *   chunks_voice: string[]  // 与 chunks 一一对应的声音 key
     *   remaining: string       // 未完结文本
     *   remaining_voice: string // remaining 对应的 voice key
     * }
     */
    splitTTSBuffer(buffer) {
        // 0. 基础清理逻辑 (保持不变)
        buffer = buffer
            .replace(/#{1,6}\s/gm, '')
            .replace(/[*~`]+/g, '')
            .replace(/^\s*[-*]\s/gm, '')
            .replace(/[\u{2600}-\u{27BF}\u{2700}-\u{27BF}\u{1F300}-\u{1F9FF}]/gu, '')
            .replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, '')
            .replace(/!\[.*?\]\(.*?\)/g, '')
            .replace(/\[(.*?)\]\(.*?\)/g, '$1');

        if (!buffer) {
            return {
                chunks: [],
                chunks_voice: [],
                remaining: '',
                remaining_voice: this.voiceStack[this.voiceStack.length - 1] // 返回栈顶
            };
        }

        // 1. 初始化栈（防御性）
        if (!this.voiceStack) this.voiceStack = ['default'];

        // 2. 构造正则
        const separators = (this.ttsSettings.separators || [])
            .map(s => s.replace(/\\n/g, '\n').replace(/\\t/g, '\t').replace(/\\r/g, '\r'));

        const voiceKeys = ['default', 'silence', ...Object.keys(this.ttsSettings.newtts || {})].filter(Boolean);
        const openTagRe = new RegExp(`<(${voiceKeys.join('|')})>`, 'gi');
        const closeTagRe = /<\/\w+>/gi; // 匹配任何结束标签
        const sepRe = separators.length
            ? new RegExp(separators.map(s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g')
            : /$^/;

        // 3. 扫描所有标记并排序
        const tokens = [];
        let m;
        openTagRe.lastIndex = 0;
        while ((m = openTagRe.exec(buffer)) !== null) tokens.push({ type: 'open', value: m[1], index: m.index, raw: m[0] });

        closeTagRe.lastIndex = 0;
        while ((m = closeTagRe.exec(buffer)) !== null) tokens.push({ type: 'close', value: m[0], index: m.index, raw: m[0] });

        sepRe.lastIndex = 0;
        while ((m = sepRe.exec(buffer)) !== null) tokens.push({ type: 'sep', value: m[0], index: m.index, raw: m[0] });

        tokens.sort((a, b) => a.index - b.index);

        // 4. 遍历处理
        const chunks = [];
        const chunks_voice = [];
        let segmentStart = 0;

        const emitText = (endIdx) => {
            const text = buffer.slice(segmentStart, endIdx);
            const cleaned = text.replace(/\s+/g, ' ').trim();
            if (cleaned && !/^[\s\p{P}]*$/u.test(cleaned)) {
                chunks.push(cleaned);
                // 关键：永远使用当前栈顶的音色
                chunks_voice.push(this.voiceStack[this.voiceStack.length - 1]);
            }
        };

        for (const tok of tokens) {
            switch (tok.type) {
                case 'open':
                    emitText(tok.index);
                    this.voiceStack.push(tok.value); // 压入新音色
                    segmentStart = tok.index + tok.raw.length;
                    break;
                case 'close':
                    emitText(tok.index);
                    if (this.voiceStack.length > 1) {
                        this.voiceStack.pop(); // 弹出当前音色，回到上一层
                    }
                    segmentStart = tok.index + tok.raw.length;
                    break;
                case 'sep':
                    emitText(tok.index);
                    segmentStart = tok.index + tok.raw.length;
                    break;
            }
        }

        // 5. 剩余文本
        const remaining = buffer.slice(segmentStart);
        // 告知外部当前处于什么音色状态（栈顶）
        const remaining_voice = this.voiceStack[this.voiceStack.length - 1];

        return { chunks, chunks_voice, remaining, remaining_voice };
    },

    // TTS处理进程 - 使用流式响应
    // 修改 TTS 处理开始时的通知
    async startTTSProcess(message) {
      if (!this.ttsSettings.enabled) return;
      this.TTSrunning = true;
      this.cur_audioDatas = [];
      
      // 使用传入的消息对象
      const lastMessage = message; 

      this.sendTTSStatusToVRM('ttsStarted', {
        totalChunks: lastMessage.ttsChunks.length
      });
      
      lastMessage.audioChunks = lastMessage.audioChunks || [];
      lastMessage.ttsQueue = lastMessage.ttsQueue || new Set();
      
      let max_concurrency = 1;
      let nextIndex = 0;
      while (this.TTSrunning) {
        if (nextIndex == 0){
          let remainingText = lastMessage.ttsChunks?.[0] || '';
          let newttsList = [];
          if (remainingText && this.ttsSettings.newtts){
            for (const key in this.ttsSettings.newtts) {
              if (this.ttsSettings.newtts[key].enabled) {
                newttsList.push(key);
              }
            }
          }
          
          if (remainingText && this.ttsSettings.bufferWordList.length > 0  && newttsList == []){
            for (const exp of this.expressionMap) {
              const regex = new RegExp(exp, 'g');
              if (remainingText.includes(exp)) {
                remainingText = remainingText.replace(regex, '').trim(); 
              }
            }
            remainingText = remainingText.replace(/<[^>]+>/g, '');
            const hasChinese = /[\u4e00-\u9fa5]/.test(remainingText);

            if ((hasChinese && remainingText?.length > 5) || 
                (!hasChinese && remainingText?.length > 10)) {
                if (this.ttsSettings.bufferWordList.length > 0) {
                    const bufferWord = this.ttsSettings.bufferWordList[
                        Math.floor(Math.random() * this.ttsSettings.bufferWordList.length)
                    ];
                    lastMessage.ttsChunks.unshift(bufferWord);
                }
            }
          }
        }

        max_concurrency = this.ttsSettings.maxConcurrency || 1; 
        while (lastMessage.ttsQueue.size < max_concurrency && 
              nextIndex < lastMessage.ttsChunks.length) {
          if (!this.TTSrunning) break;
          const index = nextIndex++;
          lastMessage.ttsQueue.add(index);
          
          this.processTTSChunk(lastMessage, index).finally(() => {
            lastMessage.ttsQueue.delete(index);
          });
          if (index == 0){
            this.stopTimer();
            console.log(`TTS chunk 0 start in ${this.elapsedTime}ms`);
            await new Promise(resolve => setTimeout(resolve, 800));
          }
        }
        
        await new Promise(resolve => setTimeout(resolve, 10));
      }
      this.messages[this.messages.length - 1].currentChunk = 0;
      console.log('TTS queue processing completed');
    },

    startTimer() {
      this.startTime = Date.now();
    },

    stopTimer() {
      this.elapsedTime = Date.now() - this.startTime;
    },

    async processTTSChunk(message, index) {
        let voice = message.chunks_voice[index];
        const chunk = message.ttsChunks[index];
        
        // 解析标记
        const isVrmSilent = voice.startsWith('danmaku_vrm_silent:');
        if (isVrmSilent) {
            voice = voice.replace('danmaku_vrm_silent:', ''); // 恢复成真实音色 ID
        }

        let chunk_text = chunk;
        let chunk_expressions = [];

        if (chunk.indexOf('<') !== -1) {
            const tagReg = /<[^>]+>/g;
            chunk_expressions = (chunk.match(tagReg) || []).map(t => t.slice(1, -1));
            chunk_text = chunk.replace(tagReg, '').trim();
        }

        const offset = message.chunks_voice.filter(v => v.startsWith('danmaku_vrm_silent:')).length;
        const vrmIndex = index - offset; // 计算发给 VRM 的虚拟索引

        try {
            if (voice === 'silence') {
                // 静音块走文本通道发指令
                const cmd = JSON.stringify({
                    type: 'startSpeaking',
                    data: { chunkIndex: index, text: chunk_text, voice: 'silence', expressions: chunk_expressions }
                });
                if (this.ttsWebSocket && (this.vrmOnline || this.vtsOnline)) this.ttsWebSocket.send(cmd);
                message.audioChunks[index] = { url: null, expressions: chunk_expressions, text: chunk_text, index };
                this.checkAudioPlayback();
            } else {
                const response = await fetch(`/tts`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ttsSettings: this.ttsSettings, text: chunk_text, index, voice })
                });

                if (response.ok) {
                    const audioBlob = await response.blob();
                    const audioUrl = URL.createObjectURL(audioBlob);
                    
                    // --- 修改点：预先转换二进制并存储，但不发送 ---
                    const audioBuffer = await audioBlob.arrayBuffer();

                    message.audioChunks[index] = { 
                        url: audioUrl, 
                        buffer: audioBuffer, // 暂存二进制数据
                        mimeType: audioBlob.type,
                        expressions: chunk_expressions, 
                        text: chunk_text, 
                        index 
                    };
                    this.checkAudioPlayback();
                }
            }
        } catch (error) {
            console.error(`TTS Chunk ${index} error:`, error);
        }
    },

    // 音频播放进程
    async startAudioPlayProcess(message, resolve) {
      if (!this.ttsSettings.enabled) {
          if(resolve) resolve();
          return;
      }
      
      const lastMessage = message;
      lastMessage.currentChunk = lastMessage.currentChunk || 0;
      lastMessage.isPlaying = false;
      
      this.audioPlayQueue = [];
      console.log('Audio playback monitor started for:', message.agentName);
      
      // 启动递归检查
      this.checkAudioPlayback(message, resolve);
    },

    async checkAudioPlayback(message, resolve) {
        if (!message) { if(resolve) resolve(); return; }
        const lastMessage = message;

        if (lastMessage.isPlaying) {
            setTimeout(() => this.checkAudioPlayback(message, resolve), 50);
            return;
        }

        const currentIndex = lastMessage.currentChunk;
        const audioChunk = lastMessage.audioChunks[currentIndex];
        
        // 如果该块还没合成好，继续等待
        if (!audioChunk) {
            // 如果所有已有的 chunk 都播完了
            const allLocalChunksPlayed = currentIndex >= (lastMessage.ttsChunks?.length || 0);
            
            if (allLocalChunksPlayed) {
                // 如果生成已结束，或者已经等了很久（比如5秒）都没新内容，就强行结束
                if (lastMessage.generationFinished) {
                    console.log("播放全部完成，正常退出");
                    this.TTSrunning = false;
                    try { fetch('/api/overlay/danmaku/clear', { method: 'POST' }).catch(()=>{}); } catch(e){}
                    if (resolve) resolve();
                    return;
                } else {
                    // 如果生成还没标记结束，但已经没东西播了，我们再等一下
                    // 增加一个保险计数器（可选）或者直接检查是否还在生成
                    if (!this.isSending) { 
                        // 如果连网络请求都结束了，还没标记 finish，那肯定是状态出错了
                        console.warn("检测到生成已停止但未标记完成，强行释放锁");
                        lastMessage.generationFinished = true; // 补救状态
                        this.TTSrunning = false;
                        try { fetch('/api/overlay/danmaku/clear', { method: 'POST' }).catch(()=>{}); } catch(e){}
                        if (resolve) resolve();
                        return;
                    }
                    setTimeout(() => this.checkAudioPlayback(message, resolve), 50);
                    return;
                }
            }
            setTimeout(() => this.checkAudioPlayback(message, resolve), 50);
            return;
        }

        const rawVoice = lastMessage.chunks_voice[currentIndex] || '';
        const isVrmSilent = rawVoice.startsWith('danmaku_vrm_silent:');
        const actualVoice = isVrmSilent ? rawVoice.replace('danmaku_vrm_silent:', '') : rawVoice;
        
        // 计算偏移
        const offset = lastMessage.chunks_voice.filter(v => v.startsWith('danmaku_vrm_silent:')).length;
        const vrmIndex = currentIndex - offset;

        if (!lastMessage.isPlaying) {
            lastMessage.isPlaying = true;
            if (currentIndex == 0){
              this.stopTimer();
              lastMessage.first_sentence_latency = this.elapsedTime;
            }

            try {
                // --- 核心同步修改点：只有非弹幕块且 VRM 在线时，才在此刻发送二进制数据 ---
                if (!isVrmSilent && vrmIndex >= 0 && (this.vrmOnline || this.vtsOnline) && audioChunk.buffer) {
                    const metadata = {
                        type: 'audio_chunk',
                        chunkIndex: vrmIndex,
                        text: audioChunk.text,
                        expressions: audioChunk.expressions,
                        mimeType: audioChunk.mimeType
                    };

                    console.log(`Sending audio chunk ${currentIndex} to VRM with metadata:`, metadata);
                    // 此时发送，VRM 插件会立刻开始播放，与浏览器端的“静音播放”逻辑完美同步
                    this.sendBinaryToVRM(metadata, audioChunk.buffer);
                }

                this.currentAudio = new Audio(audioChunk.url);
                
                if (isVrmSilent) {
                    this.currentAudio.volume = 1.0; // 弹幕声音从浏览器出
                    console.log("正在播放弹幕:", audioChunk.text);
                } else {
                    this.currentAudio.volume = this.vrmOnline ? 0.0000001 : 1.0; // AI声音从VRM出
                }
                
                // 发送指令通知 VRM 更新状态（UI显示、表情等）
                if (!isVrmSilent && vrmIndex >= 0) {
                    this.sendTTSStatusToVRM('startSpeaking', {
                        chunkIndex: vrmIndex,
                        totalChunks: lastMessage.ttsChunks.length - offset,
                        text: audioChunk.text,
                        expressions: audioChunk.expressions,
                        voice: actualVoice
                    });
                }
                
                // 等待当前这段音频播完（无论是有声还是静音）
                await new Promise((r) => {
                    this.currentAudio.onended = r;
                    this.currentAudio.onerror = r; // 报错也要释放
                    this.currentAudio.play().catch(e => {
                        console.error("播放失败", e);
                        r(); // 拦截也要释放
                    });
                    setTimeout(r, 20000); // 20秒强制跳过单个块，防止卡死
                });
                
            } catch (error) {
                console.error(`Playback error: ${error}`);
            } finally {
                lastMessage.currentChunk++;
                lastMessage.isPlaying = false;
                // 只有当前音频（弹幕）彻底 onended 之后，才会递归触发下一条（AI回复）
                setTimeout(() => this.checkAudioPlayback(message, resolve), 0);
            }
        }
    },

    // 修改轮询函数
    pollVRMStatus() {
      this.vrmPollTimer = setInterval(async () => {
        try {
          const r = await fetch('/tts/status').then(r => r.json())
          this.vrmOnline = r.vrm_connections > 0;
          this.vtsOnline = r.vts_active; // 获取 VTS 是否激活
        } catch (e) {
          this.vrmOnline = false;
          this.vtsOnline = false;
        }
      }, 3000)
    },

    // 停止音频播放（用于停止生成时）
    stopAudioPlayback() {
      // 这里可以添加停止当前播放音频的逻辑
      const lastMessage = this.messages[this.messages.length - 1];
      if (lastMessage) {
        lastMessage.isPlaying = false;
      }
    },

    toggleTTS(message) {
      if (message.isPlaying) {
        // 如果正在播放，点击则停止
        message.isPlaying = false;
        this.stopAllAudioPlayback();
        this.sendTTSStatusToVRM('stopSpeaking', {});
      } else {
        // 如果未在播放
        this.stopAllAudioPlayback();
        
        if (message.isOmni) {
          // --- 核心逻辑：检查是否播放到了末尾 ---
          // 如果当前时间 >= 总时长 (减去一个极小的偏移量防止浮点误差)
          if ((message.omniCurrentTime || 0) >= (message.omniDuration || 0) - 0.1) {
            console.log('Omni audio at end, restarting from beginning');
            message.omniCurrentTime = 0; // 重头开始
          }
          
          message.isPlaying = true;
          this.playOmniFromTime(message, message.omniCurrentTime);
        } else {
          // 普通 TTS 逻辑
          message.isPlaying = true;
          this.playAudioChunk(message);
        }
      }
    },

    // 进度条跳转
    seekOmniTTS(message, time) {
      this.stopAllAudioPlayback();
      message.omniCurrentTime = time;
      if (message.isPlaying || true) { // 跳转后通常直接播放
        message.isPlaying = true;
        this.playOmniFromTime(message, time);
      }
    },

    // 核心回放逻辑
    async playOmniFromTime(message, startTime = 0) {
      if (!message.omniAudioChunks || message.omniAudioChunks.length === 0) return;
      
      if (this.audioCtx.state === 'suspended') await this.audioCtx.resume();
      
      // 每次开始新播放时，将排程起点设为当前时间
      this.audioStartTime = this.audioCtx.currentTime;

      let accumulated = 0;
      for (const b64 of message.omniAudioChunks) {
        // 如果中途用户点了暂停，跳出循环不再排程
        if (!message.isPlaying) break;

        const chunkDuration = (atob(b64).length / 2) / 24000;
        
        // 只播放从 startTime 开始之后的块
        if (accumulated + chunkDuration > startTime) {
          this.playPCMChunk(b64, message.pure_content, message);
        }
        accumulated += chunkDuration;
      }
    },

    // 停止所有正在播放的音频
    stopAllAudioPlayback() {
      // 1. 停止 HTML5 Audio (普通 TTS)
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio = null;
      }
      
      // 2. 停止阅读音频
      if (this.currentReadAudio) {
        this.currentReadAudio.pause();
        this.currentReadAudio = null;
      }
      
      // 3. 【核心修复】停止所有 Web Audio API 的 Omni 节点
      if (this.activeSources && this.activeSources.length > 0) {
        this.activeSources.forEach(src => {
          // ✨ 新增：给节点打上被强杀的标记，防止 onended 扰乱进度条
          src.isForceStopped = true; 
          try {
            src.stop(); // 立即停止播放
          } catch (e) {
            // 忽略已经停止或未开始的错误
          }
        });
        // 清空数组
        this.activeSources = [];
      }
      
      this.isOmniPlaying = false; // ✨ 新增：重置全局播放状态
      this.audioStartTime = 0; 
      
      // 4. 重置所有消息状态
      this.messages.forEach(message => {
        message.isPlaying = false;
      });

      // 6. 发送停止信号到VRM
      this.sendTTSStatusToVRM('stopSpeaking', {});
    },

    async playAudioChunk(message) {
      if (!this.ttsSettings.enabled){
        message.isPlaying = false; // 如果没有音频块，停止播放
        message.currentChunk = 0; // 重置索引
        return;
      }

      // 初始化 cur_audioDatas 对象（如果不存在）
      if (!this.cur_audioDatas) {
        this.cur_audioDatas = {};
      }

      // 为每个消息创建唯一的键，使用消息ID
      const base64Key = `msg_${message.id}_chunk_${message.currentChunk}`;

      const audioChunk = message.audioChunks[message.currentChunk];
      if (audioChunk) {
        // 检查是否有音频URL可以播放
        if (!audioChunk.url) {
          console.log(`Audio chunk ${message.currentChunk} has no URL, skipping`);
          message.currentChunk++;
          this.playAudioChunk(message);
          return;
        }

        const audio = new Audio(audioChunk.url);
        this.currentAudio = audio; // 保存当前音频对象

        // 设置音量：VRM在线时静音，让VRM播放；不在线时正常播放
        audio.volume = this.vrmOnline ? 0.0000001 : 1;

        // 如果没有base64数据，尝试从blob URL生成
        if (!this.cur_audioDatas[base64Key] && audioChunk.url) {
          try {
            const response = await fetch(audioChunk.url);
            const blob = await response.blob();
            const base64 = await new Promise((resolve, reject) => {
              const reader = new FileReader();
              reader.onload = () => resolve(reader.result.split(',')[1]);
              reader.onerror = reject;
              reader.readAsDataURL(blob);
            });
            this.cur_audioDatas[base64Key] = `data:${blob.type};base64,${base64}`;
            console.log(`Generated base64 for ${base64Key}, length: ${this.cur_audioDatas[base64Key].length}`);
          } catch (error) {
            console.warn(`Failed to generate base64 for ${base64Key}:`, error);
            this.cur_audioDatas[base64Key] = '';
          }
        }

        // 发送 startSpeaking 状态到 VRM（每个块都需要发送）
        // 确保有base64数据才发送startSpeaking
        const audioDataUrl = this.cur_audioDatas[base64Key];
        if (audioDataUrl && audioDataUrl.length > 0) {
          console.log(`Sending startSpeaking with base64 data for ${base64Key}`);
          this.sendTTSStatusToVRM('startSpeaking', {
            audioDataUrl: audioDataUrl,
            chunkIndex: message.currentChunk,
            totalChunks: message.audioChunks.length,
            text: audioChunk.text || '',
            expressions: audioChunk.expressions || [],
            voice: message.chunks_voice ? message.chunks_voice[message.currentChunk] || 'default' : 'default',
          });
        } else {
          console.warn(`No base64 data available for ${base64Key}, skipping startSpeaking`);
        }

        try {
          await audio.play();
          audio.onended = () => {
            // 发送 chunkEnded 状态到 VRM
            this.sendTTSStatusToVRM('chunkEnded', {
              chunkIndex: message.currentChunk
            });

            message.currentChunk++; // 播放结束后，索引加一
            this.playAudioChunk(message); // 递归调用播放下一个音频块
          };
          audio.onerror = (error) => {
            console.error(`Error playing audio chunk ${message.currentChunk}:`, error);
            message.isPlaying = false; // 出错时停止播放
          };
        } catch (error) {
          console.error(`Error playing audio chunk ${message.currentChunk}:`, error);
          message.currentChunk++; // 播放结束后，索引加一
          this.playAudioChunk(message); // 递归调用播放下一个音频块
        }
      } else {
        message.isPlaying = false; // 如果没有音频块，停止播放
        message.currentChunk = 0; // 重置索引
        // 发送所有块播放完成状态到 VRM
        this.sendTTSStatusToVRM('allChunksCompleted', {});
      }
    },

    backwardTTS(message) {
      if (message.currentChunk > 0) {
        message.currentChunk--; // 当前索引减一
      }
    },

    forwardTTS(message) {
      if (message.currentChunk < message.audioChunks.length - 1) {
        message.currentChunk++; // 当前索引加一
      }
    },

    updateLanguages() {
      // 更新 ttsSettings 中的语言
      this.ttsSettings.edgettsLanguage = this.edgettsLanguage;
      
      // 更新性别和语音
      this.updateGenders(); 
      this.autoSaveSettings();
    },

    // 当语言改变时更新性别和语音
    updateGenders() {
      // 更新 ttsSettings 中的性别
      this.ttsSettings.edgettsGender = this.edgettsGender;
      // 更新到第一个语音
      this.ttsSettings.edgettsVoice = this.filteredVoices[0].name;

      // 更新语音
      this.updateVoices();
      this.autoSaveSettings();
    },

    // 当性别改变时更新语音
    updateVoices() {
      this.autoSaveSettings();
    },

    updateNewLanguages() {
      // 更新 ttsSettings 中的语言
      this.newTTSConfig.edgettsVoice = this.filteredNewVoices[0].name;
    },

    // 当语言改变时更新性别和语音
    updateNewGenders() {
      // 更新 ttsSettings 中的性别
      this.newTTSConfig.edgettsVoice = this.filteredNewVoices[0].name;
    },

      // 浏览参考音频文件
  browseGsvRefAudioFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'audio/*';
    input.onchange = (event) => {
      const files = event.target.files;
      if (files.length > 0) {
        this.newGsvAudio.name = files[0].name;
        this.newGsvAudio.file = files[0]; // 存储文件对象
      }
    };
    input.click();
  },

  // 处理参考音频拖拽
  handleGsvRefAudioDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      this.newGsvAudio.name = files[0].name;
      this.newGsvAudio.file = files[0]; // 存储文件对象
    }
  },

  // 移除已选择的参考音频
  removeNewGsvAudio() {
    this.newGsvAudio.name = '';
    this.newGsvAudio.file = null;
  },

  // 取消上传
  cancelGsvAudioUpload() {
    this.showGsvRefAudioPathDialog = false;
    this.newGsvAudio.name = '';
    this.newGsvAudio.text = '';
    this.newGsvAudio.file = null;
  },

  // 上传参考音频
  async uploadGsvAudio() {
    if (!this.newGsvAudio.file && !this.newGsvAudio.path) {
      showNotification('请先选择音频文件', 'error');
      return;
    }
    if (!this.newGsvAudio.file) {
        // 添加新音频到选项列表
        const newAudioOption = {
          path: this.newGsvAudio.path,
          name: this.newGsvAudio.name,
          text: this.newGsvAudio.text
        };
        
        this.ttsSettings.gsvAudioOptions.push(newAudioOption);
        
        // 关闭对话框并重置状态
        this.cancelGsvAudioUpload();
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('参考音频上传成功');
        return;
    }
    
    const formData = new FormData();
    formData.append('file', this.newGsvAudio.file);
    formData.append('prompt_text', this.newGsvAudio.text);
    
    try {
      const response = await fetch(`/upload_gsv_ref_audio`, {
        method: 'POST',
        body: formData
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 添加新音频到选项列表
        const newAudioOption = {
          path: result.file.unique_filename,
          name: result.file.name,
          text: this.newGsvAudio.text
        };
        
        this.ttsSettings.gsvAudioOptions.push(newAudioOption);
        
        // 关闭对话框并重置状态
        this.cancelGsvAudioUpload();
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('参考音频上传成功');
      } else {
        showNotification(`上传失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('上传参考音频失败:', error);
      showNotification('上传失败，请检查网络连接', 'error');
    }
  },

  // 处理参考音频路径改变
  handleRefAudioPathChange(value, option) {
    // 当选择新的参考音频时，更新对应的提示文本
    const selectedAudio = this.ttsSettings.gsvAudioOptions.find(
      audio => audio.path === value
    );
    
    if (selectedAudio && selectedAudio.text) {
      if (option == 'role') {
        this.newTTSConfig.gsvPromptText = selectedAudio.text;
      }
      else if (option == 'model') {
        this.ttsSettings.gsvPromptText = selectedAudio.text;
      }
      
    }
    
    // 自动保存设置
    this.autoSaveSettings();
  },

    // 删除音频选项
  async deleteAudioOption(path) {
    try {
      // 查找要删除的音频选项
      const audioIndex = this.ttsSettings.gsvAudioOptions.findIndex(
        audio => audio.path === path
      );
      
      if (audioIndex === -1) return;
      if (this.ttsSettings.gsvAudioOptions[audioIndex].path == this.ttsSettings.gsvAudioOptions[audioIndex].name){
        // 为路径上传的音频，直接从选项中移除
        this.ttsSettings.gsvAudioOptions.splice(audioIndex, 1);
        showNotification('音频已删除');
        return;
      }
      // 获取文件名用于后端删除
      const uniqueFilename = this.ttsSettings.gsvAudioOptions[audioIndex].path
        .split('/')
        .pop();
      
      // 调用后端API删除文件
      const response = await fetch(`/delete_audio/${uniqueFilename}`, {
        method: 'DELETE'
      });
      
      const result = await response.json();
      
      if (result.success) {
        // 从选项中移除
        this.ttsSettings.gsvAudioOptions.splice(audioIndex, 1);
        
        // 如果当前选中的音频被删除，则重置选择
        if (this.ttsSettings.gsvRefAudioPath === path) {
          this.ttsSettings.gsvRefAudioPath = '';
          this.ttsSettings.gsvPromptText = '';
        }
        
        // 自动保存设置
        await this.autoSaveSettings();
        
        showNotification('音频已删除');
      } else {
        showNotification(`删除失败: ${result.message}`, 'error');
      }
    } catch (error) {
      console.error('删除音频失败:', error);
      showNotification('删除失败，请稍后再试', 'error');
    }
  },

    async startVRM() {
    if (this.isElectron) {
      this.VRMConfig.name = 'default';
      await this.autoSaveSettings();
      // Electron 环境
      try {
        this.isVRMStarting = true;
        const windowConfig = {
          width: this.VRMConfig.windowWidth,
          height: this.VRMConfig.windowHeight,
        };
        await window.electronAPI.startVRMWindow(windowConfig);
      } catch (error) {
        console.error('启动失败:', error);
      } finally {
        this.isVRMStarting = false;
      }
    } else {
      // 浏览器环境
      window.open(`${this.partyURL}/vrm.html`, '_blank');
    }
  },

    async startNewVRM(name) {
    try {
      this.isVRMStarting = true;
      this.VRMConfig.name = name;
      this.VRMConfig.selectedNewModelId = this.VRMConfig.newVRM[name].selectedModelId;
      this.VRMConfig.selectedNewMotionIds = this.VRMConfig.newVRM[name].selectedMotionIds;
      await this.autoSaveSettings();
    if (this.isElectron) {
      // Electron 环境
        const windowConfig = {
          width: this.VRMConfig.newVRM[name].windowWidth,
          height: this.VRMConfig.newVRM[name].windowHeight,
        };
        await window.electronAPI.startVRMWindow(windowConfig);
    } else {
      // 浏览器环境
      window.open(`${this.partyURL}/vrm.html`, '_blank');
    }      
  } catch (error) {
    console.error('启动失败:', error);
  } finally {
    this.isVRMStarting = false;
  }
  },

  async startVRMweb() {
    if (this.isElectron) {
      window.electronAPI.openExternal(`${this.partyURL}/vrm.html`);
    }else {
      // 浏览器环境
      window.open(`${this.partyURL}/vrm.html`, '_blank');
    }
  },

    async checkServerPort() {
      try {
        // 方式1：使用专门的方法
        const serverInfo = await window.electronAPI.getServerInfo()
        
        
        if (!serverInfo.isDefaultPort) {
          const message = `默认端口 ${serverInfo.defaultPort} 被占用，已自动切换到端口 ${serverInfo.port}`
          showNotification(message, 'warning')
        }
      } catch (error) {
        console.error('获取服务器信息失败:', error)
      }
    },

    // 初始化 WebSocket 连接
    initTTSWebSocket() {
      const http_protocol = window.location.protocol;
      const ws_protocol = http_protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${ws_protocol}//${window.location.host}/ws/tts`;
      this.ttsWebSocket = new WebSocket(wsUrl);
      
      this.ttsWebSocket.onopen = () => {
        console.log('TTS WebSocket connected');
        this.wsConnected = true;
      };
      
      // 核心反馈处理：监听后端发来的 JSON 消息
      this.ttsWebSocket.onmessage = async (event) => {
        try {
          // 判断消息类型：处理文本（JSON）
          if (typeof event.data === 'string') {
            const msg = JSON.parse(event.data);
            
            // 匹配 VTS 状态反馈
            if (msg.type === 'vts_connection_status') {
              this.isVTSStarting = false; // 收到消息，停止 Loading
              
              if (msg.data.success) {
                // 真的连接成功了
                this.VTSConfig.enabled = true;
                showNotification(msg.data.message || 'VTube Studio 已连接', 'success', 'VTS');
              } else {
                // 连接失败：回退开关状态
                this.VTSConfig.enabled = false;
                // 弹出错误提示，引导用户开启 VTS
                showNotification(
                  msg.data.message || '请确保 VTube Studio 已开启 API 访问权限', 
                  'error', 
                  'VTS connection failed'
                );
              }
              this.autoSaveSettings(); // 同步保存到本地配置
            }
          } 
          // 处理二进制（音频流）：如果是音频，则转发或播放
          else if (event.data instanceof Blob) {
            // 这里可以保留你原来的逻辑，比如交给 VRM 播放器
            // this.handleAudioBlob(event.data); 
          }
        } catch (e) {
          console.error('解析 WebSocket 消息出错:', e);
        }
      };
      
      this.ttsWebSocket.onclose = () => {
        console.log('TTS WebSocket disconnected');
        this.wsConnected = false;
        this.isVTSStarting = false; // 断开时停止加载
        
        // 自动重连
        setTimeout(() => {
          if (!this.wsConnected) {
            this.initTTSWebSocket();
          }
        }, 3000);
      };
      
      this.ttsWebSocket.onerror = (error) => {
        console.error('TTS WebSocket error:', error);
        this.isVTSStarting = false;
      };
    },

    // 发送 TTS 状态到 VRM
    async sendTTSStatusToVRM(type, data) {
      if (this.ttsWebSocket && this.wsConnected) {
        this.ttsWebSocket.send(JSON.stringify({
          type,
          data,
          timestamp: Date.now()
        }));
      }
    },

  // 浏览VRM模型文件
  browseVrmModelFile() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.vrm';
    input.onchange = (event) => {
      const files = event.target.files;
      if (files.length > 0) {
        const file = files[0];
        // 检查文件扩展名
        if (!file.name.toLowerCase().endsWith('.vrm')) {
          showNotification('只支持.vrm格式的文件', 'error');
          return;
        }
        this.newVrmModel.name = file.name;
        this.newVrmModel.file = file;
        // 自动设置显示名称（去掉扩展名）
        this.newVrmModel.displayName = file.name.replace(/\.vrm$/i, '');
      }
    };
    input.click();
  },

  changeGsvAudioPath() {
    if (this.newGsvAudio.path) {
      this.newGsvAudio.name = this.newGsvAudio.path;
    }
  },

    async playPCMChunk(b64, currentText = '', message = null) {
        this.isOmniPlaying = true;
        if (message) {
            message.isPlaying = true;
            if (message.omniDuration === undefined) message.omniDuration = 0;
            if (message.omniCurrentTime === undefined) message.omniCurrentTime = 0;
            if (!message.generationFinished) message.omniAudioChunks.push(b64);
        }

        try {
            if (!this.audioCtx) this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            if (this.audioCtx.state === 'suspended') await this.audioCtx.resume();

            // 解码数据
            const raw = atob(b64);
            const pcm16 = new Int16Array(raw.length / 2);
            for (let i = 0; i < raw.length; i += 2) {
                pcm16[i >> 1] = raw.charCodeAt(i) | (raw.charCodeAt(i + 1) << 8);
            }

            const sampleRate = 24000;
            const buf = this.audioCtx.createBuffer(1, pcm16.length, sampleRate);
            const floatData = buf.getChannelData(0);
            for (let i = 0; i < pcm16.length; i++) floatData[i] = pcm16[i] / 32768;

            const chunkDuration = buf.duration;
            if (message && message.isOmni && !message.generationFinished) {
                message.omniDuration += chunkDuration;
            }

            // ======= 【核心修改：利用二进制同步到 VRM】 =======
            if ((this.vrmOnline || this.vtsOnline) && this.ttsWebSocket) {
                const pcmUint8 = new Uint8Array(raw.length);
                for(let i=0; i<raw.length; i++) pcmUint8[i] = raw.charCodeAt(i);
                
                this.sendBinaryToVRM({
                    type: 'omni_chunk',
                    text: currentText, // 传入当前文本
                    sampleRate: sampleRate
                }, pcmUint8.buffer);
            }
            // ===============================================

            const now = this.audioCtx.currentTime;
            if (this.audioStartTime < now) this.audioStartTime = now;

            const src = this.audioCtx.createBufferSource();
            src.buffer = buf;
            if (!this.activeSources) this.activeSources = [];
            this.activeSources.push(src);

            const gainNode = this.audioCtx.createGain();
            gainNode.gain.value = this.vrmOnline ? 0.000001 : 1.0;

            src.connect(gainNode);
            gainNode.connect(this.audioCtx.destination);

            src.onended = () => {
                if (this.activeSources) this.activeSources = this.activeSources.filter(s => s !== src);
                if (message && message.isOmni && !src.isForceStopped) {
                    message.omniCurrentTime += chunkDuration;
                    if (message.omniCurrentTime > message.omniDuration) message.omniCurrentTime = message.omniDuration;

                    if (message.generationFinished && this.activeSources.length === 0) {
                        message.isPlaying = false;
                        message.omniCurrentTime = message.omniDuration;
                        if (this.vrmOnline || this.vtsOnline) this.sendTTSStatusToVRM('allChunksCompleted', {});
                        this.isOmniPlaying = false;
                    }
                }
                try { src.disconnect(); gainNode.disconnect(); } catch (e) {}
            };

            src.start(this.audioStartTime);
            this.audioStartTime += buf.duration;
        } catch (error) {
            console.error('Error in playPCMChunk:', error);
            if (message) message.isPlaying = false;
        }
    },

  async fetchSystemVoices() {
      this.isLoadingSystemVoices = true;
      try {
        // 使用 fetch API 调用后端接口
        const response = await fetch('/system/voices'); // 请根据你的API前缀调整
        
        if (!response.ok) {
            // 处理 HTTP 错误状态（如 404, 500）
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data && data.voices) {
          this.systemVoices = data.voices;
          
          // 如果当前没有选中的音色，或者选中的音色不在列表里，默认选中第一个
          const currentVoiceValid = this.systemVoices.some(v => v.id === this.ttsSettings.systemVoiceName);
          if (!this.ttsSettings.systemVoiceName || !currentVoiceValid) {
             if (this.systemVoices.length > 0) {
               this.ttsSettings.systemVoiceName = this.systemVoices[0].id;
               this.autoSaveSettings(); // 保存默认选择
             }
          }
        }
      } catch (error) {
        console.error("获取系统音色失败:", error);
        if (this.$message) {
           this.$message.error(`获取系统音色列表失败: ${error.message}`);
        }
      } finally {
        this.isLoadingSystemVoices = false;
      }
    }
});
