#!/bin/bash
# ============================================================
# Super Agent Party - source deployment bootstrap (S171)
# Linux/macOS counterpart of setup_and_run.ps1. Installs ONLY what is missing
# and ONLY after an explicit Y confirmation at every step. Idempotent.
# Default sources are official (distro repositories / python.org / nodejs.org /
# PyPI / npm). Mirrors (Tsinghua PyPI, npmmirror) are opt-in after a prompt.
# Writes outside the project folder only for runtime installs you approved.
# ============================================================
set -euo pipefail
PROJECT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT"

say() { echo "[Setup] $*"; }
ask() {
  echo ""
  echo "$*"
  read -r -p "继续吗？Proceed? (y=Yes / n=No) " ans
  case "$(echo "$ans" | tr '[:upper:]' '[:lower:]')" in
    y|yes|是|好|ok) return 0 ;;
    *) return 1 ;;
  esac
}

have() { command -v "$1" >/dev/null 2>&1; }

# S175：Electron 完整性——二进制与 path.txt 标记必须存在且非空（缺一即残缺，必须修复后才允许启动）
electron_intact() {
  # S179：二进制必须有 50MB 体积下限（真实 electron 约 200MB）——0 字节残留/损坏桩绝不允许通过
  # （官方 install.js 的"已安装"判定只看存在与否，正是静默跳过的元凶）。
  local bin="$PROJECT/node_modules/electron/dist/electron" sz
  [ -f "$bin" ] || return 1
  sz="$(wc -c < "$bin" 2>/dev/null || echo 0)"
  [ "$sz" -ge 52428800 ] || return 1
  [ -s "$PROJECT/node_modules/electron/path.txt" ]
}

show_electron_evidence() {
  # S179：不再盲猜——打印判定的现场事实（关键文件大小/path.txt 内容）。
  say "现场证据 / on-site evidence:"
  local d="$PROJECT/node_modules/electron/dist" nm f
  if [ -d "$d" ]; then
    for nm in electron version; do
      f="$d/$nm"
      if [ -e "$f" ]; then say "  dist/$nm = $(wc -c < "$f" 2>/dev/null | tr -d ' ') bytes"; else say "  dist/$nm 缺失 / missing"; fi
    done
    say "  (dist 共 $(ls -1 "$d" 2>/dev/null | wc -l | tr -d ' ') 项，仅列关键文件 / entries, key files only)"
  else
    say "  dist/ 不存在 / dist/ does not exist"
  fi
  if [ -f "$PROJECT/node_modules/electron/path.txt" ]; then
    say "  path.txt = $(wc -c < "$PROJECT/node_modules/electron/path.txt" | tr -d ' ') bytes [$(cat "$PROJECT/node_modules/electron/path.txt" 2>/dev/null)]"
  else
    say "  path.txt 不存在 / path.txt does not exist"
  fi
}

calc_sha256() {
  if have sha256sum; then sha256sum "$1" | awk '{print $1}'; elif have shasum; then shasum -a 256 "$1" | awk '{print $1}'; fi
}

