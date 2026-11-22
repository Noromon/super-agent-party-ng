// S261: guest 脚本语法自检 harness（本次事故根因：arm 脚本 try 缺 catch，eval 期才炸，
// 线上表现为 start 全线 'GUEST_VIEW_MANAGER_CALL: Missing catch or finally after try'）。
// S277: 增第二段行为断言——cdpInputWheel 永挂（原生另存为等系统模态禁用宿主窗口的真实
// 形态）时，滚动阶梯必须限时落到 guest JS 回退，而不是整条 promise 链卡死。
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

    // ===== S277 行为段：wheel 通道永挂 → 必须限时回退到 JS 滚动 =====
    let s277fail = 0;
    const ok277 = (cond, name) => {
        console.log((cond ? 'PASS ' : 'FAIL ') + name);
        if (!cond) s277fail++;
    };
    global.window.__SAP_INPUT_TMO = 60;
    let wheelCalls = 0;
    global.window.electronAPI = {
        // 永挂：正是另存为模态期间 ipcRenderer.invoke 的真实形态
        cdpInputWheel: () => { wheelCalls++; return new Promise(() => {}); },
        cdpInputClick: () => { wheelCalls++; return new Promise(() => {}); },
    };
    let jsScrolls = 0;
    const ctx277 = {
        getWebview: makeWv,
        currentTabId: 'tab-1',
        _waitLoadStop: () => Promise.resolve(true),
        _wvExec: (wv, script) => {
            CAPTURED.push(script);
            if (script.indexOf('window.__netw&&window.__netw.armed') >= 0) return Promise.resolve(true);
            if (script.indexOf('scrollBy') >= 0) jsScrolls++;
            return Promise.resolve('');
        },
    };
    ctx277._netwArmExpr = m._netwArmExpr;
    ctx277._makeScroller = m._makeScroller;
    const t0 = Date.now();
    const sc = await m._makeScroller.call(ctx277, makeWv());
    const probeMs = Date.now() - t0;
    ok277(sc.mode !== 'wheel', 'S277: 探测悬挂即弃 wheel（mode=' + sc.mode + '）');
    ok277(probeMs < 3000, 'S277: 探测限时返回（' + probeMs + 'ms < 3000ms）');
    await sc.scrollOnce();
    ok277(jsScrolls > 0, 'S277: scrollOnce 落到 JS 滚动回退（jsScrolls=' + jsScrolls + '）');
    const t1 = Date.now();
    await m.scrollAndFind.call(ctx277, 'x', 'none', 1, 200, '');
    ok277(Date.now() - t1 < 6000, 'S277: scrollAndFind 不再被弹窗卡死（' + (Date.now() - t1) + 'ms）');
    ok277(wheelCalls >= 2, 'S277: wheel 通道确有尝试（calls=' + wheelCalls + '）');
    console.log(s277fail ? 'S277-HARNESS failed=' + s277fail : 'S277-HARNESS all passed');
    process.exit((fail || s277fail) ? 1 : 0);
})().catch((e) => { console.log('HARNESS_ERR: ' + (e && e.stack || e)); process.exit(3); });
