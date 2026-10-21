// 批 3 F3：页面模板装载器。
// index.html 中以 <div class="tpl-anchor" data-tpl="名字"></div> 占位，
// 实际模板在 static/templates/<名字>.html。启动时全部注入完毕后才 resolve
// __templatesReady，renderer.js 在该 Promise 上挂载 Vue，保证 v-show 的
// 页面节点在 mount 前就位、DOM 顺序与内联时代一致。
(function () {
  window.__templatesReady = (async function () {
    const anchors = Array.prototype.slice.call(
      document.querySelectorAll('.tpl-anchor[data-tpl]'));
    const fetched = await Promise.all(anchors.map(async (a) => {
      const res = await fetch('templates/' + a.getAttribute('data-tpl') + '.html',
        { cache: 'no-store' });
      if (!res.ok) throw new Error('template load failed: ' + a.getAttribute('data-tpl'));
      return { a: a, html: await res.text() };
    }));
    fetched.forEach(({ a, html }) => {
      const tpl = document.createElement('template');
      tpl.innerHTML = html.trim();
      a.replaceWith(tpl.content);
    });
  })();
})();
