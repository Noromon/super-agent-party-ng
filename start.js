// scripts/start.js
const { spawn } = require('child_process');
const path = require('path');
const fs = require('fs');

// 设置 NODE_ENV 为 development
process.env.NODE_ENV = 'development';

// ---------- S175 加固：完整性闸门 ----------
// 源码部署若 node_modules 中 Electron 包存在但二进制残缺（下载失败）→ 立刻双语报错退出，
// 不再静默启动撞出含糊的 cmd「不是内部或外部命令」报错（新机器事故实证）。
function fileSize(p) {
  try { return fs.statSync(p).size; } catch (e) { return -1; }
}

function localElectronComplete() {
  const bin = path.join(__dirname, 'node_modules', 'electron', 'dist',
    process.platform === 'win32' ? 'electron.exe' : 'electron');
  const marker = path.join(__dirname, 'node_modules', 'electron', 'path.txt');
  // S179/S180：完整性下限 50MB（真实 electron 约 200MB）——0 字节残留与损坏小桩绝不放行
  return fileSize(bin) >= 52428800 && fileSize(marker) > 0;
}

function localElectronBinary() {
  // S180：解析 dist 内真实可执行文件（path.txt 内容，如 win32 的 electron.exe；缺失时按平台兜底）。
  // 直接 spawn 它——不经 .bin 垫片、不经 cmd 命令行包装：实测 Node 对 cmd /c 参数里的内嵌引号会
  // 转义成 \"，cmd.exe 不能还原，任何 Windows 上都会报 'not recognized'（S174-S179 启动失败真因）。
  if (!localElectronComplete()) { return null; }
  let rel = '';
  try {
    rel = fs.readFileSync(path.join(__dirname, 'node_modules', 'electron', 'path.txt'), 'utf8').trim();
  } catch (e) { rel = ''; }
  if (!rel) { rel = process.platform === 'win32' ? 'electron.exe' : 'electron'; }
  const p = path.join(__dirname, 'node_modules', 'electron', 'dist', rel);
  return fs.existsSync(p) ? p : null;
}

function localElectronPackagePresent() {
  return fs.existsSync(path.join(__dirname, 'node_modules', 'electron'));
}

function friendlyRuntimeHelp() {
  console.error('[Start] 请重新运行项目根目录的 setup_and_run.bat（Windows）/ setup_and_run.sh（macOS/Linux），并在逐一确认下重装依赖（官方源失败可确认切换镜像重试，Electron 二进制亦含镜像）。');
  console.error('[Start] Re-run setup_and_run.bat (Windows) / setup_and_run.sh (macOS/Linux) in the project root and approve the repair install when prompted (mirror retry available, covering the Electron binary download).');
}

function failFriendly(reason) {
  console.error('[Start] Electron 运行时缺失或不完整 / Electron runtime missing or incomplete: ' + reason);
  friendlyRuntimeHelp();
  process.exit(1);
}

function probeGlobal() {
  // 探测全局 electron 是否可用（打包部署形态）；探测失败视为缺失
  return new Promise((resolve) => {
    const probe = spawn(process.platform === 'win32' ? 'where.exe' : 'which', ['electron'], { stdio: 'ignore' });
    probe.on('error', () => resolve(false));
    probe.on('exit', (code) => resolve(code === 0));
  });
}

async function boot() {
  if (localElectronPackagePresent()) {
    if (!localElectronComplete()) {
      failFriendly('本地 node_modules 中 Electron 二进制残缺（dist 可执行文件或 path.txt 缺失/为空 = 下载未成功）/ local Electron binary incomplete or missing (download failed)');
      return;
    }
  } else {
    const ok = await probeGlobal();
    if (!ok) {
      failFriendly('本机未安装 Electron（本地 node_modules 无此包，PATH 亦无 electron）/ no Electron available (not in node_modules, not on PATH)');
      return;
    }
  }
  launch();
}

function launch() {
  const platform = process.platform;
  let cmd, args, options;

  const localBin = localElectronBinary();
  if (localBin) {
    // S180：本地源码部署——直接 spawn dist 内真实二进制（无 shell、无引号层）。
    cmd = localBin;
    args = ['.'];
  } else if (platform === 'win32') {
    // 打包/全局形态回落：全局 electron 命令（无内嵌引号，cmd 包装在此无碍；控制台切 UTF-8）
    cmd = 'cmd.exe';
    args = ['/c', 'chcp 65001 >nul && electron .'];
  } else {
    cmd = 'electron';
    args = ['.'];
  }

  options = {
    stdio: 'inherit',
    shell: false, // 直 spawn 可执行文件；仅全局 Windows 回落走 cmd.exe（该串不含内嵌引号）
    env: process.env,
    cwd: process.cwd(),
  };

  const child = spawn(cmd, args, options);

  child.on('error', (err) => {
    failFriendly('Electron 进程启动失败 / failed to spawn Electron: ' + (err && err.message));
  });

  child.on('exit', (code) => {
    process.exit(code);
  });
}

boot();
