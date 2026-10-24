// 批 3 F2：自 vue_methods.js 搬移的 methods/96_table_a2ui.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  addTableEnhancements() {
    this.$nextTick(() => {
      const tables = document.querySelectorAll('.markdown-body table');
      
      tables.forEach((table) => {
        if (table.parentElement.classList.contains('markdown-table-wrapper')) return;

        // 1. 创建容器
        const wrapper = document.createElement('div');
        wrapper.className = 'markdown-table-wrapper';
        table.parentNode.insertBefore(wrapper, table);
        wrapper.appendChild(table);

        // 2. 创建按钮
        const btn = document.createElement('button');
        btn.className = 'table-download-btn';
        // 使用 fa-file-excel 图标，更直观
        btn.innerHTML = '<i class="fa-solid fa-file-excel"></i> XLSX';
        btn.title = '导出为 Excel 文件';
        
        // 3. 绑定点击事件 (调用新的 exceljs 逻辑)
        btn.onclick = async (e) => {
          e.stopPropagation();
          // 添加加载状态反馈（可选）
          const originalText = btn.innerHTML;
          btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 导出中...';
          btn.disabled = true;
          
          try {
            await this.downloadTableAsXLSX(table);
          } catch (error) {
            console.error('Excel 导出失败:', error);
            this.$message?.error('导出失败，请重试');
          } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
          }
        };

        wrapper.appendChild(btn);
      });
    });
  },

  // 全局点击事件代理
  handleGlobalClick(event) {
    // 1. 检查点击的是否是 Excel 导出按钮
    // closest 处理用户可能点到图标 <i> 的情况
    const btn = event.target.closest('.download-xlsx-trigger');
    
    if (btn) {
      event.preventDefault();
      event.stopPropagation();
      
      // 找到同级的前一个兄弟元素 (即 table)
      // 根据上面 markdown-it 的结构: <table>...</table> <button>...</button>
      // 所以 button.previousElementSibling 就是 table
      const table = btn.previousElementSibling;
      
      if (table && table.tagName === 'TABLE') {
        this.exportTable(btn, table);
      }
    }
  },

    handleMessageLinkClick(event) {
        // 1. 如果你原有的 handleGlobalClick 有逻辑（比如点击空白处关闭菜单），在这里调用它
        this.handleGlobalClick(event); 

        if(isElectron){

          const link = event.target.closest('a');

          if (link && link.href) {
              const href = link.href;

              // 2. 过滤逻辑：只拦截 http/https 网络链接
              if (href.startsWith('http') || href.startsWith('https')) {
                  
                  // ★ 关键：同时调用 stopPropagation 和 preventDefault
                  event.preventDefault();  // 阻止链接默认跳转
                  event.stopPropagation(); // 阻止事件继续传播
                  
                  // 3. 打开内部浏览器
                  console.log('拦截到链接，正在内部浏览器打开:', href);
                  this.openUrlInNewTab(href);
              }
          }
        
        }

    },

  // 这里的逻辑跟您原来的 click 类似，只是参数变了
  async exportTable(btn, tableElement) {
    if (btn.disabled) return; // 防止重复点击

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> 导出中...';
    btn.disabled = true;

    try {
      await this.downloadTableAsXLSX(tableElement);
    } catch (error) {
      console.error('导出失败', error);
      // 如果有 Element Plus
      if (this.$message) this.$message.error('导出失败');
    } finally {
      btn.innerHTML = originalHtml;
      btn.disabled = false;
    }
  },

  /**
   * 使用 ExcelJS 生成真正的 .xlsx 文件
   */
  async downloadTableAsXLSX(tableElement) {
    const workbook = new ExcelJS.Workbook();
    const worksheet = workbook.addWorksheet('数据导出');

    // --- 1. 提取 HTML 表格数据 ---
    const rows = tableElement.querySelectorAll('tr');
    
    // 遍历 HTML 行
    rows.forEach((row, rowIndex) => {
      const cells = row.querySelectorAll('td, th');
      const rowData = [];
      
      cells.forEach(cell => {
        // 获取纯文本
        rowData.push(cell.innerText.trim());
      });
      
      // 添加到 Worksheet
      const excelRow = worksheet.addRow(rowData);
    });

    // --- 2. 美化 Excel 样式 (Pro 模式) ---
    
    // 2.1 设置表头样式 (第一行)
    const headerRow = worksheet.getRow(1);
    headerRow.font = { 
      name: '微软雅黑', 
      bold: true, 
      color: { argb: 'FFFFFFFF' } // 白字
    };
    headerRow.fill = {
      type: 'pattern',
      pattern: 'solid',
      fgColor: { argb: 'FF1E849B' } // 使用你的主题色 (深青色)
    };
    headerRow.alignment = { vertical: 'middle', horizontal: 'center' };

    // 2.2 自动计算列宽
    worksheet.columns.forEach(column => {
      let maxLength = 0;
      column.eachCell({ includeEmpty: true }, cell => {
        const columnLength = cell.value ? cell.value.toString().length : 10;
        if (columnLength > maxLength) maxLength = columnLength;
      });
      // 限制最大宽度，防止太宽
      column.width = maxLength < 10 ? 10 : (maxLength > 50 ? 50 : maxLength + 2);
    });

    // 2.3 添加边框
    worksheet.eachRow((row, rowNumber) => {
      row.eachCell((cell) => {
        cell.border = {
          top: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          left: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          bottom: { style: 'thin', color: { argb: 'FFDCDFE6' } },
          right: { style: 'thin', color: { argb: 'FFDCDFE6' } }
        };
        // 内容垂直居中
        cell.alignment = { ...cell.alignment, vertical: 'middle', wrapText: true };
      });
    });

    // --- 3. 生成并下载文件 ---
    const buffer = await workbook.xlsx.writeBuffer();
    const blob = new Blob([buffer], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' });
    
    const link = document.createElement('a');
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[-T:]/g, "");
    link.href = URL.createObjectURL(blob);
    link.download = `table_export_${timestamp}.xlsx`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(link.href);
  },

    // [A2UI 新增] 处理用户点击操作
    handleA2UIAction(msg) {
      console.log('A2UI Action Triggered:', msg);
      this.userInput = msg;
      this.sendMessage();
    },

    // [A2UI 新增] 拆分消息内容为 文本/UI 段
    splitMessageContent(content) {
      if (!content) return [];
      // S93(F1): 字符串级缓存（同 formatMessage 理由：流式期整页表达式每帧重评）。
      // 返回浅拷贝，段对象引用不外泄；ui 段的解析结果 JSON 反而因引用稳定少重渲。
      const cache = this._segCache || (this._segCache = new Map());
      const hit = cache.get(content);
      if (hit !== undefined) { cache.delete(content); cache.set(content, hit); return hit.map(s => ({ ...s })); }
      const segments = [];
      const regex = /```a2ui\s*([\s\S]*?)\s*```/g;

      let lastIndex = 0;
      let match;

      while ((match = regex.exec(content)) !== null) {
        if (match.index > lastIndex) {
          const textPart = content.slice(lastIndex, match.index);
          if (textPart) segments.push({ type: 'text', content: textPart });
        }

        try {
          const uiConfig = JSON.parse(match[1]);
          segments.push({ type: 'ui', content: uiConfig });
        } catch (e) {
          segments.push({ type: 'text', content: match[0] });
        }
        lastIndex = regex.lastIndex;
      }

      if (lastIndex < content.length) {
        segments.push({ type: 'text', content: content.slice(lastIndex) });
      }

      cache.set(content, segments);
      if (cache.size > 150) cache.delete(cache.keys().next().value);
      return segments.map(s => ({ ...s }));
    }
});