verify_fallback_electron() {
  # S179：原生下载兜底——curl 直接下载官方运行时压缩包，SHASUMS256 强校验后 unzip 就位；
  # 完全不经 node/npm/@electron/get 与本地下载缓存（node 侧被环境破坏的机器上此路通常仍可用）。
  if ! ask "官方脚本仍未产出完整二进制。是否让本脚本直接从官方镜像下载 Electron 运行时压缩包并解压就位（SHASUMS256 强校验，校验不过拒绝解包；全程不经 node/npm）？Download the Electron runtime archive directly (SHASUMS256-verified, unpack refused on mismatch; no node/npm involved)?"; then return 0; fi
  if ! have curl; then say "缺少 curl，无法执行原生下载兜底。/ curl is required for the native fallback."; return 0; fi
  if ! have unzip; then say "缺少 unzip，无法解包运行时压缩包。/ unzip is required to unpack the runtime archive."; return 0; fi
  local ver plat arch fn tmp want u have_sha
  ver="$(grep -o '"version"[^,]*' "$PROJECT/node_modules/electron/package.json" | head -n1 | sed 's/.*"\([0-9][0-9.]*\)".*/\1/')"
  if [ -z "$ver" ]; then say "无法读取 electron 版本（package.json 缺失？）。/ Cannot read electron version."; return 0; fi
  case "$(uname -s)" in Darwin) plat=darwin;; *) plat=linux;; esac
  case "$(uname -m)" in aarch64|arm64) arch=arm64;; *) arch=x64;; esac
  fn="electron-v$ver-$plat-$arch.zip"
  tmp="${TMPDIR:-/tmp}/$fn"
  want=""
  for u in "https://npmmirror.com/mirrors/electron/v$ver/SHASUMS256.txt" "https://github.com/electron/electron/releases/download/v$ver/SHASUMS256.txt"; do
    want="$(curl -fsSL "$u" 2>/dev/null | grep -F "$fn" | head -n1 | awk '{print $1}')"
    if [ -n "$want" ]; then say "SHASUMS256 已取得 / obtained from: $u"; break; fi
  done
  if [ -z "$want" ]; then say "无法获得官方 SHA256 校验值，拒绝安装未校验二进制。/ Cannot obtain the official SHA256; refusing to install an unverified binary."; return 0; fi
  say "期望 SHA256 / expected: $want"
  for u in "https://npmmirror.com/mirrors/electron/v$ver/$fn" "https://github.com/electron/electron/releases/download/v$ver/$fn"; do
    say "下载中 / downloading: $u"
    if ! curl -fL --retry 2 -o "$tmp" "$u"; then say "下载失败 / download failed: $u"; continue; fi
    have_sha="$(calc_sha256 "$tmp")"
    say "实际 SHA256 / actual: $have_sha ($(wc -c < "$tmp" | tr -d ' ') bytes)"
    if [ "$have_sha" != "$want" ]; then say "SHA256 不匹配，弃用该来源换下一个。/ SHA256 mismatch; discarding this source and trying the next."; continue; fi
    rm -rf "$PROJECT/node_modules/electron/dist"
    mkdir -p "$PROJECT/node_modules/electron/dist"
    if unzip -oq "$tmp" -d "$PROJECT/node_modules/electron/dist"; then
      if [ "$plat" = "darwin" ]; then
        printf 'Electron.app/Contents/MacOS/Electron' > "$PROJECT/node_modules/electron/path.txt"
        chmod +x "$PROJECT/node_modules/electron/dist/Electron.app/Contents/MacOS/Electron" 2>/dev/null
      else
        printf 'electron' > "$PROJECT/node_modules/electron/path.txt"
        chmod +x "$PROJECT/node_modules/electron/dist/electron" 2>/dev/null
      fi
      say "校验通过，已解包就位 / verified and unpacked into dist."
      break
    fi
    say "解包失败 / unpack failed: $u"
  done
  rm -f "$tmp"
}

python312_ok() {
  local c
  for c in python3.12 python3 python; do
    if have "$c" && "$c" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' 2>/dev/null; then return 0; fi
  done
  return 1
}

node_major() {
  if have node; then
    node -e 'console.log(process.versions.node.split(".")[0])' 2>/dev/null || echo 0
  else
    echo 0
  fi
}

pkg_install() {
  # Install a package via the first available distro package manager (official repos).
  if have apt-get; then sudo apt-get update -y && sudo apt-get install -y "$@"
  elif have dnf; then sudo dnf install -y "$@"
  elif have pacman; then sudo pacman -S --noconfirm --needed "$@"
  elif have zypper; then sudo zypper --non-interactive install "$@"
  elif have brew; then brew install "$@"
  else return 1; fi
}

# ---------- Step 0: ready fast path (S174) / 就绪即直接启动，不再询问 ----------
if [ "${1:-}" != "--full" ] \
   && [ -x "$PROJECT/.venv/bin/python3" ] \
   && [ -d "$PROJECT/node_modules/electron" ] \
   && electron_intact \
   && "$PROJECT/.venv/bin/python3" -c 'import fastapi' 2>/dev/null; then
  say "环境已完全就绪：跳过全部确认，直接启动（如需完整检查请加 --full）。/ Everything already installed; launching now with no prompts (add --full to re-check)."
  exec node "$PROJECT/start.js"
fi

say "环境尚未就绪（或已指定 --full 强制检查）：进入引导安装。本脚本由你主动运行即代表授权开始；每个安装动作仍会逐一询问。"
say "Environment is not fully ready (or --full was requested): guided setup follows. Every install action is still confirmed one by one."

# ---------- runtimes ----------
if ! python312_ok; then
  say "缺少 Python 3.12（要求 >=3.12,<3.13）。/ Python 3.12 is required and was not found."
  if ask "将通过系统包管理器（官方软件源）安装 Python 3.12，可能需要 sudo。Install Python 3.12 from official distro repositories (may require sudo)?"; then
    pkg_install python3.12 python3.12-venv 2>/dev/null || \
    pkg_install python3.12 2>/dev/null || \
    pkg_install python3 2>/dev/null || true
  fi
  if ! python312_ok; then
    say "仍未找到 Python 3.12。请从 https://www.python.org/downloads/ 或发行版官方源安装后重新运行。/ Still missing Python 3.12 - install it from python.org or your distro, then re-run."
    exit 1
  fi
