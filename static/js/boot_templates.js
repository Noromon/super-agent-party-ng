// 批 3 F3：页面模板装载器。
// index.html 中以 <div class="tpl-anchor" data-tpl="名字"></div> 占位，
// 实际模板在 static/templates/<名字>.html。启动时全部注入完毕后才 resolve
// __templatesReady，renderer.js 在该 Promise 上挂载 Vue，保证 v-show 的
// 页面节点在 mount 前就位、DOM 顺序与内联时代一致。
(function () {
  window.__templatesReady = (async function () {
    try {
      const anchors = Array.prototype.slice.call(
        document.querySelectorAll('.tpl-anchor[data-tpl]'));
      const fetched = await Promise.all(anchors.map(async (a) => {
        const res = await fetch('templates/' + a.getAttribute('data-tpl') + '.html',
          { cache: 'no-store' });
        if (!res.ok) throw new Error('template load failed: ' + a.getAttribute('data-tpl'));
        return { a: a, html: await res.text() };
      }));
      let memoSites = 0;
      fetched.forEach(({ a, html }) => {
        memoSites += (html.match(/v-memo=/g) || []).length;
        const tpl = document.createElement('template');
        tpl.innerHTML = html.trim();
        a.replaceWith(tpl.content);
      });
      // S124: 运行版本自证——终结"加载的哪份模板"取证盲区
      console.warn('[Probe] templates ready n=' + fetched.length + ' memo-sites=' + memoSites);
    } catch (err) {
      // RA-10：装载失败不再只剩白屏+console——渲染可见错误条并保留 reject（renderer 不挂载半成品）
      console.error('[templates] 模板装载失败:', err);
      const wrap = document.createElement('div');
      wrap.setAttribute('style',
        'position:fixed;inset:0;z-index:99999;display:flex;align-items:center;' +
        'justify-content:center;background:rgba(0,0,0,0.72);color:#fff;padding:24px;');
      const box = document.createElement('div');
      box.setAttribute('style', 'max-width:460px;text-align:center;font:14px/1.7 system-ui;');
      const h = document.createElement('h3');
      h.textContent = '界面模板加载失败';
      const p = document.createElement('p');
      p.setAttribute('style', 'opacity:.85;margin:8px 0 18px;word-break:break-all;');
      p.textContent = String((err && err.message) || err);
      const btn = document.createElement('button');
      btn.textContent = '重试';
      btn.setAttribute('style', 'padding:6px 22px;font-size:14px;cursor:pointer;');
      btn.onclick = function () { location.reload(); };
      box.append(h, p, btn);
      wrap.append(box);
      document.body.appendChild(wrap);
      throw err;
    }
  })();
})();
