// 批 3 F2：自 vue_methods.js 搬移的 methods/78_behavior.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  addBehavior() {
    // 深拷贝一份默认模板
    this.behaviorSettings.behaviorList.push(JSON.parse(JSON.stringify(this.newBehavior)));
    this.autoSaveSettings();
  },

  resetBehavior(idx) {
    this.behaviorSettings.behaviorList[idx] = JSON.parse(JSON.stringify(this.newBehavior));
    this.autoSaveSettings();
  },

  removeAllBehavior() {
    this.behaviorSettings.behaviorList.forEach((b) => {
      b.enabled = false;
    });
    this.behaviorSettings.behaviorList = [];
    showNotification(this.t('deleteAllBehaviorSuccess'))
    this.autoSaveSettings();
  },

    /* 真正执行行为 */
    runBehavior(b) {
      if (!b.enabled) return
      if (!this.noInputFlag){
        this.stopGenerate()
      }
      if (b.action.type === 'prompt' && b.action.prompt) {
        console.log('Prompt:', b.action.prompt)
        this.userInput= '[system]:'+ b.action.prompt
        // 这里把 prompt 发给你的模型即可，举例：
        this.sendMessage();
      }
      if (b.action.type === 'random' && b.action.random) {
        if(b.action.random.events.length > 0){
          if (b.action.random.type === 'random'){
            let randomEvent = b.action.random.events[Math.floor(Math.random() * b.action.random.events.length)];
            if(randomEvent){
              this.userInput= '[system]:'+randomEvent;
              // 这里把 prompt 发给你的模型即可，举例：
              this.sendMessage();
            }
          }else if( b.action.random.type === 'order'){
            if(b.action.random.orderIndex >= b.action.random.events.length){
              b.action.random.orderIndex = 0;
            }
            if(b.action.random.events[b.action.random.orderIndex]){
              let randomEvent = b.action.random.events[b.action.random.orderIndex];
              b.action.random.orderIndex += 1;
              if(randomEvent){
                this.userInput= '[system]:'+randomEvent;
                // 这里把 prompt 发给你的模型即可，举例：
                this.sendMessage();
              }
            }
          }
        }
      }
    },

    /* 触发一次后，如果是“不重复”就把 enabled 关掉 */
    disableOnceBehavior(b) {
      if (b.trigger.type === 'time' && !b.trigger.time.days.length && b.platform === 'chat') {
        b.enabled = false
        this.autoSaveSettings()
      }
    },

    handleAllBriefly(){
      this.allBriefly = !this.allBriefly;
      if(this.allBriefly){
        this.messages.forEach((m) => {
          m.briefly = true;
        })
      }else{
        this.messages.forEach((m) => {
          m.briefly = false;
        })
      }
    },

    async handleDownload(file) {
      // 构造文件URL（确保是完整URL）
      const fileUrl = `${this.partyURL}/uploaded_files/${file.unique_filename}`;
      console.log(fileUrl);
      if (isElectron) {
        try {
          await window.electronAPI.downloadFile({
            url: fileUrl,
            filename: file.original_filename || file.unique_filename
          });
        } catch (e) {
          console.error(e);
        }
      } else {
        // 非Electron环境保留原逻辑
        const link = document.createElement('a');
        link.href = fileUrl;
        link.download = file.unique_filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      }
    },

  removeEvent(idx,index) {
    this.behaviorSettings.behaviorList[idx].action.random.events.splice(index, 1);
    this.autoSaveSettings(); // 删除后也触发自动保存
  },

  addNewEvent(idx) {
    this.behaviorSettings.behaviorList[idx].action.random.events.push(''); // 添加一个新的空事件，从而新增一个输入框
    this.autoSaveSettings();
  },

  // 初始化周期定时器
