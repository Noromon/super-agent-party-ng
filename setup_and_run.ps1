# ============================================================
# Super Agent Party - source deployment bootstrap (S171)
# 源码部署引导脚本（Windows）。Source-code bootstrap: installs ONLY what is
# missing, and ONLY after you answer Y to an explicit prompt. Idempotent and
# re-runnable; existing components are skipped.
#
# What it may do (each step asks first):
#   1. Install Python 3.12 / Node.js LTS via winget, or point you to official
#      installers (python.org / nodejs.org) when winget is unavailable.
#   2. Create .venv inside this project folder and install dependencies from
#      uv.lock (reproducible, official PyPI by default).
#   3. Install project Node dependencies from package-lock.json (npm ci).
#   4. Start the app via 'node start.js'.
# Mirrors (Tsinghua PyPI / npmmirror) are OFF by default and only used after
# you confirm the switch. Nothing outside this folder and the runtime install
# locations you approved is ever touched. No silent elevation.
# ============================================================
#Requires -Version 5.1

# S174：环境完全就绪时不再逐项询问——默认检测就绪即直接启动；传 -Full 可强制完整检查。
param([switch]$Full)

$ErrorActionPreference = 'Stop'
$PROJECT = $PSScriptRoot
if (-not $PROJECT) { $PROJECT = Split-Path -Parent $MyInvocation.MyCommand.Path }
Set-Location $PROJECT

# S180：控制台切 UTF-8 代码页（尽力而为，仅影响本窗口；启动已改为直 spawn，不再依赖 cmd 包装切码）
try { & chcp.com 65001 > $null 2>&1 } catch {}

function Say([string]$m) { Write-Host "[Setup] $m" }
function Ask([string]$q) {
  Write-Host ""
  Write-Host $q
  $a = Read-Host '继续吗？Proceed? (Y=Yes / N=No)'
  return ($a.Trim().ToLower() -in @('y', 'yes', '是', '好', 'ok'))
}

