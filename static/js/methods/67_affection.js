// 批 3 F2：自 vue_methods.js 搬移的好感度数据域（Object.assign 装配）。
Object.assign(vue_methods, {
  handleAffectionTabChange(tabName) {
    if (tabName === 'data') {
      this.fetchAffectionData();
    }
  },

  async fetchAffectionData() {
    try {
      // 请求我们刚才写的 FastAPI 路由
      const response = await fetch('/api/affection/get_data');
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      const data = await response.json();
      
      this.affectionRawData = data || {};
      
      // 将 Object 转换为 Array，供 el-table 渲染
      this.affectionDataList = Object.keys(this.affectionRawData).map(userName => {
        return {
          userName: userName,
          ...this.affectionRawData[userName]
        };
      });
      
      console.log("✅ 羁绊数据加载成功:", this.affectionDataList); // 调试日志，按 F12 可以在控制台看到
    } catch (error) {
      console.error("❌ 获取羁绊数据失败:", error);
      if (this.$message) this.$message.error("无法加载羁绊数据，请检查后端是否正常运行");
    }
  },

  // 3. 将前端的修改同步保存到后端
  async syncAffectionDataToBackend() {
    try {
      // 将 Array 转回 Object 结构 {"小包": {love: 10}}
      const newData = {};
      this.affectionDataList.forEach(item => {
        const { userName, ...dimensionsData } = item;
        newData[userName] = dimensionsData;
      });

      this.affectionRawData = newData; // 更新本地缓存

      // 使用 fetch 发送 POST 请求
      const response = await fetch('/api/affection/save_data', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(newData)
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      if (this.$message) this.$message.success("羁绊数据已同步");
    } catch (error) {
      console.error("❌ 保存羁绊数据失败:", error);
      if (this.$message) this.$message.error("羁绊数据保存失败");
    }
  },

  // 3. 打开新增/编辑对话框
  openAffectionDataDialog(row = null) {
    this.isEditingAffection = !!row; // 如果传了 row 说明是编辑
    
    if (row) {
      // 编辑：深拷贝当前行数据
      this.currentAffectionForm = JSON.parse(JSON.stringify(row));
    } else {
      // 新增：初始化表单，把所有维度默认设为 0
      const newForm = { userName: '' };
      if (this.loveSettings.dimensions) {
        this.loveSettings.dimensions.forEach(dim => {
          newForm[dim] = 0;
        });
      }
      this.currentAffectionForm = newForm;
    }
    
    this.showAffectionDataDialog = true;
  },

  // 4. 保存对话框表单
  saveAffectionData() {
    const form = this.currentAffectionForm;
    if (!form.userName) return;

    if (this.isEditingAffection) {
      // 寻找并替换
      const index = this.affectionDataList.findIndex(item => item.userName === form.userName);
      if (index !== -1) {
        this.affectionDataList.splice(index, 1, { ...form });
      }
    } else {
      // 查重：防止用户名重复
      const exists = this.affectionDataList.find(item => item.userName === form.userName);
      if (exists) {
        this.$message.warning("该用户名已存在！");
        return;
      }
      // 追加新用户
      this.affectionDataList.push({ ...form });
    }

    this.showAffectionDataDialog = false;
    this.syncAffectionDataToBackend(); // 触发网络请求同步到后端
  },

  // 5. 删除用户数据
  deleteAffectionData(userName) {
    this.$confirm(this.t('confirmDelete') || '确认删除该用户数据吗？', this.t('warning') || '警告', {
      confirmButtonText: this.t('confirm') || '确定',
      cancelButtonText: this.t('cancel') || '取消', 
      type: 'warning'
    }).then(() => {
      const index = this.affectionDataList.findIndex(item => item.userName === userName);
      if (index !== -1) {
        this.affectionDataList.splice(index, 1);
        this.syncAffectionDataToBackend(); // 触发网络请求同步到后端
      }
    }).catch(() => {});
  }
});
