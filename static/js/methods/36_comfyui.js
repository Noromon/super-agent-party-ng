// 批 3 F2：自 vue_methods.js 搬移的 methods/36_comfyui.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    // 添加ComfyUI服务器
    addComfyUIServer() {
      this.comfyuiServers.push('http://localhost:8188')
      this.autoSaveSettings()
    },

    // 移除服务器
    removeComfyUIServer(index) {
      if (this.comfyuiServers.length > 1) {
        this.comfyuiServers.splice(index, 1)
        this.autoSaveSettings()
      }
    },

    // 连接服务器
    async connectComfyUI(index) {
      this.isConnecting = true
      try {
        const url = this.comfyuiServers[index]
        const response = await fetch(`${url}/history`, {
          method: 'HEAD',
          mode: 'cors'
        })
        if (response.ok) {
          this.activeComfyUIUrl = url
          showNotification('服务器连接成功')
        }
      } catch (e) {
        showNotification('无法连接ComfyUI服务器', 'error')
      }
      this.isConnecting = false
    },

    // 浏览文件
    browseWorkflowFile() {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = '.json';
      input.onchange = (event) => {
        const files = event.target.files;
        if (files.length > 0) {
          this.workflowFile = files[0];
          this.loadWorkflowFile(this.workflowFile); // 确保在文件已选择后调用
        }
      };
      input.click();
    },

    // 移除文件
    removeWorkflowFile() {
      this.workflowFile = null;
    },

    // 删除工作流
    async deleteWorkflow(filename) {
      try {
        const response = await fetch(`/delete_workflow/${filename}`, {
          method: 'DELETE',
        });
        const data = await response.json();
        if (data.success) {
          this.workflows = this.workflows.filter(file => file.unique_filename !== filename);
          await this.autoSaveSettings();
          showNotification('删除成功');
        } else {
          this.workflows = this.workflows.filter(file => file.unique_filename !== filename);
          await this.autoSaveSettings();
          showNotification('删除失败', 'error');
        }
      } catch (error) {
        console.error('删除失败:', error);
       showNotification('删除失败', 'error');
      }
    },

      // 处理文件拖拽
  handleWorkflowDrop(event) {
    event.preventDefault();
    const files = event.dataTransfer.files;
    if (files.length > 0) {
      this.workflowFile = files[0];
      this.loadWorkflowFile(this.workflowFile); // 加载工作流文件以生成选择项
    }
  },

  // 加载工作流文件
  async loadWorkflowFile(file) {
    const reader = new FileReader();
    reader.onload = (event) => {
      const workflowJson = JSON.parse(event.target.result);
      this.populateInputOptions(workflowJson);
    };
    reader.readAsText(file);
  },

  // 填充输入选择项
  populateInputOptions(workflowJson) {
    this.textInputOptions = [];
    this.imageInputOptions = [];
    this.seedInputOptions = [];
    
    for (const nodeId in workflowJson) {
      const node = workflowJson[nodeId];
      if (!node.inputs) continue;
      
      // 查找所有包含text/value/prompt的文本输入字段
      const textInputKeys = Object.keys(node.inputs).filter(key => 
        (key.includes('text') || key.includes('value') || key.includes('prompt')) &&
        typeof node.inputs[key] === 'string' // 确保值是字符串类型
      );
      
      // 为每个符合条件的字段创建选项
      textInputKeys.forEach(key => {
        this.textInputOptions.push({
          label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
          value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
        });
      });
      
      // 查找图片输入字段
      if (node.class_type === 'LoadImage') {
        const imageKeys = Object.keys(node.inputs).filter(key => 
          key.includes('image') && 
          typeof node.inputs[key] === 'string' // 确保值是字符串类型
        );
        
        imageKeys.forEach(key => {
          this.imageInputOptions.push({
            label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
            value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
          });
        });
      }

      // 查找所有包含seed的种子输入字段
      const seedInputKeys = Object.keys(node.inputs).filter(
        key => key.includes('seed') && typeof node.inputs[key] === 'number' // 确保值是数字类型
      )
      seedInputKeys.forEach(key => {
        this.seedInputOptions.push({
          label: `${node._meta.title} - ${key} (ID: ${nodeId})`,
          value: { nodeId, inputField: key, id : `${nodeId}-${key}` },
        });
      })
    }
  },

    // 上传文件
    async uploadWorkflow() {
      if (!this.workflowFile) return;

      const formData = new FormData();
      formData.append('file', this.workflowFile);

      // 记录所选的输入位置
      const workflowData = {
        textInput: this.selectedTextInput,
        textInput2: this.selectedTextInput2,
        imageInput: this.selectedImageInput,
        imageInput2: this.selectedImageInput2,
        seedInput: this.selectedSeedInput,
        seedInput2: this.selectedSeedInput2,
        description: this.workflowDescription,
      };

      // 发送 JSON 字符串作为普通字段
      formData.append('workflow_data', JSON.stringify(workflowData));

      try {
        const response = await fetch(`/add_workflow`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) { // 检查响应状态
          const errorText = await response.text(); // 获取错误文本
          console.error("Server error:", errorText); // 输出错误信息
          throw new Error("Server error");
        }

        const data = await response.json();
        if (data.success) {
          this.workflows.push(data.file);
          this.showWorkflowUploadDialog = false;
          this.workflowFile = null;
          this.selectedTextInput = null; // 重置选中
          this.selectedImageInput = null; // 重置选中
          this.selectedTextInput2 = null; // 重置选中
          this.selectedImageInput2 = null; // 重置选中
          this.selectedSeedInput = null; // 重置选中
          this.selectedSeedInput2 = null; // 重置选中
          this.workflowDescription = ''; // 清空描述
          await this.autoSaveSettings();
          showNotification('上传成功');
        } else {
          showNotification('上传失败', 'error');
        }
      } catch (error) {
        console.error('上传失败:', error);
        showNotification('上传失败', 'error');
      }
    },

    cancelWorkflowUpload() {
      this.showWorkflowUploadDialog = false;
      this.workflowFile = null;
      this.selectedTextInput = null; // 重置选中
      this.selectedImageInput = null; // 重置选中
      this.selectedTextInput2 = null; // 重置选中
      this.selectedImageInput2 = null; // 重置选中
      this.selectedSeedInput = null; // 重置选中
      this.selectedSeedInput2 = null; // 重置选中
      this.workflowDescription = ''; // 清空描述
    }
});
