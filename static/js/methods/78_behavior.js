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
}
});
