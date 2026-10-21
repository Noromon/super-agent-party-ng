// 批 3 F2：自 vue_methods.js 搬移的 methods/20_files_upload.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
  async browseAllFiles() {
    if (!this.isElectron) {
      // 浏览器环境
      const input = document.createElement('input')
      input.type = 'file'
      input.multiple = true
      // 合并接受的文件类型
      input.accept = ALL_ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')
      
      input.onchange = (e) => {
        const files = Array.from(e.target.files)
        // 统一验证：只要在合并后的列表中即可
        const validFiles = files.filter(file => {
          const ext = file.name.split('.').pop()?.toLowerCase();
          return ALL_ALLOWED_EXTENSIONS.includes(ext);
        })
        this.handleFiles(validFiles)
      }
      input.click()
    } else {
      // Electron 环境
      // 假设你的 electronAPI.openFileDialog 支持多选并返回路径
      const result = await window.electronAPI.openFileDialog(); 
      if (!result.canceled) {
        const files = await Promise.all(
          result.filePaths
            .filter(path => {
              const ext = path.split('.').pop()?.toLowerCase() || '';
              return ALL_ALLOWED_EXTENSIONS.includes(ext);
            })
            .map(async path => {
              const buffer = await window.electronAPI.readFile(path);
              const blob = new Blob([buffer]);
              return new File([blob], path.split(/[\\/]/).pop());
            })
        );
        this.handleFiles(files);
      }
    }
  },

    async sendFiles() {
      this.showUploadDialog = true;
      // 设置文件上传专用处理
      this.currentUploadType = 'file';
    },

    async sendImages() {
      this.showUploadDialog = true;
      // 设置图片上传专用处理
      this.currentUploadType = 'image';
    },

    browseFiles() {
      if (this.currentUploadType === 'image') {
        this.browseImages();
      } else {
        this.browseDocuments();
      }
    },

    // 专门处理图片选择
    async browseImages() {
      if (!this.isElectron) {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = true
        input.accept = ALLOWED_IMAGE_EXTENSIONS.map(ext => `.${ext}`).join(',')
        
        input.onchange = (e) => {
          const files = Array.from(e.target.files)
          const validFiles = files.filter(this.isValidImageType)
          this.handleFiles(validFiles)
        }
        input.click()
      } else {
        const result = await window.electronAPI.openImageDialog();
        if (!result.canceled) {
          // 转换Electron文件路径为File对象
          const files = await Promise.all(
            result.filePaths
              .filter(path => {
                const ext = path.split('.').pop()?.toLowerCase() || '';
                return ALLOWED_IMAGE_EXTENSIONS.includes(ext);
              })
              .map(async path => {
                // 读取文件内容并转换为File对象
                const buffer = await window.electronAPI.readFile(path);
                const blob = new Blob([buffer]);
                return new File([blob], path.split(/[\\/]/).pop());
              })
          );
          this.handleFiles(files);
        }
      }
    },

    // 文件选择处理方法
    async browseDocuments() {
      if (!this.isElectron) {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = true
        input.accept = ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')
        
        input.onchange = (e) => {
          const files = Array.from(e.target.files)
          const validFiles = files.filter(this.isValidFileType)
          this.handleFiles(validFiles)
        }
        input.click()
      } else {
        const result = await window.electronAPI.openFileDialog();
        if (!result.canceled) {
          // 转换Electron文件路径为File对象
          const files = await Promise.all(
            result.filePaths
              .filter(path => {
                const ext = path.split('.').pop()?.toLowerCase() || '';
                return ALLOWED_EXTENSIONS.includes(ext);
              })
              .map(async path => {
                // 读取文件内容并转换为File对象
                const buffer = await window.electronAPI.readFile(path);
                const blob = new Blob([buffer]);
                return new File([blob], path.split(/[\\/]/).pop());
              })
          );
          this.handleFiles(files);
        }
      }
    },

    // 文件选择处理方法
    async browseReadFiles() {
      if (!this.isElectron) {
        const input = document.createElement('input')
        input.type = 'file'
        input.multiple = true
        input.accept = ALLOWED_EXTENSIONS.map(ext => `.${ext}`).join(',')
        
        input.onchange = (e) => {
          const files = Array.from(e.target.files)
          const validFiles = files.filter(this.isValidFileType)
          this.handleReadFiles(validFiles)
        }
        input.click()
      } else {
        const result = await window.electronAPI.openFileDialog();
        if (!result.canceled) {
          // 转换Electron文件路径为File对象
          const files = await Promise.all(
            result.filePaths
              .filter(path => {
                const ext = path.split('.').pop()?.toLowerCase() || '';
                return ALLOWED_EXTENSIONS.includes(ext);
              })
              .map(async path => {
                // 读取文件内容并转换为File对象
                const buffer = await window.electronAPI.readFile(path);
                const blob = new Blob([buffer]);
                return new File([blob], path.split(/[\\/]/).pop());
              })
          );
          this.handleReadFiles(files);
        }
      }
    },

    // 文件验证方法
    isValidFileType(file) {
      if (this.currentUploadType === 'image') {
        return this.isValidImageType(file);
      }
      const ext = (file.name.split('.').pop() || '').toLowerCase()
      return ALLOWED_EXTENSIONS.includes(ext) || MIME_WHITELIST.some(mime => file.type.includes(mime))
    },

    isValidImageType(file) {
      const ext = (file.name.split('.').pop() || '').toLowerCase()
      return ALLOWED_IMAGE_EXTENSIONS.includes(ext) || IMAGE_MIME_WHITELIST.some(mime => file.type.includes(mime))
    },

  // 拖拽释放处理
  async handleInputDrop(event) {
    this.isDragging = false;
    const files = Array.from(event.dataTransfer.files);
    if (files.length > 0) {
      await this.handleFiles(files);
    }
  },

    // 统一处理文件
    async handleFiles(files) {
      // 1. 合并所有允许的后缀，用于初步过滤
      const allAllowed = [...ALLOWED_VIDEO_EXTENSIONS, ...ALLOWED_IMAGE_EXTENSIONS, ...ALLOWED_EXTENSIONS];
      
      // 2. 遍历处理每一个选中的文件
      files.forEach(file => {
        try {
          const filename = file.name || (file.path && file.path.split(/[\\/]/).pop()) || '';
          const ext = filename.split('.').pop()?.toLowerCase() || '';

          // 检查是否在允许名单内
          if (ALLOWED_IMAGE_EXTENSIONS.includes(ext)) {
            // 如果是图片，按图片逻辑添加
            this.addFiles([file], 'image');
          } else if (ALLOWED_VIDEO_EXTENSIONS.includes(ext)) {
            // 如果是文档，按文件逻辑添加
            this.addFiles([file], 'video');
          } else if (ALLOWED_EXTENSIONS.includes(ext)) {
            // 如果是文档，按文件逻辑添加
            this.addFiles([file], 'file');
          } else {
            // 不支持的类型
            console.warn(`不支持的文件类型: ${ext}`);
            // 可以选加：this.showErrorAlert('file'); 
          }
        } catch (e) {
          console.error('文件分拣错误:', e);
        }
      });
    },

    // 统一处理文件
    async handleReadFiles(files) {
      this.showFileDialog = false;
      const allowedExtensions = this.currentUploadType === 'image' ? ALLOWED_IMAGE_EXTENSIONS : ALLOWED_EXTENSIONS;

      const validFiles = files.filter(file => {
        try {
          // 安全获取文件扩展名
          const filename = file.name || (file.path && file.path.split(/[\\/]/).pop()) || '';
          const ext = filename.split('.').pop()?.toLowerCase() || '';
          return allowedExtensions.includes(ext);
        } catch (e) {
          console.error('文件处理错误:', e);
          return false;
        }
      });

      if (validFiles.length > 0) {
        const formData = new FormData();

        for (const file of validFiles) {
          formData.append('files', file, file.name);
        }

        try {
          console.log('Uploading files...');
          const response = await fetch(`/load_file`, {
            method: 'POST',
            body: formData
          });

          if (!response.ok) {
            const errorText = await response.text();
            console.error('Server responded with an error:', errorText);
            showNotification(this.t('file_upload_failed'), 'error');
            return;
          }

          const data = await response.json();
          if (data.success) {      
            // 将新的文件信息添加到 this.textFiles
            this.textFiles = [...data.textFiles,...this.textFiles];
            this.selectedFile = data.textFiles[0].unique_filename;
            this.autoSaveSettings();
            this.parseSelectedFile();
          } else {
            showNotification(this.t('file_upload_failed'), 'error');
          }
        } catch (error) {
          console.error('Error during file upload:', error);
          showNotification(this.t('file_upload_failed'), 'error');
        }
      } else {
        this.showErrorAlert(this.currentUploadType);
      }
    },

    clearLongText() {
      this.selectedFile = null;
      this.readConfig.longTextList = [];
      this.longTextListIndex = 0;
      this.readConfig.longText = '';
    },

    removeItem(index, type) {
      if (type === 'file') {
        this.files.splice(index, 1);
      } else {
        // 如果是图片，则从图片列表中删除，考虑this.files长度
        index = index - this.files.length;
        this.images.splice(index, 1);
      }
    },

    // 错误提示
    showErrorAlert(type = 'file') {
      const fileTypes = {
        file: this.t('file_type_error'),
        image: this.t('image_type_error')
      };
      showNotification(fileTypes[type], 'error');
    },

    // 拖放处理
    handleDrop(event) {
      event.preventDefault()
      const files = Array.from(event.dataTransfer.files)
        .filter(this.isValidFileType)
      this.handleFiles(files)
    },

        // 拖放处理
    handleReadDrop(event) {
      event.preventDefault()
      const files = Array.from(event.dataTransfer.files)
        .filter(this.isValidFileType)
      this.handleReadFiles(files)
    },

    // 添加文件到列表
    addFiles(files, type = 'file') {
      // 决定存入哪个展示数组 (图片和视频都进入 this.images 用于视觉预览)
      const targetArray = type === 'image' || type === 'video' ? this.images : this.files;

      const newFiles = files.map(file => {
        // ✨ 在这里进行精准类型判定
        let detectedType = type; 

        return {
          path: URL.createObjectURL(file),
          name: file.name,
          file: file,
          detectedType: detectedType // 存入具体的类型：'video', 'image' 或 'file'
        };
      });

      targetArray.push(...newFiles);
      this.showUploadDialog = false;
    }
});
