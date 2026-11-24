// 批 3 F2：自 vue_methods.js 搬移的 methods/10_chat_stream.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    async sendMessage(role = 'user') {
        // S188：生成期间输入非空=插话（入队注入，不开并行流；opencode 式三态按钮）
        if (this.isSending && this.userInput.trim()) { this.interjectSend(); return; }
        // [XMPP Bridge] 扩展注入的图片附件（已上传到 uploaded_files，形如 [{path,name,type}]）
        const hasExtensionImages = Array.isArray(this.extensionImageLinks) && this.extensionImageLinks.length > 0;
        // 基础校验
        if (!this.userInput.trim() && (!this.files || this.files.length === 0) && (!this.images || this.images.length === 0) && !hasExtensionImages) return;
        if (this.isTyping) return;
        // /compact 指令：手动压缩当前会话上下文，不进入常规发送流程
        {
            const _cmd = this.userInput.trim();
            if (_cmd === '/compact' || _cmd.startsWith('/compact ')) {
                const _focus = _cmd.slice('/compact'.length).trim();
                this.userInput = '';
                this.handleCompactCommand(_focus);
                return;
            }
        }
        if (this.CLISettings.enabled) {
            const pathToCheck = this.CLISettings.cc_path;

            if (this.isDangerousPath(pathToCheck)) {
                showNotification(
                    this.t('dangerous_path_detected'),
                    'error',
                );
                return; // 直接返回，不执行后续逻辑
            }

            // 如果校验通过，继续执行...
        }
        // [V2新增]：切换菜单
        if (this.activeMenu === 'dashboard'){
          this.activeMenu = 'home'
        }

        // 处理 TTS/Read 中断
        if (this.readState.isPlaying && this.ttsSettings.enabled) { 
            if (this.isReadRunning){
                this.pauseRead();
            } else {
                this.stopSegmentTTS(false);
            }
            this.isReadInterruption = true;
        }

        if (this.currentAudio){
            this.currentAudio.pause();
            this.currentAudio = null;
        }
        this.stopAllAudioPlayback();
        this.TTSrunning = false;

        if ((this.vrmOnline || this.vtsOnline) && this.ttsWebSocket) {
            this.ttsWebSocket.send(JSON.stringify({ type: 'ttsStarted', data: {} }));
        }

        this.isTyping = true;
        this.startTimer();

        if (typeof this.sendTTSStatusToVRM === 'function') {
            this.sendTTSStatusToVRM('ttsStarted', {});
        }

      let captureFlag = false;
      if (this.isElectron && this.visionSettings?.desktopVision) {
          if (this.visionSettings.enableWakeWord && this.visionSettings.wakeWord) {
              const wakeWords = this.visionSettings.wakeWord.split('\n');
              if (wakeWords.some(word => this.userInput.includes(word.trim()))) {
                  captureFlag = true;
              }
          } else {
              captureFlag = true;
          }
      }

        // --- 文件上传处理 ---
        const userInput = this.userInput.trim();
        let fileLinks = this.files || [];
        
        if (fileLinks.length > 0){
            const formData = new FormData();
            for (const file of fileLinks) {
                if (file.file instanceof Blob) { 
                    formData.append('files', file.file, file.name);
                }
            }
            try {
                const response = await fetch(`/load_file`, { method: 'POST', body: formData });
                const data = await response.json();
                if (data.success) {
                    fileLinks = data.fileLinks;
                    this.textFiles = [...this.textFiles, ...data.textFiles];
                }
            } catch (error) { console.error(error); }
        }

        let imageLinks = this.images || [];
        if (imageLinks.length > 0){
            const formData = new FormData();
              for (const file of imageLinks) {
                  if (file.file instanceof Blob) { 
                      formData.append('files', file.file, file.name , file.detectedType); // [V2新增]：detectedType
                  } 
              }
              try {
                  const response = await fetch(`/load_file`, { method: 'POST', body: formData });
                  const data = await response.json();
                  if (data.success) {
                    imageLinks = data.fileLinks;
                    this.imageFiles = [...this.imageFiles, ...data.imageFiles];
                    if(data.vedioFiles) { // [V2新增]：视频支持
                        this.vedioFiles = [...(this.vedioFiles || []), ...data.vedioFiles];
                    }
                  }
              } catch (error) { console.error(error); }
        }

        // [XMPP Bridge] 合并扩展注入的图片附件（已上传到 SAP，无需再次上传），作为本次发言的附图传给 Agent
        if (hasExtensionImages) {
            const validExtLinks = this.extensionImageLinks.filter(l => l && typeof l.path === 'string' && /^https?:\/\//i.test(l.path));
            if (validExtLinks.length > 0) {
                imageLinks = [...imageLinks, ...validExtLinks];
            }
        }

        // --- 核心修复点：确保 this.fileLinks 是数组 ---
        if (!Array.isArray(this.fileLinks)) {
            this.fileLinks = []; 
        }

        // 构造文件链接字符串
        const fileLinks_content = fileLinks.map(fileLink => `\n[文件名：${fileLink.name}\n文件链接: ${fileLink.path}]`).join('\n') || '';
        const fileLinks_list = Array.isArray(fileLinks) ? fileLinks.map(fileLink => fileLink.path).flat() : []
        this.fileLinks = this.fileLinks.concat(fileLinks_list)

        // --- 推送用户消息到界面 ---
        this.messages.push({
            id: Date.now() + Math.random(),
            role: role,
            content: userInput,
            fileLinks: fileLinks,
            fileLinks_content: fileLinks_content,
            imageLinks: imageLinks || [],
            hasDesktopVision: captureFlag, // ✨ 新增标记：告诉 UI 这条消息触发了后端截图
            agentName: this.memorySettings.userName || 'User' 
        });

        this.sendMessagesToExtension();
        this.files = [];
        this.images = [];
        this.extensionImageLinks = []; // [XMPP Bridge] 消费后清空注入附件，避免下次发言重复附图
        this.userInput = '';
        
        this.$nextTick(() => { this.requestScrollToBottom(); });

        // --- 调度逻辑：群聊 vs 单聊 ---
        this.isSending = true; 
        this.abortController = new AbortController(); 

        try {
                if (this.isGroupMode && this.selectedGroupAgents && this.selectedGroupAgents.length > 0) {
                    // == 群聊模式：随机串行调用 ==
                    
                    // 创建副本并随机打乱 (Fisher-Yates Shuffle)
                    let executionList = [...this.selectedGroupAgents];
                    for (let i = executionList.length - 1; i > 0; i--) {
                        const j = Math.floor(Math.random() * (i + 1));
                        [executionList[i], executionList[j]] = [executionList[j], executionList[i]];
                    }

                    // 遍历打乱后的列表
                    for (const targetId of executionList) {
                        if (this.abortController.signal.aborted) break;

                        let agentDisplayName = "Unknown";
                        
                        // 解析显示名称
                        if (targetId.startsWith('memory/')) {
                            const memId = targetId.split('/')[1];
                            const memRecord = this.memories.find(m => String(m.id) === String(memId));
                            agentDisplayName = memRecord ? memRecord.name : "Role";
                        } else if (targetId === 'super-model') {
                            agentDisplayName = this.t('defaultAgent');
                        } else if (this.agents[targetId]) {
                            agentDisplayName = this.agents[targetId].name;
                        }

                        // 调用生成函数
                        await this.generateAIResponse(targetId, agentDisplayName);
                    }
                } else {
                // == 单聊模式 ==
                let currentName = 'Assistant';
                if (this.mainAgent === 'super-model') currentName = this.t('defaultAgent');
                else if (this.agents[this.mainAgent]) currentName = this.agents[this.mainAgent].name;

                await this.generateAIResponse(this.mainAgent, currentName);
            }
        } catch (e) {
            console.error("Chat dispatch error:", e);
        } finally {
            this.isTyping = false;
            this.isSending = false;
            this.abortController = null;
            await this.autoSaveSettings();
            await this.flushDirtyConversations();
        }
    },

    // ==========================================
    // 2. AI 生成与流式处理函数（支持 Human-in-the-loop 审批）
    // ==========================================
    async generateAIResponse(targetAgentId, agentDisplayName = null, isResume = false) {
        this.startTimer();
        this.voiceStack = ['default'];
        let tts_buffer = '';
        let isCodeBlock = false;
        this.cur_voice = 'default';

        const toolCallStack = [];
        this.toolArgsAccumulator = this.toolArgsAccumulator || {};

        // 内部函数：准备发送给 API 的消息历史（保持不变）
        const prepareMessages = (msgs) => {
            const rawMessages = msgs.flatMap(msg => {
                const userName = this.memorySettings?.userName || 'User';

                // --- 1. 处理人类用户 / 群聊消息 ---
                if (this.isGroupMode && (msg.role === 'user' || (msg.role === 'assistant' && msg.agentName !== agentDisplayName))) {
                    let textContent = (msg.pure_content ?? msg.content) + (msg.fileLinks_content ?? '');
                    const prefix = msg.role === 'user' ? userName : msg.agentName;
                    const finalContent = `${prefix}: ${textContent}`;

                    if (msg.imageLinks && msg.imageLinks.length > 0) {
                        const contentArray = [{ type: "text", text: finalContent }];
                        msg.imageLinks.forEach(imageLink => {
                            const ext = imageLink.path.split('.').pop().toLowerCase();
                            const videoExts = ['mp4', 'webm', 'ogg', 'mov', 'avi'];
                            if (videoExts.includes(ext)) {
                                contentArray.push({ type: "video_url", video_url: { url: imageLink.path } });
                            } else {
                                contentArray.push({ type: "image_url", image_url: { url: imageLink.path } });
                            }
                        });
                        return [{ role: 'user', content: contentArray }];
                    } else {
                        return [{ role: 'user', content: finalContent }];
                    }
                }

                if (msg.role === 'assistant' && msg.backend_content && msg.backend_content.length > 0) {
                    const kept = msg.backend_content.filter(m => 
                        (m.content && String(m.content).trim() !== '') || 
                        (m.tool_calls && m.tool_calls.length > 0) || 
                        m.role === 'tool'
                    );
                    if (kept.length > 0) return kept;
                    const body = String((msg.pure_content ?? msg.content ?? '') + (msg.fileLinks_content ?? ''));
                    if (body.trim()) return [{ role: 'assistant', content: body }];
                    return kept;
                }
                
                let apiRole = msg.role === 'system' ? 'system' : (msg.role === 'assistant' ? 'assistant' : 'user');
                let textContent = (msg.pure_content ?? msg.content) + (msg.fileLinks_content ?? '');
                
                // --- 2. 处理单聊 / 常规消息 ---
                if (msg.imageLinks && msg.imageLinks.length > 0) {
                    const contentArray = [{ type: "text", text: textContent }];
                    msg.imageLinks.forEach(imageLink => {
                        const ext = imageLink.path.split('.').pop().toLowerCase();
                        const videoExts = ['mp4', 'webm', 'ogg', 'mov', 'avi'];
                        if (videoExts.includes(ext)) {
                            contentArray.push({ type: "video_url", video_url: { url: imageLink.path } });
                        } else {
                            contentArray.push({ type: "image_url", image_url: { url: imageLink.path } });
                        }
                    });
                    return [{ role: apiRole, content: contentArray }];
                } else {
                    return [{ role: apiRole, content: textContent }];
                }
            });

            const sanitized =[];
            for (let i = 0; i < rawMessages.length; i++) {
                const current = rawMessages[i];
                if (current.role === 'tool') {
                    let prev = sanitized.length > 0 ? sanitized[sanitized.length - 1] : null;
                    if (!prev || prev.role !== 'assistant') {
                        prev = { role: 'assistant', content: null, tool_calls:[] };
                        sanitized.push(prev);
                    }
                    if (!prev.tool_calls) prev.tool_calls =[];
                    
                    const safeToolCallId = current.tool_call_id || `call_${Date.now()}_${Math.random().toString(36).substr(2, 5)}`;
                    current.tool_call_id = safeToolCallId;

                    const hasMatchingId = prev.tool_calls.some(tc => tc.id === safeToolCallId);
                    if (!hasMatchingId) {
                        prev.tool_calls.push({
                            id: safeToolCallId,
                            type: 'function',
                            function: { name: current.name || 'unknown_tool', arguments: "{}" }
                        });
                    }
                }
                sanitized.push(current);
            }
            return sanitized;
        };

        // 第一步：打包 Payload
        let messagesPayload = prepareMessages(this.messages);
        if (this.extensionsSystemPromptsDict) {
            const combinedPrompt = Object.values(this.extensionsSystemPromptsDict).filter(Boolean).join('\n\n');
            if (messagesPayload[0]?.role === 'system') messagesPayload[0].content += '\n\n' + combinedPrompt;
            else messagesPayload.unshift({ role: 'system', content: combinedPrompt });
        }

        let currentMsg;
        let shouldSyncGroupMemory = false;
        if (isResume && this.messages.length > 0) {
            // S307(F5)：续跑溯源观测（df2f8248 头部残缺取证）——每次 resume POST 向
            // evidence 通道留一条消息形态记录，firstUserIdx=-1 即缺头冒烟证据。
            try {
                const _fu = this.messages.findIndex(m => m && m.role === 'user');
                console.warn('[ResumeProvenance] conv=' + this.stringifyEntityId(this.conversationId)
                    + ' msgs=' + this.messages.length + ' payload=' + messagesPayload.length
                    + ' firstUserIdx=' + _fu + ' page=' + (location.pathname.split('/').pop() || 'index'));
            } catch (_) { }
            currentMsg = this.messages[this.messages.length - 1];
            currentMsg.generationFinished = false;
        } else {
            const newMsgData = {
                id: Date.now() + Math.random(),
                role: 'assistant',
                agentName: agentDisplayName,
                content: '',         // 不再使用 HTML，最后会被清空
                pure_content: '',
                backend_content: [{ role: 'assistant', content: '' }],
                toolBlocks: {},
                displayBlocks: [],
                isOmni: this.settings.enableOmniTTS || this.fastSettings.enableOmniTTS,
                omniAudioChunks: [], ttsChunks: [], chunks_voice: [], audioChunks: [],
                isPlaying: false, total_tokens: 0, completion_tokens: 0, context_tokens: 0,
                tok_per_sec: 0, usage_est: false, first_token_latency: 0, elapsedTime: 0,
                generationFinished: false
            };
            this.messages.push(newMsgData);
            currentMsg = this.messages[this.messages.length - 1];
        }
        // B2-2(16f079d4): 提前创建会话，深度研究等长耗时流式期间 30s 增量保存正常工作
        this.ensureConversationCreated(messagesPayload);
        const latestUserMessage = [...this.messages].reverse().find(msg => msg.role === 'user');

        // 获取块的辅助函数（带冻结，支持流式复用）
        const getBlock = (type, id = null, name = null) => {
            if (!currentMsg.displayBlocks) currentMsg.displayBlocks = [];
            const blocks = currentMsg.displayBlocks;
            
            // 如果有 id，先查找已存在的块（如 tool_call / tool_result 复用）
            if (id) {
                const existing = blocks.find(b => b.type === type && b.id === id);
                if (existing) {
                    // S187：冻结块补写 name 会抛 set falsish → 先判冻结
                    if (name && !existing.name) {
                        const _rex = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(existing) : existing;
                        if (!Object.isFrozen(_rex)) existing.name = name;
                    }
                    return existing;
                }
            }
            
            // 检查最后一个块是否可复用（类型相同且未被冻结）
            const last = blocks[blocks.length - 1];
            const canReuse = last && last.type === type && !Object.isFrozen(last) && (!id || last.id === id);
            if (canReuse) {
                if (name && !last.name) last.name = name;
                return last;
            }
            
            // 不复用，先冻结上一个不同类型的块（使其脱离响应式）
            // S187：toRaw 原目标操作，根治「先冻块后经代理读 .data」的 V8 不变量违例；
            // 未批复审批卡不冻结（批复/点击需要可写），转结果块后下次收尾自然可冻
            if (last) {
                const _raw = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(last) : last;
                if (_raw.type !== 'approval' && !Object.isFrozen(_raw)) {
                    Object.freeze(_raw);
                    if (typeof _raw.content === 'string') Object.freeze(_raw.content);
                    if (typeof _raw.args === 'string') Object.freeze(_raw.args);
                    if (_raw.data) {
                        if (typeof Vue !== 'undefined' && Vue.markRaw) Vue.markRaw(_raw.data);
                        Object.freeze(_raw.data);
                    }
                }
            }
            
            // 创建新块并推入数组
            const newBlock = { type, id, name, content: '', args: '', data: null };
            blocks.push(newBlock);
            return newBlock;
        };

        this.$nextTick(() => { this.requestScrollToBottom(); });

        let audioResolve = null;
        let audioProcess = null;
        const audioPromise = new Promise((resolve) => { audioResolve = resolve; });
        if (this.ttsSettings.enabled) {
            this.startTTSProcess(currentMsg);
            this.startAudioPlayProcess(currentMsg, audioResolve);
            audioProcess = audioPromise;
        }

        const escapeHtml = (text) => {
            if (!text) return '';
            return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        // === 断点续传：追踪 stream_id 和已处理 chunk 数量 ===
        // 必须声明在 try 之前：catch 的续传分支需要可见（原声明在 try 体内=
        // 断线时 catch 抛 ReferenceError，resume 从未生效且吞掉错误提示，eslint no-undef 抓获）
        let _streamId = null;
        let _chunkIndex = 0;
        const _enableStreamResume = this.settings?.enableStreamResume !== false;
            this._resumeSawApproval = false; // S172: 每条新流重置审批刹车标记
            this._pendingApprovalToolCallId = null; // S186: 每条新流重置活卡点名标记
            this._resumeSawAsk = false; // S195: 提问刹车标记
            this._pendingAskToolCallId = null; // S195: 活提问卡点名标记

        try {
            const response = await fetch(`/v1/chat/completions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    model: targetAgentId,
                    messages: messagesPayload,
                    stream: true,
                    fileLinks: this.fileLinks,
                    asyncToolsID: this.asyncToolsID || [],
                    reasoning_effort: this.reasoning_effort,
                    conversation_id: this.stringifyEntityId(this.conversationId),
                    group_id: this.stringifyEntityId(this.activeConversationGroupId || this.draftConversationGroupId || 'default'),
                    user_message_id: this.stringifyEntityId(latestUserMessage?.id || null),
                }),
                signal: this.abortController.signal
            });

            if (!response.ok) {
                let errText = await response.text();
                try { const errObj = JSON.parse(errText); errText = errObj.error?.message || errText; } catch (e) { }
                throw new Error(errText);
            }

            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                let errText = await response.text();
                try { const errObj = JSON.parse(errText); errText = errObj.error?.message || errText; } catch (e) { }
                throw new Error(errText);
            }


            // 初始化流式文本批量更新状态
            this._streamTargetMsg = currentMsg;
            this._streamTextBuffer = '';
            this._streamReasoningBuffer = '';
            this._streamRecvChars = 0;
            this._streamFlushChars = 0;
            this._streamT0 = Date.now(); // S309b：tok/s 速率基准（resume 路径不重置，保持整段口径）
            this._flowTs = 0; this._flowChars = 0; this._tokEma = 0; // S316：瞬时速率窗口状态重置
            this.streamLiveStats = null; // S310：实时徽章随流重置

            // C-14: 响应头兜底获取 stream_id——meta 首帧之前（长排队/长提示）
            // 断线也能 resume，停止按钮也能取消后端生产者流
            if (_enableStreamResume && !_streamId) {
                const _hdrStreamId = response.headers.get('X-Stream-Id');
                if (_hdrStreamId) {
                    _streamId = _hdrStreamId;
                    this._currentStreamId = _streamId;
                }
            }

            await iterateSse(response, (parsed) => {
                    // 上下文管理：服务端自动压缩事件 -> 前端替换历史落账
                    if (parsed.type === 'context_compact') {
                        this.applyContextCompact(parsed);
                        return;
                    }
                    if (parsed.type === 'context_usage') {
                        this.updateContextStats(parsed);
                        return;
                    }
                    if (parsed.type === 'stream_usage') { // S309b：消息级计费累计控制帧
                        this._applyStreamUsage(currentMsg, parsed);
                        return;
                    }
                    if (parsed.type === 'todo_stats') {
                        this.updateTodoStats(parsed);
                        return;
                    }
                    const delta = parsed.choices?.[0]?.delta;
                    if (!delta) return;

                    // 断点续传：捕获 stream_id（后端首帧携带）
                    if (delta.stream_id && !_streamId) {
                        _streamId = delta.stream_id;
                        this._currentStreamId = _streamId;
                        return;
                    }
                    // S207：瞬断恢复控制帧——重试提示 + 整轮重发预备（保留半截
                    // 气泡，直到新输出到达才替换；重试边界不含工具执行）
                    if (delta.stream_retry) { this._showStreamRetryNote(delta.stream_retry); return; }
                    if (delta.stream_reset) { this._armStreamReset(delta.stream_reset); return; }
                    _chunkIndex++;

                    if (!currentMsg.first_token_latency) { // S309b: guarded-once，任意类型首帧即首token（修每帧覆写 bug）
                        const hasPayload = delta.content || delta.reasoning_content || delta.tool_progress
                            || (delta.tool_calls && delta.tool_calls.length) || delta.audio?.data;
                        if (hasPayload) {
                            this.stopTimer();
                            currentMsg.first_token_latency = this.elapsedTime;
                        }
                    }

                    // A. 处理思考 (Reasoning) —— S92: 与文本同款 80ms 缓冲，杜绝每 token 触发渲染
                    if (delta.reasoning_content) {
                        this._consumeStreamReset(currentMsg, toolCallStack); // S207: 半截气泡在此刻替换
                        this._streamTargetMsg = currentMsg;
                        this._streamReasoningBuffer = (this._streamReasoningBuffer || '') + delta.reasoning_content;
                        this._streamRecvChars = (this._streamRecvChars || 0) + delta.reasoning_content.length;
                        if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                        this._streamUpdateTimer = setTimeout(() => {
                            this.flushStreamTextBuffer();
                        }, this.streamFlushWait());
                    }

                    // B. 处理文本 (Content) —— 流式防抖更新
                    if (delta.content) {
                        this._consumeStreamReset(currentMsg, toolCallStack); // S207: 半截气泡在此刻替换
                        // 缓冲文本，不再直接操作 DOM
                        this._streamTextBuffer += delta.content;
                        this._streamRecvChars = (this._streamRecvChars || 0) + delta.content.length;

                        // 为 TTS 即时处理
                        const parts = delta.content.split('```');
                        for (let i = 0; i < parts.length; i++) {
                            if (!isCodeBlock) { tts_buffer += parts[i]; }
                            if (i < parts.length - 1) { isCodeBlock = !isCodeBlock; }
                        }
                        const { chunks, chunks_voice, remaining, remaining_voice } = this.splitTTSBuffer(tts_buffer);
                        if (chunks.length > 0) {
                            currentMsg.chunks_voice.push(...chunks_voice);
                            currentMsg.ttsChunks.push(...chunks);
                        }
                        tts_buffer = remaining;
                        this.cur_voice = remaining_voice;

                        // 防抖合并到 displayBlocks
                        if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                        this._streamUpdateTimer = setTimeout(() => {
                            this.flushStreamTextBuffer();
                        }, this.streamFlushWait());
                    }

                    // C. 工具 Loading 状态 (tool_progress) —— 只更新 displayBlocks
                    if (delta.tool_progress) {
                        this._consumeStreamReset(currentMsg, toolCallStack); // S207: 新轮调用参数到达=替换时刻
                        this._ingestToolProgress(delta.tool_progress, getBlock, toolCallStack, currentMsg);
                        return;
                    }

                    // D. 工具结果 / 错误 / 审批 —— 共用摄取器（与 resume 重放同一事实源）
                    if (delta.tool_content) {
                        this._ingestToolFrame(delta.tool_content, delta, currentMsg, getBlock, toolCallStack);
                    }

                    if (delta.audio?.data) {
                        this.playPCMChunk(delta.audio.data, currentMsg.pure_content, currentMsg);
                    }
                    if (parsed.usage?.total_tokens) {
                        currentMsg.total_tokens += parsed.usage.total_tokens;
                    }
                    if (delta.async_tool_id) {
                        if (!this.asyncToolsID) this.asyncToolsID = [];
                        if (!this.asyncToolsID.includes(delta.async_tool_id)) {
                            this.asyncToolsID.push(delta.async_tool_id);
                        }
                    }

                    if (delta.approval_pending) {
                        // S186：后端宣告唯一活卡——流收尾时仅该卡保留可操作
                        this._pendingApprovalToolCallId = delta.approval_pending.tool_call_id || null;
                        this._resumeSawApproval = true;
                    }

                    if (delta.ask_pending) {
                        // S195：后端宣告唯一活提问卡——流收尾时仅该卡保留可操作
                        this._pendingAskToolCallId = delta.ask_pending.tool_call_id || null;
                    }

                    if (delta.interject) {
                        this._ackInterject(delta.interject.content); // S188：插话注入确认
                    }

                    this.sendMessagesToExtension();
            });

            // 循环结束后，强制刷新缓冲区中剩余的文字
            if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
            this.flushStreamTextBuffer();
            this._finalizeUsage(currentMsg); // S309b：无 usage 帧时字符估算兜底
            this._flushToolStream(); // S93(F4)
            this._collapseStaleApprovalCards(currentMsg); // S186: 收尾折叠未点名孤儿审批卡
            this._collapseStaleAskCards(currentMsg); // S195: 收尾折叠未点名孤儿提问卡
            this._ijFinished(); // S188: 插话收尾兜底（停止留区/审批挂起/自动补发）
            if (currentMsg) currentMsg._rv = (currentMsg._rv || 0) + 1; // S107: 流尾终态兜底 bump

            if (tts_buffer.trim() && this.ttsSettings.enabled) {
                currentMsg.chunks_voice.push(this.cur_voice);
                currentMsg.ttsChunks.push(tts_buffer);
            }

            this._markReasoningDone(currentMsg); // S93(F2)
            currentMsg.generationFinished = true;

            // R2-5：生成完毕系统通知（Electron 且窗口未聚焦且开关开启）
            if (this.isElectron && this.systemSettings.enableNotifications && !document.hasFocus()) {
              window.electronAPI?.showNotification('Super Agent Party', this.t('aiGenerationComplete'));
            }

            // S81：流式收尾不再手动 MathJax typeset——KaTeX/texmath 已在渲染管线内排版

            if (this.ttsSettings.enabled) {
                if (this.audioStartTime > this.audioCtx.currentTime) {
                    const remainingTime = (this.audioStartTime - this.audioCtx.currentTime) * 1000;
                    setTimeout(() => { this.sendTTSStatusToVRM('allChunksCompleted', {}); }, remainingTime);
                } else {
                    this.sendTTSStatusToVRM('allChunksCompleted', {});
                }
            }

        } catch (error) {
            console.error(error);
            if (error.name !== 'AbortError') {
                // === 断点续传：如果是网络中断且后端支持续传，尝试自动恢复 ===
                if (_enableStreamResume && _streamId && _chunkIndex > 0 && currentMsg && !currentMsg.generationFinished && !this._resumeSawApproval) {
                    console.log(`[StreamResume] 网络中断，尝试断点续传: stream_id=${_streamId}, from_index=${_chunkIndex}`);
                    const resumed = await this._resumeStream(
                        _streamId, _chunkIndex, currentMsg, getBlock,
                        isCodeBlock, tts_buffer, toolCallStack
                    );
                    if (resumed) {
                        // 续传成功，更新 chunkIndex 并跳过错误处理
                        _chunkIndex = resumed.newChunkIndex;
                        _streamId = resumed.newStreamId || _streamId;
                        // 续传成功后正常完成
                        if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                        this.flushStreamTextBuffer();
                        this._finalizeUsage(currentMsg); // S309b
                        this._flushToolStream(); // S93(F4)
                        this._collapseStaleApprovalCards(currentMsg); // S186: 续传收尾折叠孤儿审批卡
                        this._collapseStaleAskCards(currentMsg); // S195: 续传收尾折叠孤儿提问卡
                        this._ijFinished(); // S188: 插话收尾兜底
                        this._markReasoningDone(currentMsg); // S93(F2)
                        currentMsg.generationFinished = true;
                        if (audioResolve) audioResolve();
                        return; // 跳过 finally 中的错误处理
                    }
                    // 续传失败，回退到原有错误处理逻辑
                    console.warn('[StreamResume] 断点续传失败，回退到错误处理');
                }
                showNotification(error.message, 'error');

                const b = getBlock('error', 'err', 'System Error');
                b.content = this.truncateDisplayContent(error.message);
                if (currentMsg) {
                    if (Array.isArray(currentMsg.displayBlocks)) {
                        if (!currentMsg.displayBlocks.some(bl => bl && bl.type === 'error')) {
                            currentMsg.displayBlocks.push(b);
                        }
                    } else {
                        currentMsg.displayBlocks = [b];
                    }
                }
                if (currentMsg) {
                    const fallbackText = 'response error';
                    if (!currentMsg.pure_content && currentMsg.backend_content.length <= 1) {
                        currentMsg.pure_content = fallbackText;
                        currentMsg.backend_content = [{ role: 'assistant', content: fallbackText }];
                    } else {
                        const lastBackend = currentMsg.backend_content[currentMsg.backend_content.length - 1];
                        if (lastBackend && lastBackend.role === 'assistant' && lastBackend.tool_calls) {
                            delete lastBackend.tool_calls;
                        }
                        currentMsg.backend_content.push({ role: 'assistant', content: fallbackText });
                    }
                }
            }
            if (audioResolve) audioResolve();
        } finally {
            this.isSending = false;
            this.isTyping = false;
            this.voiceStack = ['default'];
            if (this.allBriefly) currentMsg.briefly = true;

            // 清空 content 字段（不再需要 HTML）
            if (currentMsg) {
                currentMsg.content = '';
            }

            // 消息去重和保存（B2-2: 创建/刷新逻辑收拢到 ensureConversationCreated 单点）
            this.ensureConversationCreated(messagesPayload);

            // 历史全量保留：旧消息不再截断/掏空（渲染由 MAX_RENDERED_BLOCKS 分块虚拟化，
            // 上下文体积由服务端 contextManagement 管线负责）

            // 正文写回：pure_content → backend_content 尾项 + content（防 LLM 侧整条消失）
            if (currentMsg) this._syncAssistantBody(currentMsg);

            // 截断后端消息中过长的 tool content，保护 AI 上下文
            if (currentMsg && currentMsg.backend_content) {
                const AI_MAX_TOOL_LENGTH = 15000;
                currentMsg.backend_content.forEach(item => {
                    if (item.role === 'tool' && item.content && typeof item.content === 'string') {
                        if (item.content.length > AI_MAX_TOOL_LENGTH) {
                            item.content = item.content.slice(0, AI_MAX_TOOL_LENGTH) + '\n... (Truncated)';
                        }
                    }
                });
            }

            // 冻结已完成消息的所有 displayBlocks 及内部字符串，减少响应式开销
            if (currentMsg && Array.isArray(currentMsg.displayBlocks)) {
                currentMsg.displayBlocks.forEach(block => {
                    // S187：toRaw 原目标 + 未批复审批卡跳过（toast 元凶=冻结后经代理读 .data）
                    const _raw = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(block) : block;
                    if (_raw.type === 'approval' || _raw.type === 'ask') return; // S195: 活提问卡同审批不冻结
                    if (!Object.isFrozen(_raw)) {
                        Object.freeze(_raw);
                        if (typeof _raw.content === 'string') Object.freeze(_raw.content);
                        if (typeof _raw.args === 'string') Object.freeze(_raw.args);
                        if (_raw.data) {
                            if (typeof Vue !== 'undefined' && Vue.markRaw) Vue.markRaw(_raw.data);
                            Object.freeze(_raw.data);
                        }
                    }
                });
            }
            // S82(B10/399b66ea)：backend_content 不再浅冻结——条目后续仍会被
            // 截断/同步/追加改写，冻结对象在 strict 下改写抛错=渲染卡死元凶
            // （displayBlocks 的冻结保留：纯展示+getBlock 有 isFrozen 复用判定）

            this.markConvDirty(this.conversationId);
            this.flushDirtyConversations();

            // 【修复】流完成后强制广播最终消息状态，确保插件收到完整回复
            // 即使流末尾的 chunk 调用因 WS 断线被暂存，此处也会补发或排队
            this.sendMessagesToExtension(true);

            if (this.ttsSettings.enabled && audioProcess) {
                await audioProcess;
            }

            this.isThinkOpen = false;
            shouldSyncGroupMemory = !!currentMsg?.pure_content?.trim();

            setTimeout(() => {
                if (!this.isSending && this.audioStartTime <= this.audioCtx.currentTime) {
                    this.sendTTSStatusToVRM('allChunksCompleted', {});
                }
            }, 1000);

            if (shouldSyncGroupMemory && latestUserMessage?.id && currentMsg?.id) {
                await this.syncGroupMemoryAfterReply(latestUserMessage, currentMsg);
            }

            // 清理流式缓冲区状态
            this.flushStreamTextBuffer(); // 兜底：异常路径也确保缓冲落账
            this._flushToolStream(); // S93(F4)
            this._streamTargetMsg = null;
            this._streamTextBuffer = '';
            this._streamReasoningBuffer = '';
            this._streamRecvChars = 0;
            this._streamFlushChars = 0;
            if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
        }
    },

    // === Human-in-the-loop 处理函数 ===
    async processToolApproval(toolCallId, action) {
        const currentMsg = this.messages[this.messages.length - 1];
        if (!currentMsg) return;

        // S186：仅 per-toolCallId 处理中锁拒重入（生成期间点击活卡合法；
        // S185 的全局 isSending/isTyping 拒入会让卡片在生成期点击零反馈——撤销）
        if (!this._approvalInFlight) this._approvalInFlight = {};
        if (this._approvalInFlight[toolCallId]) {
            if (typeof showNotification === 'function') {
                showNotification('该审批正在处理中，请勿重复点击', 'warning');
            }
            return;
        }
        if (!this.approvalMap[toolCallId]) {
            // 审批已消费或失效：安全降级——不触后端、不唤醒模型
            if (typeof showNotification === 'function') {
                showNotification('该审批已处理或已失效，未触发新的请求', 'warning');
            }
            return;
        }
        this._approvalInFlight[toolCallId] = true;
        try {
        const data = this.approvalMap[toolCallId];
        const toolName = data?.tool_name || 'Tool';
        const blockId = `approval-${toolCallId}`;

        // 【修复1】：用变量直接缓存找到的目标块的引用，不再二次查找
        // S187：数组元素替换式转块——冻结卡经代理改写必失败；替换出新可写对象，
        // 点击瞬间即变结果块（不等本次回应完成）
        let targetBlock = null;
        if (currentMsg.displayBlocks) {
            // 严格限定不仅 id 要匹配，而且必须是我们初始的 approval 块
            const _idx = currentMsg.displayBlocks.findIndex(b => b && b.id === toolCallId && b.type === 'approval');
            if (_idx !== -1) {
                const _src = (typeof Vue !== 'undefined' && Vue.toRaw)
                    ? Vue.toRaw(currentMsg.displayBlocks[_idx]) : currentMsg.displayBlocks[_idx];
                const _nb = Object.assign({}, _src, {
                    type: 'tool_result',
                    name: action === 'deny' ? this.t('denying') : `${this.t('executing')} ${toolName}...`,
                });
                this._setResultDisplay(_nb, '');
                currentMsg.displayBlocks[_idx] = _nb;
                targetBlock = _nb;
                currentMsg._rv = (currentMsg._rv || 0) + 1;
            }
        }

        if (!targetBlock) {
            // 审批卡已不存在（已转结果块）：安全降级，不触后端也不唤醒模型
            if (typeof showNotification === 'function') {
                showNotification('该审批已处理或已失效，未触发新的请求', 'warning');
            }
            return;
        }

        // 【修复2】：补充定义转义方法，避免 this.escapeHtml 报错崩溃
        const escapeHtml = (text) => {
            if (!text) return '';
            return String(text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
        };

        const feedbackTitle = action === 'deny' ? (this.t('denying') || 'Denying...') : `${this.t('executing') || 'Executing'} ${toolName}...`;
        this.updateUIBlock(currentMsg, blockId, `\n`);

        this.isSending = true; 
        this.isTyping = true;
        this.abortController = new AbortController(); 

        try {
            let resultText = "";
            if (action === 'deny') {
                resultText = `User denied the execution of tool '${toolName}'.`;
            } else {
                resultText = await this.executeToolBackend(toolName, data.tool_params, action, data._stream_id);

                // S186：幂等吞掉/已取消的闭合结果——折叠为禁用结果块、回写历史，
                // 绝不唤醒模型（旧版把 "[已处理]" 当正常结果照样 generateAIResponse）
                const _finalNote = String(resultText || '');
                if (_finalNote.startsWith('[已处理]') || _finalNote.startsWith('[Cancelled]')) {
                    if (targetBlock) {
                        targetBlock.type = 'tool_result';
                        targetBlock.expired = true;
                        targetBlock.name = `${toolName} ${this.t('tool_result')}`;
                        this._setResultDisplay(targetBlock, _finalNote);
                        currentMsg._rv = (currentMsg._rv || 0) + 1;
                    }
                    this.updateUIBlock(currentMsg, blockId, `\n<div class="sap-process-block type-result" id="${blockId}"><div class="sp-header"><i class="fa-solid fa-circle-info"></i> ${escapeHtml(toolName)}</div><pre class="sp-content sp-code">${escapeHtml(_finalNote)}</pre></div>\n`);
                    if (currentMsg.backend_content) {
                        for (let i = currentMsg.backend_content.length - 1; i >= 0; i--) {
                            const item = currentMsg.backend_content[i];
                            if (item.role === 'tool' && item.tool_call_id === toolCallId) {
                                item.content = _finalNote;
                                break;
                            }
                        }
                    }
                    return;
                }

                // 1. UI 显示：处理 \r 确保显示正常（比如手动执行了带进度条的脚本）
                if (targetBlock) {
                    targetBlock.type = action === 'deny' ? 'error' : 'tool_result';
                    targetBlock.name = action === 'deny' ? this.t('tool_deny') : `${toolName} ${this.t('tool_result')}`;
                    this._setResultDisplay(targetBlock, this.smartMergeTerminal('', resultText)); 
                    currentMsg._rv = (currentMsg._rv || 0) + 1;
                }

                // 2. AI 历史：直接存入清理后的版本
                const cleanedForAI = this.truncateForAI(resultText);

                if (currentMsg.backend_content) {
                    for (let i = currentMsg.backend_content.length - 1; i >= 0; i--) {
                        const item = currentMsg.backend_content[i];
                        if (item.role === 'tool' && item.tool_call_id === toolCallId) {
                            item.content = cleanedForAI; // 存入截断版给 AI
                            break;
                        }
                    }
                } 
            }

            // 【修复1】：直接使用缓存的对象修改，不会影响到同 id 的 tool_call 块
            if (targetBlock) {
                targetBlock.type = action === 'deny' ? 'error' : 'tool_result';
                targetBlock.name = action === 'deny' ? this.t('tool_deny') : `${toolName} ${this.t('tool_result')}`;
                this._setResultDisplay(targetBlock, resultText);
                currentMsg._rv = (currentMsg._rv || 0) + 1;
            }

            const blockClass = action === 'deny' ? 'type-error' : 'type-result';
            const iconClass = action === 'deny' ? 'fa-xmark' : 'fa-check';
            const finalTitle = action === 'deny' ? this.t('tool_deny') : `${toolName} ${this.t('tool_result')}`;

            const resultHtml = `\n<div class="sap-process-block ${blockClass}" id="${blockId}">
                <div class="sp-header"><i class="fa-solid ${iconClass}"></i> ${escapeHtml(finalTitle)}</div>
                <pre class="sp-content sp-code">${escapeHtml(resultText)}</pre>
            </div>\n`;
            this.updateUIBlock(currentMsg, blockId, resultHtml);

            if (currentMsg.backend_content) {
                for (let i = currentMsg.backend_content.length - 1; i >= 0; i--) {
                    const item = currentMsg.backend_content[i];
                    if (item.role === 'tool' && item.tool_call_id === toolCallId) {
                        item.content = resultText;
                        break;
                    }
                }
            }
            
            // 成功走到这里，大模型才会被重新唤醒
            await this.generateAIResponse(this.mainAgent, currentMsg.agentName, true);

        } catch (e) {
            console.error("Approval flow failed:", e);
            // S187：失败不再恢复回卡——保持结果块形态，把真实异常写为错误文本（即时反馈）
            if (targetBlock) {
                const _cm = (e && e.message) ? String(e.message).slice(0, 200) : String(e);
                targetBlock.name = `${toolName} 执行失败`;
                this._setResultDisplay(targetBlock, `执行失败: ${_cm}`);
                currentMsg._rv = (currentMsg._rv || 0) + 1;
            }
            // 兼容性判断，防止 showNotification 在其他环境也没有定义而二次崩溃
            if (typeof showNotification === 'function') {
                const _em = (e && e.message) ? String(e.message).slice(0, 140) : String(e);
                showNotification(`Tool execution failed: ${_em}`, 'error');
            }
            this.isSending = false;
            this.isTyping = false;
        }
        } finally {
            // S185：处理结束后释放幂等锁，允许用户基于结果块继续新的决策
            delete this._approvalInFlight[toolCallId];
        }
    },

    // === S188：插话（interject）——生成期消息入队，轮边界注入随下一轮推理处理 ===
    async interjectSend() {
        const text = this.userInput.trim();
        if (!text) return;
        this.userInput = '';
        const sid = this._currentStreamId || null;
        const item = { id: `ij_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`, text, state: 'sending', streamId: sid };
        this.interjectQueue.push(item);
        if (!sid) { item.state = 'held'; this._flushInterjectsSoon(); return; }
        try {
            const res = await fetch(`/v1/streams/${sid}/interject`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ content: text }),
            });
            if (res.ok) { item.state = 'queued'; return; }
        } catch (e) { /* 网络失败 → 兜底路径 */ }
        item.state = 'held';
        if (!this.isSending) this._flushInterjectsSoon();
    },

    _ackInterject(content) {
        const i = (this.interjectQueue || []).findIndex(q => q.state !== 'sent' && q.text === content);
        if (i !== -1) this.interjectQueue.splice(i, 1);
        // 后端已在轮边界注入本轮历史；前端补 user 气泡保持双端历史一致
        this.messages.push({
            id: Date.now() + Math.random(), role: 'user', content,
            fileLinks: [], fileLinks_content: '', imageLinks: [],
            hasDesktopVision: false, agentName: this.memorySettings.userName || 'User',
        });
        this.requestScrollToBottom();
    },

    _ijFinished() {
        // S188 流收尾兜底：用户主动停→留待发区手动处置；审批未决→挂起（批复闭环
        // 必然重启模型，其流结束时按本规则再判）；其余→自动转普通发送，绝不丢
        const q = this.interjectQueue || [];
        if (!q.length) { this._ijUserStopped = false; return; }
        if (this._ijUserStopped) {
            this._ijUserStopped = false;
            q.forEach(it => { it.state = 'held'; });
            return;
        }
        if (this._resumeSawApproval || this._resumeSawAsk) { q.forEach(it => { it.state = 'held'; }); return; }
        this._flushInterjectsSoon();
    },

    _flushInterjectsSoon() { setTimeout(() => { this._flushInterjects(); }, 400); },

    async _flushInterjects() {
        if (!this.interjectQueue || !this.interjectQueue.length) return;
        if (this.isSending || this.isTyping) return;
        const items = this.interjectQueue.slice();
        for (const it of items) {
            if (this.isSending || this.isTyping) return;
            const idx = this.interjectQueue.indexOf(it);
            if (idx === -1) continue;
            this.interjectQueue.splice(idx, 1);
            this.userInput = it.text;
            try {
                await this.sendMessage();
            } catch (e) {
                if (!this.userInput) this.userInput = it.text;
                this.interjectQueue.push({ ...it, state: 'held' });
                break;
            }
        }
    },

    updateUIBlock(msg, blockId, newHtml) {
        const content = msg.content;
        const startTag = `id="${blockId}"`;
        const startSearchIndex = content.indexOf(startTag);
        
        if (startSearchIndex === -1) {
            msg.content += newHtml;
            return;
        }

        const startIndex = content.lastIndexOf('<div', startSearchIndex);
        let endIndex = -1;
        const searchPart = content.substring(startIndex);
        
        if (searchPart.includes('</div></div>')) {
            endIndex = startIndex + searchPart.indexOf('</div></div>') + 12;
        } else if (searchPart.includes('</div>\n')) {
            endIndex = startIndex + searchPart.indexOf('</div>\n') + 7;
        }

        if (startIndex !== -1 && endIndex !== -1) {
            msg.content = content.substring(0, startIndex) + newHtml + content.substring(endIndex);
        } else {
            msg.content += newHtml;
        }
    },

    getVisibleBlocks(msg) {
        if (!msg.displayBlocks || !msg.displayBlocks.length) return [];
        const blocks = msg.displayBlocks;
        // 如果块总数未超过限制，全量渲染
        if (blocks.length <= MAX_RENDERED_BLOCKS) return blocks;
        // 否则只渲染最后 MAX_RENDERED_BLOCKS 个（因为新内容在尾部）
        return blocks.slice(-MAX_RENDERED_BLOCKS);
    },

    // 辅助：调用后端手动执行接口
    async executeToolBackend(name, params, type, streamId) {
        try {
            const res = await fetch('/execute_tool_manually', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ 
                    tool_name: name, 
                    tool_params: params,
                    approval_type: type,
                    stream_id: streamId || null
                })
            });
            const json = await res.json();
            return json.result || JSON.stringify(json);
        } catch (e) {
            return `System Error: ${e.message}`;
        }
    },

    // 1. 带截断的工具结果显示
    truncateDisplayContent(content) {
        if (typeof content !== 'string') return content;
        if (content.length > MAX_DISPLAY_LENGTH) {
            return content.slice(0, MAX_DISPLAY_LENGTH) + '\n... (The result is too long and has been truncated.)';
        }
        return content;
    },

    // 2. 节流版滚动（requestAnimationFrame）
    requestScrollToBottom() {
        if (!this.scrollPending) {
            this.scrollPending = true;
            requestAnimationFrame(() => {
                // ✅ 改为调用原始的 scrollToBottom
                if (typeof this.scrollToBottom === 'function') {
                    this.scrollToBottom();
                }
                this.scrollPending = false;
            });
        }
    },

    // S314：实时徽章 DOM 直连——绕开 Vue 模板/Teleport/v-memo/祖先样式语境，
    // 直接挂 body；1.5s 无更新看门狗自动清理（任何终止路径自愈）。绝不抛出。
    _liveBadgePaint(stats) {
        try {
            let el = document.getElementById('sap-live-badge');
            if (!el) {
                el = document.createElement('div');
                el.id = 'sap-live-badge';
                el.className = 'stream-live-badge';
                el.innerHTML = '<i class="fa-solid fa-gauge-high"></i><span></span>';
                document.body.appendChild(el);
            }
            const _sp = el.querySelector('span');
            _sp.textContent = this.t('tokens_per_sec') + ' ' + stats.tok
                + '  ·  ' + this.t('completion_tokens') + ' ~' + stats.out
                + '  ·  ' + this.t('total_tokens') + ' ~' + stats.total;
            this._liveBadgeTs = Date.now();
            if (!this._liveBadgeTimer) {
                this._liveBadgeTimer = setInterval(() => {
                    if (Date.now() - (this._liveBadgeTs || 0) > 1500) {
                        const b = document.getElementById('sap-live-badge');
                        if (b) b.remove();
                        clearInterval(this._liveBadgeTimer);
                        this._liveBadgeTimer = null;
                    }
                }, 1000);
            }
        } catch (e) { /* 徽章绝不扰主流 */ }
    },
    // S309b：stream_usage 控制帧落账——厂商真实计费（多轮累计）覆盖估算，精算 tok/s
    _applyStreamUsage(msg, u) {
        if (!msg || !u) return;
        msg.completion_tokens = u.completion_tokens || 0;
        msg.context_tokens = u.prompt_tokens || 0;
        msg.total_tokens = u.total_tokens || (msg.completion_tokens + msg.context_tokens);
        msg.usage_est = false;
        msg._usageFinal = true;
        const secs = (Date.now() - (this._streamT0 || Date.now())) / 1000;
        if (msg.completion_tokens > 0 && secs > 0.5) {
            msg.tok_per_sec = Math.max(1, Math.round(msg.completion_tokens / secs));
        }
    },
    // S309b：流收尾时若厂商未回 usage（旧后端/网关不支持），按 字符/1.8 估算并标 usage_est
    _finalizeUsage(msg) {
        if (!msg || msg._usageFinal) return;
        const chars = this._streamRecvChars || 0;
        if (chars > 0 && !msg.total_tokens) {
            msg.usage_est = true;
            msg.completion_tokens = Math.round(chars / 1.8);
            msg.total_tokens = msg.completion_tokens;
        }
    },

    // 3. 流式文本批量更新（防抖 80ms；S92: 含 reasoning 缓冲）
    // S109 追赶模式：接收-落账字符差 >4000 判定积压，放宽提交/工具 bump 节奏，
    // 用更少更大渲染换泵吞吐；追平自动回到 80ms 手感档
    streamBacklog() {
        return (this._streamRecvChars || 0) - (this._streamFlushChars || 0) > 4000;
    },
    streamFlushWait() {
        if (this.streamBacklog()) return 240;
        return Date.now() - (this._streamLastFlushTs || 0) > 150 ? 0 : 80;
    },
    flushStreamTextBuffer() {
        // S106: flush 时间戳（防抖饥饿守卫用）+ 行修订号 bump（v-memo 依赖）
        this._streamLastFlushTs = Date.now();
        this._streamFlushChars = this._streamRecvChars || 0;
        const __m = this._streamTargetMsg;
        if (this._streamTargetMsg && this._streamReasoningBuffer) {
            const rBlock = this.getBlockForMsg(this._streamTargetMsg, 'reasoning');
            if (rBlock) rBlock.content += this._streamReasoningBuffer;
            this._streamReasoningBuffer = '';
            this.requestScrollToBottom();
        }
        if (this._streamTargetMsg && this._streamTextBuffer) {
            const block = this.getBlockForMsg(this._streamTargetMsg, 'text');
            if (block) {
                this._markReasoningDone(this._streamTargetMsg); // S93(F2): 正文开始=思考结束
                block.content += this._streamTextBuffer;
                // 同时更新 pure_content 和 content 纯文本（不再拼 HTML）
                this._streamTargetMsg.pure_content += this._streamTextBuffer;
                this._streamTargetMsg.content += this._streamTextBuffer;
            }
            this._streamTextBuffer = '';
            // 触发滚动（节流版）
            this.requestScrollToBottom();
        }
        if (__m && !__m._usageFinal) { // S309b/S310/S316：流式期节流估算落账+实时徽章（usage 帧到达后停用）
            const _nowMs = Date.now();
            const _secs = (_nowMs - (this._streamT0 || _nowMs)) / 1000;
            if (_secs > 0.5) {
                const _est = Math.round((this._streamRecvChars || 0) / 1.8);
                let _tps = Math.max(1, Math.round(_est / _secs)); // 兜底=全程均值（窗口尚无样本时）
                const _dt = this._flowTs ? (_nowMs - this._flowTs) / 1000 : 0;
                if (_dt >= 0.4) { // S316：滚动窗口瞬时速率 Δchars/Δt + EMA(0.45)，不再从 0 慢爬
                    const _inst = Math.max(0, (((this._streamRecvChars || 0) - (this._flowChars || 0)) / 1.8) / _dt);
                    this._tokEma = this._tokEma ? this._tokEma * 0.55 + _inst * 0.45 : _inst;
                    this._flowTs = _nowMs;
                    this._flowChars = this._streamRecvChars || 0;
                }
                if (this._tokEma) _tps = Math.max(0, Math.round(this._tokEma));
                __m.tok_per_sec = _tps;
                if (_est > 0) {
                    __m.usage_est = true;
                    __m.completion_tokens = _est;
                    __m.total_tokens = _est;
                }
                this.streamLiveStats = { tok: _tps, out: _est, total: _est };
                this._liveBadgePaint(this.streamLiveStats); // S314：DOM 直连（模板链路环境不可靠）
            }
        }
        if (__m) __m._rv = (__m._rv || 0) + 1;
    },

    // ===== S207：瞬断整轮重发（后端只重发 create+读流，工具执行永不重放） =====
    _showStreamRetryNote(info) {
        const n = (info && info.attempt) || 1;
        const m = (info && info.attempts) || 1;
        let text = this.t('streamRetrying') || 'Model connection lost, retrying…';
        text = text.replace('{n}', n).replace('{m}', m);
        showNotification(text, 'warning');
    },

    _armStreamReset(info) {
        // 仅挂起：保留半截气泡原样展示，直到重试的新输出真正到达才替换
        this._streamResetPending = { keep: Math.max(0, Number((info && info.keep_text_chars)) || 0) };
    },

    _consumeStreamReset(currentMsg, toolCallStack) {
        const r = this._streamResetPending;
        if (!r) return false;
        this._streamResetPending = null;
        if (this._streamUpdateTimer) { clearTimeout(this._streamUpdateTimer); this._streamUpdateTimer = null; }
        this._streamTextBuffer = '';
        this._streamReasoningBuffer = '';
        this._streamRecvChars = 0;
        const m = this._streamTargetMsg || currentMsg;
        if (!m) return true;
        const keep = r.keep;
        if (Array.isArray(m.displayBlocks)) {
            // 块可能被 S187 冻结——越限/在途块整块剔除，跨界文本块换新对象
            let used = 0;
            const pendingIds = new Set(Array.isArray(toolCallStack)
                ? toolCallStack.filter(c => !c.resolved).map(c => c.id) : []);
            const out = [];
            for (const b of m.displayBlocks) {
                const raw = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(b) : b;
                if (raw.type === 'reasoning') continue; // 思考面板属易失展示，失败轮整段丢弃
                if (raw.type === 'text') {
                    const c = String(raw.content || '');
                    if (used >= keep) continue;
                    if (used + c.length <= keep) { used += c.length; out.push(b); continue; }
                    out.push(Object.assign({}, raw, { content: c.slice(0, keep - used) }));
                    used = keep;
                    continue;
                }
                if (raw.type === 'tool_call' && pendingIds.has(raw.id)) continue; // 失败轮在途块
                out.push(b);
            }
            m.displayBlocks = out;
        }
        m.content = String(m.content || '').slice(0, keep);
        m.pure_content = String(m.pure_content || '').slice(0, keep);
        if (Array.isArray(toolCallStack)) {
            for (let i = toolCallStack.length - 1; i >= 0; i--) { if (!toolCallStack[i].resolved) toolCallStack.splice(i, 1); }
        }
        if (this.toolArgsAccumulator) this.toolArgsAccumulator = {};
        m._rv = (m._rv || 0) + 1;
        return true;
    },

    async translateMessage(index) {
      const msg = this.messages[index];
      const originalContent = msg.content;
      if (msg.isTranslating) return;
      if (originalContent.trim() === '') return;

      // 1. 先占坑
      this.messages[index] = {
        ...msg,
        content: this.t('translating') + '...',
        isTranslating: true,
        originalContent
      };

      try {
        const abortController = new AbortController();
        this.abortController = abortController;

        // 2. 组装 TTS 提示
        let newttsList = [];
        if (this.ttsSettings?.newtts) {
          for (const key in this.ttsSettings.newtts) {
            if (this.ttsSettings.newtts[key].enabled) newttsList.push(key);
          }
        }
        const ttsMsg = (newttsList.length === 0 || !this.ttsSettings?.enabled)
          ? '如果被翻译的文字与目标语言一致，则返回原文即可'
          : `你还需要在翻译的同时，添加对应的音色标签。如果被翻译的文字与目标语言一致，则只需要添加对应的音色标签。注意！不要使用<!--  -->这会导致部分文字不可见！你可以使用以下音色：\n${newttsList.join(', ')}\n，当你生成回答时，将不同的旁白或角色的文字用<音色名></音色名>括起来，以表示这些话是使用这个音色，以控制不同TTS转换成对应音色。对于没有对应音色的部分，可以不括。即使音色名称不为英文，还是可以照样使用<音色名>使用该音色的文本</音色名>来启用对应音色。注意！如果是你扮演的角色的名字在音色列表里，你必须用这个音色标签将你扮演的角色说话的部分括起来！只要是非人物说话的部分，都视为旁白！角色音色应该标记在人物说话的前后！例如：<Narrator>现在是下午三点，她说道：</Narrator><角色名>”天气真好哇！“</角色名><Narrator>说完她伸了个懒腰。</Narrator>\n\n`;

        // 3. 发起流式请求
        const response = await fetch('/simple_chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            model: this.mainAgent,
            messages: [
              {
                role: 'system',
                content: `你是一位专业翻译，请将用户提供的任何内容严格翻译为${this.target_lang}，保持原有格式（如Markdown、换行等），不要添加任何额外内容。只需返回翻译结果。${ttsMsg}`
              },
              {
                role: 'user',
                content: `请翻译以下内容到${this.target_lang}：\n\n${originalContent}`
              }
            ],
            stream: true,
            temperature: 0.1
          }),
          signal: abortController.signal
        });

        if (!response.ok) throw new Error('Translation failed');

        let translated = '';  // 累积结果
            await iterateNdjsonLines(response, (chunk) => {
          const delta = chunk.choices?.[0]?.delta?.content ?? '';
          if (delta) {
            translated += delta;
            this.messages[index].content = translated; // 实时渲染
          }
            });

        // 5. 翻译完成
        this.messages[index].isTranslating = false;
        this.messages[index].translated = true;

      } catch (error) {
        if (error.name === 'AbortError') {
          // 用户中断，恢复原文
          this.messages[index] = { ...msg, content: originalContent, isTranslating: false };
        } else {
          this.messages[index].content = `Translation error: ${error.message}`;
          this.messages[index].isTranslating = false;
        }
      } finally {
        this.abortController = null;
      }
    }
});
