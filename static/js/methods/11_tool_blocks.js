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

    // 根据块类型返回对应的图标类名
    getToolBlockIcon(type) {
        const icons = {
            'tool_call': 'fa-solid fa-wrench',
            'tool_result': 'fa-solid fa-check',
            'error': 'fa-solid fa-xmark',
            'approval': 'fa-solid fa-lock'
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
