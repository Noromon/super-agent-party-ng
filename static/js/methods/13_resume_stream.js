// 批 3 F2：自 vue_methods.js 搬移的 methods/13_resume_stream.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    /**
     * 断点续传：SSE 连接中断后，调用 /v1/chat/resume 恢复接收剩余内容
     * 复用现有的 SSE 解析逻辑，继续追加到 currentMsg
     */
    async _resumeStream(streamId, fromIndex, currentMsg, getBlock, isCodeBlock, tts_buffer, toolCallStack) {
        const maxRetries = 3;
        const baseDelay = 1000;
        let currentFromIndex = fromIndex; // 跨重试追踪，避免重复处理 chunk

        for (let attempt = 0; attempt < maxRetries; attempt++) {
            let chunkIndex = currentFromIndex; // 声明在 try 外部，使 catch 可访问
            try {
                const delay = baseDelay * Math.pow(2, attempt);
                if (attempt > 0) {
                    console.log(`[StreamResume] 第 ${attempt + 1} 次重试，从 index=${currentFromIndex} 恢复，等待 ${delay}ms...`);
                    await new Promise(r => setTimeout(r, delay));
                }

                // 添加超时保护，防止 resume 连接永久挂起
                const resumeController = new AbortController();
                const timeoutId = setTimeout(() => resumeController.abort(), 60000);

                const resumeResponse = await fetch('/v1/chat/resume', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ stream_id: streamId, from_index: currentFromIndex }),
                    signal: resumeController.signal
                });

                clearTimeout(timeoutId);

                if (!resumeResponse.ok) {
                    console.warn(`[StreamResume] 恢复请求失败: ${resumeResponse.status}`);
                    continue;
                }

                let newStreamId = streamId;

                await iterateSse(resumeResponse, (parsed) => {
                try { // RA-08：毒帧吞错继续（旧 catch 罩全帧处理），避免中止整轮进重试环重放半帧副作用
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

                chunkIndex++;

                if (delta.reasoning_content) {
                    // S92: reasoning 与文本同款 80ms 缓冲（flush 由共享 flushStreamTextBuffer 处理）
                    this._streamTargetMsg = currentMsg;
                    this._streamReasoningBuffer = (this._streamReasoningBuffer || '') + delta.reasoning_content;
                    if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                    this._streamUpdateTimer = setTimeout(() => {
                        this.flushStreamTextBuffer();
                    }, Date.now() - (this._streamLastFlushTs || 0) > 150 ? 0 : 80);
                }

                if (delta.content) {
                    this._streamTargetMsg = currentMsg;
                    this._streamTextBuffer = (this._streamTextBuffer || '') + delta.content;

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

                    if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                    this._streamUpdateTimer = setTimeout(() => {
                        this.flushStreamTextBuffer();
                    }, Date.now() - (this._streamLastFlushTs || 0) > 150 ? 0 : 80);
                }

                if (delta.tool_progress) {
                    this._ingestToolProgress(delta.tool_progress, getBlock, toolCallStack, currentMsg);
                    return;
                }

                if (delta.tool_content) {
                    this._ingestToolFrame(delta.tool_content, delta, currentMsg, getBlock, toolCallStack);
                }

                if (delta.async_tool_id) {
                    if (!this.asyncToolsID) this.asyncToolsID = [];
                    if (!this.asyncToolsID.includes(delta.async_tool_id)) {
                        this.asyncToolsID.push(delta.async_tool_id);
                    }
                }

                this.sendMessagesToExtension();
                } catch (frameErr) {
                    console.warn('[StreamResume] 帧处理异常，已跳过该帧:', frameErr.message);
                }
                });

                // 恢复成功，flush 剩余文本
                if (this._streamUpdateTimer) clearTimeout(this._streamUpdateTimer);
                this.flushStreamTextBuffer();
                currentMsg._rv = (currentMsg._rv || 0) + 1; // S107: 流尾终态兜底 bump
                this._flushToolStream(); // S93(F4)

                if (tts_buffer.trim() && this.ttsSettings.enabled) {
                    currentMsg.chunks_voice.push(this.cur_voice);
                    currentMsg.ttsChunks.push(tts_buffer);
                }

                // 正文写回：resume 路径此前漏调，导致断线重连后 backend_content 无正文（历史遗忘）
                this._syncAssistantBody(currentMsg);

                console.log(`[StreamResume] 断点续传成功，已恢复 ${chunkIndex - fromIndex} 个 chunk`);
                return { newChunkIndex: chunkIndex, newStreamId };
            } catch (retryError) {
                // 保存已处理的 chunk 进度，下次重试从断点继续，避免重复处理
                currentFromIndex = chunkIndex;
                console.warn(`[StreamResume] 第 ${attempt + 1} 次恢复失败 (已处理到 index=${currentFromIndex}):`, retryError.message);
            }
        }


        // 所有重试均失败
        console.error('[StreamResume] 所有重试均失败');
        return null;
    },

    // C-2: tool_progress 帧摄取单一来源 —— 主循环与 resume 重放共用。
    _ingestToolProgress(progress, getBlock, toolCallStack, msg) {
        this._markReasoningDone(this._streamTargetMsg); // S93(F2): 工具开跑=思考结束
        let toolCallId = progress.tool_call_id || progress.id;
        if (!toolCallId) {
            const existingCall = toolCallStack.find(c => c.name === progress.name && !c.resolved);
            if (existingCall) { toolCallId = existingCall.id; }
            else {
                toolCallId = `call_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                toolCallStack.push({ id: toolCallId, name: progress.name, resolved: false });
            }
        } else if (!toolCallStack.find(c => c.id === toolCallId)) {
            toolCallStack.push({ id: toolCallId, name: progress.name, resolved: false });
        }
        let accArgs = this.toolArgsAccumulator[toolCallId] || "";
        if (progress.arguments !== undefined) {
            if (progress.incremental) {
                accArgs += progress.arguments;                 // S85-A 新协议：服务端只发本帧增量
            } else if (progress.arguments.startsWith(accArgs) && accArgs !== "") {
                accArgs = progress.arguments;                  // 旧全量协议：前缀延长，整串替换
            } else {
                // S85-B 防卡死：全量但前缀断裂 = 跨轮复用同一 id 的新调用 → 整体替换。
                // 旧实现在此 append 全量串，复读风暴下 O(n²) 字符串膨胀 → 渲染进程
                // GC 死亡螺旋 → Electron 整窗无响应（含自定义标题栏关闭按钮）。
                accArgs = progress.arguments;
            }
            if (accArgs.length > 65536) accArgs = accArgs.slice(0, 65536);  // S85-B 封顶
            this.toolArgsAccumulator[toolCallId] = accArgs;
        }
        const b = getBlock('tool_call', toolCallId, progress.name);
        // S106: args 显示写节流(≥120ms)+行 rv bump——66KB 级文件参数的 token 流
        // 曾每帧全文重写+全屏 flush，是排空积压的头号贡献者
        const nowMs = Date.now();
        if (!b._lastArgsW || nowMs - b._lastArgsW > 120) {
            b._lastArgsW = nowMs;
            this._setToolArgs(b, this.truncateDisplayContent(accArgs));
            if (msg) msg._rv = (msg._rv || 0) + 1;
        }
        this.requestScrollToBottom();
    },

    // C-2+C-6: tool_content 帧摄取单一来源 —— displayBlocks + backend_content（LLM 可见链）
    // + 审批帧/异步工具 id 摘除。修复前 resume 重放路径整段跳过 backend_content（C-2）
    // 且丢 approval_required/async 帧（C-6=审批按钮不重现、工具链永久卡死）。
    _ingestToolFrame(tool, delta, currentMsg, getBlock, toolCallStack) {
        // S107: bump 节流(≥80ms)——tool 帧 token 流曾每帧一次全屏 flush（profile
        // 实锤 Vue 管线 65.5%）；终态兜底=流尾 bump+审批/result 直写 bump
        const nowMsRv = Date.now();
        if (!this._lastRvBump || nowMsRv - this._lastRvBump > 80) {
            this._lastRvBump = nowMsRv;
            currentMsg._rv = (currentMsg._rv || 0) + 1;
        }
        if (!Array.isArray(currentMsg.backend_content)) currentMsg.backend_content = [];
        this._markReasoningDone(currentMsg); // S93(F2): 工具帧=思考结束
        // S93(F4): 切换到新工具调用时先落挂起的流式块（同 id 帧保持合并，80ms 后统一 flush）
        if (this._toolStreamPending && this._toolStreamPending.id !== (delta.tool_call_id || delta.async_tool_id)) this._flushToolStream();
        const toolName = tool.title || 'unknown';
        let toolCallId = delta.tool_call_id || delta.async_tool_id;
        if (tool.type === 'call') {
            if (!toolCallId) toolCallId = `call_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
            toolCallStack.push({ id: toolCallId, name: toolName, resolved: false });
        } else {
            if (!toolCallId) {
                const pendingCall = toolCallStack.find(c => c.name === toolName && !c.resolved);
                if (pendingCall) { toolCallId = pendingCall.id; pendingCall.resolved = true; }
                else { toolCallId = `call_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`; }
            }
            const callItem = toolCallStack.find(c => c.id === toolCallId);
            if (callItem) callItem.resolved = true;
        }
        if (delta.async_tool_id && (tool.type === 'tool_result' || tool.type === 'error')) {
            if (this.asyncToolsID) {
                const index = this.asyncToolsID.indexOf(delta.async_tool_id);
                if (index > -1) {
                    this.asyncToolsID.splice(index, 1);
                    const stackIndex = toolCallStack.findIndex(c => c.id === delta.async_tool_id);
                    if (stackIndex > -1) toolCallStack.splice(stackIndex, 1);
                }
            }
        }
        let isApproval = false;
        let approvalData = null;
        // 审批嗅探（C-20/T-9 同源收紧）：仅结构哨兵帧触发
        if (tool.type === 'tool_result' && typeof tool.content === 'string' && tool.content.startsWith('{"__sap_approval_v1__":1,')) {
            try {
                const temp = JSON.parse(tool.content);
                if (temp.type === 'approval_required') { isApproval = true; approvalData = temp; }
            } catch (e) { }
        }
        if (isApproval && approvalData) {
            const b = getBlock('approval', toolCallId, toolName);
            b.data = approvalData;
            // 围栏快照：审批必须记住产生它的流，停止/换流后不得借用新流身份执行
            approvalData._stream_id = this._currentStreamId || null;
            this.approvalMap[toolCallId] = approvalData;
            currentMsg.backend_content.push({ role: 'tool', tool_call_id: toolCallId, name: toolName, content: "{}" });
            currentMsg.backend_content.push({ role: 'assistant', content: '' });
            this.requestScrollToBottom();
        } else if (tool.type === 'tool_result_stream' && tool.title === "tool_result_stream") {
            // S93(F4): 流式结果 80ms 合并 + 50K 显示封顶（写满不再改动 block）。
            // 旧版每帧全文复制+全量重渲染，浏览器工具大结果 → O(总长×帧数) GC 死亡螺旋整窗卡死。
            const pend = this._toolStreamPending;
            this._toolStreamPending = {
                id: toolCallId, name: toolName, msg: currentMsg,
                chunk: (pend && pend.id === toolCallId ? pend.chunk : '') + (typeof tool.content === 'string' ? tool.content : String(tool.content ?? ''))
            };
            if (!this._toolStreamTimer) {
                this._toolStreamTimer = setTimeout(() => this._flushToolStream(), 80);
            }
            const BE_CAP = 131072; // S93(F4): LLM 链累加上限（后端另有二次截断；防 MB 级串每帧复制与 stringify 爆炸）
            for (let i = currentMsg.backend_content.length - 1; i >= 0; i--) {
                if (currentMsg.backend_content[i].role === 'tool' && currentMsg.backend_content[i].tool_call_id === toolCallId) {
                    const it = currentMsg.backend_content[i];
                    if ((it.content || '').length < BE_CAP) it.content = ((it.content || '') + (tool.content || '')).slice(0, BE_CAP);
                    break;
                }
            }
        } else {
            let bType = 'tool_result';
            if (tool.type === 'error') bType = 'error';
            else if (tool.type === 'call') bType = 'tool_call';
            const targetBlock = getBlock(bType, toolCallId, toolName);
            if (tool.type === 'call') {
                this._setToolArgs(targetBlock, this.truncateDisplayContent(tool.content));
            } else {
                this._setResultDisplay(targetBlock, this.truncateDisplayContent(tool.content));
            }
            let rawContent = tool.content || '';
            if (tool.type === 'call') {
                let last = currentMsg.backend_content[currentMsg.backend_content.length - 1];
                if (last && last.role === 'assistant') {
                    if (!last.tool_calls) last.tool_calls = [];
                    if (!last.tool_calls.some(tc => tc.id === toolCallId)) {
                        last.tool_calls.push({ id: toolCallId, type: 'function', function: { name: tool.title, arguments: tool.content || "{}" } });
                    }
                } else {
                    currentMsg.backend_content.push({ role: 'assistant', content: null, tool_calls: [{ id: toolCallId, type: 'function', function: { name: tool.title, arguments: tool.content || "{}" } }] });
                }
            } else if (tool.type === 'tool_result' || tool.type === 'tool_result_stream' || tool.type === 'error') {
                const hide = this.toolsSettings?.hideToolResults?.enabled && tool.type === 'tool_result';
                rawContent = hide ? '<hide to save token>' : rawContent;
                if (typeof rawContent === 'string' && rawContent.length > 131072) rawContent = rawContent.slice(0, 131072) + '\n... [truncated]'; // S93(F4)
                let updated = false;
                for (let i = currentMsg.backend_content.length - 1; i >= 0; i--) {
                    if (currentMsg.backend_content[i].role === 'tool' && currentMsg.backend_content[i].tool_call_id === toolCallId) {
                        currentMsg.backend_content[i].content = rawContent;
                        updated = true;
                        break;
                    }
                }
                if (!updated) {
                    currentMsg.backend_content.push({ role: 'tool', tool_call_id: toolCallId, name: toolName, content: rawContent });
                }
                if (currentMsg.backend_content[currentMsg.backend_content.length - 1].role !== 'assistant') {
                    currentMsg.backend_content.push({ role: 'assistant', content: '' });
                }
            }
        }
        this.requestScrollToBottom();
    },

    // S93(F4): 流式工具结果 80ms 合并落账；显示块写满 50K 后不再改动（避免每帧全量重渲染）
    _flushToolStream() {
        if (this._toolStreamTimer) { clearTimeout(this._toolStreamTimer); this._toolStreamTimer = null; }
        const p = this._toolStreamPending;
        this._toolStreamPending = null;
        if (!p) return;
        const block = this.getBlockForMsg(p.msg, 'tool_result', p.id, p.name);
        if ((block.content || '').length >= 50000) return;
        this._setResultDisplay(block, this.truncateDisplayContent(this.smartMergeTerminal(block.content || '', p.chunk)));
        if (p.msg) p.msg._rv = (p.msg._rv || 0) + 1; // S106: v-memo 行修订号
        this.requestScrollToBottom();
    },

    // 将 pure_content 正文写回 backend_content 尾部 assistant 空项与 content 字段。
    // SSE 文本流只写 pure_content，导致 backend_content（LLM 可见链）正文缺失，
    // prepareMessages 过滤空项后整条消息从请求中消失（历史遗忘根因）。
    _syncAssistantBody(msg) {
      if (!msg || msg.role !== 'assistant') return;
      const body = msg.pure_content ?? '';
      if (!String(body).trim()) return;
      if (!Array.isArray(msg.backend_content)) return;
      if (msg.backend_content.length === 0) {
        msg.backend_content.push({ role: 'assistant', content: body });
      } else {
        let target = null;
        for (let i = msg.backend_content.length - 1; i >= 0; i--) {
          const it = msg.backend_content[i];
          if (it.role === 'assistant' && !(it.tool_calls && it.tool_calls.length)) { target = it; break; }
          if (it.role !== 'assistant') break;
        }
        if (target) {
          if (!String(target.content ?? '').trim()) target.content = body;
        } else {
          msg.backend_content.push({ role: 'assistant', content: body });
        }
      }
      if (!String(msg.content ?? '').trim()) msg.content = body;
    },

    stopGenerate() {
      // 安全围栏：先取消后端生产者流（阻止取消后继续工具调度/后续轮次），再断开本地读取
      if (this._currentStreamId) {
        try { fetch(`/v1/streams/cancel/${this._currentStreamId}`, { method: 'POST' }).catch(() => {}); } catch (e) {}
        this._currentStreamId = null;
      }
      if (this.abortController) {

        this.abortController.abort();
      }
      // 中止配对清理：给最后一条 assistant 中未闭合的 tool_calls 补中断存根（防服务端 Sanitizer 丢弃整对）
      for (let mi = this.messages.length - 1; mi >= 0; mi--) {
        const m = this.messages[mi];
        if (m.role !== 'assistant' || !Array.isArray(m.backend_content) || m.backend_content.length === 0) continue;
        const bc = m.backend_content;
        const pending = [];
        bc.forEach((b, bi) => {
          if (b.role === 'assistant' && Array.isArray(b.tool_calls)) {
            b.tool_calls.forEach(tc => {
              if (!bc.some((t, ti) => ti > bi && t.role === 'tool' && t.tool_call_id === tc.id)) {
                pending.push({ id: tc.id, name: (tc.function && tc.function.name) || 'tool' });
              }
            });
          }
        });
        pending.forEach(p => bc.push({ role: 'tool', tool_call_id: p.id, name: p.name, content: '[interrupted by user]' }));
        this._syncAssistantBody(m);
        break;
      }
      this.isThinkOpen = false;
      this.isSending = false;
      this.isTyping = false;
      this.abortController = null;
      if(this.settings.enableOmniTTS){
        if (this.activeSources && this.activeSources.length > 0) {
          this.activeSources.forEach(src => {
            try {
              src.stop(); // 立即停止播放
            } catch (e) {
              // 忽略已经停止或未开始的错误
            }
          });
          // 清空数组
          this.activeSources = [];
        }
        this.audioStartTime = 0; 
        this.stopAllAudioPlayback();
      }
    }
});