fi

NM="$(node_major || echo 0)"
if [ "${NM:-0}" -lt 18 ]; then
  say "缺少 Node.js LTS（需 v18+，当前未检测到）。/ Node.js LTS (v18+) is required but was not found."
  if ask "将通过系统包管理器（官方软件源）安装 Node.js LTS，可能需要 sudo。Install Node.js LTS from official repositories (may require sudo)?"; then
    pkg_install nodejs npm 2>/dev/null || true
    have brew && brew install node 2>/dev/null || true
  fi
  NM="$(node_major || echo 0)"
  if [ "${NM:-0}" -lt 18 ]; then
    say "仍未找到 Node.js LTS。请从 https://nodejs.org/ 安装后重新运行。/ Still missing Node.js - install LTS from nodejs.org, then re-run."
    exit 1
  fi
fi
say "运行时就绪 / Runtimes present: Node v$NM."

# ---------- local virtual environment ----------
if [ ! -x "$PROJECT/.venv/bin/python3" ]; then
  if ask "将在项目目录内创建 Python 虚拟环境 .venv（仅写入本目录）。Create .venv inside this project folder?"; then
    python3.12 -m venv "$PROJECT/.venv" 2>/dev/null || python3 -m venv "$PROJECT/.venv"
    say "虚拟环境已创建 / .venv created."
  else
    exit 1
  fi
else
  # S177：校验 .venv 确为 Python 3.12（半环境残留旧环境会静默带病运行）
  if "$PROJECT/.venv/bin/python3" -c 'import sys; sys.exit(0 if sys.version_info[:2]==(3,12) else 1)' 2>/dev/null; then
    say "检测到 .venv（Python 3.12 校验通过），跳过创建 / .venv verified (Python 3.12), skipping creation."
  else
    say "检测到 .venv 但其中并非 Python 3.12（本项目硬性要求 >=3.12,<3.13）——需删除重建。/ .venv exists but is NOT Python 3.12 (project requires >=3.12,<3.13); it must be recreated."
    if ask "确认删除现有 .venv 并用 Python 3.12 重建？（仅删除项目目录内的 .venv）Delete the existing .venv and recreate it with Python 3.12 (removes only .venv inside this project)?"; then
      rm -rf "$PROJECT/.venv"
      python3.12 -m venv "$PROJECT/.venv" 2>/dev/null || python3 -m venv "$PROJECT/.venv"
      [ -x "$PROJECT/.venv/bin/python3" ] || { say "虚拟环境重建失败 / Failed to recreate .venv."; exit 1; }
      say "虚拟环境已用 Python 3.12 重建 / .venv recreated with Python 3.12."
    else
      say "未同意重建 .venv，无法保证 Python 3.12 环境，终止。/ Recreation declined; a guaranteed Python 3.12 environment is impossible, aborting."
      exit 1
    fi
  fi
fi

# ---------- reproducible dependency install (uv.lock) ----------
DEPS_OK=0
if ask "将安装 uv 并按 uv.lock 执行可复现依赖安装（默认官方 PyPI）。Install uv and run 'uv sync --frozen' (official PyPI)?"; then
  if python3 -m pip install --disable-pip-version-check uv; then
    if uv sync --frozen; then DEPS_OK=1; say "依赖安装完成（uv.lock 可复现）。/ Dependencies installed from uv.lock."; fi
  fi
  if [ "$DEPS_OK" -eq 0 ] && ask "官方源失败，切换清华大学 PyPI 镜像重试 uv 安装？Official sources failed - retry uv install via the Tsinghua PyPI mirror?"; then
    if python3 -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple uv; then
      if command -v uv >/dev/null 2>&1 && uv sync --frozen; then DEPS_OK=1; say "镜像源依赖安装完成 / Locked dependencies installed via mirror."; fi
    fi
  fi
fi

if [ "$DEPS_OK" -eq 0 ]; then
  echo ""
  echo "[Setup] 警告 / WARNING: 锁定安装失败，唯一兜底是非锁定 pip 安装（版本由解析器现场决定，不再是可复现清单）。"
  echo "        Locked install failed. The only fallback is a NON-reproducible 'pip install -e .'."
  if ask "确认改用非锁定 pip 安装吗？Proceed with the non-reproducible pip fallback?"; then
    if python3 -m pip install --disable-pip-version-check -e "$PROJECT" || \
       { ask "官方源失败，切换清华 PyPI 镜像重试兜底安装？Retry fallback via the Tsinghua mirror?" && \
         python3 -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -e "$PROJECT"; }; then
      say "兜底安装完成（注意：非可复现清单）。/ Fallback installed (NOT a reproducible manifest)."
    else
      say "兜底安装失败 / Fallback install failed."; exit 1
    fi
  else
    exit 1
  fi
