// 批 3 F2：自 vue_methods.js 搬移的 methods/75_driver_guide.js 域（Object.assign 装配，
// 加载顺序在宿主之后、renderer 之前）。方法体互调仍走 this。
Object.assign(vue_methods, {
isTargetPlatform(behavior, platformKey) {
  // 1. 如果 behavior 本身不存在
  if (!behavior) return false;

  // 2. 检查新字段 platforms (数组)
  // 必须先判断 Array.isArray 且长度 > 0，才能读取 [0]
  if (behavior.platforms && Array.isArray(behavior.platforms) && behavior.platforms.length > 0) {
    if (behavior.platforms.includes('all')) return true;
    return behavior.platforms.includes(platformKey);
  }

  // 3. 兼容老数据：检查旧字段 platform (字符串)
  if (behavior.platform && typeof behavior.platform === 'string') {
    return behavior.platform === 'all' || behavior.platform === platformKey;
  }

  // 4. 兜底逻辑
  return platformKey === 'chat';
},

    startDriverGuide() {
      const KEY = 'driver_guide_shown';
      if (localStorage.getItem(KEY)) return;
      localStorage.setItem(KEY, '1');

      const driver = window.driver.js.driver;

      const d = driver({
        allowClose: true,
        disableActiveInteraction: false,
        showProgress: true,
        nextBtnText: this.t('next'),
        prevBtnText: this.t('prev'),
        doneBtnText: this.t('done'),
        steps: [
          {
            element: '#driver-guide-btn',
            popover: {
              title: this.t('guide.driver-guide-btn'),
              description: this.t('guide.driver-guide-btn-notice'),
              side: 'right',
              align: 'start',
            },
          },
          {
            element: '#model-config',
            popover: {
              title: this.t('guide.model-config'),
              description: this.t('guide.model-config-notice'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: async () => {
                await this.handleSelect('model-config');
                // 手动触发下一步导航
                d.moveNext();
              }
            },
          },
          {
            element: '#add-provider-card',
            popover: {
              title: this.t('guide.add-provider-card'),
              description: this.t('guide.add-provider-card-notice'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: () => {
                this.showAddDialog = true;
                setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
              }
            }
          },
          {
            element: '#show-Add-Dialog',
            popover: {
              title: this.t('guide.show-Add-Dialog'),
              description: this.t('guide.show-Add-Dialog-notice'),
              side: 'top',
              // 添加 onNextClick 处理逻辑
              onNextClick: async () => {
                // 1. 判断是否已选择供应商 (假设 newProviderTemp.vendor 为空即未选)
                if (!this.newProviderTemp.vendor) {
                  // 2. 确保供应商列表至少有3个，防止报错
                  if (this.vendorOptions && this.vendorOptions.length >= 3) {
                    // 取出第三个供应商的值 (数组索引从0开始，所以是2)
                    const thirdVendorValue = this.vendorOptions[2].value;
                    
                    // 调用你的选择方法，或者直接赋值
                    // this.newProviderTemp.vendor = thirdVendorValue; 
                    this.handleSelectVendor(thirdVendorValue);
                    
                    // 3. 等待 Vue 更新 DOM (这一步很重要，因为下一步要高亮"确认"按钮，
                    // 需要确保按钮的 disable 状态已被移除)
                    await this.$nextTick(); 
                  }
                }
                
                // 4. 手动触发下一步
                d.moveNext();
              }
            }
          },
          {
            element: '#confirm-Add-Provider-Button',
            popover: {
              title: this.t('guide.confirm-Add-Provider-Button'),
              side: 'right',
              // 使用 onNextClick 替代 onNext
              onNextClick: async () => {
                this.confirmAddProvider();
                // 手动触发下一步导航
                d.moveNext();
              }
            }
          },
          {
            element: '#get-API-key',
            popover: {
              title: this.t('guide.get-API-key'),
              description: this.t('guide.get-API-key-notice'),
              side: 'right',
              onPrevClick: () => {
                this.showAddDialog = true;
                setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
              },
            }
          },
          {
            element: '#input-api-Key',
            popover: {
              title: this.t('guide.input-api-Key'),
              description: this.t('guide.input-api-Key-notice'),
              side: 'right',
            }
          },
          {
            element: '#get-Models-List',
            popover: {
              title: this.t('guide.get-Models-List'),
              description: this.t('guide.get-Models-List-notice'),
              side: 'right',
            }
          },
          {
            element: '#model-Id',
            popover: {
              title: this.t('guide.model-Id'),
              description: this.t('guide.model-Id-notice'),
              side: 'right',
            }
          },
        ]
      });

      // 监听高亮元素点击
      const checkClick = (e) => {
        if (e.target.closest('#model-config')) {
          d.moveNext();
        }
        if (e.target.closest('#add-provider-card')) {
          d.moveNext();
        }
        if (e.target.closest('#confirm-Add-Provider-Button')) {
          d.moveNext();
        }
        if (e.target.closest('#get-API-key')) {
          d.moveNext();
        }
        if (e.target.closest('#get-Models-List')) {
          d.moveNext();
        }
        if (e.target.closest('#vendor-Option')) {
          setTimeout(() => d.moveNext(), 100); // 手动触发下一步导航
        }
      };
      document.addEventListener('click', checkClick);

      // 清理监听
      d.onDestroyed = () => document.removeEventListener('click', checkClick);

      setTimeout(() => d.drive(), 300);
    },

  // 手动重开引导（可绑定到按钮）
  restartDriverGuide() {
    localStorage.removeItem('driver_guide_shown');
    this.startDriverGuide();
  },

  showToolInfo(tool) {
    this.toolForShowInfo = tool;
    this.showToolInfoDialog = true;
  }
});
