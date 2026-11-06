// 批 3 F2：自 vue_methods.js 搬移的 methods/11_tool_blocks.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    isLastActiveBlock(msg, blockIndex) {
        if (!msg.displayBlocks || msg.displayBlocks.length === 0) return false;
        const lastBlock = msg.displayBlocks[msg.displayBlocks.length - 1];
        // 只要该块是最后一个，并且消息还没生成完，就认为是“正在更新的块”
        if (!msg.generationFinished && blockIndex === msg.displayBlocks.length - 1) {
            return true;
        }
        // 如果已经生成完，最后一块也当作静态块，不再实时展开
        return false;
    },

    // 判断是否为工具类块
    isToolBlock(block) {
        return block.type === 'tool_call' || block.type === 'tool_result' || block.type === 'reasoning';
    },

    // 打开工具块详情（点击折叠块时）
    openToolBlockDetail(message, block) {
        if (!block || !this.isToolBlock(block)) return;
        
        // 直接保存块对象和消息引用
        this.activeToolBlock = {
            messageIndex: this.messages.indexOf(message),
            blockIndex: message.displayBlocks.indexOf(block), // 保留原始索引，用于可能的后续操作
            block: block
        };
        
        this.activeSideView = 'toolDetail';
        if (!this.sidePanelOpen) {
            this.expandSidePanel();
        }
        this.updatePanelWidths();
    },

    // 关闭工具详情
    closeToolBlockDetail() {
        this.activeToolBlock = null;
        this.activeSideView = 'list';  // 回到扩展列表视图
    },

    // S186：孤儿审批卡折叠——流收尾/新审批卡出现时，未被点名活卡的
    // approval 块一律折叠成已失效结果块（右侧详情走 openToolBlockDetail）
    _collapseStaleApprovalCards(msg, keepOverride) {
        if (!msg || !Array.isArray(msg.displayBlocks)) return;
        const keep = (keepOverride !== undefined) ? keepOverride : (this._pendingApprovalToolCallId || null);
        let changed = false;
        msg.displayBlocks.forEach((b, idx) => {
            if (b && b.type === 'approval' && b.id !== keep) {
                const _src = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(b) : b;
                const d = _src.data || {};
                // S187：元素替换式——冻结卡经代理改写必失败；替换为普通可冻结果块
                const _nb = Object.assign({}, _src, {
                    type: 'tool_result',
                    expired: true,
                    name: `${_src.name || 'Tool'} 已失效：流程已继续`,
                });
                this._setResultDisplay(_nb, `[已失效] 操作 ${d.tool_name || _src.name || '?'} 的审批未获批复，生成流程已继续或结束，该批复入口已关闭。\n\n审批载荷：\n${JSON.stringify(d, null, 2)}`);
                msg.displayBlocks[idx] = _nb;
                changed = true;
            }
        });
        if (changed) msg._rv = (msg._rv || 0) + 1;
    },

    // S195：孤儿提问卡折叠——流收尾/新提问卡出现时，未被点名活卡的 ask 块
    // 一律元素替换为已失效结果块（同 S186/S187 纪律：冻结卡经代理改写必失败）
    _collapseStaleAskCards(msg, keepOverride) {
        if (!msg || !Array.isArray(msg.displayBlocks)) return;
        const keep = (keepOverride !== undefined) ? keepOverride : (this._pendingAskToolCallId || null);
        let changed = false;
        msg.displayBlocks.forEach((b, idx) => {
            if (b && b.type === 'ask' && b.id !== keep) {
                const _src = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(b) : b;
                const _nb = Object.assign({}, _src, {
                    type: 'tool_result',
                    expired: true,
                    name: '提问卡已失效：流程已继续',
                });
                this._setResultDisplay(_nb, '[已失效] 该提问未以此卡答复（可能已在输入框作答、超时或被新提问取代），流程已继续，此卡通道已关闭。');
                msg.displayBlocks[idx] = _nb;
                changed = true;
            }
        });
        if (changed) msg._rv = (msg._rv || 0) + 1;
    },

    // S195：提问卡选项选中（点选不提交，逐题选完后统一提交）
    pickAskOption(block, qIdx, optIdx) {
        if (!block || block.type !== 'ask') return;
        if (!block.sel) block.sel = {};
        block.sel[qIdx] = optIdx;
        if (block.other) block.other[qIdx] = '';
    },

    // S195：提交按钮可用态——至少一题有选中且可解析为选项文本，或任一题有自定义文本
    askCardReady(block) {
        const qs = (block && block.data && Array.isArray(block.data.questions)) ? block.data.questions : [];
        return qs.some((q, i) => {
            const other = ((block.other && block.other[i]) || '').trim();
            if (other) return true;
            const s = block.sel ? block.sel[i] : undefined;
            return s !== undefined && q.options && q.options[s] !== undefined;
        });
    },

    // S195/S198：提交答复——组合「题号. 答案」行交 /ask_card_answer 服务端结算，
    // 卡原地转结果块、backend_content 回写服务端格式化结果（模型所见=历史），
    // 再走审批同款无 user 消息重放续跑（答案不再以工具结果+用户消息双份出现）。
    // 卡已失效/请求失败 → 降级为普通消息发送（输入路径的拦截兜底不变）。
    async submitAskAnswer(msg, block) {
        if (!block || block.type !== 'ask') return;
        if (!this._askInFlight) this._askInFlight = {};
        if (this._askInFlight[block.id]) return;
        if (this.isSending || this.isTyping) {
            if (typeof showNotification === 'function') showNotification('正在生成中，暂无法提交答复', 'warning');
            return;
        }
        const qs = (block.data && Array.isArray(block.data.questions)) ? block.data.questions : [];
        const lines = [];
        qs.forEach((q, i) => {
            const other = ((block.other && block.other[i]) || '').trim();
            if (other) { lines.push(`${i + 1}. ${other}`); return; }
            const s = block.sel ? block.sel[i] : undefined;
            if (s !== undefined && q.options && q.options[s] !== undefined) lines.push(`${i + 1}. ${q.options[s]}`);
        });
        if (!lines.length) return;
        const answerText = lines.join('\n');
        this._askInFlight[block.id] = true;
        let resp = null;
        try {
            const res = await fetch('/ask_card_answer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    conversation_id: this.stringifyEntityId ? this.stringifyEntityId(this.conversationId) : this.conversationId,
                    answer_text: answerText,
                }),
            });
            resp = await res.json();
        } catch (e) { resp = null; }
        if (!resp || !resp.ok) {
            delete this._askInFlight[block.id];
            if (typeof showNotification === 'function') showNotification('提问卡已失效，答复将作为普通消息发送', 'warning');
            this.userInput = answerText;
            Promise.resolve(this.sendMessage()).catch(() => { });
            return;
        }
        const resultText = resp.result_text || answerText;
        if (msg && Array.isArray(msg.displayBlocks)) {
            const _idx = msg.displayBlocks.findIndex(b => b && b.id === block.id && b.type === 'ask');
            if (_idx !== -1) {
                const _src = (typeof Vue !== 'undefined' && Vue.toRaw) ? Vue.toRaw(msg.displayBlocks[_idx]) : msg.displayBlocks[_idx];
                const _nb = Object.assign({}, _src, { type: 'tool_result', name: '已提交答复' });
                this._setResultDisplay(_nb, answerText);
                msg.displayBlocks[_idx] = _nb;
                msg._rv = (msg._rv || 0) + 1;
            }
        }
        if (msg && Array.isArray(msg.backend_content)) {
            for (let i = msg.backend_content.length - 1; i >= 0; i--) {
                const it = msg.backend_content[i];
                if (it && it.role === 'tool' && it.tool_call_id === block.id) { it.content = resultText; break; }
            }
        }
        this.markConvDirty && this.conversationId && this.markConvDirty(this.conversationId);
        try {
            await this.generateAIResponse(this.mainAgent, (msg && msg.agentName) || undefined, true);
        } catch (e) {
            console.error('[AskCard] 续跑失败:', e);
        } finally {
            delete this._askInFlight[block.id];
        }
    },

    // 根据块类型返回对应的图标类名
    getToolBlockIcon(type) {
        const icons = {
            'tool_call': 'fa-solid fa-wrench',
            'tool_result': 'fa-solid fa-check',
            'error': 'fa-solid fa-xmark',
            'approval': 'fa-solid fa-lock',
            'ask': 'fa-solid fa-circle-question'
        };
        return icons[type] || 'fa-solid fa-file-lines';
    },

    // 格式化工具块内容（处理 \n 和 \" 显示）
    formatToolBlockContent(block) {
        if (!block) return '';
        if (block.type === 'approval') {
            return JSON.stringify(block.data?.tool_params, null, 2);
        }
        let content = block.type === 'tool_call' ? (block.args || '') : (block.content || '');
        if (typeof content !== 'string') content = JSON.stringify(content, null, 2);
        return content.replace(/\\n/g, '\n').replace(/\\"/g, '"');
    },

    // S93(F2): reasoning 块完成标记——流式期纯文本 pre，done 后才走 markdown 全量渲染
    _markReasoningDone(msg) {
      if (!msg || !Array.isArray(msg.displayBlocks)) return;
      for (const b of msg.displayBlocks) {
        if (b.type === 'reasoning' && !b.done) b.done = true;
      }
    },

    // 获取消息的指定类型 block（复用原逻辑，但独立出来）
    // S101: 工具结果/错误的显示文本在 ingest 时一次性预计算（unquote 写时做）。
    // 此前模板表达式每次整页重渲都对最高 130K 内容现场跑正则=每帧 O(内容长度)
    // 的税（stucked-log 实锤与微任务洪峰叠加成数十秒长帧）。渲染期零写入纪律不破：
    // 本函数只在流回调里调用。
    _setResultDisplay(block, content) {
      block.content = content;
      block.displayContent = (typeof content === 'string')
        ? content.replace(/\\n/g, '\n').replace(/\\"/g, '"')
        : content;
    },

    // S102: tool_call args 显示文本同样写时预计算（progress 每帧重写增长串，
    // 模板 live-replace=每帧全文正则；本函数只在流回调里调用）。
    _setToolArgs(block, args) {
      block.args = args;
      block.displayArgs = (typeof args === 'string')
        ? args.replace(/\\n/g, '\n').replace(/\\"/g, '"')
        : args;
    },

    getBlockForMsg(msg, type, id = null, name = null) {
        if (!msg.displayBlocks) msg.displayBlocks = [];
        if (id) {
            const existing = msg.displayBlocks.find(b => b.type === type && b.id === id);
            if (existing) {
                if (name && !existing.name) existing.name = name;
                return existing;
            }
        }
        // S113: 思考被工具穿插不再拆块——反向扫描最近的 reasoning 块；
        // 其后仅隔 tool_call（结果未回=同段思考续写）→ 复用并复活 live 态；
        // 一旦出现 text 或 tool_result/error（结果已见=真·新一轮）→ 另起新块
        if (type === 'reasoning') {
            for (let i = msg.displayBlocks.length - 1; i >= 0; i--) {
                const b = msg.displayBlocks[i];
                if (b.type === 'reasoning') { b.done = false; return b; }
                if (b.type === 'text' || b.type === 'tool_result' || b.type === 'error') break;
            }
            const nb = { type, id, name, content: '', args: '', data: null };
            msg.displayBlocks.push(nb);
            return nb;
        }
        let last = msg.displayBlocks[msg.displayBlocks.length - 1];
        const canReuse = last && last.type === type && (!id || last.id === id);
        if (canReuse) {
            if (name && !last.name) last.name = name;
            return last;
        }
        const newBlock = { type, id, name, content: '', args: '', data: null };
        msg.displayBlocks.push(newBlock);
        return newBlock;
    },

    // methods 增加此函数
    smartMergeTerminal(existing, chunk) {
        if (!chunk) return existing;
        
        // 如果 chunk 包含回车符 \r，说明需要覆盖当前行
        if (chunk.includes('\r')) {
            let combined = existing + chunk;
            let lines = combined.split('\n');
            let lastLine = lines[lines.length - 1];

            // 处理最后一行内部的 \r
            if (lastLine.includes('\r')) {
                let subParts = lastLine.split('\r');
                // 只保留最后一个 \r 之后的内容（即最新的进度）
                lines[lines.length - 1] = subParts[subParts.length - 1];
            }
            return lines.join('\n');
        }
        
        // 如果没有 \r，直接追加
        return existing + chunk;
    },

    // 辅助：为 AI 准备的精简函数
    truncateForAI(text) {
        if (!text) return '';
        const MAX_LIMIT = 8000; // 传回 AI 的上限，根据需求调整
        
        // 1. 剔除进度条行（包含 █ 或大量进度字符的行对 AI 没用，浪费 Token）
        let lines = text.split('\n');
        let cleanedLines = lines.filter(line => {
            // 过滤掉包含进度条特征的行
            const isProgressBar = (line.includes('█') || line.includes('░') || (line.includes('%') && line.includes('|')));
            return !isProgressBar;
        });
        
        let cleanedText = cleanedLines.join('\n').trim();
        
        // 2. 如果依然超长，进行头尾截断
        if (cleanedText.length > MAX_LIMIT) {
            return cleanedText.substring(0, 2000) + 
                  `\n\n... [Total ${text.length} chars. Output truncated for context. User sees full output above.] ...\n\n` + 
                  cleanedText.slice(-4000);
        }
        return cleanedText;
    }
});