fi

# ---------- Node dependencies ----------
# S175：包目录存在但二进制/path.txt 残缺 = 半残安装（新机器事故实证）——绝不跳过，必须经确认重装
if [ -d "$PROJECT/node_modules/electron" ] && electron_intact; then
  say "Node 依赖完整，跳过安装 / Node dependencies complete; skipping install."
else
  if [ -d "$PROJECT/node_modules/electron" ]; then
    say "检测到 Node 依赖包存在但 Electron 二进制残缺（dist/electron 或 path.txt 缺失/为空），需重装修复。/ Packages present but the Electron binary is incomplete; a repair install is required."
  fi
  # S176→S178：仍先查 install-scripts 放行闸门（只读），但仅供参考——事故实证：有机器 npm 即便 approve
  # 放行后仍静默跳过生命周期脚本且谎报成功。Electron 二进制产出不依赖 npm 生命周期脚本（下一步直跑
  # install.js）；放行只影响 esbuild/@serialport 原生产出，故降为可选。
  say "先检查 npm 安装脚本放行闸门状态（只读，仅供参考）/ Checking the npm install-scripts gate (read-only, informational)..."
  npm install-scripts ls
  if ask "上方若有未放行包，可经官方命令 npm install-scripts approve 放行 esbuild/@serialport 等原生组件（Electron 不依赖此步：二进制由下一步官方 install.js 直跑产出）。是否放行？/ If packages above await approval, npm install-scripts approve can clear esbuild/@serialport natives (Electron does NOT depend on this step). Approve now?"; then
    for pkg in electron esbuild '@serialport/bindings-cpp'; do
      npm install-scripts approve "$pkg" || say "npm install-scripts approve $pkg 失败 / approval failed."
    done
  else
    say "已跳过放行：不影响 Electron 二进制产出（官方 install.js 直跑）；esbuild/@serialport 原生组件可能残缺，相应功能降级。/ Approval skipped: Electron binary is still produced via the official install.js; esbuild/@serialport natives may stay incomplete (those features degrade)."
  fi
  # S177：安装与产出**必须分离**——新版 npm 默认 allowScripts 白名单拒绝，npm ci 即便脚本已放行也可能静默跳过
  # postinstall（实测：ci"成功"却抹掉 rebuild 已产出的二进制）。故 ci 显式 --ignore-scripts 只做确定性全量安装，
  # Electron 二进制唯一由随后的官方 install.js 直跑产出（S178：绕开 npm 脚本机制，要么产出、要么见真错）。
  if ask "将按 package-lock.json 安装/重装 Node 依赖（--ignore-scripts 确定性安装，二进制由下一步显式生成）。Install Node dependencies with npm ci --ignore-scripts (deterministic; binaries produced in the next step)?"; then
    if ! npm ci --no-audit --no-fund --ignore-scripts; then
      say "npm ci 失败（官方源）。/ npm ci failed against official sources."
      if ask "经确认改用 npmmirror 镜像（npm registry）重试？Switch to the npmmirror registry and retry?"; then
        npm ci --no-audit --no-fund --ignore-scripts --registry=https://registry.npmmirror.com || { say "镜像安装 Node 依赖仍失败 / mirror install also failed."; exit 1; }
      else
        exit 1
      fi
    fi
    # S179：证据驱动产出——现场打印 → 0 字节残留清理 → force_no_cache 绕缓存直跑（打印退出码）→
    # 镜像直跑 → 仍败则原生下载兜底（SHASUMS256 强校验解包）→ 三因如实。不再盲猜。
    show_electron_evidence
    if { [ -f "$PROJECT/node_modules/electron/dist/electron" ] && [ ! -s "$PROJECT/node_modules/electron/dist/electron" ]; } || { [ -f "$PROJECT/node_modules/electron/path.txt" ] && [ ! -s "$PROJECT/node_modules/electron/path.txt" ]; }; then
      say "检测到 0 字节残留：官方 install.js 判定\"已安装\"时只看文件存在（不看大小），会静默跳过并退 0——先删除残留再重产。/ Zero-byte residue detected: the official install.js only checks file existence when deciding it is already installed and exits silently; removing the residue before re-production."
      rm -rf "$PROJECT/node_modules/electron/dist"
      rm -f "$PROJECT/node_modules/electron/path.txt"
    fi
    BUILD_OK=1
    if ! electron_intact; then
      if ask "将直接执行 Electron 官方安装脚本 node_modules/electron/install.js 下载并解包运行时二进制（将设 force_no_cache=true 绕开本地下载缓存以防缓存投毒；失败可确认切 npmmirror 镜像，另有原生下载兜底做 SHA256 强校验解包）。Run the official Electron install script (with force_no_cache to bypass the local download cache; mirror retry and a native verified fallback follow)?"; then
        force_no_cache=true node "$PROJECT/node_modules/electron/install.js"; rc=$?
        say "install.js 退出码 / exit code: $rc"
        [ "$rc" -eq 0 ] || BUILD_OK=0
        if ! electron_intact; then
          if ask "Electron 二进制仍未产出（官方下载源不可达？）。是否设 ELECTRON_MIRROR 走 npmmirror 二进制镜像再次直跑？Electron binary still missing (official source unreachable?). Set ELECTRON_MIRROR to the npmmirror binary mirror and re-run install.js directly?"; then
            export ELECTRON_MIRROR="https://npmmirror.com/mirrors/electron/"
            force_no_cache=true node "$PROJECT/node_modules/electron/install.js"; rc=$?
            say "install.js 退出码 / exit code: $rc"
            [ "$rc" -eq 0 ] || BUILD_OK=0
          fi
        fi
      else
        exit 1
      fi
    fi
    if ! electron_intact; then
      verify_fallback_electron
    fi
    if ! electron_intact; then
      show_electron_evidence
      say "Electron 二进制仍未产出（本脚本已直跑官方 install.js 绕开缓存、并尝试原生校验下载兜底，不依赖 npm 生命周期脚本）。原因只有三类：① 官方与 npmmirror 下载均不可达/失败（上方已打印每次尝试的 URL 与错误——检查网络/代理/防火墙，给 curl/sh 与 node 放行直连）；② 本地 0 字节残留或损坏缓存（本脚本已尝试清理与绕开，现场清单已打印于上方——删除 ~/.electron 或 ~/.cache/electron 后重跑本脚本）；③ 离线修复：从同版本（见 package-lock.json）完好安装拷贝 node_modules/electron/dist 整目录与 path.txt 到本项目相同位置，或直接改用自带运行时的官方打包版。/ Electron binary still missing (official install.js was run directly with cache bypass, and a native verified download was attempted; independent of npm lifecycle scripts). Three causes only: (1) both official and npmmirror downloads unreachable/failed (URLs and errors printed above; allow curl/sh and node through network/proxy/firewall); (2) local zero-byte residue or poisoned cache (cleaned and bypassed by this script; evidence printed above; delete ~/.electron or ~/.cache/electron and re-run); (3) offline repair: copy node_modules/electron/dist and path.txt from a healthy same-version install (see package-lock.json), or use the official packaged release with bundled runtimes."
      exit 1
    fi
    if [ "$BUILD_OK" -eq 0 ]; then
      say "Electron 安装脚本退出码非零，但完整性复验通过——按可用继续；若启动异常请重跑本脚本。/ install.js exited non-zero yet the integrity re-check passed; proceeding. Re-run this script if the app misbehaves."
    fi
    say "esbuild/@serialport 原生组件不在本路径强修：如残缺仅串口等功能降级，不影响应用启动。/ esbuild/@serialport natives are not force-repaired here; if incomplete those features degrade without blocking launch."
    say "Node 依赖安装完成且 Electron 二进制完整 / Node dependencies installed; Electron binary verified complete."
  else
    exit 1
  fi
fi

# ---------- run the application ----------
if ! electron_intact; then
  say "Electron 二进制不完整，暂不启动：请重新运行本脚本——确认安装（ci --ignore-scripts）后直跑官方 install.js 产出二进制（下载失败可切 npmmirror 镜像；仍不行则离线拷贝同版本 dist+path.txt，或改用官方打包版）。/ Electron binary incomplete; not launching. Re-run this script: after the confirmed ci --ignore-scripts install, the binary is produced by running the official install.js directly (npmmirror mirror retry available; if that still fails, offline-copy dist+path.txt from a healthy same-version install, or use the official packaged release)."
  exit 1
fi
if ask "环境就绪。现在启动 Super Agent Party（node start.js）？Everything is ready. Start Super Agent Party now (node start.js)?"; then
  say "启动中…/ Starting..."
  exec node "$PROJECT/start.js"
else
  say "已选择暂不启动。稍后可重新运行本脚本选择启动。/ Not starting now. Re-run later to start the app."
fi
exit 0
