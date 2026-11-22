// S297 行为回归：验证码域级熔断。
// 装载 80_webview_agent.js（vue_methods 打桩），驱动快照探针与交互守卫：
//   1) 探针命中 → 快照带 captcha_detected 与熔断字样；同 host 六个交互全拒
//   2) 干净快照 → captcha_cleared 自解除；交互放行（走 stub 执行通道）
//   3) 熔断仅作用于该 host，其他域照常放行
'use strict';
const fs = require('fs');

const src = fs.readFileSync(process.argv[2] || 'static/js/methods/80_webview_agent.js', 'utf8');
global.vue_methods = {};
const _run = new Function('window', src + '\n;return {_captchaFrozen, _captchaHostOf};');
const hostObj = {};
const G = _run(hostObj);
const vm = global.vue_methods;

const probeFlags = { 'tieba.baidu.com': true, 'www.baidu.com': false };
function mkWv(url) {
    return {
        _url: url,
        getURL() { return this._url; },
        src: url,
        isLoading() { return false; },
        focus() {},
    };
}
const TIEBA = 'https://tieba.baidu.com/f?kw=%E6%AF%8F%E6%AF%AB';
const CLEAN = 'https://www.baidu.com/s?wd=x';

let stubExec = null;
const ctx = Object.assign({}, vm, {
    getWebview() { return this._wv; },
    _wvExec(wv, script) { return stubExec(wv, script); },
    _humanDelay() { return Promise.resolve(); },
    _wvAct() { return Promise.resolve({ ok: true }); },
});

function snapshotProbe(hit) {
    stubExec = (wv, script) => Promise.resolve(script.indexOf('passMod') >= 0 ? hit : 'SNAP');
    return vm.getWebviewSnapshot.call(ctx);
}

function allowExec() {
    stubExec = () => Promise.resolve('OK');
}

(async () => {
    const guards = ['webviewClick', 'webviewFill', 'webviewFillForm', 'webviewDrag', 'webviewHover', 'webviewPressKey'];

    // 阶段 0：干净域交互放行
    ctx._wv = mkWv(CLEAN);
    allowExec();
    for (const g of guards) {
        const r = await vm[g].call(ctx, 'ai-1', 'x');
        if (String(r).indexOf('熔断') >= 0) throw new Error('S297-stage0 reject on clean host: ' + g);
    }

    // 阶段 1：探针命中 → 快照提示 + 六交互熔断
    ctx._wv = mkWv(TIEBA);
    let snap = await snapshotProbe(true);
    if (snap.indexOf('captcha_detected=true') < 0) throw new Error('S297-stage1 missing captcha_detected');
    if (snap.indexOf('已熔断') < 0) throw new Error('S297-stage1 missing freeze note');
    if (!G._captchaFrozen.has('tieba.baidu.com')) throw new Error('S297-stage1 host not frozen');
    for (const g of guards) {
        const r = String(await vm[g].call(ctx, 'ai-1', 'x'));
        if (r.indexOf('captcha 域级熔断') < 0) throw new Error('S297-stage1 not refused: ' + g + ' -> ' + r.slice(0, 40));
        if (r.indexOf('手动完成验证') < 0) throw new Error('S297-stage1 refusal lacks user guidance: ' + g);
    }

    // 阶段 2：其他域不受影响
    ctx._wv = mkWv(CLEAN);
    allowExec();
    for (const g of guards) {
        const r = await vm[g].call(ctx, 'ai-1', 'x');
        if (String(r).indexOf('熔断') >= 0) throw new Error('S297-stage2 collateral freeze on other host: ' + g);
    }

    // 阶段 3：干净快照自解除；交互恢复放行
    ctx._wv = mkWv(TIEBA);
    snap = await snapshotProbe(false);
    if (snap.indexOf('captcha_cleared=true') < 0) throw new Error('S297-stage3 missing cleared note');
    if (G._captchaFrozen.has('tieba.baidu.com')) throw new Error('S297-stage3 still frozen');
    allowExec();
    const r = String(await vm.webviewClick.call(ctx, 'ai-1'));
    if (r.indexOf('熔断') >= 0) throw new Error('S297-stage3 click still refused: ' + r.slice(0, 40));

    // 阶段 4：再次命中 → 重新熔断（过关后复挂不做特赦）
    snap = await snapshotProbe(true);
    if (snap.indexOf('captcha_detected=true') < 0) throw new Error('S297-stage4 re-freeze note lost');
    ctx._wv = mkWv(TIEBA);
    const r2 = String(await vm.webviewFill.call(ctx, 'ai-1', 'x'));
    if (r2.indexOf('captcha 域级熔断') < 0) throw new Error('S297-stage4 re-freeze not enforced');

    console.log('S297-HARNESS all passed');
})().catch((e) => { console.error(e.message); process.exit(1); });
