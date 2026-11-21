// S261: guest 脚本语法自检 harness（本次事故根因：arm 脚本 try 缺 catch，eval 期才炸，
// 线上表现为 start 全线 'GUEST_VIEW_MANAGER_CALL: Missing catch or finally after try'）。
// 用法: node guest_check_harness.js <80_webview_agent.js 路径>
// 原理: 以 stub this 驱动 networkWatch/scrollAndFind/getWebviewSnapshot，把真实拼接出的
// 每一段 guest 脚本捕获下来，逐个 new Function() 验语法——拼接 bug 从此在 CI 拦截。
'use strict';
const fs = require('fs');
const path = process.argv[2];
if (!path) { console.error('usage: node guest_check_harness.js <80_webview_agent.js>'); process.exit(2); }
const src = fs.readFileSync(path, 'utf8');
const vue_methods = {};
new Function('vue_methods', src)(vue_methods);

global.window = global.window || {};
const CAPTURED = [];
function makeWv() {
    return {
        isLoading: () => false,
        getWebContentsId: () => 42,
        addEventListener: () => {}, removeEventListener: () => {},
        executeJavaScript: (s) => { CAPTURED.push(s); return Promise.resolve(''); },
    };
}
const ctx = {
    getWebview: makeWv,
    currentTabId: 'tab-1',
    _waitLoadStop: () => Promise.resolve(true),
    _wvExec: (wv, script) => {
        CAPTURED.push(script);
        // 模拟"已挂钩"，让 read 分支把真正的收割脚本也拼出来
        if (script.indexOf('window.__netw&&window.__netw.armed') >= 0) return Promise.resolve(true);
        return Promise.resolve('');
    },
};
(async () => {
    const m = vue_methods;
    ctx._netwArmExpr = m._netwArmExpr;
    ctx._makeScroller = m._makeScroller;
    await m.networkWatch.call(ctx, 'start', '', true, -1);
    await m.networkWatch.call(ctx, 'start', '', false, -1);
    await m.networkWatch.call(ctx, 'read', 'frs/section', true, -1);
    await m.networkWatch.call(ctx, 'read', '', false, -1);
    await m.networkWatch.call(ctx, 'pull', '', false, 7);
    await m.networkWatch.call(ctx, 'start', '', true, -1, { scrolls: 2, wait_ms: 300 });
    await m.networkWatch.call(ctx, 'start', '', false, -1, null);
    await m.networkWatch.call(ctx, 'stop', '', false, -1);
    await m.scrollAndFind.call(ctx, '标题片段', 'click', 1, 200, 'data-url');
    await m.scrollAndFind.call(ctx, 'x', 'none', 1, 200, '');
    await m.collectList.call(ctx, { item: '.thread-card-wrapper', fields: { title: '.thread-title', href: 'a@href', t: 'time[datetime]@datetime' }, max_scrolls: 2, pause_ms: 200, max_items: 50 });
    await m.collectList.call(ctx, { item: 'li', fields: { text: '' }, max_scrolls: 1, pause_ms: 200, older_than: '2026-01-01', date_field: 'text' });
    await m._makeScroller.call(ctx, makeWv());
    await m.getWebviewSnapshot.call(ctx, false);
    let fail = 0;
    for (let i = 0; i < CAPTURED.length; i++) {
        const s = CAPTURED[i];
        try { new Function(s); } catch (e) {
            fail++;
            console.log('FAIL[' + i + ']: ' + e.message);
            console.log('  head: ' + JSON.stringify(String(s).slice(0, 110)));
        }
    }
    console.log('captured=' + CAPTURED.length + ' failed=' + fail);
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('HARNESS_ERR: ' + (e && e.stack || e)); process.exit(3); });
