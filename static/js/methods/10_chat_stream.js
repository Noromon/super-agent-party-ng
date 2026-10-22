// 批 3 F2：自 vue_methods.js 搬移的 methods/10_chat_stream.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    async sendMessage(role = 'user') {
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
                isPlaying: false, total_tokens: 0, first_token_latency: 0, elapsedTime: 0,
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
                    if (name && !existing.name) existing.name = name;
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
            if (last && !Object.isFrozen(last)) {
                Object.freeze(last);
                if (typeof last.content === 'string') Object.freeze(last.content);
                if (typeof last.args === 'string') Object.freeze(last.args);
                if (last.data) Object.freeze(last.data);
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
                    _chunkIndex++;

                    if (currentMsg.content === '' && !isResume) {

                        this.stopTimer();
                        currentMsg.first_token_latency = this.elapsedTime;
                    }

                    // A. 处理思考 (Reasoning) —— 仅更新 displayBlocks，不拼 HTML
                    if (delta.reasoning_content) {
                        const block = getBlock('reasoning');
                        block.content += delta.reasoning_content;
                        // 不再操作 currentMsg.content
                        this.requestScrollToBottom();
                    }

                    // B. 处理文本 (Content) —— 流式防抖更新
                    if (delta.content) {
                        // 缓冲文本，不再直接操作 DOM
                        this._streamTextBuffer += delta.content;

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
                        }, 80);
                    }

                    // C. 工具 Loading 状态 (tool_progress) —— 只更新 displayBlocks
                    if (delta.tool_progress) {
                        this._ingestToolProgress(delta.tool_progress, getBlock, toolCallStack);
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

                    this.sendMessagesToExtension();
            });

            // 循环结束后，强制刷新缓冲区中剩余的文字
            if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
            this.flushStreamTextBuffer();

            if (tts_buffer.trim() && this.ttsSettings.enabled) {
                currentMsg.chunks_voice.push(this.cur_voice);
                currentMsg.ttsChunks.push(tts_buffer);
            }

            currentMsg.generationFinished = true;

            // S81(A8)：流式收尾不再手动 MathJax typeset——KaTeX/texmath 已在渲染管线内排版

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
                if (_enableStreamResume && _streamId && _chunkIndex > 0 && currentMsg && !currentMsg.generationFinished) {
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
                    if (!Object.isFrozen(block)) {
                        Object.freeze(block);
                        if (typeof block.content === 'string') Object.freeze(block.content);
                        if (typeof block.args === 'string') Object.freeze(block.args);
                        if (block.data) Object.freeze(block.data);
                    }
                });
            }
            if (currentMsg && Array.isArray(currentMsg.backend_content)) {
                currentMsg.backend_content.forEach(item => {
                    if (!Object.isFrozen(item)) Object.freeze(item);
                });
            }

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
            this._streamTargetMsg = null;
            this._streamTextBuffer = '';
            if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
        }
    },

    // === Human-in-the-loop 处理函数 ===
    async processToolApproval(toolCallId, action) {
        const currentMsg = this.messages[this.messages.length - 1];
        if (!currentMsg) return;
        
        const data = this.approvalMap[toolCallId];
        const toolName = data?.tool_name || 'Tool';
        const blockId = `approval-${toolCallId}`;

        // 【修复1】：用变量直接缓存找到的目标块的引用，不再二次查找
        let targetBlock = null;
        if (currentMsg.displayBlocks) {
            // 严格限定不仅 id 要匹配，而且必须是我们初始的 approval 块
            targetBlock = currentMsg.displayBlocks.find(b => b.id === toolCallId && b.type === 'approval');
            if (targetBlock) {
                targetBlock.type = 'tool_result';
                targetBlock.name = action === 'deny' ? this.t('denying') : `${this.t('executing')} ${toolName}...`;
                targetBlock.content = ''; 
            }
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

                // 1. UI 显示：处理 \r 确保显示正常（比如手动执行了带进度条的脚本）
                if (targetBlock) {
                    targetBlock.type = action === 'deny' ? 'error' : 'tool_result';
                    targetBlock.name = action === 'deny' ? this.t('tool_deny') : `${toolName} ${this.t('tool_result')}`;
                    targetBlock.content = this.smartMergeTerminal('', resultText); 
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
                targetBlock.content = resultText;
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
            // 兼容性判断，防止 showNotification 在其他环境也没有定义而二次崩溃
            if (typeof showNotification === 'function') {
                showNotification("Tool execution failed", 'error');
            }
            this.isSending = false;
            this.isTyping = false;
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

    // 3. 流式文本批量更新（防抖 80ms）
    flushStreamTextBuffer() {
        if (this._streamTargetMsg && this._streamTextBuffer) {
            const block = this.getBlockForMsg(this._streamTargetMsg, 'text');
            if (block) {
                block.content += this._streamTextBuffer;
                // 同时更新 pure_content 和 content 纯文本（不再拼 HTML）
                this._streamTargetMsg.pure_content += this._streamTextBuffer;
                this._streamTargetMsg.content += this._streamTextBuffer;
            }
            this._streamTextBuffer = '';
            // 触发滚动（节流版）
            this.requestScrollToBottom();
        }
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