initCycleTimer(behavior, index) {
  if (this.cycleTimers[index]) {
    clearInterval(this.cycleTimers[index]);
  }
  const [hours, minutes, seconds] = behavior.trigger.cycle.cycleValue.split(':').map(Number);
  const cycleMs = (hours * 3600 + minutes * 60 + seconds) * 1000;
  let currentCount = 0;
  
  this.cycleTimers[index] = setInterval(() => {
    // 运行前再次确认启用状态和平台
    if (!behavior || !behavior.enabled || !this.isTargetPlatform(behavior, 'chat')) return;
    
    if (behavior.trigger.cycle.isInfiniteLoop || currentCount < behavior.trigger.cycle.repeatNumber) {
      this.runBehavior(behavior);
      currentCount++;
      if (!behavior.trigger.cycle.isInfiniteLoop && currentCount >= behavior.trigger.cycle.repeatNumber) {
        clearInterval(this.cycleTimers[index]);
        this.cycleTimers[index] = null;
        behavior.enabled = false;
      }
    }
  }, cycleMs);
},

// --- 修改重置逻辑 ---
resetCycleTimers() {
  // 防护：如果设置还没加载好，或者列表不存在，直接跳过
  if (!this.behaviorSettings || !Array.isArray(this.behaviorSettings.behaviorList)) {
    return;
  }

  // 确保 cycleTimers 是个数组
  if (!Array.isArray(this.cycleTimers)) {
    this.cycleTimers = [];
  }

  // 清除旧的计时器
  this.cycleTimers.forEach((timer, index) => {
    if (timer) clearInterval(timer);
    this.cycleTimers[index] = null;
  });

  // 重新初始化
  this.behaviorSettings.behaviorList.forEach((b, index) => {
    // 增加 b && b.trigger 的判断
    if (b && b.enabled && b.trigger && b.trigger.type === 'cycle' && this.isTargetPlatform(b, 'chat')) {
      this.initCycleTimer(b, index);
    }
  });
},

    // 打开编辑/新增对话框
    openBehaviorDialog(index) {
      this.currentBehaviorIndex = index;
      if (index === -1) {
        // 新增模式：创建默认模板的深拷贝
        this.tempBehavior = this.createDefaultBehavior();
      } else {
        // 编辑模式：创建现有数据的深拷贝（切断引用）
        // 假设您的数据在 behaviorSettings.behaviorList 中
        this.tempBehavior = JSON.parse(JSON.stringify(this.behaviorSettings.behaviorList[index]));
        // S73：旧配置无工具策略字段 -> 回填补齐（后端 pydantic 同样兜底）
        if (!this.tempBehavior.tools_mode) this.tempBehavior.tools_mode = 'none';
        if (!Array.isArray(this.tempBehavior.tools_list)) this.tempBehavior.tools_list = [];
      }
      
      this.showBehaviorDialog = true;
    },

    // 创建默认行为模板
    createDefaultBehavior() {
      return {
        enabled: true,
        trigger: {
          type: 'time',
          time: { timeValue: '08:00:00', days: [1, 2, 3, 4, 5] },
          noInput: { latency: 60 },
          cycle: { cycleValue: '00:30:00', repeatNumber: 1, isInfiniteLoop: true }
        },
        action: {
          type: 'prompt',
          prompt: '',
          random: { type: 'random', events: [''] }
        },
        platforms: ["chat"],  // 新增多选渠道字段（字符串数组）
        tools_mode: 'none',   // S73：自主事件工具策略，默认无工具
        tools_list: [],
      };
    },

    // 关闭对话框后的清理
    resetBehaviorDialogState() {
      this.tempBehavior = null;
      this.currentBehaviorIndex = -1;
    },

    // 保存行为设置（新增或更新）
    saveBehavior() {
      if (!this.tempBehavior) return;

      // 1. 核心修复：确保 platforms 字段一定是数组且有值
      if (!Array.isArray(this.tempBehavior.platforms)) {
        // 如果没有数组，根据旧的单选字段转换，或者给默认值
        let oldVal = this.tempBehavior.platform || 'chat';
        this.tempBehavior.platforms = [oldVal];
      }
      
      // 如果用户一个都没选（空数组），强制给个 'chat'
      if (this.tempBehavior.platforms.length === 0) {
        this.tempBehavior.platforms = ['chat'];
      }

      // 2. 同步旧字段 platform，取数组第一个元素
      this.tempBehavior.platform = this.tempBehavior.platforms[0];

      // S73：工具策略字段兜底（防止旧对象/新增路径缺省）
      if (!this.tempBehavior.tools_mode) this.tempBehavior.tools_mode = 'none';
      if (!Array.isArray(this.tempBehavior.tools_list)) this.tempBehavior.tools_list = [];

      // 3. 保存逻辑
      if (this.isEditingBehavior) {
        // 查找并替换旧项
        const idx = this.behaviorSettings.behaviorList.findIndex(b => b === this.editingItemOrigin);
        if (idx !== -1) {
          this.behaviorSettings.behaviorList[idx] = JSON.parse(JSON.stringify(this.tempBehavior));
        }
      } else {
        // 新增项
        this.behaviorSettings.behaviorList.push(JSON.parse(JSON.stringify(this.tempBehavior)));
      }

      this.showBehaviorDialog = false;
      
      // 4. 保存后刷新计时器
      this.$nextTick(() => {
        this.resetCycleTimers();
      });
    },

    // 确认删除行为
    confirmRemoveBehavior(index) {
      this.$confirm(
        this.t('confirmDeleteBehavior') || 'Are you sure you want to delete this behavior?',
        this.t('warning') || 'Warning',
        {
          confirmButtonText: this.t('confirm'),
          cancelButtonText: this.t('cancel'),
          type: 'warning',
        }
      ).then(() => {
        this.removeBehavior(index);
      }).catch(() => {});
    },

    // 处理全局开关变化
    handleGlobalSwitchChange() {
      this.resetCycleTimers();
      this.autoSaveSettings();
    },

    // 处理单个行为开关变化
    handleBehaviorChange() {
      this.resetCycleTimers();
      this.autoSaveSettings();
    },

    // 根据触发类型返回图标类名
    getTriggerIcon(type) {
      const map = {
        'time': 'fa-regular fa-clock',
        'noInput': 'fa-solid fa-hourglass-half',
        'cycle': 'fa-solid fa-arrows-spin'
      };
      return map[type] || 'fa-solid fa-bolt';
    },

    // 生成卡片上的摘要文本
    getBehaviorSummary(b) {
      if (!b || !b.trigger) return '';
      
      if (b.trigger.type === 'time') {
        const time = b.trigger.time.timeValue;
        const days = b.trigger.time.days.length;
        const daysText = this.t('repeatDays') || 'Days'; // 简单处理，实际根据你的 t 函数逻辑
        return `${time} (${daysText}: ${days})`;
      } else if (b.trigger.type === 'noInput') {
        return `${this.t('noInputLatency') || 'Latency'}: ${b.trigger.noInput.latency}s`;
      } else if (b.trigger.type === 'cycle') {
        const loopText = b.trigger.cycle.isInfiniteLoop ? '∞' : b.trigger.cycle.repeatNumber;
        return `${this.t('cycleValue') || 'Cycle'}: ${b.trigger.cycle.cycleValue} (x${loopText})`;
      }
      return '';
    },

    // 辅助工具：生成数字范围数组
    makeRange(start, end) {
      const result = [];
      for (let i = start; i <= end; i++) {
        result.push(i);
      }
      return result;
    },

    // 禁用小时
    disabledHours() {
      // 只有在最小值的小时大于 0 时才需要禁用
      // 如果最小是 00:00:01，则不禁用任何小时
      return this.makeRange(0, 23).filter(h => h < this.minLimit.h);
    },

    // 禁用分钟 (selectedHour 是当前转盘选中的小时)
    disabledMinutes(selectedHour) {
      // 只有当选中的小时等于最小值的小时时，才限制分钟
      if (selectedHour === this.minLimit.h) {
        return this.makeRange(0, 59).filter(m => m < this.minLimit.m);
      }
      return [];
    },

    // 禁用秒钟 (selectedHour 和 selectedMinute 是当前选中的时和分)
    disabledSeconds(selectedHour, selectedMinute) {
      // 只有当时和分都处于最小值临界点时，才限制秒钟
      if (selectedHour === this.minLimit.h && selectedMinute === this.minLimit.m) {
        return this.makeRange(0, 59).filter(s => s < this.minLimit.s);
      }
      return [];
    }
});
