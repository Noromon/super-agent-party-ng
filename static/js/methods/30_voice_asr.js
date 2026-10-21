// 批 3 F2：自 vue_methods.js 搬移的 methods/30_voice_asr.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    removeJsonFile() {
      this.jsonFile = null; // 清空文件
    },

    // 初始化ASR WebSocket连接（修改版本，支持Web Speech API）
    async initASRWebSocket() {
      if (this.asrSettings.engine === 'webSpeech') return;
      
      // 🌟 关键：如果当前已经有连接或正在连接，先清理
      if (this.asrWs) {
        this.asrWs.onclose = null;
        this.asrWs.close();
        this.asrWs = null;
      }

      const ws_protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      const ws_url = `${ws_protocol}//${window.location.host}/ws/asr`;

      console.log('Initializing ASR WebSocket...');
      this.asrWs = new WebSocket(ws_url);
      
      this.asrWs.onopen = () => {
        if (this.asrWs && this.asrWs.readyState === WebSocket.OPEN) {
          console.log('ASR WebSocket connection established');
          this.asrWs.send(JSON.stringify({ type: 'init' }));
        }
      };

      this.asrWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          this.handleASRResult(data);
        } catch (e) {
          console.error('Invalid JSON from ASR server:', event.data);
        }
      };

      this.asrWs.onclose = (event) => {
        // 只有当 ASR 处于启用状态，且我们没有手动销毁 asrWs 时才重连
        if (this.asrSettings.enabled && this.asrWs !== null) {
          console.log('ASR WebSocket unexpected closed, reconnecting in 3s...');
          setTimeout(() => {
            if (this.asrSettings.enabled) this.initASRWebSocket();
          }, 3000);
        }
      };

      this.asrWs.onerror = (error) => {
        console.error('ASR WebSocket error observed');
      };
    },

    // 修改：初始化Web Speech API（不自动启动）
    initWebSpeechAPI() {
      if(isElectron){
        showNotification(this.t('webSpeechNotSupportedInElectron'), 'error');
        this.asrSettings.enabled = false;
        this.autoSaveSettings();
        return false;
      }

      // 检查浏览器是否支持Web Speech API
      if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
        showNotification(this.t('webSpeechNotSupported'), 'error');
        this.asrSettings.enabled = false;
        return false;
      }

      // 创建语音识别对象
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      this.recognition = new SpeechRecognition();

      // 配置语音识别参数
      this.recognition.continuous = true; // 改为非持续识别，由VAD控制
      this.recognition.interimResults = true;
      if (this.asrSettings.webSpeechLanguage != 'auto'){
        this.recognition.lang = this.asrSettings.webSpeechLanguage;
      }
      // 识别结果处理
      this.recognition.onresult = (event) => {
        let finalTranscript = '';
        let interimTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript;
          } else {
            interimTranscript += transcript;
          }
        }

        // 处理中间结果
        if (interimTranscript) {
          this.handleASRResult({
            type: 'transcription',
            text: interimTranscript,
            is_final: false
          });
        }

        // 处理最终结果
        if (finalTranscript) {
          this.handleASRResult({
            type: 'transcription',
            text: finalTranscript,
            is_final: true
          });
        }
      };

      // 错误处理
      this.recognition.onerror = (event) => {
        console.error('Web Speech API error:', event.error);
        let errorMessage = null;
        
        switch (event.error) {
          case 'no-speech':
            errorMessage = null;
            break;
          case 'audio-capture':
            errorMessage = this.t('microphoneError');
            break;
          case 'not-allowed':
            errorMessage = this.t('micPermissionDenied');
            break;
          case 'network':
            errorMessage = this.t('networkError');
            break;
        }
        if (errorMessage) {
          showNotification(errorMessage, 'error');
        }
        
        // 重置识别状态
        this.isWebSpeechRecognizing = false;
      };

      // 识别结束处理
      this.recognition.onend = () => {
        console.log('Web Speech API recognition ended');
        this.isWebSpeechRecognizing = false;
        // 不再自动重启，由VAD控制
      };

      // 识别开始处理
      this.recognition.onstart = () => {
        console.log('Web Speech API recognition started');
        this.isWebSpeechRecognizing = true;
      };

      return true;
    },

    openWakeWindow() {
      this.withinWakeWindow = true;
      this.wakeWindowTimer = setTimeout(() => {
        this.withinWakeWindow = false;
      }, 30_000);
    },

    /* 刷新 30s 窗口（每次成功交互后调用） */
    resetWakeWindow() {
      clearTimeout(this.wakeWindowTimer);
      this.openWakeWindow();
    },

    /* 清理计时器，可在组件销毁时调用 */
    clearWakeWindow() {
      clearTimeout(this.wakeWindowTimer);
      this.withinWakeWindow = false;
    },

    // 修改：统一的ASR结果处理函数
    handleASRResult(data) {
      if (data.type === 'transcription') {
        const lastMessage = this.messages[this.messages.length - 1];
        if (!this.ttsSettings.enabledInterruption && (this.ttsSettings.enabled||this.settings.enableOmniTTS)) {
          // 如果TTS正在运行，并且不允许中断，则不处理ASR结果
          if(this.TTSrunning){
            if ((!lastMessage || (lastMessage?.currentChunk ?? 0) >= (lastMessage?.ttsChunks?.length ?? 0)) && !this.isTyping) {
              console.log('All audio chunks played');
              lastMessage.currentChunk = 0;
              this.TTSrunning = false;
              this.cur_audioDatas = [];
              // 通知VRM所有音频播放完成
              this.sendTTSStatusToVRM('allChunksCompleted', {});
            }
            else{
              console.log('Audio chunks still playing');
              return;
            }
          }
        }
        else if (this.ttsSettings.enabledInterruption && this.ttsSettings.enabled) {
            console.log('All audio chunks played');
            lastMessage.currentChunk = 0;
            this.TTSrunning = false;
            this.cur_audioDatas = [];
            // 通知VRM所有音频播放完成
            this.sendTTSStatusToVRM('allChunksCompleted', {});
        }
        else if(this.settings.enableOmniTTS && this.ttsSettings.enabledInterruption){
            this.stopAllAudioPlayback();
            this.sendTTSStatusToVRM('allChunksCompleted', {});
        }
        if (data.is_final) {
          // 最终结果
          if (this.userInputBuffer.length > 0) {
            // 用data.text替换this.userInput中最后一个this.userInputBuffer
            this.userInput = this.userInput.slice(0, -this.userInputBuffer.length) + data.text;
            this.userInputBuffer = '';
          } else {
            // 如果没有临时结果，直接添加到userInput
            this.userInput += data.text;
            this.userInputBuffer = '';
          }
          
          if (this.isPttMode || this.waitingForPttResult) {
            console.log("PTT 识别完成，自动发送:", data.text);
            this.sendMessage(); 
            this.userInput = ''; // 发送后清空
            this.waitingForPttResult = false; // 重置标记
            return;
          }

          // 根据交互方式处理
          if (this.asrSettings.interactionMethod == "auto") {
            if (this.ttsSettings.enabledInterruption) {
              this.sendMessage();
            } else if (!this.TTSrunning ||  !this.ttsSettings.enabled) {
              this.sendMessage();
            }
          }
          
          if (this.asrSettings.interactionMethod == "wakeWord") {
            const lowerInput = this.userInput.toLowerCase();
            const hasWakeWord = lowerInput.includes(this.asrSettings.wakeWord.toLowerCase());

            /* 1. 如果在 30s 免唤醒窗口，直接发送 */
            if (this.withinWakeWindow) {
              this.sendMessage();
              this.resetWakeWindow();          // 刷新 30s
              return;
            }

            /* 2. 否则必须检测唤醒词 */
            if (hasWakeWord) {
              this.sendMessage();
              this.openWakeWindow();           // 进入 30s 免唤醒
            } else {
              this.userInput = '';             // 未唤醒，清空输入
            }
          }
          
          if (this.asrSettings.interactionMethod == "wakeWordAndEndWord") {
            const userInputLower = this.userInput.toLowerCase();
            const wakeWordLower = this.asrSettings.wakeWord.toLowerCase();
            const endWordLower = this.asrSettings.endWord.toLowerCase();
            
            // 检查是否包含结束词
            if (userInputLower.includes(endWordLower)) {
              this.inAutoMode = false;
              console.log('End word detected, exiting auto mode');
              showNotification(this.t('endWordDetected'));
              // 可以选择发送包含结束词的消息，或者清空不发送
              this.userInput = '';
            }
            // 检查是否包含唤醒词
            else if (userInputLower.includes(wakeWordLower)) {
              this.inAutoMode = true;
              console.log('ake word detected, entering auto mode');
              // 发送包含唤醒词的消息
              if (this.ttsSettings.enabledInterruption) {
                this.sendMessage();
              } else if (!this.TTSrunning ||  !this.ttsSettings.enabled) {
                this.sendMessage();
              }
            }
            // 如果在自动模式下，所有消息都自动发送
            else if (this.inAutoMode) {
              if (this.ttsSettings.enabledInterruption) {
                this.sendMessage();
              } else if (!this.TTSrunning ||  !this.ttsSettings.enabled) {
                this.sendMessage();
              }
            }
            else{
              this.userInput = '';             // 未唤醒，清空输入
            }
          }
        } else {
          if (this.asrSettings.engine === 'webSpeech'){
            this.userInput = data.text;
            this.userInputBuffer = data.text;
          }else {
            // 临时结果
            this.userInput += data.text;
            this.userInputBuffer += data.text;
          }

        }
      } else if (data.type === 'error') {
        console.error('ASR error:', data.message);
        showNotification(this.t('transcriptionFailed'), 'error');
      } else if (data.type === 'init_response') {
        if (data.status === 'ready') {
          
        }
      }
    },

    // 修改：开关ASR功能
    async toggleASR() {
      this.asrSettings.enabled = !this.asrSettings.enabled;
      this.autoSaveSettings();
      if (this.asrSettings.enabled === true && this.asrSettings.engine === 'sherpa'){
        if (!this.sherpaModelExists){
          showNotification(this.t('autoDownloadModel'), 'info');
          this.asrSettings.enabled = false;
          let source = await this.getAutoSource();
          await this.sherpaDownload(source);
          this.autoSaveSettings();
          return;
        }
      }
      if (this.asrSettings.enabled) {
        await this.startASR();
      } else {
        this.stopASR();
      }
    },

    // 修改：处理ASR设置变化
    async handleASRchange() {
      // 🌟 锁保护：如果正在启动中，直接返回，防止疯狂点击
      if (this.isStartingASR) return;
      
      // 先彻底停止
      await this.stopASR(); 
      if (this.asrSettings.enabled === true && this.asrSettings.engine === 'sherpa'){
        if (!this.sherpaModelExists){
          showNotification(this.t('autoDownloadModel'), 'info');
          this.asrSettings.enabled = false;
          let source = await this.getAutoSource();
          await this.sherpaDownload(source);
          this.autoSaveSettings();
          return;
        }
      }

      if (this.asrSettings.enabled) {
        // 给系统 200ms 时间回收资源
        await new Promise(resolve => setTimeout(resolve, 200));
        await this.startASR();
      }

      this.autoSaveSettings();
    },

    // 修改：启动ASR
    async startASR() {
      if (!this.asrSettings.enabled) return;
      if (this.asrSettings.interactionMethod === 'globalKeyTriggered' || this.asrSettings.interactionMethod === 'keyTriggered') return;
      
      // 🌟 开启启动锁
      if (this.isStartingASR) return;
      this.isStartingASR = true;

      try {
        // 1. 统一获取流
        if (!this.mediaStream) {
          this.mediaStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true }
          });
        }

        // 2. 初始化 VAD
        await this.initVAD();

        // 3. 初始化引擎
        if (this.asrSettings.engine === 'webSpeech') {
          this.initWebSpeechAPI();
        } else {
          // 确保在创建新连接前，旧连接已死
          await this.initASRWebSocket();
        }

        if (this.vad) {
          await this.vad.start();
        }
        
        this.isRecording = true;
      } catch (error) {
        console.error('Start ASR Error:', error);
        this.stopASR();
      } finally {
        // 🌟 释放启动锁
        this.isStartingASR = false;
      }
    },

    // 修改：停止ASR
    async stopASR() {
      console.log('Stopping ASR...');
      this.isRecording = false;
      this.isStartingASR = false;

      // 1. 彻底切断 WebSocket (关键：先抹除监听器)
      if (this.asrWs) {
        this.asrWs.onclose = null; // 🌟 抹除监听，防止触发自动重连死循环
        this.asrWs.onerror = null;
        this.asrWs.onmessage = null;
        this.asrWs.onopen = null;
        if (this.asrWs.readyState !== WebSocket.CLOSED) {
          this.asrWs.close();
        }
        this.asrWs = null;
      }

      // 2. 停止 Web Speech
      if (this.recognition) {
        try {
          this.recognition.onend = null;
          this.recognition.onerror = null;
          this.recognition.abort();
        } catch (e) {}
        this.recognition = null;
        this.isWebSpeechRecognizing = false;
      }

      // 3. 停止 VAD
      if (this.vad) {
        try {
          this.vad.pause();
          if (this.vad.destroy) await this.vad.destroy();
        } catch (e) {}
        this.vad = null;
      }

      // 4. 释放麦克风硬件
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => {
          track.stop();
        });
        this.mediaStream = null;
      }

      // 5. 释放音频上下文
      if (this.audioContext) {
        try {
          await this.audioContext.close();
        } catch (e) {}
        this.audioContext = null;
      }
      
      this.ASRrunning = false;
    },

    // 修改：初始化VAD（Web Speech模式也使用VAD）
    async initVAD() {
      if (!this.mediaStream) return;

      const min_probabilities = this.asrSettings.engine === 'webSpeech' ? 0.7 : 0.2;

      this.vad = await vad.MicVAD.new({
        stream: this.mediaStream,
        preSpeechPadFrames: 10,
        onSpeechStart: () => {
          this.ASRrunning = true;
          this.handleSpeechStart();
        },
        onFrameProcessed: (probabilities, frame) => {
          if (probabilities["isSpeech"] > min_probabilities) {
            // 打断逻辑
            if (this.ttsSettings.enabledInterruption) {
              if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio = null;
              }
              this.stopGenerate();
              this.sendTTSStatusToVRM('stopSpeaking', {});
            }

            if (!this.currentAudio || this.currentAudio.paused) {
              if (this.asrSettings.engine === 'webSpeech') {
                this.handleWebSpeechFrameProcessed();
              } else {
                this.handleFrameProcessed(frame);
              }
            }
          }
        },
        onSpeechEnd: (audio) => {
          this.ASRrunning = false;
          if (this.asrSettings.engine === 'webSpeech') {
            this.handleWebSpeechEnd();
          } else {
            this.handleSpeechEnd(audio);
          }
        },
      });
    },

    handleWebSpeechSpeechStart() {
      console.log('VAD detected speech start for Web Speech API');
      if (!this.isWebSpeechRecognizing && this.recognition) {
        try {
          this.recognition.start();
        } catch (error) {
          // 忽略已经启动的报错
        }
      }
    },


    handleWebSpeechEnd() {
      console.log('VAD detected speech end for Web Speech API');
      if (this.isWebSpeechRecognizing && this.recognition) {
        try {
          this.recognition.stop();
        } catch (error) {
          console.error('Failed to stop Web Speech API:', error);
        }
      }
    },

    // 修改：开始录音（两种模式都需要）
    async startRecording() {
      try {
        // 请求麦克风权限
        this.mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
        
        // 初始化音频上下文
        this.audioContext = new AudioContext();
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);
        
        // 设置VAD参数
        this.vad.start();
        
        this.isRecording = true;
      } catch (error) {
        console.error('Error starting recording:', error);
        this.asrSettings.enabled = false;
        showNotification(this.t('micPermissionDenied'), 'error');
      }
    },

    // 修改：停止录音（两种模式都需要）
    stopRecording() {
      if (this.vad) {
        this.vad.pause();
      }
      
      if (this.mediaStream) {
        this.mediaStream.getTracks().forEach(track => track.stop());
        this.mediaStream = null;
      }
      
      if (this.audioContext) {
        this.audioContext.close();
        this.audioContext = null;
      }
      
      this.isRecording = false;
    },

    async handleSpeechStart() {
      if (this.asrSettings.engine === 'webSpeech') {
        this.handleWebSpeechSpeechStart();
      } else {
        if (!this.asrWs || this.asrWs.readyState !== WebSocket.OPEN) return;
        
        this.currentTranscriptionId = uuid.v4();
        this.asrWs.send(JSON.stringify({
          type: 'audio_start',
          id: this.currentTranscriptionId,
        }));
      }
    },

    async handleSpeechEnd(audio) {
      // 语音结束时的处理
      if (!this.asrWs || this.asrWs.readyState !== WebSocket.OPEN) return;
      
        // 非流式模式，发送完整音频数据
        // 将音频数据转换为WAV格式
        const wavFile = await this.audioToWav(audio);
        
        // 将WAV文件转换为base64编码
        const reader = new FileReader();
        reader.readAsDataURL(wavFile);
        reader.onloadend = () => {
          const base64data = reader.result.split(',')[1]; // 移除前缀
          
          // 发送完整音频数据
          this.asrWs.send(JSON.stringify({
            type: 'audio_complete',
            id: this.currentTranscriptionId,
            audio: base64data,
            format: 'wav'
          }));
        };
    },

  // 1. 按下：开始录音
  async handlePttPress(event) {
    this.stopAllAudioPlayback(); // 停止所有正在播放的音频
    this.TTSrunning = false; // 停止任何正在播放的 TTS
    // 手动阻止默认事件，解决 _withMods 报错
    if (event && event.preventDefault) {
      if (event.type !== 'touchstart') {
        event.preventDefault();
      }
    }

    if (this.isPttRecording || this.isProcessingPtt) return;
    this.isPttRecording = true;

    // ==========================================
    // 分支 A: Web Speech API 模式 (直接复用你现有的 initWebSpeechAPI)
    // ==========================================
    if (this.asrSettings.engine === 'webSpeech') {
      // 如果还没有初始化识别对象，则进行初始化
      if (!this.recognition) {
        const success = this.initWebSpeechAPI();
        if (!success) {
          this.isPttRecording = false;
          return;
        }
      }
      
      try {
        this.recognition.start();
        if (navigator.vibrate) navigator.vibrate(50);
      } catch (e) {
        // 捕获“已经启动”的错误，避免控制台报错
        console.warn("Web Speech already started:", e);
      }
      return; // ⚠️ 关键：直接跳出，不执行下方的 MediaRecorder 逻辑
    }

    // ==========================================
    // 分支 B: 其他 ASR 模式 (二进制流模式：Sherpa/FunASR/OpenAI)
    // ==========================================
    this.audioChunks = []; // 重置数据桶

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.pttStream = stream;

      let options = { mimeType: 'audio/webm' };
      if (!MediaRecorder.isTypeSupported('audio/webm')) {
        options = { mimeType: 'audio/mp4' }; // Safari 兼容
      }
      
      this.pttMediaRecorder = new MediaRecorder(stream, options);

      this.pttMediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          this.audioChunks.push(e.data);
        }
      };

      this.pttMediaRecorder.start();
      
      if (navigator.vibrate) navigator.vibrate(50);

    } catch (error) {
      console.error("PTT Start Error:", error);
      // 如果定义了 showNotification 则调用，否则用 alert 兜底
      if (typeof showNotification === 'function') {
        showNotification(this.t('micPermissionDenied'), 'error');
      }
      this.isPttRecording = false;
    }
  },

  // 2. 松开：停止录音 -> 转码 -> 发送
  async handlePttRelease(event) {
    // 手动阻止默认事件
    if (event && event.preventDefault && event.type !== 'touchend') {
       event.preventDefault();
    }

    if (!this.isPttRecording) return;
    this.isPttRecording = false;

    // ==========================================
    // 分支 A: Web Speech API 模式
    // ==========================================
    if (this.asrSettings.engine === 'webSpeech') {
      if (this.recognition) {
        // 【核心修复】：创建一个一次性的监听器，确保在文字识别彻底完成后发送
        const sendAfterRecognition = () => {
          // 移除监听器，避免下次重复触发
          this.recognition.removeEventListener('end', sendAfterRecognition);
          
          // 给一点点延迟（100ms），确保 handleASRResult 已经把最后的文字更新到 userInput
          setTimeout(() => {
            if (this.userInput && this.userInput.trim() !== '') {
              this.sendMessage(); // 触发发送逻辑
            }
          }, 100);
        };

        // 绑定一次性结束监听
        this.recognition.addEventListener('end', sendAfterRecognition);
        
        this.recognition.stop(); // 停止识别
        if (navigator.vibrate) navigator.vibrate(30);
      }
      return; 
    }

    // ==========================================
    // 分支 B: 其他 ASR 模式 (二进制流停止逻辑)
    // ==========================================
    if (!this.pttMediaRecorder) return;

    this.isProcessingPtt = true;

    // 停止录制
    if(this.pttMediaRecorder.state !== 'inactive') {
        this.pttMediaRecorder.stop();
    }
    
    // 关闭麦克风红点
    if (this.pttStream) {
      this.pttStream.getTracks().forEach(track => track.stop());
      this.pttStream = null;
    }
    
    if (navigator.vibrate) navigator.vibrate(30);

    // 等待录制彻底结束并合并数据
    await new Promise(resolve => {
      this.pttMediaRecorder.onstop = () => resolve();
    });

    // 处理音频逻辑 (原有的 processAndSendPttAudio)
    await this.processAndSendPttAudio();
    
    this.isProcessingPtt = false;
    this.pttMediaRecorder = null;
  },

  // 3. 处理音频逻辑
  async processAndSendPttAudio() {
    if (this.audioChunks.length === 0) return;

    try {
      // 合并录音片段
      const mimeType = this.pttMediaRecorder ? this.pttMediaRecorder.mimeType : 'audio/webm';
      const rawBlob = new Blob(this.audioChunks, { type: mimeType });

      // ★ 核心转换：将 WebM/MP4 转为 16000Hz WAV
      // 这是后端 ASR 通常能识别的最稳妥格式
      const wavBlob = await this.convertBlobToWav(rawBlob, 16000);

      // 发送
      await this.sendPttToBackend(wavBlob);

    } catch (error) {
      console.error("PTT Process Error:", error);
    }
  },

  // 4. 发送给后端 (复用 WebSocket)
  async sendPttToBackend(wavBlob) {
    // 确保连接
    if (!this.asrWs || this.asrWs.readyState !== WebSocket.OPEN) {
      try {
        await this.initASRWebSocket();
        await new Promise(r => setTimeout(r, 500));
      } catch (e) {
        showNotification("无法连接语音服务器", 'error');
        return;
      }
    }

    const reader = new FileReader();
    reader.readAsDataURL(wavBlob);
    reader.onloadend = () => {
      const base64data = reader.result.split(',')[1];
      const reqId = uuid.v4();

      // 发送完整音频包
      this.asrWs.send(JSON.stringify({
        type: 'audio_complete', 
        id: reqId,
        audio: base64data,
        format: 'wav',
        sample_rate: 16000
      }));
      
      // 标记我们在等待 PTT 结果
      this.waitingForPttResult = true;
    };
  },

  // 5. 音频格式转换工具 (必须包含)
  async convertBlobToWav(blob, targetSampleRate = 16000) {
    const arrayBuffer = await blob.arrayBuffer();
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);

    // 离线重采样
    const offlineCtx = new OfflineAudioContext(1, audioBuffer.duration * targetSampleRate, targetSampleRate);
    const source = offlineCtx.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(offlineCtx.destination);
    source.start();
    
    const renderedBuffer = await offlineCtx.startRendering();
    
    return this.bufferToWav(renderedBuffer);
  },

  // 6. Buffer 转 WAV 封装 (必须包含)
  bufferToWav(abuffer) {
    const numOfChan = abuffer.numberOfChannels;
    const length = abuffer.length * numOfChan * 2 + 44;
    const buffer = new ArrayBuffer(length);
    const view = new DataView(buffer);
    const channels = [];
    let i, sample, offset = 0, pos = 0;

    // 写入 WAV 头
    setUint32(0x46464952); // "RIFF"
    setUint32(length - 8); // file length - 8
    setUint32(0x45564157); // "WAVE"
    setUint32(0x20746d66); // "fmt " chunk
    setUint32(16); // length = 16
    setUint16(1); // PCM (uncompressed)
    setUint16(numOfChan);
    setUint32(abuffer.sampleRate);
    setUint32(abuffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
    setUint16(numOfChan * 2); // block-align
    setUint16(16); // 16-bit

    setUint32(0x61746164); // "data" - chunk
    setUint32(length - pos - 4); // chunk length

    for (i = 0; i < abuffer.numberOfChannels; i++)
      channels.push(abuffer.getChannelData(i));

    while (pos < abuffer.length) {
      for (i = 0; i < numOfChan; i++) {
        sample = Math.max(-1, Math.min(1, channels[i][pos]));
        sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
        view.setInt16(44 + offset, sample, true);
        offset += 2;
      }
      pos++;
    }

    function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
    function setUint32(data) { view.setUint32(pos, data, true); pos += 4; } // 注意这里修正了 pos+=4

    return new Blob([buffer], { type: 'audio/wav' });
  }
});
