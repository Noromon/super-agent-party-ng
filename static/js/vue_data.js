const isElectron = window.electronAPI ? true : false;
// 事件监听改造
if (isElectron) {
    document.addEventListener('contextmenu', (e) => {
      // S241：已被元素级处理器 prevent 过的右键(标签条/会话行等专属菜单)直接放行——
      // 此前无条件弹 default, 第二个原生菜单把专属菜单盖掉(S240 根因)
      if (e.defaultPrevented) return;
      const imgTarget = e.target.closest('img');
      
      if (imgTarget) {
        e.preventDefault();
        window.electronAPI.showContextMenu('image', { 
          src: imgTarget.src,
          x: e.x,
          y: e.y
        });
      } else {
        window.electronAPI.showContextMenu('default');
      }
    });
  
    const HOST = "127.0.0.1"
    const PORT = window.location.port
    document.addEventListener('click', async (event) => {
      const link = event.target.closest('a[href]');
      if (!link) return;
      const href = link.getAttribute('href');
      
      try {
        const url = new URL(href);
        
        if (url.hostname === HOST && 
            url.port === PORT &&
            url.pathname.startsWith('/uploaded_files/')) {
          event.preventDefault();
          
          // 使用预加载接口处理路径
          const filename = url.pathname.split('/uploaded_files/')[1];
          const filePath = window.electronAPI.pathJoin(
            window.electronAPI.getAppPath(), 
            'uploaded_files', 
            filename
          );
          
          await window.electronAPI.openPath(filePath);
          return;
        }
        if (['http:', 'https:'].includes(url.protocol)) {
          event.preventDefault();
          await window.electronAPI.openExternal(href); // 确保调用electronAPI
          return;
        }
        
      } catch {
        event.preventDefault();
        window.location.href = href;
      }
    });
  }
  else {
    const HOST = window.location.hostname
    const PORT = window.location.port
  }
  // 判断协议
  const protocol = window.location.protocol;
  const backendURL = `${window.location.protocol}//${window.location.host}`;
let vue_data = {};