function Test-Command([string]$name) {
  return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-ElectronIntact {
  # S175：Electron 完整性判定（只读）。S179：二进制必须有体积下限——真实 win32 electron.exe 约 200MB，
  # 0 字节残留或损坏小桩绝不允许通过（官方 install.js 的"已安装"判定只看存在与否，正是静默跳过的元凶）。
  $bin = Get-Item (Join-Path $PROJECT 'node_modules\electron\dist\electron.exe') -ErrorAction SilentlyContinue
  if (-not $bin -or $bin.Length -lt 52428800) { return $false }
  $pt = Get-Item (Join-Path $PROJECT 'node_modules\electron\path.txt') -ErrorAction SilentlyContinue
  if (-not $pt -or $pt.Length -le 0) { return $false }
  return $true
}

function Get-ElectronVersion {
  try { return (Get-Content (Join-Path $PROJECT 'node_modules\electron\package.json') -Raw | ConvertFrom-Json).version } catch { return '' }
}

function Show-ElectronEvidence {
  # S179：不再盲猜——把判定的现场事实全部打印出来（目录清单/大小/path.txt 内容）。
  Say '现场证据 / on-site evidence:'
  $d = Join-Path $PROJECT 'node_modules\electron\dist'
  if (Test-Path $d) {
    $items = @(Get-ChildItem $d -Force -ErrorAction SilentlyContinue)
    if ($items.Count -gt 30) {
      foreach ($nm in @('electron.exe', 'version')) {
        $it = $items | Where-Object { $_.Name -eq $nm } | Select-Object -First 1
        if ($it) { Say ("  dist\{0} = {1} bytes" -f $nm, $it.Length) } else { Say "  dist\$nm 缺失 / missing" }
      }
      Say ("  (dist 共 {0} 项，仅列关键文件 / {0} entries, key files only)" -f $items.Count)
    } else {
      $items | ForEach-Object { Say ("  dist\{0} = {1} bytes" -f $_.Name, $_.Length) }
    }
  } else { Say '  dist\ 不存在 / dist\ does not exist' }
  $pt = Join-Path $PROJECT 'node_modules\electron\path.txt'
  if (Test-Path $pt) { Say ("  path.txt = {0} bytes [{1}]" -f (Get-Item $pt).Length, (Get-Content $pt -Raw -ErrorAction SilentlyContinue)) } else { Say '  path.txt 不存在 / path.txt does not exist' }
}

function Get-PsNativeElectronFallback {
  # S179：PowerShell 原生兜底——直接下载 Electron 官方运行时压缩包，SHASUMS256 强校验后解压就位。
  # 完全不经 node/npm/@electron/get 与本地下载缓存：node 侧下载路径被环境破坏的机器上此路通常仍可用。
  if (-not (Ask '官方脚本仍未产出完整二进制。是否让本脚本用 PowerShell 直接从官方镜像下载 Electron 运行时压缩包并解压就位（SHASUMS256 强校验，校验不过拒绝解包；全程不经 node/npm）？Download the Electron runtime archive directly via PowerShell (verified against the official SHASUMS256, unpack refused on mismatch; no node/npm involved)?')) { return }
  $ver = Get-ElectronVersion
  if (-not $ver) { Say '无法读取 electron 版本（node_modules\electron\package.json 缺失？请先完成上一步安装）。/ Cannot read electron version; complete the dependency install step first.'; return }
  $fn = "electron-v$ver-win32-x64.zip"
  $zipUrls = @("https://npmmirror.com/mirrors/electron/v$ver/$fn", "https://github.com/electron/electron/releases/download/v$ver/$fn")
  $sumUrls = @("https://npmmirror.com/mirrors/electron/v$ver/SHASUMS256.txt", "https://github.com/electron/electron/releases/download/v$ver/SHASUMS256.txt")
  $want = ''
  foreach ($su in $sumUrls) {
    try {
      $txt = (Invoke-WebRequest -Uri $su -UseBasicParsing -TimeoutSec 60).Content
      foreach ($line in ($txt -split "`n")) {
        if ($line -like "*$fn*") { $want = ($line.Trim() -split '\s+')[0]; Say "SHASUMS256 已取得 / obtained from: $su"; break }
      }
    } catch { Say "SHASUMS 获取失败 / SHASUMS fetch failed: $su : $($_.Exception.Message)" }
    if ($want) { break }
  }
  if (-not $want) { Say '无法获得官方 SHA256 校验值，拒绝安装未校验二进制。/ Cannot obtain the official SHA256; refusing to install an unverified binary.'; return }
  Say "期望 SHA256 / expected: $want"
  $tmp = Join-Path $env:TEMP $fn
  $dist = Join-Path $PROJECT 'node_modules\electron\dist'
  foreach ($u in $zipUrls) {
    try {
      Say "下载中 / downloading: $u"
      Invoke-WebRequest -Uri $u -OutFile $tmp -UseBasicParsing -TimeoutSec 1800
      $have = (Get-FileHash -Path $tmp -Algorithm SHA256).Hash
      Say "实际 SHA256 / actual: $have ($((Get-Item $tmp).Length) bytes)"
      if ($have -ne $want) { Say 'SHA256 不匹配，弃用该来源换下一个。/ SHA256 mismatch; discarding this source and trying the next.'; continue }
      Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
      New-Item -ItemType Directory -Force -Path $dist | Out-Null
      Expand-Archive -Path $tmp -DestinationPath $dist -Force
      [System.IO.File]::WriteAllText((Join-Path $PROJECT 'node_modules\electron\path.txt'), 'electron.exe')
      Say '校验通过，已解包就位 / verified and unpacked into dist.'
      break
    } catch { Say "下载/解包失败 / download or unpack failed: $u : $($_.Exception.Message)" }
  }
  Remove-Item -Force $tmp -ErrorAction SilentlyContinue
}

function Test-EnvironmentReady {
  # S174：就绪判定（只读）——项目内 .venv 已建且依赖可导入且 Electron 已就位
  # S175：就绪判定必须验证 Electron 二进制与 path.txt 完整（缺一即未就绪，进引导修复路径）
  $venvPython = Join-Path $PROJECT '.venv\Scripts\python.exe'
  if (-not (Test-Path $venvPython)) { return $false }
  if (-not (Test-Path (Join-Path $PROJECT 'node_modules\electron'))) { return $false }
  if (-not (Test-ElectronIntact)) { return $false }
  try {
    & $venvPython -c 'import fastapi' 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch {
    return $false
  }
}

function Test-Python312 {
  if (Test-Command 'py') {
    try { $v = & py -3.12 --version 2>$null; if ($LASTEXITCODE -eq 0 -and "$v" -match '3\.12\.') { return $true } } catch {}
  }
  foreach ($c in @('python3.12', 'python3', 'python')) {
    if (-not (Test-Command $c)) { continue }
    try { $v = & $c --version 2>$null; if ($LASTEXITCODE -eq 0 -and "$v" -match '3\.12\.') { return $true } } catch {}
  }
  return $false
}

function Get-NodeMajorVersion {
  if (-not (Test-Command 'node')) { return 0 }
  try {
    $v = & node --version 2>$null
    if ($LASTEXITCODE -eq 0 -and "$v" -match 'v(\d+)\.') { return [int]$Matches[1] }
  } catch {}
  return 0
}

function Install-WingetPackage([string]$id, [string]$label) {
  if (-not (Test-Command 'winget')) {
    Say "winget 不可用 / winget unavailable. Install '$label' manually from the official site, then re-run this script."
    Write-Host '  Python: https://www.python.org/downloads/'
    Write-Host '  Node.js: https://nodejs.org/zh-cn/download'
    return $false
  }
  if (-not (Ask "将通过 winget 安装 $label（官方源）。Install $label from winget (official source)?")) { return $false }
  try {
    & winget install --id $id -e --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { Say "winget 安装 $label 失败 / install failed (exit $LASTEXITCODE)。" ; return $false }
    Say "$label 安装完成 / installed."
    return $true
  } catch {
    Say "winget 安装 $label 出错 / install error: $_"
    return $false
  }
}

# ---------- Step 0: ready fast path (S174) / 就绪即直接启动，不再询问 ----------
if (-not $Full -and (Test-EnvironmentReady)) {
  Say '环境已完全就绪：跳过全部确认，直接启动（如需完整检查请加 -Full）。/ Everything already installed; launching now with no prompts (add -Full to re-check).'
  & node (Join-Path $PROJECT 'start.js')
  exit $LASTEXITCODE
}

Say '环境尚未就绪（或已指定 -Full 强制检查）：进入引导安装。本脚本由你主动运行即代表授权开始；每个安装动作仍会逐一询问。'
Say 'Environment is not fully ready (or -Full was requested): guided setup follows. Every install action is still confirmed one by one.'

# ---------- Step 1: runtimes ----------
if (-not (Test-Python312)) {
  Say '未检测到 Python 3.12（本项目要求 >=3.12,<3.13）。/ Python 3.12 is required and was not found.'
  Install-WingetPackage 'Python.Python.3.12' 'Python 3.12 (Python.Python.3.12)' | Out-Null
  if (-not (Test-Python312)) {
    Say '仍未找到 Python 3.12。请从上方官方地址安装后重新运行本脚本。/ Still missing - install it from python.org, then re-run.'
    exit 1
  }
}

$nodeMajor = Get-NodeMajorVersion
if ($nodeMajor -lt 18) {
  Say "未检测到可用的 Node.js LTS（需 v18+，建议 v20/v22 LTS）。/ Node.js LTS (v18+) is required (found: $nodeMajor)."
  Install-WingetPackage 'OpenJS.NodeJS.LTS' 'Node.js LTS (OpenJS.NodeJS.LTS)' | Out-Null
  $nodeMajor = Get-NodeMajorVersion
  if ($nodeMajor -lt 18) {
    Say '仍未找到可用的 Node.js。请从 nodejs.org 安装 LTS 后重新运行本脚本。/ Still missing - install Node LTS from nodejs.org, then re-run.'
    exit 1
  }
}
Say "运行时就绪 / Runtimes present: Node v$nodeMajor."

# ---------- Step 2: create local virtual environment ----------
$venvPy = Join-Path $PROJECT '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPy)) {
  if (-not (Ask '将在项目目录内创建 Python 虚拟环境 .venv（仅写入本目录）。Create .venv inside this project folder?')) { exit 1 }
  if (Test-Command 'py') { & py -3.12 -m venv (Join-Path $PROJECT '.venv') } else { & python -m venv (Join-Path $PROJECT '.venv') }
  if (-not (Test-Path $venvPy)) { Say '虚拟环境创建失败 / Failed to create .venv.'; exit 1 }
  Say '虚拟环境已创建 / .venv created.'
} else {
  # S177：校验 .venv 确为 Python 3.12（半环境残留 3.10 等旧环境会静默带病运行）
  $venvVerOk = $false
  try {
    & $venvPy -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' 2>$null
    $venvVerOk = ($LASTEXITCODE -eq 0)
  } catch { $venvVerOk = $false }
  if ($venvVerOk) {
    Say '检测到 .venv（Python 3.12 校验通过），跳过创建 / .venv verified (Python 3.12), skipping creation.'
  } else {
    Say '检测到 .venv 但其中并非 Python 3.12（本项目硬性要求 >=3.12,<3.13）——需删除重建。/ .venv exists but is NOT Python 3.12 (project requires >=3.12,<3.13); it must be recreated.'
    if (Ask '确认删除现有 .venv 并用 Python 3.12 重建？（仅删除项目目录内的 .venv）Delete the existing .venv and recreate it with Python 3.12 (removes only .venv inside this project)?') {
      Remove-Item -Recurse -Force (Join-Path $PROJECT '.venv')
      if (Test-Command 'py') { & py -3.12 -m venv (Join-Path $PROJECT '.venv') } else { & python -m venv (Join-Path $PROJECT '.venv') }
      if (-not (Test-Path $venvPy)) { Say '虚拟环境重建失败 / Failed to recreate .venv.'; exit 1 }
      Say '虚拟环境已用 Python 3.12 重建 / .venv recreated with Python 3.12.'
    } else {
      Say '未同意重建 .venv，无法保证 Python 3.12 环境，终止。/ Recreation declined; a guaranteed Python 3.12 environment is impossible, aborting.'
      exit 1
    }
  }
}

# ---------- Step 3: reproducible dependency install (uv.lock) ----------
$depsInstalled = $false
if (-not (Ask '将安装 uv 并按 uv.lock 执行可复现依赖安装（默认官方 PyPI；uv 可在确认后经校验自动获取官方 CPython）。Install uv and run "uv sync --frozen" (official PyPI)?')) { exit 1 }
try {
  & python -m pip install --disable-pip-version-check uv
  if ($LASTEXITCODE -ne 0) { throw 'pip install uv failed' }
  Say 'uv 已安装，开始 uv sync --frozen / uv installed, syncing locked dependencies.'
} catch {
  Say 'uv 安装失败（官方源）。/ Installing uv from official PyPI failed.'
  if (Ask '是否切换清华大学 PyPI 镜像重试 uv 安装？Retry uv installation via the Tsinghua PyPI mirror?') {
    try {
      & python -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple uv
      if ($LASTEXITCODE -ne 0) { throw 'mirror install failed' }
      $depsInstalled = $true
      Say '镜像安装 uv 成功，开始 uv sync --frozen / uv installed via mirror, syncing locked dependencies.'
    } catch { Say '镜像安装 uv 仍失败 / uv install via mirror also failed.' }
  }
}

if (Test-Command 'uv') {
  try {
    & uv sync --frozen
    if ($LASTEXITCODE -eq 0) { $depsInstalled = $true; Say '依赖安装完成（uv.lock 可复现）。/ Dependencies installed reproducibly from uv.lock.' }
  } catch { Say "uv sync 失败 / uv sync failed: $_" }
}

if (-not $depsInstalled) {
  Write-Host ''
  Write-Host '[Setup] 警告 / WARNING: 锁定安装失败，唯一兜底是非锁定 pip 安装（版本由解析器现场决定，不再是可复现清单）。'
  Write-Host '        Locked install failed. The only fallback is a NON-reproducible "pip install -e .".'
  if (-not (Ask '确认改用非锁定 pip 安装吗？Proceed with the non-reproducible pip fallback?')) { exit 1 }
  & python -m pip install --disable-pip-version-check -e (Join-Path $PROJECT '.')
  if ($LASTEXITCODE -ne 0) {
    if (Ask '官方源失败，切换清华 PyPI 镜像重试兜底安装？Retry the fallback via the Tsinghua PyPI mirror?') {
      & python -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -e (Join-Path $PROJECT '.')
      if ($LASTEXITCODE -ne 0) { Say '兜底安装仍失败 / fallback install still failed.'; exit 1 }
    } else { exit 1 }
  }
  Say '兜底安装完成（注意：非可复现清单）。/ Fallback installed (NOT a reproducible manifest).'
}

# ---------- Step 4: Node dependencies (Electron etc.) ----------
# S175：包目录存在但二进制/path.txt 残缺 = 半残安装（新机器事故实证）——绝不跳过，必须经确认重装
$pkgPresent = Test-Path (Join-Path $PROJECT 'node_modules\electron')
if ($pkgPresent -and (Test-ElectronIntact)) {
  Say 'Node 依赖完整，跳过安装 / Node dependencies complete; skipping install.'
} else {
  if ($pkgPresent) {
    Say '检测到 Node 依赖包存在但 Electron 二进制残缺（dist\electron.exe 或 path.txt 缺失/为空），需重装修复。/ Packages present but the Electron binary is incomplete; a repair install is required.'
  }
  # S176→S178：仍先查 install-scripts 放行闸门（只读），但仅供参考——事故实证：有机器 npm 即便 approve
  # 放行后仍静默跳过生命周期脚本且谎报成功（Proxifier 全程零网络）。Electron 二进制产出不再依赖 npm
  # 生命周期脚本（下一步直跑官方 install.js）；放行只影响 esbuild/@serialport 原生产出，故降为可选。
  Say '先检查 npm 安装脚本放行闸门状态（只读，仅供参考）/ Checking the npm install-scripts gate (read-only, informational)...'
  & npm install-scripts ls
  if (Ask '上方若有未放行包，可经官方命令 npm install-scripts approve 放行 esbuild/@serialport 等原生组件（Electron 不依赖此步：二进制由下一步官方 install.js 直跑产出）。是否放行？/ If packages above await approval, the official npm install-scripts approve can clear esbuild/@serialport natives (Electron does NOT depend on this step - its binary is produced by the official install.js in the next step). Approve now?') {
    foreach ($pkg in @('electron', 'esbuild', '@serialport/bindings-cpp')) {
      & npm install-scripts approve $pkg
      if ($LASTEXITCODE -ne 0) { Say "npm install-scripts approve $pkg 失败 / approval failed (exit $LASTEXITCODE)。" }
    }
  } else {
    Say '已跳过放行：不影响 Electron 二进制产出（官方 install.js 直跑）；esbuild/@serialport 原生组件可能残缺，相应功能降级。/ Approval skipped: Electron binary is still produced via the official install.js; esbuild/@serialport natives may stay incomplete (those features degrade).'
  }
  # S177：安装与产出**必须分离**——新版 npm 默认 allowScripts 白名单拒绝，npm ci 即便脚本已放行也可能静默跳过
  # postinstall（实测：ci"成功"却抹掉 rebuild 已产出的二进制）。故 ci 显式 --ignore-scripts 只做确定性全量安装，
  # Electron 二进制唯一由随后的官方 install.js 直跑产出（S178：绕开 npm 脚本机制，要么产出、要么见真错）。
  if (-not (Ask '将按 package-lock.json 安装/重装 Node 依赖（--ignore-scripts 确定性安装，二进制由下一步显式生成）。Install Node dependencies with npm ci --ignore-scripts (deterministic; binaries produced in the next step)?')) { exit 1 }
  & npm ci --no-audit --no-fund --ignore-scripts
  if ($LASTEXITCODE -ne 0) {
    Say 'npm ci 失败（官方源）。/ npm ci failed against official sources.'
    if (Ask '是否经确认改用 npmmirror 镜像（npm registry）重试？Switch to the npmmirror registry and retry after your confirmation?') {
      & npm ci --no-audit --no-fund --ignore-scripts --registry=https://registry.npmmirror.com
      if ($LASTEXITCODE -ne 0) { Say '镜像安装 Node 依赖仍失败 / Node dependency install via mirror also failed.'; exit 1 }
    } else { exit 1 }
  }
  # S179：产出步（证据驱动，不再盲猜）。故障机实证：闸门清白、相关 Env 全空、文件 SHA256 与官方逐字节
  # 一致、node 与网络皆正常，官方 install.js 却瞬间静默退 0 零流量——唯一可能的静默路径是 isInstalled()
  # 误判"已安装"（判定只看文件存在、不看大小与内容真伪：0 字节 electron.exe 或损坏桩也过关），或本地
  # 下载缓存为损坏/空 zip（cache 命中 → 零网络"成功"）。
  # 因此：打印现场 → 清理 0 字节残留 → force_no_cache 绕缓存直跑官方脚本（打印退出码）→ 镜像直跑重试 →
  # 仍败则 PowerShell 原生下载官方 zip、SHASUMS256 强校验、Expand-Archive 解包就位（完全不经 node）→ 三因如实。
  Show-ElectronEvidence
  $ebBin = Join-Path $PROJECT 'node_modules\electron\dist\electron.exe'
  $ebPt = Join-Path $PROJECT 'node_modules\electron\path.txt'
  if (((Test-Path $ebBin) -and (Get-Item $ebBin).Length -le 0) -or ((Test-Path $ebPt) -and (Get-Item $ebPt).Length -le 0)) {
    Say '检测到 0 字节残留：官方 install.js 判定"已安装"时只看文件存在（不看大小），会静默跳过并退 0——先删除残留再重产。/ Zero-byte residue detected: the official install.js only checks file existence when deciding it is already installed and exits silently; removing the residue before re-production.'
    Remove-Item -Recurse -Force (Join-Path $PROJECT 'node_modules\electron\dist') -ErrorAction SilentlyContinue
    Remove-Item -Force $ebPt -ErrorAction SilentlyContinue
  }
  $electronBuildOk = $true
  if (-not (Test-ElectronIntact)) {
    if (-not (Ask '将直接执行 Electron 官方安装脚本 node_modules\electron\install.js 下载并解包运行时二进制（将设 force_no_cache=true 绕开本地下载缓存以防缓存投毒；失败可确认切 npmmirror 镜像，另有 PowerShell 原生下载兜底做 SHA256 强校验解包）。Run the official Electron install script (with force_no_cache to bypass the local download cache; mirror retry and a PowerShell-native verified fallback follow on failure)?')) { exit 1 }
    $env:force_no_cache = 'true'
    & node (Join-Path $PROJECT 'node_modules\electron\install.js')
    Say "install.js 退出码 / exit code: $LASTEXITCODE"
    $electronBuildOk = ($LASTEXITCODE -eq 0)
    if (-not (Test-ElectronIntact)) {
      if (Ask 'Electron 二进制仍未产出（官方下载源不可达？）。是否设 ELECTRON_MIRROR 走 npmmirror 二进制镜像再次直跑？Electron binary still missing (official source unreachable?). Set ELECTRON_MIRROR to the npmmirror binary mirror and re-run install.js directly?') {
        $env:ELECTRON_MIRROR = 'https://npmmirror.com/mirrors/electron/'
        & node (Join-Path $PROJECT 'node_modules\electron\install.js')
        Say "install.js 退出码 / exit code: $LASTEXITCODE"
        $electronBuildOk = ($LASTEXITCODE -eq 0)
      }
    }
    Remove-Item Env:\force_no_cache -ErrorAction SilentlyContinue
  }
  if (-not (Test-ElectronIntact)) {
    Get-PsNativeElectronFallback
  }
  if (-not (Test-ElectronIntact)) {
    Show-ElectronEvidence
    Say 'Electron 二进制仍未产出（本脚本已直跑官方 install.js 绕开缓存、并尝试 PowerShell 原生校验下载兜底，不依赖 npm 生命周期脚本）。原因只有三类：① 官方与 npmmirror 下载均不可达/失败（上方已打印每次尝试的 URL 与错误——检查网络/代理/防火墙，给 PowerShell 与 node.exe 放行直连）；② 本地 0 字节残留或损坏缓存（本脚本已尝试清理与绕开，现场清单已打印于上方——删除 %LOCALAPPDATA%\electron\Cache 后重跑本脚本）；③ 离线修复：从同版本（见 package-lock.json）完好安装拷贝 node_modules\electron\dist 整目录与 path.txt 到本项目相同位置，或直接改用自带运行时的官方打包版。/ Electron binary still missing (official install.js was run directly with cache bypass, and a PowerShell-native verified download was attempted; independent of npm lifecycle scripts). Three causes only: (1) both official and npmmirror downloads unreachable/failed (URLs and errors printed above; allow PowerShell and node.exe direct through network/proxy/firewall); (2) local zero-byte residue or poisoned cache (cleaned and bypassed by this script; evidence printed above; delete %LOCALAPPDATA%\electron\Cache and re-run); (3) offline repair: copy node_modules\electron\dist and path.txt from a healthy same-version install (see package-lock.json), or use the official packaged release with bundled runtimes.'
    exit 1
  }
  if (-not $electronBuildOk) {
    Say 'Electron 安装脚本退出码非零，但完整性复验通过——按可用继续；若启动异常请重跑本脚本。/ install.js exited non-zero yet the integrity re-check passed; proceeding. Re-run this script if the app misbehaves.'
  }
  Say 'esbuild/@serialport 原生组件不在本路径强修：如残缺仅串口等功能降级，不影响应用启动。/ esbuild/@serialport natives are not force-repaired here; if incomplete those features degrade without blocking launch.'
  Say 'Node 依赖安装完成且 Electron 二进制完整 / Node dependencies installed; Electron binary verified complete.'
}

# ---------- Step 5: run the application ----------
if (-not (Test-ElectronIntact)) {
  Say 'Electron 二进制不完整，暂不启动：请重新运行本脚本——确认安装（ci --ignore-scripts）后直跑官方 install.js 产出二进制（下载失败可切 npmmirror 镜像；仍不行则离线拷贝同版本 dist+path.txt，或改用官方打包版）。/ Electron binary incomplete; not launching. Re-run this script: after the confirmed ci --ignore-scripts install, the binary is produced by running the official install.js directly (npmmirror mirror retry available; if that still fails, offline-copy dist+path.txt from a healthy same-version install, or use the official packaged release).'
  exit 1
}
if (Ask '环境就绪。现在启动 Super Agent Party（node start.js）？Everything is ready. Start Super Agent Party now (node start.js)?') {
  Say '启动中…应用将由本地 Electron 拉起并自动启动后端（使用项目内 .venv）。/ Starting: Electron launches and the backend runs from the project .venv.'
  & node (Join-Path $PROJECT 'start.js')
} else {
  Say '已选择暂不启动。稍后可运行 setup_and_run.bat 选择启动，或直接双击一键启动脚本。/ Not starting now. Re-run this script or use the launcher later.'
}
exit 0
