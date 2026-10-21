// 批 3 F2：自 vue_methods.js 搬移的任务中心域（Object.assign 装配）。
Object.assign(vue_methods, {
    async probeDocker() {
      try {
        const res = await fetch('/api/docker/probe');
        const data = await res.json();
        this.dockerInstalled = data.installed;
      } catch (error) {
        console.error("Docker 探测失败:", error);
        this.dockerInstalled = false;
      }
    },

    // 创建任务
    async submitCreateTask() {
        if (!this.newTaskForm.title || !this.newTaskForm.description) {
            showNotification(this.t('fillRequired'), 'error');
            return;
        }

        this.isCreatingTask = true;
        try {
            console.log(this.newTaskForm); // 打印表单数据
            const res = await fetch(`/v1/tasks/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    title: this.newTaskForm.title,
                    description: this.newTaskForm.description,
                    agent_type: this.newTaskForm.agent_type,
                    task_type: this.newTaskForm.task_type,
                    platforms: this.newTaskForm.platforms,
                    trigger_config: this.newTaskForm.trigger_config // 发送完整配置
                })
            });
            const data = await res.json();
            
            if (data.success) {
                showNotification(this.t('success'));
                this.showCreateTaskDialog = false;
                // 重置表单
                this.newTaskForm = { 
                    title: '', description: '', task_type: 'once', agent_type: 'default',
                    trigger_config: { timeValue: '09:00:00', days: [1,2,3,4,5], cycleValue: '01:00:00', repeatNumber: 1, isInfiniteLoop: true }
                };
                this.fetchTasks();
            } else {
                showNotification(data.error, 'error');
            }
        } catch (e) {
            showNotification(this.t('networkError'), 'error');
        } finally {
            this.isCreatingTask = false;
        }
    },

    // 取消任务
    async handleCancelTask(taskId) {
        try {
            await fetch(`/v1/tasks/cancel/${taskId}`, { method: 'POST' });
            showNotification(this.t('cancelSuccess') || '取消任务成功');
            this.fetchTasks();
        } catch (e) { console.error(e); }
    },

    // 删除任务
    async handleDeleteTask(taskId) {
        try {
            this.handleCancelTask(taskId);
            const res = await fetch(`/v1/tasks/${taskId}`, { 
                method: 'DELETE' 
            });
            
            if (res.ok) {
                showNotification(this.t('deleteSuccess') || '删除任务成功');
                this.fetchTasks(); // 刷新列表
            } else {
                console.error("Delete failed with status:", res.status);
            }
        } catch (e) { 
            console.error("Network error during delete:", e); 
        }
    },

    // 跳转设置
    jumpToCLIConfig() {
        this.activeMenu = 'toolkit';
        this.subMenu = 'CLI';
    },

    formatTaskTime(isoStr) {
        if (!isoStr) return '-';
        const date = new Date(isoStr);
        return date.toLocaleString();
    },

    getTaskStatusType(status) {
        const map = {
            'pending': 'info',
            'running': 'primary',
            'completed': 'success',
            'failed': 'danger',
            'cancelled': 'warning'
        };
        return map[status] || 'info';
    },

  // 打开任务结果弹窗
// 在 Vue 组件的 methods 中
openTaskResult(task) {
    this.selectedTaskTitle = task.title;
    
    // 1. 获取该任务的所有历史产出记录
    // 如果没有历史记录（比如旧任务），我们造一个包含当前结果的伪记录
    const rawHistory = task.context?.results_history || [];
    
    if (rawHistory.length === 0 && task.result) {
        this.selectedTaskHistory = [{
            time: task.updated_at || task.created_at,
            result: task.result
        }];
    } else {
        // 将历史记录倒序排列（最新的在最上面）
        this.selectedTaskHistory = [...rawHistory].reverse();
    }
    
    // 2. 默认选中第一项（即最新的一项）
    this.currentResultIdx = 0;
    
    // 3. 打开弹窗
    this.showTaskResultDialog = true;
},

    getModeIcon(type) {
        const iconMap = {
            'once': 'fa-solid fa-bolt-lightning',
            'time': 'fa-regular fa-clock',
            'cycle': 'fa-solid fa-arrows-rotate'
        };
        // 如果 type 为空或不在 map 中，返回默认图标
        return iconMap[type] || 'fa-solid fa-terminal';
    },

    // 打开新建窗口
    openCreateTaskDialog() {
        this.resetTaskForm(); // 确保每次新建前都干净
        this.showCreateTaskDialog = true;
    },

    openEditTaskDialog(task) {
        // 1. 先重置，清除上一次可能残留的状态
        this.resetTaskForm();
        
        // 2. 标记为编辑模式
        this.isEditing = true;
        this.editingTaskId = task.task_id;
        
        // 3. 填充基础数据
        this.newTaskForm.title = task.title;
        this.newTaskForm.description = task.description;
        this.newTaskForm.platforms = task.platforms || [];
        this.newTaskForm.agent_type = task.agent_type || 'default';
        this.newTaskForm.task_type = task.context?.task_type || task.task_type || 'once';
        
        // 4. 填充触发器配置
        const savedConfig = task.context?.trigger_config;
        if (savedConfig) {
            // 使用 assign 或 spread 确保响应式更新
            Object.assign(this.newTaskForm.trigger_config, JSON.parse(JSON.stringify(savedConfig)));
        }
        
        this.showCreateTaskDialog = true;
    },

    // 2. 统一的提交处理函数
    async submitTaskForm() {
        if (!this.newTaskForm.title || !this.newTaskForm.description) {
            showNotification(this.t('fillRequired'), 'error');
            return;
        }

        this.isCreatingTask = true;

        try {
            // 如果是编辑模式，先停止并删除旧任务
            if (this.isEditing && this.editingTaskId) {
                // A. 停止原有任务
                await fetch(`/v1/tasks/cancel/${this.editingTaskId}`, { method: 'POST' });
                // B. 删除原有任务
                await fetch(`/v1/tasks/${this.editingTaskId}`, { method: 'DELETE' });
                console.log(`Old task ${this.editingTaskId} removed for re-creation`);
            }

            // C. 创建新任务 (无论是新建还是编辑后的“重建”，都走这个接口)
            const res = await fetch(`/v1/tasks/create`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.newTaskForm)
            });
            const data = await res.json();
            
            if (data.success) {
                showNotification(this.t('success'));
                this.showCreateTaskDialog = false; // 关闭窗口
                this.resetTaskForm();             // ⭐ 提交成功后重置表单
                this.fetchTasks();                // 刷新列表
            } else {
                showNotification(data.error, 'error');
            }
        } catch (e) {
            showNotification(this.t('networkError'), 'error');
        } finally {
            this.isCreatingTask = false;
            // 提交完成后重置编辑状态
            this.isEditing = false;
            this.editingTaskId = null;
        }
    },

// 打开详情页
openTaskDetailView(task) {
    this.viewingTaskDetail = task;
},

// 关闭详情页回到列表
closeTaskDetail() {
    this.viewingTaskDetail = null;
},

// 1. 懒加载读取文件目录
  async loadWorkspaceNode(node, resolve) {
    // 顶层节点：加载工作区根目录
    if (node.level === 0) {
      if (!this.CLISettings || !this.CLISettings.cc_path) {
        return resolve([]); 
      }
      
      // ⚠️ 暴力触发：只要根节点加载，就立刻启动监听器！
      console.log('准备启动文件监听:', this.CLISettings.cc_path);
      this.setupWorkspaceWatcher(this.CLISettings.cc_path);

      try {
        const res = await window.electronAPI.readDirectory(this.CLISettings.cc_path);
        if (res.success) {
          return resolve(res.data);
        } else {
          this.$message?.error(this.t('readDirError') || '读取工作区目录失败: ' + res.error);
          return resolve([]);
        }
      } catch (error) {
        console.error(error);
        return resolve([]);
      }
    }

    // 子节点：加载被点击的子目录
    if (node.level > 0 && node.data.isDirectory) {
      try {
        const res = await window.electronAPI.readDirectory(node.data.path);
        if (res.success) {
          return resolve(res.data);
        } else {
          this.$message?.error(this.t('readDirError') || '读取子目录失败: ' + res.error);
          return resolve([]);
        }
      } catch (error) {
        console.error(error);
        return resolve([]);
      }
    }
    
    resolve([]);
  },

  // 2. 使用系统默认程序打开文件
  openWorkspaceFile(filePath) {
    if (window.electronAPI && window.electronAPI.openPath) {
      window.electronAPI.openPath(filePath);
    }
  },

  // 3. 删除文件/文件夹
  async deleteWorkspaceFile(data, node) {
    try {
      // 弹出确认框 (兼容 Element Plus 的 this.$confirm)
      await this.$confirm(
        (this.t('confirmDelete') || '确认将该文件放入回收站吗？') + `\n${data.name}`,
        this.t('warning') || '警告',
        { 
          confirmButtonText: this.t('confirm') || '确定', 
          cancelButtonText: this.t('cancel') || '取消', 
          type: 'warning' 
        }
      );
      
      const res = await window.electronAPI.deleteWorkspaceFile(data.path);
      if (res.success) {
        showNotification(this.t('deleteSuccess'),'success');
        // 从前端界面中动态移除该节点，避免重新读取整个目录树
        const parent = node.parent;
        const children = parent.data.children || parent.childNodes;
        const index = children.findIndex(d => d.data.path === data.path);
        if (index !== -1) {
          children.splice(index, 1);
        }
        
      } else {
        showNotification(this.t('deleteFailed'),'error');
      }
    } catch (error) {
      // 用户点击了取消，不做任何处理
    }
  },

  // 5. 刷新整个工作区树
  refreshWorkspaceTree() {
    // 改变 key 值会让 Vue 销毁并重建 el-tree，从而重新触发 load()
    this.workspaceTreeKey += 1;
  },

    // 核心上传逻辑
    async executeUpload(targetPath) {
        try {
            // 1. 调用选择文件对话框
            const result = await window.electronAPI.openFileDialog();
            
            if (result.canceled || result.filePaths.length === 0) return;

            // 2. 执行上传
            const uploadRes = await window.electronAPI.uploadToWorkspace(targetPath, result.filePaths);
            
            if (uploadRes.success) {
                showNotification(this.t('uploadSuccess'),'success');
                this.refreshWorkspaceTree(); // 刷新显示新文件
            } else {
                showNotification(this.t('uploadFailed'),'error');
            }
        } catch (err) {
            console.error('Upload Error:', err);
            this.$message.error('操作失败，请检查控制台日志');
        }
    },

    // 顶部按钮：上传到根目录
    handleRootUpload() {
        const rootPath = this.CLISettings.cc_path;
        if (!rootPath) {
            showNotification(this.t('pleaseConfigWorkspace'),'error');
            return;
        }
        this.executeUpload(rootPath);
    },

    // 文件夹按钮：上传到子目录
    handleFolderUpload(folderPath) {
        console.log("正在上传到子目录:", folderPath);
        this.executeUpload(folderPath);
    },

    // 开启工作区监控
    setupWorkspaceWatcher(path) {
      if (window.electronAPI && window.electronAPI.startWorkspaceWatch) {
        window.electronAPI.startWorkspaceWatch(path);
        
        window.electronAPI.onWorkspaceChanged((data) => {
          console.log('前端收到文件系统变化:', data.action, data.path);
          
          // ⚠️ 关键修复：使用原生定时器彻底解决 this 指向丢失的问题
          if (this.workspaceRefreshTimer) {
            clearTimeout(this.workspaceRefreshTimer);
          }
          
          this.workspaceRefreshTimer = setTimeout(() => {
            console.log('触发防抖更新 UI ...');
            this.refreshWorkspaceTreeKeepExpanded();
          }, 500);
        });
      }
    },

    // 刷新前保留展开状态
    refreshWorkspaceTreeKeepExpanded() {
      const treeRef = this.$refs.workspaceTreeRef;
      if (treeRef) {
        const store = treeRef.store;
        const expandedKeys = [];
        for (const key in store.nodesMap) {
          if (store.nodesMap[key].expanded) {
            expandedKeys.push(key);
          }
        }
        this.expandedNodeKeys = expandedKeys;
        console.log('当前记录的展开文件夹节点:', this.expandedNodeKeys);
      } else {
        console.warn('未找到 el-tree 的引用 (workspaceTreeRef)');
      }
      
      this.refreshWorkspaceTree();
    },

createNewTask(){
  this.activeMenu = 'home';
  this.expandSidePanel();
  this.activeSideView = 'tasks';

}
});
