// S305：config/env/窗口尺寸域自 main.js 逐字搬移（Electron 主进程模块）。
// 纯移动：函数体未动。saveWindowBounds/persistMaximized 及 rememberWindowSize
// 开关依赖主窗口引用，留 main.js 原样调用本模块导出；路径/文件语义不变。
const path = require('path')
const fs = require('fs')
const { app, screen } = require('electron')

// 获取配置文件路径
function getConfigPath() {
  return path.join(app.getPath('userData'), 'config.json');
}

// S142：主窗口尺寸记忆（userData/window-bounds.json，独立于设置文件，避免启动顺序依赖）
const WINDOW_BOUNDS_FILE = path.join(app.getPath('userData'), 'window-bounds.json')
function loadWindowBounds() {
  try { return JSON.parse(fs.readFileSync(WINDOW_BOUNDS_FILE, 'utf8')) } catch (e) { return {} }
}
function writeWindowBounds(obj) {
  try { fs.writeFileSync(WINDOW_BOUNDS_FILE, JSON.stringify(obj)) } catch (e) { console.error('save window bounds failed', e) }
}
function validBounds(b) {
  if (!b || !(b.width >= 600) || !(b.height >= 400) || !(b.x >= -32000) || !(b.y >= -32000)) return false
  return screen.getAllDisplays().some((d) => {
    const a = d.bounds
    return b.x < a.x + a.width - 60 && b.x + b.width > a.x + 60 && b.y < a.y + a.height - 60 && b.y + b.height > a.y + 60
  })
}

// 加载环境变量
function loadEnvVariables() {
  const configPath = getConfigPath();
  if (fs.existsSync(configPath)) {
    try {
      const config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
      
      // 遍历配置加载到环境变量
      for (const key in config) {
        const val = config[key];
        // ★ 同样只把基本类型加载到 env
        if (typeof val === 'string' || typeof val === 'number') {
          process.env[key] = val;
        }
      }
      return config; // ★ 返回完整配置对象给 CDP 逻辑使用
    } catch (e) {
      console.error('加载配置失败:', e);
    }
  }
  return {};
}

function saveEnvVariable(key, value) {
  const configPath = getConfigPath();
  let config = {};
  
  // 1. 读取现有文件
  try {
    if (fs.existsSync(configPath)) {
      config = JSON.parse(fs.readFileSync(configPath, 'utf8'));
    }
  } catch (e) { console.error('配置文件读取出错:', e); }

  // 2. 更新文件内容 (对象和字符串都能存)
  config[key] = value;
  fs.writeFileSync(configPath, JSON.stringify(config, null, 2));
  
  // 3. ★ 关键改进：类型检查 ★
  // 只有字符串或数字才写入 process.env，防止对象变 "[object Object]"
  if (typeof value === 'string' || typeof value === 'number') {
    process.env[key] = value;
  }
}

module.exports = { getConfigPath, loadWindowBounds, writeWindowBounds,
               validBounds, loadEnvVariables, saveEnvVariable }
