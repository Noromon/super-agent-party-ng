// 批 3 F2：自 vue_methods.js 搬移的 methods/28_media_library.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
    formatDate(date) {
      // 时间戳转日期
      return new Date(date).toLocaleString();
    },

    async deleteFile(file) {
      console.log('deleteFile:', file);
      this.textFiles = this.textFiles.filter(f => f !== file);
      await this.autoSaveSettings();
      const fileName = file.unique_filename
      try {
        // 向/delete_file发送请求
        const response = await fetch(`/delete_file`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileName: fileName })
        });
        // 处理响应
        if (response.ok) {
          console.log('File deleted successfully');
          showNotification(this.t('fileDeleted'), 'success');
        }
      } catch (error) {
        console.error('Error:', error);
        showNotification(this.t('fileDeleteFailed'), 'error');
      }
    },

    // 顶部“全选 / 取消全选”
    toggleAll(checked) {
      this.selectedFiles = checked
        ? this.textFiles.map(f => f.unique_filename)
        : [];
    },

    async batchDeleteFiles() {
      if (this.selectedFiles.length === 0) return;

      try {
        const res = await fetch('/delete_files', {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileNames: this.selectedFiles })
        });
        const data = await res.json();

        // 只要后端说“有成功”就提示成功
        if (data.success && data.successFiles?.length) {
          // 把后端返回已成功删除的文件干掉
          this.textFiles = this.textFiles.filter(
            f => !data.successFiles.includes(f.unique_filename)
          );
          this.selectedFiles = [];          // 清空选中
          showNotification(this.t('batchDeleteSuccess'), 'success');
          await this.autoSaveSettings();
        } else {
          console.log('batchDeleteFiles error:', data);
          showNotification(this.t('batchDeleteFailed'), 'error');
        }
      } catch (e) {
        console.log('batchDeleteFiles error:', e);
        showNotification(this.t('batchDeleteFailed'), 'error');
      }
    },

    // 图片全选切换
    toggleAllImages(checked) {
      this.selectedImages = checked
        ? this.imageFiles.map(i => i.unique_filename)
        : []
    },

    // 视频全选切换
    toggleAllVideos(checked) {
      this.selectedVideos = checked
        ? this.videoFiles.map(v => v.unique_filename)
        : []
    },

    // 图片批量删除
    async batchDeleteImages() {
      if(!this.selectedImages.length) return
      
      try {
        const res = await fetch('/delete_files', {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({fileNames: this.selectedImages})
        })
        
        if(res.ok) {
          // 更新前端列表
          this.imageFiles = this.imageFiles.filter(
            img => !this.selectedImages.includes(img.unique_filename)
          )
          this.selectedImages = []
          showNotification(this.t('batchDeleteSuccess'), 'success')
          await this.autoSaveSettings();
        }
      } catch(e) {
        showNotification(this.t('batchDeleteFailed'), 'error')
      }
    },

    // 视频批量删除（复用同一API）
    async batchDeleteVideos() {
      if(!this.selectedVideos.length) return
      try {
        const res = await fetch('/delete_files', {
          method: 'DELETE',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({fileNames: this.selectedVideos})
        })
        
        if(res.ok) {
          // 更新前端列表
          this.videoFiles = this.videoFiles.filter(
            img => !this.selectedVideos.includes(img.unique_filename)
          )
          this.selectedVideos = []
          showNotification(this.t('batchDeleteSuccess'), 'success')
          await this.autoSaveSettings();
        }
      } catch(e) {
        showNotification(this.t('batchDeleteFailed'), 'error')
      }
    },

    async deleteImage(img) {
      this.imageFiles = this.imageFiles.filter(i => i !== img);
      await this.autoSaveSettings();
      const fileName = img.unique_filename
      try {
        // 向/delete_file发送请求
        const response = await fetch(`/delete_file`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileName: fileName })
        });
        // 处理响应
        if (response.ok) {
          console.log('File deleted successfully');
          showNotification(this.t('fileDeleted'), 'success');
        }
      } catch (error) {
        console.error('Error:', error);
        showNotification(this.t('fileDeleteFailed'), 'error');
      }
    },

    getVendorLogo(vendor) {
      return this.vendorLogoList[vendor] || "source/providers/logo.png";
    },

    getMCPVendorLogo(vendor) {
      return this.MCPvendorLogoList[vendor] || "source/providers/logo.png";
    },

    getPromptVendorLogo(vendor) {
      return this.promptLogoList[vendor] || "source/providers/logo.png";
    },

    getCardVendorLogo(vendor) {
      return this.cardLogoList[vendor] || "source/providers/logo.png";
    },

    handleSelectVendor(vendor) {
      this.newProviderTemp.vendor = vendor;
      this.handleVendorChange(vendor);
    },

    async deleteVideo(video) {
      this.videoFiles = this.videoFiles.filter(i => i !== video);
      await this.autoSaveSettings();
      const fileName = video.unique_filename
      try {
        // 向/delete_file发送请求
        const response = await fetch(`/delete_file`, {
          method: 'DELETE',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ fileName: fileName })
        });
        // 处理响应
        if (response.ok) {
          console.log('File deleted successfully');
          showNotification(this.t('fileDeleted'), 'success');
        }
      } catch (error) {
        console.error('Error:', error);
        showNotification(this.t('fileDeleteFailed'), 'error');
      }
    }
});
