# -*- coding: utf-8 -*-
"""S299：启动期底层工具（自 server.py 逐字搬移）。

端口绑定探测/回退、macOS PATH 修复、onnxruntime DLL 路径修复。
执行序敏感：server 侧模块级调用必须以 boot_utils. 前缀在本 import 之后执行。
"""
import errno
import importlib
import os
import pathlib
import socket
import subprocess
import sys
from pathlib import Path


def port_listener_pid(port, host="127.0.0.1"):
    """S328: 真实 TCP connect 探测 + netstat 点名占用者 PID。
    Windows 的 SO_REUSEADDR 使 bind() 探测在端口已被监听时照样成功——
    探测必须走 connect，否则双胞胎 server 会静默共存、随机分连接。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect((host, port))
        s.close()
    except OSError:
        return None
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=6).stdout
        suffix = ":%d" % port
        for line in out.splitlines():
            cols = line.split()
            if (len(cols) >= 5 and cols[0].upper() == "TCP"
                    and cols[1].endswith(suffix)
                    and cols[3].upper() == "LISTENING"):
                return cols[4]
    except Exception:
        pass
    return "unknown"


def is_addr_in_use_error(e):
    """跨平台判断是否为地址被占用错误"""
    if hasattr(e, 'errno'):
        if e.errno == errno.EADDRINUSE:
            return True
        # Windows 有时用 WSAEADDRINUSE (10048)
        if sys.platform == 'win32' and e.errno == 10048:
            return True
    # Windows winerror 属性
    if hasattr(e, 'winerror') and e.winerror == 10048:
        return True
    # macOS/Linux 错误消息
    if 'address already in use' in str(e).lower():
        return True
    return False

def is_permission_error(e):
    """跨平台判断是否为权限/拒绝访问错误"""
    if isinstance(e, PermissionError):
        return True
    if hasattr(e, 'errno'):
        if e.errno in (errno.EACCES, errno.EPERM):
            return True
        # Windows ERROR_ACCESS_DENIED (5)
        if sys.platform == 'win32' and e.errno == 13:
            return True
    if hasattr(e, 'winerror') and e.winerror in (5, 10013):
        return True
    err_str = str(e).lower()
    if any(x in err_str for x in ['permission', 'denied', 'access', 'not permitted']):
        return True
    return False

def force_bind_or_fallback(host, preferred_port):
    """
    跨平台端口绑定：
    1. 尝试强制绑定指定端口（处理TIME_WAIT）
    2. 如果被真正占用/无权限/系统保留，自动降级到随机端口
    3. 绝不抛出异常导致退出
    """
    # S328: Windows 下 SO_REUSEADDR 的 bind() 探测在端口已被监听时也会
    # "成功"→ 双 server 静默共存、新连接随机分（曾致前端修复看似无效）。
    # 用真实 TCP connect 探测并点名占用者；行为保持兼容（仍尝试绑定），
    # 但把共存事实大声写进日志。
    occupier = port_listener_pid(preferred_port, host if host != "0.0.0.0" else "127.0.0.1")
    if occupier is not None:
        print(f"[PortProbe] WARNING port {preferred_port} already LISTENING "
              f"(pid={occupier}); windows SO_REUSEADDR allows coexistence - "
              f"new connections may split randomly. Kill the stale instance "
              f"and restart.", file=sys.stderr, flush=True)
    # 尝试绑定首选端口
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 关键：允许快速复用 TIME_WAIT 状态的端口
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, preferred_port))
        sock.close()
        return preferred_port
        
    except (socket.error, OSError, PermissionError) as e:
        # 判断错误类型
        if is_addr_in_use_error(e):
            reason = "in use"
        elif is_permission_error(e):
            reason = "permission denied/system reserved"
        else:
            reason = f"error ({e})"
        
        print(f"Port {preferred_port} unavailable ({reason}), auto-assigning...", 
              file=sys.stderr, flush=True)
        
        # 关闭失败的 socket
        try:
            if sock:
                sock.close()
        except:
            pass
        
        # 降级：让系统分配端口
        return auto_assign_port(host)
        
    except Exception as e:
        # 捕获所有其他异常
        print(f"Unexpected error binding port {preferred_port}: {e}, auto-assigning...", 
              file=sys.stderr, flush=True)
        try:
            if sock:
                sock.close()
        except:
            pass
        return auto_assign_port(host)

def auto_assign_port(host):
    """自动分配可用端口，带多重降级"""
    # 尝试 127.0.0.1
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, 0))
        port = sock.getsockname()[1]
        sock.close()
        print(f"Auto-assigned port: {port}", file=sys.stderr, flush=True)
        return port
    except Exception as e:
        print(f"Failed to bind {host}: {e}", file=sys.stderr, flush=True)
        try:
            sock.close()
        except:
            pass
    
    # 降级 1: 尝试 0.0.0.0 (所有接口)
    if host != "0.0.0.0":
        try:
            print("Trying 0.0.0.0...", file=sys.stderr, flush=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("0.0.0.0", 0))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Auto-assigned port on 0.0.0.0: {port}", file=sys.stderr, flush=True)
            return port
        except Exception as e:
            print(f"Failed to bind 0.0.0.0: {e}", file=sys.stderr, flush=True)
            try:
                sock.close()
            except:
                pass
    
    # 降级 2: 尝试 localhost
    if host != "localhost":
        try:
            print("Trying localhost...", file=sys.stderr, flush=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("localhost", 0))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Auto-assigned port on localhost: {port}", file=sys.stderr, flush=True)
            return port
        except Exception as e:
            print(f"Failed to bind localhost: {e}", file=sys.stderr, flush=True)
            try:
                sock.close()
            except:
                pass
    
    # 最后手段：硬编码高位端口（极端情况）
    fallback_ports = [45678, 45679, 45680, 0]
    for fp in fallback_ports:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host if host != "0.0.0.0" else "127.0.0.1", fp))
            port = sock.getsockname()[1]
            sock.close()
            print(f"Fallback to hardcoded port: {port}", file=sys.stderr, flush=True)
            return port
        except:
            try:
                sock.close()
            except:
                pass
            continue
    
    # 理论上不会到这里，如果真的到了，返回一个肯定能用的
    return 0

def fix_macos_environment():
    """
    专门修复 macOS 下找不到 node (nvm) 和 uv (python framework) 的问题
    """
    if sys.platform != 'darwin':
        return

    user_home = Path.home()
    paths_to_add = []

    # ---------------------------------------------------------
    # 1. 自动发现 NVM 安装的 Node.js
    # 路径通常是: ~/.nvm/versions/node/vX.X.X/bin
    # ---------------------------------------------------------
    nvm_path = user_home / ".nvm" / "versions" / "node"
    if nvm_path.exists():
        # 获取所有版本文件夹 (如 v20.19.5, v18.0.0)
        # 使用 glob 匹配所有 v 开头的文件夹
        node_versions = sorted(nvm_path.glob("v*"), key=lambda p: p.name, reverse=True)
        
        # 将所有版本的 bin 目录都加入，或者只加最新的
        for version_dir in node_versions:
            bin_path = version_dir / "bin"
            if bin_path.exists():
                paths_to_add.append(str(bin_path))
                # 如果只想用最新的 node，这里可以 break
                # break 

    # ---------------------------------------------------------
    # 2. 自动发现 Python Framework 中的 uv
    # 路径通常是: /Library/Frameworks/Python.framework/Versions/X.X/bin
    # ---------------------------------------------------------
    py_framework_path = Path("/Library/Frameworks/Python.framework/Versions")
    if py_framework_path.exists():
        # 查找所有版本，如 3.13, 3.12
        py_versions = py_framework_path.glob("*")
        for ver in py_versions:
            bin_path = ver / "bin"
            if bin_path.exists():
                paths_to_add.append(str(bin_path))

    # ---------------------------------------------------------
    # 3. 补充 macOS 常见的其他路径 (Homebrew, Cargo, Local)
    # uv 也经常被安装在 .local/bin 或 .cargo/bin 下
    # ---------------------------------------------------------
    common_extras = [
        "/opt/homebrew/bin",           # Apple Silicon Mac Homebrew
        "/usr/local/bin",              # Intel Mac Homebrew
        str(user_home / ".local" / "bin"), # 用户级安装通常在这里
        str(user_home / ".cargo" / "bin"), # Rust 工具链 (uv 可能在这里)
    ]
    paths_to_add.extend(common_extras)

    # ---------------------------------------------------------
    # 4. 将发现的路径注入到当前进程的环境变量中
    # ---------------------------------------------------------
    current_path = os.environ.get("PATH", "")
    new_path_str = current_path
    
    # 将新路径加到最前面 (优先级最高)
    for p in paths_to_add:
        if p and os.path.isdir(p):
            # 避免重复添加
            if p not in new_path_str:
                new_path_str = p + os.pathsep + new_path_str
    
    # 更新环境变量
    os.environ['PATH'] = new_path_str

def _fix_onnx_dll():
    if sys.platform == 'darwin':
        return
    # 1. 找到 uv 虚拟环境里的 onnxruntime
    spec = importlib.util.find_spec("onnxruntime")
    if spec is None or spec.origin is None:
        return          # 没装 onnxruntime，随它去
    # DLL 就在 site-packages/onnxruntime/capi 里
    dll_dir = pathlib.Path(spec.origin).with_name("capi")
    if not dll_dir.is_dir():
        return

    # 2. 置顶搜索路径
    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ["PATH"]
    if hasattr(os, "add_dll_directory"):      # Python 3.8+
        os.add_dll_directory(str(dll_dir))

    # 3. 如果已经有人 import 过 onnxruntime，清掉缓存
    for mod in list(sys.modules):
        if mod.startswith("onnxruntime"):
            del sys.modules[mod]
