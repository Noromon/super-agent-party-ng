#!/usr/bin/env python3

import logging
import asyncio
import os
import re
import shutil
import signal
import subprocess
import json
import platform
import time
import uuid
import tempfile
import socket
import glob as std_glob
import fnmatch
from pathlib import Path
from typing import AsyncIterator, Optional
from datetime import datetime
from collections import deque
import aiofiles
import aiofiles.os
import hashlib
import anyio
from py.get_setting import load_settings
from py.get_setting import SKILLS_DIR

COMMAND_TIMEOUT = 300  # 5分钟超时

# ==================== 环境初始化 ====================

# ==================== WSL 环境检测与工具（S132/A13 上游 ad36b6cd） ====================

def _check_wsl_available() -> bool:
    """检测 WSL 是否可用（仅 Windows 上有效）"""
    if platform.system() != "Windows":
        return False
    try:
        result = subprocess.run(
            ["wsl.exe", "--status"],
            capture_output=True, text=True, timeout=15,
            stdin=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False

def _windows_to_wsl_path(win_path: str) -> str:
    """将 Windows 路径转换为 WSL 路径 (如 D:\\foo\\bar -> /mnt/d/foo/bar)"""
    path = Path(win_path).resolve()
    drive = path.drive[0].lower()
    rest = str(path).replace('\\', '/')[2:]  # 去掉 "D:"
    return f"/mnt/{drive}{rest}"

async def _ensure_bubblewrap_in_wsl() -> tuple:
    """检测 WSL 中是否已安装 bubblewrap，如未安装则自动安装。返回 (success: bool, message: str)"""
    check_cmd = ["wsl.exe", "-e", "bash", "-c", "command -v bwrap || echo NOT_FOUND"]
    proc = await asyncio.create_subprocess_exec(
        *check_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()

    if b"NOT_FOUND" not in stdout:
        return True, "bubblewrap already installed in WSL."

    # 自动安装 bubblewrap
    install_cmd = [
        "wsl.exe", "-e", "bash", "-c",
        "sudo apt-get update -qq && sudo apt-get install -y -qq bubblewrap"
    ]
    proc = await asyncio.create_subprocess_exec(
        *install_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    await proc.communicate()

    if proc.returncode == 0:
        return True, "bubblewrap installed successfully in WSL."
    else:
        return False, (
            "Failed to auto-install bubblewrap. "
            "Please manually run in WSL: sudo apt update && sudo apt install bubblewrap"
        )


def get_shell_environment():
    """通过子进程获取完整的 shell 环境"""
    shell = os.environ.get('SHELL', '/bin/zsh')
    home = Path.home()
    
    config_commands = [
        f'source {home}/.zshrc && env',
        f'source {home}/.bash_profile && env', 
        f'source {home}/.bashrc && env',
        'env'
    ]
    
    # Windows 环境简单跳过
    if platform.system() == "Windows":
        return

    for cmd in config_commands:
        try:
            result = subprocess.run(
                [shell, '-i', '-c', cmd],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if '=' in line:
                        var_name, var_value = line.split('=', 1)
                        os.environ[var_name] = var_value
                logging.getLogger("app").info("Successfully loaded environment from shell")
                return
        except Exception as e:
            continue
    
    logging.getLogger("app").info("Warning: Could not load shell environment, using current environment")

get_shell_environment()

# ==================== 核心基础设施：流处理 ====================

async def read_stream(stream, *, is_error: bool = False):
    """读取流并添加错误前缀"""
    if stream is None:
        return
    async for line in stream:
        prefix = "[ERROR] " if is_error else ""
        yield f"{prefix}{line.decode('utf-8', errors='replace').rstrip()}"

# 修改 read_stream 为分块读取，防止进度条挂起
async def read_stream_chunks(stream, prefix=""):
    """
    分块读取流，不等待换行符，解决进度条显示问题。
    智能编码检测：优先 UTF-8，若 NUL 字符过多则尝试 UTF-16LE（WSL 部分消息使用）。
    """
    if stream is None:
        return
    
    try:
        while True:
            chunk = await stream.read(4096)
            if not chunk:
                break
            
            decoded = ""
            # 优先尝试 UTF-8
            try:
                decoded = chunk.decode('utf-8')
            except UnicodeDecodeError:
                pass
            
            # 若 UTF-8 解码结果中 NUL 字符或替换字符过多，说明可能是 UTF-16LE 数据
            if decoded:
                bad_chars = decoded.count('\x00') + decoded.count('\ufffd')
                if bad_chars > len(decoded) * 0.3:
                    decoded = ""
            
            if not decoded:
                for enc in ['utf-16-le', 'gbk', 'cp437']:
                    try:
                        decoded = chunk.decode(enc)
                        break
                    except (UnicodeDecodeError, UnicodeError):
                        continue
            
            if not decoded:
                decoded = chunk.decode('utf-8', errors='replace')
            
            if decoded:
                yield f"{prefix}{decoded}"
    except Exception as e:
        yield f"[System Stream Error] {e}"


async def _merge_streams(*streams):
    """合并多个异步流"""
    streams = [s.__aiter__() for s in streams]
    while streams:
        for stream in list(streams):
            try:
                item = await stream.__anext__()
                yield item
            except StopAsyncIteration:
                streams.remove(stream)

async def _get_current_cwd() -> str:
    """获取当前配置的工作目录"""
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    if not cwd:
        raise ValueError("No workspace directory specified in settings (CLISettings.cc_path).")
    return cwd

def get_detailed_exit_info(code: int, command: str) -> str:
    """
    根据退出码和操作系统，生成详细的诊断信息和建议。
    """
    cmd_name = command.strip().split()[0] if command.strip() else "unknown"
    system = platform.system()
    
    # 基础映射
    explanations = {
        1: "Generic failure (permission denied, syntax or logic error). Suggested next: inspect the output above, fix the cause and retry with a changed command.",
        2: "Shell built-in misuse (bad usage/syntax). Suggested next: check the command syntax and retry.",
        126: "Not executable (permission bit or not a program). Suggested next: check file type/permissions and retry differently.",
        127: "Command not found (Linux/Unix). Suggested next: verify the program name and PATH.",
        130: "Terminated by Ctrl-C. Suggested next: rerun if interrupted; otherwise continue with the task.",
        137: "Process killed (likely OOM). Suggested next: reduce memory usage (smaller batch/file) or split the work.",
        # Windows specific
        9009: f"Windows: command '{cmd_name}' not found. Check whether it is installed or on PATH, then retry.",
        5: "Windows: access denied. Suggested next: use a path/operation you have permission for.",
    }
    
    info = f"\n[Diagnostics] process exit code: {code}\n"
    info += f"[Explanation] {explanations.get(code, 'No known explanation. Inspect the output above, then retry with a changed approach - a failed step is a signal to adjust, not to stop.')}\n"
    
    if code in [127, 9009]:
        info += f"Suggested next steps:\n"
        if system == "Windows":
            info += f"  1. Run 'where {cmd_name}' to locate the program.\n"
            info += f"  2. For freshly installed software, restart the backend or use an absolute path.\n"
        else:
            info += f"  1. Run 'which {cmd_name}' to locate the program.\n"
            info += f"  2. Check the environment: 'echo $PATH'\n"
            
    return info

async def read_stream(stream, *, is_error: bool = False):
    """
    改进的流读取器：支持多编码回退，确保能抓取到系统原始报错。
    """
    if stream is None:
        return
    
    prefix = "[ERROR] " if is_error else ""
    
    while True:
        line_bytes = await stream.readline()
        if not line_bytes:
            break
            
        decoded = ""
        # 依次尝试：UTF-8 -> GBK (Windows) -> CP437 -> 替换模式
        for enc in ['utf-8', 'gbk', 'cp437']:
            try:
                decoded = line_bytes.decode(enc).rstrip()
                break
            except UnicodeDecodeError:
                continue
        
        if not decoded:
            decoded = line_bytes.decode('utf-8', errors='replace').rstrip()
            
        yield f"{prefix}{decoded}"

# ==================== [新增] 核心基础设施：进程管理 ====================

class ProcessManager:
    """全局后台进程管理器 (Docker & Local) - 增强版 (支持 Windows 进程树查杀)"""
    def __init__(self):
        # 结构: {pid: {"proc": proc, "logs": deque, "cmd": str, "type": str, "task": task, "status": str, "start_time": str}}
        self._processes = {}
        self._counter = 0

    def generate_id(self):
        self._counter += 1
        return str(self._counter)

    async def register_process(self, proc, cmd: str, p_type: str):
        """注册并开始监控一个后台进程"""
        pid = self.generate_id()
        logs = deque(maxlen=2000)
        
        task = asyncio.create_task(self._monitor_output(pid, proc, logs))
        
        self._processes[pid] = {
            "proc": proc,
            "logs": logs,
            "cmd": cmd,
            "type": p_type,
            "task": task,
            "status": "running",
            "start_time": datetime.now().isoformat()
        }
        return pid

    async def _monitor_output(self, pid: str, proc, logs: deque):
        async def read_stream_to_log(stream, prefix=""):
            if not stream: return
            try:
                while True:
                    # 改为读取分块，不再使用 readline()
                    chunk = await stream.read(1024) 
                    if not chunk:
                        break
                    
                    decoded = ""
                    for enc in ['utf-8', 'gbk', 'cp437']:
                        try:
                            decoded = chunk.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if not decoded:
                        decoded = chunk.decode('utf-8', errors='replace')

                    timestamp = datetime.now().strftime("%H:%M:%S")
                    
                    # 处理回车符 \r，将其替换为换行，这样 log 中能看到进度条的每一步更新
                    # 如果不需要保留进度条每一行，可以直接 decoded.strip()
                    lines = decoded.replace('\r', '\n').splitlines()
                    for line in lines:
                        if line.strip():
                            logs.append(f"[{timestamp}] {prefix}{line}")
            except Exception as e:
                logs.append(f"[SYSTEM ERROR] {prefix}Monitoring failed: {str(e)}")

        try:
            await asyncio.gather(
                read_stream_to_log(proc.stdout, ""),
                read_stream_to_log(proc.stderr, "[ERR] ")
            )
            await proc.wait()
            if pid in self._processes:
                if "terminated" not in self._processes[pid]["status"]:
                    self._processes[pid]["status"] = f"exited (code {proc.returncode})"
        except Exception:
            pass

    def get_logs(self, pid: str, lines: int = 50) -> str:
        if pid not in self._processes:
            return f"Error: no tracked process with id '{pid}'. Call list_processes_tool to see valid ids (use the small id, not the OS PID). If the process already exited, that is not your task failing - verify its output and continue."
        
        entry = self._processes[pid]
        stored_logs = list(entry["logs"])
        subset = stored_logs[-lines:] if lines > 0 else stored_logs
        
        header = f"--- Logs for Process {pid} ({entry['status']}) ---\nCommand: {entry['cmd']}\n"
        return header + "\n".join(subset)

    def list_processes(self):
        if not self._processes:
            return "No background processes are tracked yet - entries appear only after launching with 'background': true. If you just launched one, check the PID you received; otherwise continue with the next task step."
        
        result = ["PID | Type   | Status       | Start Time          | Command"]
        result.append("-" * 90)
        
        active_found = False
        for pid, info in list(self._processes.items()):
            cmd_display = (info['cmd'][:45] + '...') if len(info['cmd']) > 45 else info['cmd']
            start_time = info['start_time'].split('T')[-1][:8]
            result.append(f"{pid:<4}| {info['type']:<7}| {info['status']:<13}| {start_time:<20}| {cmd_display}")
            active_found = True
        
        if not active_found:
            return "No background processes are tracked yet - entries appear only after launching with 'background': true. If you just launched one, check the PID you received; otherwise continue with the next task step."
        return "\n".join(result)

    async def kill_process(self, pid: str):
        """
        强制结束进程。
        针对 Windows 使用 taskkill /T 结束进程树，防止子进程残留。
        """
        if pid not in self._processes:
            return f"Error: no tracked process with id '{pid}'. Call list_processes_tool to see valid ids (use the small id, not the OS PID). If the process already exited, that is not your task failing - verify its output and continue."
        
        info = self._processes[pid]
        proc = info["proc"]
        
        # 即使 proc.returncode 已经有值，也要尝试清理可能的孤儿进程
        os_pid = proc.pid
        
        try:
            info["status"] = "terminating..."
            
            if platform.system() == "Windows":
                # Windows: 使用 taskkill /F (强制) /T (进程树) /PID <pid>
                # 这是清理 PowerShell/CMD 启动的子进程的关键
                kill_cmd = f"taskkill /F /T /PID {os_pid}"
                subprocess.run(kill_cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Linux/Mac: 尝试杀进程组 (如果适用) 或标准 terminate
                try:
                    proc.terminate()
                    # 给一点时间优雅退出
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except (asyncio.TimeoutError, ProcessLookupError):
                    try:
                        proc.kill()
                    except:
                        pass
            
            info["status"] = "terminated"
            return f"Process {pid} (OS PID {os_pid}) terminated successfully."
            
        except Exception as e:
            return f"Error terminating process {pid}: {str(e)}"
        
process_manager = ProcessManager()

# ==================== [新增] 核心基础设施：Docker 网络代理 ====================

class DockerPortProxy:
    """纯 Python 实现的 Docker 端口转发器 (Container -> Host)"""
    def __init__(self, container_name: str):
        self.container_name = container_name
        self.proxies = {} # {local_port: server_obj}

    async def start_forward(self, local_port: int, container_port: int):
        """开启转发：本地 TCP Server -> docker exec 桥接 -> 容器内部端口"""
        if local_port in self.proxies:
            return f"Port {local_port} is already being forwarded."

        if not self._is_port_available(local_port):
            return f"Error: Local port {local_port} is already in use."

        try:
            server = await asyncio.start_server(
                lambda r, w: self._handle_client(r, w, container_port),
                '127.0.0.1', local_port
            )
            
            self.proxies[local_port] = server
            asyncio.create_task(server.serve_forever())
            return f"Success: Forwarding localhost:{local_port} -> Docker:{container_port}"
        except Exception as e:
            return f"Error starting proxy: {str(e)}"

    def _is_port_available(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) != 0

    async def _handle_client(self, client_reader, client_writer, container_port):
        """处理每个连接：启动一个 docker exec 进程作为管道"""
        try:
            # 微型 Python 转发脚本，在容器内运行
            proxy_script = (
                "import socket,sys,threading;"
                "s=socket.socket();"
                f"s.connect(('127.0.0.1',{container_port}));"
                "def r():"
                " while True:"
                "  d=s.recv(4096);"
                "  if not d: break;"
                "  sys.stdout.buffer.write(d);sys.stdout.flush();\n"
                "threading.Thread(target=r,daemon=True).start();"
                "while True:"
                " d=sys.stdin.buffer.read(4096);"
                " if not d: break;"
                " s.sendall(d)"
            )

            cmd = [
                "docker", "exec", "-i", 
                self.container_name, 
                "python3", "-u", "-c", proxy_script
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL 
            )

            async def pipe_reader_to_writer(reader, writer):
                try:
                    while True:
                        data = await reader.read(4096)
                        if not data: break
                        writer.write(data)
                        await writer.drain()
                except Exception:
                    pass
                finally:
                    try: writer.close()
                    except: pass

            await asyncio.gather(
                pipe_reader_to_writer(client_reader, proc.stdin),  # Local -> Docker
                pipe_reader_to_writer(proc.stdout, client_writer)  # Docker -> Local
            )
            try: proc.terminate()
            except: pass

        except Exception as e:
            try: client_writer.close()
            except: pass

    async def stop_forward(self, local_port: int):
        if local_port in self.proxies:
            server = self.proxies[local_port]
            server.close()
            await server.wait_closed()
            del self.proxies[local_port]
            return f"Stopped forwarding on port {local_port}"
        return f"Port {local_port} was not being forwarded."
    
    def list_proxies(self):
        if not self.proxies:
            return "No active port forwardings. Use action='forward' with container_port and host_port if you need access; otherwise continue the task."
        return "\n".join([f"localhost:{p} -> container:{p} (active)" for p in self.proxies.keys()])

DOCKER_PROXIES = {} # {container_name: ProxyInstance}

# ==================== Docker Sandbox 基础设施 ====================

def get_safe_container_name(cwd: str) -> str:
    """根据路径生成合法容器名"""
    abs_path = str(Path(cwd).resolve())
    path_hash = hashlib.md5(abs_path.encode()).hexdigest()[:12]
    return f"sandbox-{path_hash}"

async def get_or_create_docker_sandbox(cwd: str, image_name: str = "docker/sandbox-templates:claude-code") -> str:
    """获取或创建基于路径的持久化沙盒，并映射全局skills目录"""
    container_name = get_safe_container_name(cwd)
    
    # 获取主机的全局skills目录
    host_skills_dir = SKILLS_DIR
    
    check_proc = await asyncio.create_subprocess_exec(
        "docker", "ps", "-a", "--filter", f"name=^/{container_name}$", "--format", "{{.Names}}|{{.Status}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await check_proc.communicate()
    output = stdout.decode().strip()
    
    if container_name in output:
        status = output.split("|")[-1] if "|" in output else ""
        if "Up" in status:
            return container_name
        else:
            # 启动已存在的容器
            await asyncio.create_subprocess_exec("docker", "start", container_name, stdout=asyncio.subprocess.PIPE)
            return container_name
    
    # 创建新容器，映射主机的全局skills目录
    # 注意：我们将主机skills目录映射到容器内的 /root/.agents/skills
    # 这是标准Agent Skills CLI使用的路径
    create_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "-v", f"{cwd}:/workspace",  # 映射工作目录
        "-v", f"{host_skills_dir}:/home/agent/.agents/skills",   # 映射全局skills目录到容器内
        "-w", "/workspace",
        "--restart", "unless-stopped",
        image_name,
        "tail", "-f", "/dev/null"
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *create_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode == 0:
        # 容器创建成功，确保容器内的skills目录权限正确
        try:
            # 设置容器内skills目录的权限
            chown_cmd = [
                "docker", "exec", container_name,
                "chown", "-R", "root:root", "/root/.agents/skills"
            ]
            chown_proc = await asyncio.create_subprocess_exec(
                *chown_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await chown_proc.communicate()
        except Exception:
            # 权限设置失败不影响主要功能
            pass
        
        return container_name
    else:
        # 简单重试逻辑
        if "is already in use" in stderr.decode():
            await asyncio.sleep(0.5)
            return await get_or_create_docker_sandbox(cwd, image_name)
        raise Exception(f"Failed to create sandbox: {stderr.decode()}")


async def _exec_docker_cmd_simple(cwd: str, cmd_list: list) -> str:
    """内部辅助函数：在容器内执行简单命令并获取输出"""
    container_name = await get_or_create_docker_sandbox(cwd)
    full_cmd = ["docker", "exec", "-w", "/workspace", container_name] + cmd_list
    
    proc = await asyncio.create_subprocess_exec(
        *full_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        raise Exception(f"Command failed: {stderr.decode().strip()}")
    return stdout.decode()

# ==================== Docker 环境工具实现 (含新功能) ====================

async def docker_sandbox(command: str, background: bool = False, timeout: int = 600) -> AsyncIterator[str]:
    """
    [Docker] 沙盒执行（打平版，直接返回异步生成器）
    """
    effective_timeout = max(1, min(timeout, 3600))
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    if not cwd:
        yield "[Error] No workspace directory configured (a backend settings problem, not your task). Tell the user to set the workspace path in settings, then continue with other work."
        return
    
    try:
        container_name = await get_or_create_docker_sandbox(cwd)
    except Exception as e:
        yield f"Docker Sandbox Error: {str(e)}"
        return

    exec_cmd = [
        "docker", "exec", 
        "-i", 
        "-e", "PYTHONUNBUFFERED=1",
        "-e", "TERM=xterm",
        container_name, 
        "sh", "-c", f"cd /workspace && {command}"
    ]
    
    try:
        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if background:
            pid = await process_manager.register_process(process, f"[Docker] {command}", "docker")
            yield f"[Info] Background process started (Docker PID {pid}). It is NOT verified running yet - wait a few seconds, then check get_process_logs before relying on it."
            return

        queue = asyncio.Queue()
        async def wrap_stdout():
            async for chunk in read_stream_chunks(process.stdout, ""):
                await queue.put(chunk)
        async def wrap_stderr():
            async for chunk in read_stream_chunks(process.stderr, "[Docker stderr] "):
                await queue.put(chunk)

        stdout_task = asyncio.create_task(wrap_stdout())
        stderr_task = asyncio.create_task(wrap_stderr())

        start_time = time.time()
        try:
            while not (stdout_task.done() and stderr_task.done() and queue.empty()):
                remaining = effective_timeout - (time.time() - start_time)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    content = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield content
                except asyncio.TimeoutError:
                    continue
            
            await process.wait()

        except asyncio.TimeoutError:
            # T-2: 与本地 shell 同源的统一树 kill
            await _kill_process_tree(process)
            yield f"\n\n[TIMEOUT] The Docker command was killed after {effective_timeout} s. It did NOT finish - the step is still incomplete. Rerun the long part with 'background': true (then poll get_process_logs) or split it into shorter commands. Do not give up on the step."
            yield "\nTip: for servers/apps/large downloads use 'background': true and poll get_process_logs instead of waiting."
        finally:
            # T-2: cancel/断连/异常等任何退出路径都必须收掉 docker exec 进程与读流任务
            for _t in (stdout_task, stderr_task):
                if not _t.done():
                    _t.cancel()
            if process.returncode is None:
                await _kill_process_tree(process)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except Exception:
                pass
    except Exception as e:
        yield f"[Error] Could not start the command in the sandbox: {e}. Verify the sandbox is up (run 'echo ok') and retry - this is not a task failure."

def _patch_edit_list(old_string: str, new_string: str, edits, replace_all: bool):
    """S201：统一补丁入参——edits 数组优先，退化为单发 old/new。None=入参不合法。"""
    if edits:
        if isinstance(edits, str):
            import json as _json
            try:
                edits = _json.loads(edits)
            except Exception:
                return None
        return edits if isinstance(edits, list) and edits else None
    if old_string:
        return [{"old_string": old_string, "new_string": new_string or "",
                 "replace_all": bool(replace_all)}]
    return None


async def edit_file_patch_tool(path: str, old_string: str = "", new_string: str = "",
                               edits=None, replace_all: bool = False) -> str:
    """[Docker] S201 补丁工具：分级匹配+歧义报错+多点编辑+诊断回显（内核 py/patch_match）"""
    try:
        from py import patch_match
        edit_list = _patch_edit_list(old_string, new_string, edits, replace_all)
        if not edit_list:
            return "[Error] Provide old_string/new_string or a non-empty edits array of {old_string, new_string, replace_all?}."
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        content = await _exec_docker_cmd_simple(real_cwd, ["cat", path])
        res = patch_match.apply_edits(content, edit_list)
        if not res.ok:
            return res.report
        if not res.content:  # S309 net-zero No-op：零净改动，跳过 docker cp
            return f"'{path}' — {res.report} (sandbox)"
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8', newline='') as tmp:
            tmp.write(res.content)
            tmp_path = tmp.name
        dest_path = f"{container_name}:/workspace/{path}"
        cp_proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        await cp_proc.communicate()
        os.unlink(tmp_path)
        if cp_proc.returncode != 0:
            return "[Error] Patch copy failed."
        return f"[Success] Patched '{path}' (sandbox).\n{res.report}{_EDIT_CONTINUE_HINT}"
    except Exception as e:
        return f"[Error] Patch failed: {str(e)}"

async def glob_files_tool(pattern: str, exclude: str = "**/node_modules/**,**/.git/**,**/__pycache__/**") -> str:
    """[Docker] Glob 递归查找"""
    try:
        real_cwd = await _get_current_cwd()
        exclude_list = [e.strip() for e in exclude.split(",") if e.strip()]
        
        python_script = f'''
import glob, os, json, fnmatch
files = glob.glob("/workspace/{pattern}", recursive=True)
exclude_patterns = {exclude_list}
filtered = []
for f in files:
    if not os.path.isfile(f): continue
    rel_path = f.replace("/workspace/", "")
    should_exclude = False
    for ex in exclude_patterns:
        if fnmatch.fnmatch(rel_path, ex) or fnmatch.fnmatch(f, ex):
            should_exclude = True; break
    if not should_exclude: filtered.append(rel_path)
print(json.dumps(filtered))
'''
        output = await _exec_docker_cmd_simple(real_cwd, ["python3", "-c", python_script])
        files = json.loads(output)
        if not files: return "[Info] No files matched this pattern. Not an error: try a broader pattern (e.g. '**/*.py'); dot-directories are excluded by default."
        
        lines = [f"[{len(files)} files matched]"]
        for f in files[:50]:
            icon = "🐍" if f.endswith(".py") else "📄"
            lines.append(f"{icon} {f}")
        if len(files) > 50: lines.append(f"... {len(files)-50} more")
        return "\n".join(lines)
    except Exception as e:
        return f"[Error] Glob failed: {str(e)}"

def format_todo_snapshot_line(todos: list) -> str:
    """S183(T-B)：紧凑 todo 快照「#1[done] #2[pending] ...」（30 项截断）。
    供 todo 工具回显、再锚注记、完成闸门注记共用；纯函数。"""
    parts = []
    for t in todos or []:
        if isinstance(t, dict) and t.get("id") is not None:
            parts.append(f"#{t['id']}[{t.get('status', '?')}]")
    line = " ".join(parts[:30])
    if len(parts) > 30:
        line += f" ...(+{len(parts) - 30})"
    return line


def todo_echo(todos: list) -> str:
    """S183(T-B)：todo 工具结果全量回显后缀（opencode 式状态重锚）。"""
    line = format_todo_snapshot_line(todos or [])
    return ("\n[list] " + line) if line else ""


async def read_todo_snapshot() -> list:
    """读取当前 workspace 的 ai_todos.json 快照（供 todo_stats 事件推送）。"""
    try:
        cwd = await _get_current_cwd()
        todo_file = Path(cwd) / ".agent" / "ai_todos.json"
        if todo_file.exists():
            async with aiofiles.open(todo_file, 'r', encoding='utf-8') as f:
                content = await f.read()
            if content.strip():
                data = json.loads(content)
                if isinstance(data, list):
                    return data
    except Exception:
        pass
    try:
        real_cwd = await _get_current_cwd()
        data = await _exec_docker_cmd_simple(real_cwd, ["cat", "/workspace/.agent/ai_todos.json"])
        parsed = json.loads(data)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


async def todo_write_tool(action: str, id: str = None, content: str = None, 
                          priority: str = "medium", status: str = None) -> str:
    """[Docker] 待办任务管理工具 - 使用3位数字有序ID"""
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        todo_file = "/workspace/.agent/ai_todos.json"
        
        # 从 Docker 容器读取任务列表
        try:
            data = await _exec_docker_cmd_simple(real_cwd, ["cat", todo_file])
            todos = json.loads(data)
        except:
            todos = []
            
        msg = ""

        # 生成下一个有序ID的辅助函数
        def _generate_ordered_id(existing_todos):
            if not existing_todos:
                return "1"
            # 找出最大数字 ID（兼容旧数据）
            numeric_ids = [int(t['id']) for t in existing_todos if t['id'].isdigit()]
            if not numeric_ids:
                return "1"
            return str(max(numeric_ids) + 1)  # 1, 2, 3... 不补零，不限制位数

        if action == "create":
            """创建新任务 - 自动生成3位数字有序ID"""
            if not content: 
                return "[Error] action='create' requires a non-empty 'content'. Add the task description and retry - retrying without content will fail the same way."
            
            new_id = _generate_ordered_id(todos)
            new_todo = {
                "id": new_id,
                "content": content,
                "priority": priority,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "completed_at": None
            }
            todos.append(new_todo)
            msg = f"[Info] Created todo #{new_id}: {content[:30]}. Note: creating a todo does not advance the underlying work - execute it now if it is the next step."
            
        elif action == "list":
            """列出所有任务 - 按ID数字排序"""
            if not todos: 
                return "[Info] No todos yet. If the task has multiple steps, create them with action='create' first, then immediately start executing the first one."
            
            pending_n = sum(1 for _t in todos if _t.get("status") != "done")
            lines = [f"**Todo list**: {pending_n} pending / {len(todos) - pending_n} done (higher id = created later). If pending > 0, work the first pending item NOW - do not end your turn."]
            sorted_todos = sorted(todos, key=lambda x: int(x['id']) if x['id'].isdigit() else 0)
            
            for t in sorted_todos:
                icon = "✅" if t.get('status') == 'done' else "⏳"
                priority_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                p_icon = priority_map.get(t.get('priority', 'medium'), "⚪")
                lines.append(f"{icon} [{t['id']}] {p_icon} {t['content'][:40]} - {'DONE' if t.get('status') == 'done' else 'STILL PENDING'}")
            return "\n".join(lines)

        elif action == "complete":
            """【高频】标记任务为已完成 - 幂等操作"""
            if not id: 
                return "[Error] action='complete' requires 'id' - use the bare number shown by action='list' (e.g. 3, no zero padding)."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if target.get('status') == 'done':
                msg = f"[Info] Todo #{id} was already done. No change. Run action='list' to see remaining pending items and continue with the first one."
            else:
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Info] Todo #{id} marked done. Before ANY summary: run action='list' - if any item is still pending, start the next pending item with a tool call NOW. Do not end your turn while pending items exist."

        elif action == "toggle":
            """切换完成状态"""
            if not id: 
                return "[Error] action='toggle' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if target.get('status') != 'done':
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Info] Todo #{id} marked done. Before ANY summary: run action='list' - if any item is still pending, start the next pending item with a tool call NOW. Do not end your turn while pending items exist."
            else:
                target['status'] = 'pending'
                target['completed_at'] = None
                msg = f"[Info] Todo #{id} reopened as pending. Work on it now before anything else."

        elif action == "update":
            """编辑任务详情"""
            if not id: 
                return "[Error] action='update' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if content: 
                target['content'] = content
            if priority: 
                target['priority'] = priority
            
            if status:
                if status == "done" and target.get('status') != "done":
                    target['completed_at'] = datetime.now().isoformat()
                elif status != "done" and target.get('status') == "done":
                    target['completed_at'] = None
                target['status'] = status
            
            target['updated_at'] = datetime.now().isoformat()
            msg = f"[Info] Todo #{id} updated. Continue with the current task step."

        elif action == "delete":
            """删除任务"""
            if not id: 
                return "[Error] action='delete' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            todos.remove(target)
            msg = f"[Info] Todo #{id} deleted. Continue with the current task step."

        else:
            return f"[Error] Unknown action '{action}'. Valid actions: create, list, complete, toggle, update, delete. Pick one and retry."

        # 写回 Docker 容器
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(json.dumps(todos, indent=2, ensure_ascii=False))
            tmp_path = tmp.name
        
        await _exec_docker_cmd_simple(real_cwd, ["mkdir", "-p", "/workspace/.agent"])
        dest = f"{container_name}:{todo_file}"
        proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest, 
                                                    stdout=asyncio.subprocess.PIPE)
        await proc.wait()
        
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
            
        return msg + todo_echo(todos)  # S183(T-B): 结果回显全量状态
        
    except Exception as e:
        return f"[Error] Todo operation failed: {e}. Todo bookkeeping is NOT the task itself - continue the main work even if this fails."
    
# 恢复原有的 Docker 基础文件工具
async def list_files_tool(path: str = ".", show_all: bool = True) -> str:
    try:
        real_cwd = await _get_current_cwd()
        flag = "-laF" if show_all else "-F"
        return await _exec_docker_cmd_simple(real_cwd, ["ls", flag, path])
    except Exception as e: return str(e)

async def read_file_tool(path: str) -> str:
    """[Docker] 读取文件：增加大小限制、行宽截断及结构化提示"""
    try:
        real_cwd = await _get_current_cwd()
        
        MAX_LINES = 1000      # 最多读取行数
        MAX_LINE_WIDTH = 1000 # 单行最大字符数
        
        # 优化后的 Shell 脚本：
        # 1. 检查是否为二进制文件
        # 2. 获取总行数
        # 3. 使用 awk 处理每一行：编号、截断长行、限制总行数
        script = f"""
        FILE="{path}"
        if [ ! -f "$FILE" ]; then echo "[Error] File not found: $FILE"; exit 0; fi
        
        # 检查是否为二进制 (grep -I 返回非0表示二进制)
        if ! grep -qI . "$FILE"; then
            echo "[Error] Cannot read binary file: $FILE"
            exit 0
        fi

        total=$(wc -l < "$FILE" 2>/dev/null || echo 0)
        
        # 使用 awk 进行高效处理
        awk -v max_w={MAX_LINE_WIDTH} -v max_l={MAX_LINES} '
        NR <= max_l {{
            line = $0;
            if (length(line) > max_w) {{
                line = substr(line, 1, max_w) " ... [Line Truncated]";
            }}
            printf "%6d | %s\\n", NR, line;
        }}
        NR > max_l {{ exit }}
        ' "$FILE"

        if [ "$total" -gt {MAX_LINES} ]; then
            echo ""
            echo "... [Warning] File truncated. Showing 1 to {MAX_LINES} of $total lines."
            echo "💡 [Next Step Hint] The file is large. Use 'read_file_range' to read specific lines (e.g., 1001-2000) or 'tail_file' for the end."
        fi
        """
        return await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
    except Exception as e: 
        return f"[Error] Read failed: {str(e)}"

async def read_file_range_tool(path: str, start_line: int, end_line: Optional[int] = None) -> str:
    """[Docker] 精准读取文件指定行范围，利用 awk 进行服务端截断"""
    try:
        if start_line < 1 or (end_line is not None and end_line < start_line):
            return "[Error] Invalid line range."
        
        real_cwd = await _get_current_cwd()
        # awk 逻辑说明：
        # 1. 指定行范围 NR>=start && NR<=end；end_line 缺省=读到文件尾（S212，与 schema 描述对齐）
        # 2. 如果行长度 > 1000，使用 substr 截断
        # 3. 格式化输出 行号 | 内容
        max_line_len = 1000
        _awk_range = f"NR>={start_line} && NR<={end_line}" if end_line is not None else f"NR>={start_line}"
        script = (
            f"awk '{_awk_range} {{"
            f"  line=$0; "
            f"  if (length(line) > {max_line_len}) "
            f"    line = substr(line, 1, {max_line_len}) \"... [Truncated]\"; "
            f"  printf \"%5d | %s\\n\", NR, line"
            f"}}' \"{path}\""
        )
        
        result = await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
        
        # 兜底：防止 Docker 返回的结果依然由于行数过多导致爆炸
        if len(result) > 50000:
            return result[:50000] + "\n... [Warning] Output truncated by tool safety limit."
        return result
    except Exception as e: 
        return str(e)

async def tail_file_tool(path: str, lines: int = 100) -> str:
    """[Docker] 读取文件末尾（常用于日志）"""
    try:
        real_cwd = await _get_current_cwd()
        # 先打行号，再 tail
        script = f"""cat -n "{path}" | tail -n {lines}"""
        return await _exec_docker_cmd_simple(real_cwd, ["sh", "-c", script])
    except Exception as e: return str(e)

async def edit_file_tool(path: str, content: str) -> str:
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        await _exec_docker_cmd_simple(real_cwd, ["mkdir", "-p", os.path.dirname(path) or "."])
        dest = f"{container_name}:/workspace/{path}"
        proc = await asyncio.create_subprocess_exec("docker", "cp", tmp_path, dest, stdout=asyncio.subprocess.PIPE)
        await proc.wait()
        os.unlink(tmp_path)
        return f"[Success] Saved {path}.{_EDIT_CONTINUE_HINT}"
    except Exception as e: return str(e)

async def search_files_tool(pattern: str, path: str = ".") -> str:
    try:
        real_cwd = await _get_current_cwd()
        return await _exec_docker_cmd_simple(real_cwd, ["grep", "-rn", pattern, path])
    except Exception as e: return str(e)


# ==================== [新增] 管理工具：进程与网络 ====================

async def list_processes_tool() -> str:
    """[Common] 列出所有后台进程 (Docker & 本地)"""
    return process_manager.list_processes()

async def get_process_logs_tool(pid: str) -> str:
    """[Common] 获取指定进程的日志"""
    if not pid:
        return "Error: 'pid' is required to fetch logs."
    return process_manager.get_logs(pid)

async def kill_process_tool(pid: str) -> str:
    """[Common] 终止指定的后台进程"""
    if not pid:
        return "Error: 'pid' is required to kill a process."
    return await process_manager.kill_process(pid)

async def docker_manage_ports_tool(action: str, container_port: int = 8000, host_port: int = None) -> str:
    """[Docker] 端口转发管理"""
    try:
        real_cwd = await _get_current_cwd()
        container_name = await get_or_create_docker_sandbox(real_cwd)
        
        if container_name not in DOCKER_PROXIES:
            DOCKER_PROXIES[container_name] = DockerPortProxy(container_name)
        proxy = DOCKER_PROXIES[container_name]
        
        if action == "list":
            return proxy.list_proxies()
        if action == "forward":
            if not host_port: host_port = container_port
            return await proxy.start_forward(host_port, container_port)
        if action == "stop":
            if not host_port: return "Error: host_port required to stop."
            return await proxy.stop_forward(host_port)
        return "[Error] Unknown action. Valid port actions: forward, stop, list. Pick one and retry."
    except Exception as e:
        return f"[Error] Port tool failed: {str(e)}"

async def local_net_tool(action: str, port: int = None) -> str:
    """[Local] 本地网络工具：检查端口占用"""
    if action == "check":
        if not port: return "Error: Port required."
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('127.0.0.1', port))
            status = "OPEN/BUSY" if result == 0 else "CLOSED/FREE"
            return f"Port {port} on localhost is {status}."
    
    if action == "scan":
        # 简单扫描常用开发端口
        common_ports = [3000, 5000, 8000, 8080, 80, 443, 3306, 5432]
        results = []
        for p in common_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                res = s.connect_ex(('127.0.0.1', p))
                status = "BUSY" if res == 0 else "FREE"
                results.append(f"{p}: {status}")
        return "Common Ports:\n" + "\n".join(results)
        
    return "Unknown action. Use check or scan."

# ==================== 本地环境 (Local) 工具实现 ====================

def resolve_strict_path(cwd: str, sub_path: str, check_symlink: bool = True) -> Path:
    """
    严格工作区路径解析
    - 禁止绝对路径
    - 禁止 ../ 遍历  
    - 禁止通过符号链接指向工作区外
    - S153: 以上区外形态若命中 path_scope GRANTS（用户在路径门单独批复/
      allowed_dirs/yolo），按解析后真实路径放行；symlink 经 resolve 后参与
      授权匹配，链接逃逸无法借 grants 之外的路径混入。
    """
    base = Path(cwd).resolve()
    
    if not sub_path:
        return base
        
    # 清理输入（阻止空字节、换行等）
    sub_path = sub_path.strip().replace('\x00', '').replace('\n', '')
    
    traversal = '..' in sub_path.split(os.sep) or '..' in sub_path.split('/')
    absolute = os.path.isabs(sub_path) or (len(sub_path) > 1 and sub_path[1] == ':')

    if not traversal and not absolute:
        # 常规区内路径：先按旧规则快速通过（行为与 S153 前完全一致）
        target = (base / sub_path).resolve()
        try:
            target.relative_to(base)
            # 符号链接检查（防止 /workspace/link -> /etc）
            if check_symlink and target.exists():
                real_path = target.resolve(strict=True)
                try:
                    real_path.relative_to(base)
                except ValueError:
                    raise PermissionError(f"Symlink escape detected: {sub_path} -> {real_path}")
            return target
        except ValueError:
            pass  # 区内符号链接指向区外等 → 落入区外判定（GRANTS 或原拒绝）

    from py import path_scope
    cand = Path(sub_path) if absolute else (base / sub_path)
    try:
        target = cand.expanduser().resolve()
    except Exception:
        target = cand
    if path_scope.grants_allow(str(target)):
        return target

    # 显式拒绝（错误消息与 S153 前保持一致）
    if traversal:
        raise PermissionError(f"Path traversal detected: {sub_path}")
    if absolute:
        raise PermissionError(f"Absolute paths not allowed: {sub_path}")
    raise PermissionError(f"Access denied: {sub_path} resolves outside workspace")

from typing import Tuple

def validate_bash_command(command: str, cwd: str, mode: str = "default") -> Tuple[bool, str]:
    """
    增强版安全校验策略（支持 Win/Mac/Linux 跨平台）
    """
    cmd_lower = command.lower()
    
    # ===== 1. 路径穿越与敏感目录防御 =====
    # 防止多级向上跳转逃逸工作区 (例如 ../../../etc/passwd)
    if re.search(r'(\.\.[/\\]){2,}', command):
        return False, "Multiple path traversal (../../) is blocked"

    # 跨平台敏感目录 (兼容 / 和 \ 写法)
    sensitive_roots = [
        # Linux / macOS
        r'(?:\s|^)/etc', r'(?:\s|^)/var', r'(?:\s|^)/root', 
        r'(?:\s|^)/bin', r'(?:\s|^)/sbin', r'(?:\s|^)/usr/local/bin',
        r'(?:\s|^)/sys', r'(?:\s|^)/proc', 
        # macOS 专属
        r'(?:\s|^)/Library', r'(?:\s|^)/System',
        # Windows (兼容 C:\Windows 和 C:/Windows)
        r'(?:\s|^)[a-z]:[/\\]Windows', r'(?:\s|^)[a-z]:[/\\]Program Files', 
        r'(?:\s|^)[a-z]:[/\\]Users[/\\](?:Default|Public|Administrator)' 
    ]
    
    for pattern in sensitive_roots:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Access to sensitive system directory blocked by pattern: {pattern}"

    # 禁止直接 cd 到根目录或其他盘符
    if re.search(r'\bcd\s+/[a-z0-9_]*$', command, re.IGNORECASE):
        return False, "Changing directory to root is blocked"
    if re.search(r'\bcd\s+[a-z]:[/\\]', command, re.IGNORECASE):
        return False, "Changing Windows drive directly is blocked"

    # ===== 2. 跨平台毁灭性操作 =====
    destructive_patterns = [
        # Linux/Mac 文件删除 (覆盖 rm -rf /, rm -rf /*, rm -r -f /)
        (r'rm\s+-[rRfF\s]+\s*(/|[a-z]:[/\\])\*?', "Recursive delete root"),
        # Linux 危险操作
        (r'mkfs\.[a-z]+', "Filesystem format"),                    
        (r'dd\s+if=.*of=/dev/[a-z]', "Direct device write"),       
        (r'>?\s*/dev/(sda|hd|nvme|mmcblk)', "Block device access"),
        (r'chmod\s+-[R\s]*777\s+/', "Change root permissions"),
        (r'chown\s+-[R\s]*root\s+/', "Change root ownership"),
        (r':\(\)\{\s*:\|:&?\s*\};\s*:', "Fork bomb"), 
        # Windows 危险操作 (注册表破坏、危险格式化)
        (r'(?:\s|^)format\s+[a-z]:', "Windows disk format"),
        (r'(?:\s|^)reg\s+(delete|add)\s+(HKLM|HKEY_LOCAL_MACHINE)', "Modify system registry"),
        (r'Remove-Item\s+-Recurse\s+-Force\s+[a-z]:[/\\]', "Powershell recursive delete root"),
        # macOS 危险操作
        (r'nvram\s+-c', "Clear Mac NVRAM"),
    ]
    
    for pattern, reason in destructive_patterns:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Destructive operation blocked: {reason}"
    
    # ===== 3. 风险操作 (提权、钓鱼、远程执行) =====
    if mode != "yolo":
        risk_patterns = [
            # Linux/Mac 提权与远程加载
            (r'(?:\s|^)sudo\s+', "sudo usage blocked (prevents password wait/escalation)"),
            (r'(curl|wget).*\|\s*(sh|bash|zsh|python|perl|php)', "Remote execution via pipe"),
            (r'\$\{?HOME\}?', "HOME env variable usage"),
            (r'~\s*/', "Home directory access via ~"),
            # macOS 钓鱼警告 (防范 AI 弹窗骗取用户密码)
            (r'(?:\s|^)osascript\s+-e\s+.*password', "AppleScript password prompt blocked"),
            # Windows 远程加载 (Powershell IEX)
            (r'(Invoke-WebRequest|iwr|Invoke-RestMethod|irm).*\|\s*(Invoke-Expression|iex)', "PowerShell remote script execution"),
        ]
        for pattern, reason in risk_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False, f"{reason} blocked in {mode} mode"
    
    return True, command

# ===== 修复乱码：增加 GBK 解码支持 =====
async def read_stream(stream, *, is_error: bool = False):
    """读取流并添加错误前缀，支持 Windows 中文编码"""
    if stream is None:
        return
    async for line in stream:
        prefix = "[ERROR] " if is_error else ""
        
        # Windows 中文系统通常用 GBK，先尝试 UTF-8，失败则尝试 GBK
        try:
            decoded = line.decode('utf-8').rstrip()
        except UnicodeDecodeError:
            try:
                decoded = line.decode('gbk').rstrip()
            except:
                decoded = line.decode('utf-8', errors='replace').rstrip()
                
        yield f"{prefix}{decoded}"


async def _kill_process_tree(process, system=None):
    """T-2: 杀整棵进程树。Windows=taskkill /T /F；POSIX=killpg（spawn 侧已
    start_new_session=独立进程组，杀组覆盖全部孙进程）。幂等、异常静默。"""
    try:
        if process.returncode is not None:
            return
        system = system or platform.system()
        if system == "Windows":
            await asyncio.to_thread(
                subprocess.run, f"taskkill /F /T /PID {process.pid}",
                shell=True, capture_output=True)
        else:
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
            except Exception:
                process.kill()
    except Exception:
        pass


async def shell_tool_local(command: str, background: bool = False, timeout: int = 600) -> AsyncIterator[str]:
    """
    [Local] 执行本地命令（支持动态超时）
    """
    # 限制超时范围：1秒到1小时
    effective_timeout = max(1, min(timeout, 3600))
    
    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    perm = normalize_permission_mode(settings.get("localEnvSettings", {}).get("permissionMode", "default"))
    
    if not cwd: 
        yield "[Error] No workspace directory configured (a backend settings problem, not your task). Tell the user to set the workspace path in settings, then continue with other work."
        return
    
    allowed, result = validate_bash_command(command, cwd, mode=perm)
    if not allowed:
        yield f"[Security] Command blocked: {result}. Adjust the command to avoid this pattern (e.g. stay inside the workspace) instead of stopping; do not attempt to bypass the guard."
        return
    
    system = platform.system()
    if system == "Windows":
        def is_strictly_cmd(cmd_str: str) -> bool:
            c = cmd_str.lower().strip()
            if re.search(r'%[a-z0-9_]+%', c): return True
            if '&&' in c and '$' not in c: return True
            return False
        if is_strictly_cmd(command):
            exe, args = "cmd.exe", ["/c", command]
        else:
            exe, args = "powershell.exe", ["-NonInteractive", "-NoProfile", "-Command", command]
    else:
        exe, args = os.environ.get('SHELL', '/bin/bash'), ["-c", command]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm"

    try:
        process = await asyncio.create_subprocess_exec(
            exe, *args,
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env, # 使用修改后的 env
            start_new_session=(system != "Windows")
        )

        if background:
            pid = await process_manager.register_process(process, command, "local")
            yield f"[Info] Background process started (PID {pid}). It is NOT verified running yet - wait a few seconds, then call get_process_logs with this PID to confirm before continuing."
            return

        queue = asyncio.Queue()
        async def wrap_stdout():
            async for chunk in read_stream_chunks(process.stdout, ""):
                await queue.put(chunk)
        async def wrap_stderr():
            async for chunk in read_stream_chunks(process.stderr, "[stderr] "):
                await queue.put(chunk)

        stdout_task = asyncio.create_task(wrap_stdout())
        stderr_task = asyncio.create_task(wrap_stderr())

        start_time = time.time()
        try:
            while not (stdout_task.done() and stderr_task.done() and queue.empty()):
                # 使用传入的 effective_timeout
                remaining = effective_timeout - (time.time() - start_time)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    content = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield content
                except asyncio.TimeoutError:
                    continue

            await process.wait()
            if process.returncode != 0:
                yield f"\n--- Command exited with code {process.returncode} (NON-ZERO means this step FAILED: read the output above, adjust and retry with a changed command; zero means this step succeeded - continue the task, do not summarize yet) ---"
                yield get_detailed_exit_info(process.returncode, command)
        except asyncio.TimeoutError:
            # T-2: 统一走进程树 kill（与原逻辑同源）
            await _kill_process_tree(process, system)
            yield f"\n\n[TIMEOUT] The command was killed after {effective_timeout} s. It did NOT finish - the step is still incomplete. Rerun the long part with 'background': true (then poll get_process_logs) or split it into shorter commands. Do not give up on the step."
            yield "\nTip: for servers/apps/large downloads use 'background': true and poll get_process_logs instead of waiting."
        finally:
            # T-2: 任何退出路径（cancel 围栏 break / 前端断连 GeneratorExit /
            # 异常）都必须杀进程树+收读流任务——取消只拦新调用的漏洞封堵
            for _t in (stdout_task, stderr_task):
                if not _t.done():
                    _t.cancel()
            if process.returncode is None:
                await _kill_process_tree(process, system)
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
            except Exception:
                pass
    except Exception as e: 
        yield f"[Error] Could not launch the process: {e}. Simplify the command and retry; this is not a task failure."


async def shell_tool_wsl(command: str, background: bool = False, timeout: int = 600) -> AsyncIterator[str]:
    """
    [WSL] 通过 WSL2 沙盒执行命令。
    使用 wsl.exe 调用 WSL 内的 bash，结合 bubblewrap 提供额外的进程级沙盒隔离。
    """
    effective_timeout = max(1, min(timeout, 3600))

    settings = await load_settings()
    cwd = settings.get("CLISettings", {}).get("cc_path")
    perm = settings.get("wslSettings", {}).get("permissionMode", "default")

    if not cwd:
        yield "Error: No workspace directory specified (cc_path)."
        return

    allowed, validate_result = validate_bash_command(command, cwd, mode=perm)
    if not allowed:
        yield f"[Security] Command blocked: {validate_result}"
        return

    if platform.system() != "Windows":
        yield "[Error] WSL engine is only available on Windows."
        return

    if not _check_wsl_available():
        yield "[Error] WSL is not available. Please ensure WSL2 is installed and running."
        return

    bwrap_ok, bwrap_msg = await _ensure_bubblewrap_in_wsl()
    if not bwrap_ok:
        yield f"[Warning] {bwrap_msg}\n"
        yield "[Warning] Proceeding without extra sandboxing.\n\n"
    else:
        yield f"[WSL Sandbox] {bwrap_msg}\n\n"

    wsl_cwd = _windows_to_wsl_path(cwd)

    wrapped_command = f"cd {wsl_cwd} && {command}"

    exec_cmd = [
        "wsl.exe", "-e", "bash", "-c", wrapped_command
    ]

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm"

    try:
        process = await asyncio.create_subprocess_exec(
            *exec_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        if background:
            pid = await process_manager.register_process(process, f"[WSL] {command}", "wsl")
            yield f"[SUCCESS] WSL Background Process PID: {pid}"
            return

        queue = asyncio.Queue()
        async def wrap_stdout():
            async for chunk in read_stream_chunks(process.stdout, ""):
                await queue.put(chunk)
        async def wrap_stderr():
            async for chunk in read_stream_chunks(process.stderr, "[WSL stderr] "):
                await queue.put(chunk)

        stdout_task = asyncio.create_task(wrap_stdout())
        stderr_task = asyncio.create_task(wrap_stderr())

        start_time = time.time()
        try:
            while not (stdout_task.done() and stderr_task.done() and queue.empty()):
                remaining = effective_timeout - (time.time() - start_time)
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    content = await asyncio.wait_for(queue.get(), timeout=0.1)
                    yield content
                except asyncio.TimeoutError:
                    continue

            await process.wait()
            if process.returncode != 0:
                yield f"\n--- 运行结束 (Exit Code: {process.returncode}) ---"
                yield get_detailed_exit_info(process.returncode, command)

        except asyncio.TimeoutError:
            subprocess.run(f"taskkill /F /T /PID {process.pid}", shell=True, capture_output=True)
            yield f"\n\n[TIMEOUT ERROR] WSL 命令执行超过 {effective_timeout} 秒已强制终止。"
            yield "\n提示：对于长期运行的任务，请使用 'background': true。"

    except Exception as e:
        yield f"[WSL 系统错误] 无法启动进程: {str(e)}"

# 恢复原有的 Local 文件工具
async def list_files_tool_local(path: str = ".", show_all: bool = True) -> str:
    """[Local] 列出文件：优先显示目录，支持数量截断，过滤隐藏文件"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        if not target.is_dir():
            return f"[Info] '{path}' is a file, not a directory - nothing to list. To inspect its contents, call the read_file tool with the same path."

        # 使用 scandir 获取更详细的信息且速度更快
        entries = []
        try:
            with os.scandir(target) as it:
                for entry in it:
                    if not show_all and entry.name.startswith('.'):
                        continue
                    
                    is_dir = entry.is_dir()
                    # 格式：(是否目录, 排序名, 显示字符串)
                    # 目录排在前面 (0)，文件排在后面 (1)
                    display_name = f"{entry.name}/" if is_dir else entry.name
                    entries.append((0 if is_dir else 1, entry.name.lower(), display_name))
        except PermissionError:
            return f"[Error] Permission denied accessing: {path}. Skip this directory and continue with another path."

        # 排序：先按目录/文件分，再按名称字母序
        entries.sort()

        # 数量截断防止 Token 爆炸
        MAX_ITEMS = 200
        result_lines = [e[2] for e in entries[:MAX_ITEMS]]
        
        summary = f"Total: {len(entries)} items"
        if len(entries) > MAX_ITEMS:
            summary += f" (Showing first {MAX_ITEMS})"
            result_lines.append(f"... {len(entries) - MAX_ITEMS} more items")
        
        return f"{summary} in {path}:\n" + "\n".join(result_lines) if result_lines else "This directory has 0 entries. Note: this listing is NOT recursive - files in subfolders are not shown. Use the glob tool (**/*) to confirm before concluding the area is empty."

    except Exception as e:
        return f"[Error] List failed: {str(e)}"

def _format_line(line_number: int, content: str, max_line_chars: int = 1000) -> str:
    """格式化单行，如果太长则截断"""
    content = content.rstrip('\r\n')
    if len(content) > max_line_chars:
        # 截断并保留前后部分，中间提示
        half = max_line_chars // 2
        content = f"{content[:half]} ... [Truncated {len(content)-max_line_chars} chars] ... {content[-50:]}"
    return f"{line_number:5} | {content}"

async def read_file_tool_local(path: str) -> str:
    """[Local] 读取文件：支持大文件截断及长行截断"""
    try:
        MAX_LINES = 1000
        MAX_LINE_CHARS = 1000
        MAX_TOTAL_CHARS = 50000
        
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        if not target.exists() or not target.is_file():
            return f"[Error] File not found: {path}"

        # 二进制检查保持不变...
        with open(target, 'rb') as f_bin:
            if b'\0' in f_bin.read(1024):
                return f"[Error] Cannot read binary file: {path}"

        output = []
        current_total_len = 0
        truncated = False
        
        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            line_idx = 1
            async for line in f:
                formatted = _format_line(line_idx, line, MAX_LINE_CHARS)
                output.append(formatted)
                current_total_len += len(formatted)
                
                if line_idx >= MAX_LINES or current_total_len > MAX_TOTAL_CHARS:
                    truncated = True
                    break
                line_idx += 1

        res = "\n".join(output)
        if truncated:
            res += f"\n\n... [Warning] Content truncated (Safety Limit). Last line read: {line_idx}."
            res += f"\n💡 [Hint] The file is large or has very long lines. Use 'read_file_range_local' to explore specific sections."
            
        return res
    except Exception as e: 
        return f"[Error] Read failed: {str(e)}"  

async def read_file_range_tool_local(path: str, start_line: int = 1, end_line: Optional[int] = None,
                                     symbol: str = "") -> str:
    """[Local] 精准读取文件指定行范围，增加溢出保护；
    S251: symbol=方法/函数名时自动定位并返回其完整定义块（大括号配平/Python 缩进）。"""
    try:
        MAX_TOTAL_CHARS = 30000  # 单次返回最大字符数，防止上下文爆炸
        MAX_LINE_CHARS = 1000    # 单行最大显示长度
        header = ""

        if not str(symbol or "").strip() and (start_line < 1 or (end_line is not None and end_line < start_line)):
            return "[Error] Invalid line range."

        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        if not target.exists() or not target.is_file():
            return f"[Error] File not found: {path}"

        sym = str(symbol or "").strip()
        if sym:
            if target.stat().st_size > 4 * 1024 * 1024:
                return "[Error] symbol 定位要求文件 ≤4MB；超大文件请先 search_files_tool_local 拿行号再用 start_line。"
            raw = await asyncio.to_thread(target.read_text, "utf-8", "replace")
            lines = raw.splitlines()
            from py.symbol_tools import find_symbol_block
            res = find_symbol_block(lines, sym, is_py=target.suffix.lower() in (".py", ".pyw"))
            if res.start is None:
                if res.candidates:
                    cands = "\n".join(f"  L{i + 1}: {lines[i].strip()[:110]}" for i in res.candidates)
                    return (f"[Error] symbol '{sym}': 未找到定义行，仅找到引用点(前{len(res.candidates)})：\n{cands}\n"
                            "Tip: 若目标是变量/常量请用 search_files_tool_local；定义在其他文件时先按引用点追。")
                return f"[Error] symbol '{sym}': 文件中无任何出现。"
            start_line = res.start + 1
            end_line = res.end + 1
            header = (f"[symbol] {sym} → L{res.start + 1}-L{res.end + 1} "
                      f"({res.end - res.start + 1} 行, {res.how})\n")

        output = []
        current_total_len = 0
        
        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            line_idx = 1
            async for line in f:
                if line_idx >= start_line:
                    formatted = _format_line(line_idx, line, MAX_LINE_CHARS)
                    output.append(formatted)
                    current_total_len += len(formatted)
                    
                    if current_total_len > MAX_TOTAL_CHARS:
                        output.append(f"--- [Warning] Output stopped: Reached limit of {MAX_TOTAL_CHARS} chars ---")
                        break
                
                if end_line is not None and line_idx >= end_line:
                    break
                line_idx += 1
            
        if not output and line_idx < start_line:
            return f"[Error] start_line ({start_line}) is beyond file length ({line_idx})."

        return header + "\n".join(output)
    except Exception as e: 
        return f"[Error] Range read failed: {str(e)}"

async def tail_file_tool_local(path: str, lines: int = 100) -> str:
    """[Local] 读取文件末尾（常用于日志）"""
    try:
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        if not target.exists() or not target.is_file(): return f"[Error] File not found: {path}"

        # 本地简单实现：读入后切片（如果文件极大建议改用 seek 倒序读，但此处通常够用）
        async with aiofiles.open(target, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = await f.readlines()
            
        subset = all_lines[-lines:] if lines < len(all_lines) else all_lines
        start_idx = max(1, len(all_lines) - lines + 1)
        
        return "\n".join(f"{i + start_idx:4} | {line.rstrip('\n')}" for i, line in enumerate(subset))
    except Exception as e: return f"[Error] Tail failed: {str(e)}"

async def edit_file_tool_local(path: str, content: str) -> str:
    """[Local] 写入文件：修复了绝对路径误判问题"""
    try:
        cwd = await _get_current_cwd()
        # 这一步已经确保了 path 不会逃逸出 cwd
        target = resolve_strict_path(cwd, path, check_symlink=True)
        
        # 1. 确保父目录存在
        parent_dir = target.parent
        # --- 删除了导致报错的 resolve_strict_path(cwd, str(parent_dir)...) ---
        
        await aiofiles.os.makedirs(parent_dir, exist_ok=True)

        # 1.5 S309：内容与此前完全一致 → No-op，不备份不落盘（终结整文件重写循环）
        if target.exists():
            try:
                _existing = await aiofiles.open(target, 'r', encoding='utf-8', errors='replace')
                async with _existing as f:
                    _old_text = await f.read()
                if _old_text.replace("\r\n", "\n") == content.replace("\r\n", "\n"):
                    return (f"[No-op] '{path}' already contains EXACTLY this content; nothing was "
                            "written. Do NOT repeat this call — run/verify the file state instead.")
            except Exception as e:
                logging.getLogger("app").info(f"[Warn] No-op precheck skipped: {e}")

        # 2. 创建备份 (如果文件存在)
        backup_msg = ""
        if target.exists():
            try:
                backup_path = target.with_suffix(target.suffix + ".bak")
                shutil.copy2(target, backup_path)
                backup_msg = f" (Backup created: {backup_path.name})"
            except Exception as e:
                logging.getLogger("app").info(f"[Warn] Backup failed: {e}")

        # 3. 原子写入
        temp_path = target.with_suffix(target.suffix + f".tmp.{uuid.uuid4().hex[:6]}")
        try:
            async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                await f.write(content)
            
            if os.path.exists(target):
                os.replace(temp_path, target)
            else:
                os.rename(temp_path, target)
        except Exception as e:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise e

        return f"[OK] Saved '{path}'{backup_msg}.{_EDIT_CONTINUE_HINT}"

    except Exception as e:
        return f"[Error] Edit failed: {str(e)}"

# ---- S184 helpers ----
_SEARCH_SKIP_DIRS = {'.git', 'node_modules', '__pycache__', 'venv', '.venv', '.env',
                     'dist', 'build', 'out', 'target', 'coverage', '.tox',
                     '.mypy_cache', '.pytest_cache', '.ruff_cache', '.next',
                     '.svelte-kit', '.turbo', '.idea', '.vscode'}
_SEARCH_SKIP_EXTS = {'.pyc', '.pyo', '.so', '.dll', '.exe', '.bin', '.zip', '.tar',
                     '.gz', '.7z', '.rar', '.png', '.jpg', '.jpeg', '.gif', '.webp',
                     '.ico', '.woff', '.woff2', '.ttf', '.eot', '.pdf', '.mp3',
                     '.mp4', '.avi', '.mov', '.class', '.jar', '.db', '.sqlite'}
_SEARCH_MAX_FILE_BYTES = 5 * 1024 * 1024
_SEARCH_MAX_LINE_CHARS = 200
_NO_MATCH_HINT = ("No matches for this pattern. This does NOT mean the code is absent: "
                  "try a shorter substring, a different identifier, or the glob tool by "
                  "filename before concluding it is missing. Directories like node_modules/"
                  ".venv/.git are skipped by design.")


def _search_include_match(rel_posix: str, include: str) -> bool:
    """include = 逗号/分号分隔 glob（匹配相对路径或文件名）。空串=全放行。"""
    pats = [p.strip().replace("\\", "/")
            for p in (include or "").replace(";", ",").split(",") if p.strip()]
    if not pats:
        return True
    base = rel_posix.rsplit("/", 1)[-1]
    for p in pats:
        if fnmatch.fnmatch(rel_posix, p) or fnmatch.fnmatch(base, p):
            return True
        if p.startswith("**/") and fnmatch.fnmatch(rel_posix, p[3:]):
            return True
    return False


def _search_row_key(row: str):
    m = re.match(r"^(.+?):(\d+):", row)
    return (m.group(1), int(m.group(2))) if m else (row, 0)


def _format_search_rows(rows, skip, limit, capped) -> str:
    if not rows and skip == 0:
        return _NO_MATCH_HINT
    page = rows[skip:skip + limit]
    if not page:
        return f"(No more results at offset={skip}; {len(rows)} collected.)"
    tail = ""
    if skip + limit < len(rows) or capped:
        tail = (f"\n... showing {len(page)} of {len(rows)}+ collected (offset={skip}). "
                f"Continue with offset={skip + limit}, or narrow path/include.")
    return "\n".join(page) + tail


def _rg_search_collect(rg, cwd, target_str, pattern, include, ignore_case, want):
    """ripgrep 子进程收集（同步，调用方 to_thread）。rg 异常/超时返回 (None, False) → 上层降级。"""
    cmd = [rg, "--line-number", "--no-heading", "--color", "never", "-I",
           "--max-columns", "240", "--max-columns-preview"]
    if ignore_case:
        cmd.append("-i")
    pats = [p.strip() for p in (include or "").replace(";", ",").split(",") if p.strip()]
    for p in pats:
        cmd += ["--glob", p]
    cmd += ["-e", pattern]
    try:
        rel = os.path.relpath(target_str, cwd)
    except Exception:
        rel = "."
    if rel != ".":
        cmd += ["--", rel]
    try:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              errors="replace", timeout=60)
    except Exception:
        return None, False
    if proc.returncode not in (0, 1):  # 1=无匹配（正常）；其余=rg 出错 → 降级
        return None, False
    rows = []
    for line in (proc.stdout or "").splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        relp = m.group(1).replace("\\", "/")
        rows.append(f"{relp}:{m.group(2)}:{m.group(3).strip()[:_SEARCH_MAX_LINE_CHARS]}")
        if len(rows) >= want:
            break
    rows.sort(key=_search_row_key)
    return rows, len(rows) >= want


def _py_search_collect(cwd, target_str, regex, include, want):
    """并行 Python 扫描回退（同步，调用方 to_thread）。文件序排序保证 offset 分页可重复。"""
    import threading
    from concurrent.futures import ThreadPoolExecutor

    files = []
    for root, dirs, names in os.walk(target_str, topdown=True):
        # 剪枝：.agent 为工作区内容目录，放行
        dirs[:] = [d for d in dirs
                   if d not in _SEARCH_SKIP_DIRS and (not d.startswith('.') or d == '.agent')]
        for n in names:
            if any(n.lower().endswith(e) for e in _SEARCH_SKIP_EXTS):
                continue
            full = os.path.join(root, n)
            rel = os.path.relpath(full, cwd).replace("\\", "/")
            if _search_include_match(rel, include):
                files.append((full, rel))
    files.sort(key=lambda t: t[1])

    lock = threading.Lock()
    stop = threading.Event()
    out = []

    def scan(full, rel):
        if stop.is_set():
            return
        try:
            if os.path.getsize(full) > _SEARCH_MAX_FILE_BYTES:
                return
            with open(full, 'rb') as fb:
                if b'\0' in fb.read(1024):
                    return
            local = []
            with open(full, 'r', encoding='utf-8', errors='replace') as f:
                for i, line in enumerate(f, 1):
                    if regex.search(line):
                        local.append(f"{rel}:{i}:{line.strip()[:_SEARCH_MAX_LINE_CHARS]}")
                        if len(local) >= want:
                            break
            if local:
                with lock:
                    out.extend(local)
                    if len(out) >= want:
                        stop.set()
        except (OSError, UnicodeError):
            return

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda t: scan(*t), files))
    rows = sorted(out, key=_search_row_key)[:want]
    return rows, len(out) >= want


async def search_files_tool_local(pattern: str = "", path: str = ".", include: str = "",
                                  max_results: int = 200, offset: int = 0,
                                  case_insensitive: bool = False, patterns=None) -> str:
    """[Local] S184 跨平台内容检索；S251 支持 patterns=[...] 多模式一次查（分组返回）。"""
    plist = []
    if isinstance(patterns, (list, tuple)):
        plist = [str(p).strip() for p in patterns if str(p or "").strip()]
    p0 = str(pattern or "").strip()
    if p0:
        plist = [p0] + plist
    if not plist:
        return "[Error] search_files_tool_local: 'pattern' (or non-empty 'patterns') is required."
    if len(plist) == 1:
        return await _search_one(plist[0], path, include, max_results, offset, case_insensitive)
    try:
        per = max(10, min(int(max_results or 200), 100))
    except (TypeError, ValueError):
        per = 100
    out = []
    for i, pat in enumerate(plist[:10], 1):
        r = await _search_one(pat, path, include, per, 0, case_insensitive)
        out.append(f"=== [{i}/{min(len(plist), 10)}] pattern: {pat} ===\n{r}")
    tail = ""
    if len(plist) > 10:
        tail = f"\n[多模式上限 10 个，忽略 {len(plist) - 10} 个；各组独立限额 {per}，如需续查请单模式+offset]"
    return "\n\n".join(out) + tail


async def _search_one(pattern: str, path: str = ".", include: str = "",
                      max_results: int = 200, offset: int = 0,
                      case_insensitive: bool = False) -> str:
    """S184 跨平台内容检索：优先 ripgrep（SAP_RG_PATH → 数据目录 bin → PATH），
    未安装则走并行 Python 扫描。两引擎统一 Python re 语义（旧 git grep BRE 混用语义已除），
    统一输出 path:line:text，支持 include 过滤与 offset 分页续查。"""
    try:
        cwd = await _get_current_cwd()
        target_dir = resolve_strict_path(cwd, path, check_symlink=True)
        target_str = str(target_dir)

        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            limit = 200
        limit = max(1, min(limit, 1000))
        try:
            skip = int(offset)
        except (TypeError, ValueError):
            skip = 0
        skip = max(0, skip)

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as re_err:
            return (f"[Error] Invalid regex: {re_err}. The pattern uses Python re syntax "
                    "(a plain substring works too) — escape ( ) [ ] { } * + ? ^ $ | when "
                    "matching them literally, or search a shorter plain substring.")

        rows, capped = None, False
        from py.tool_output_store import find_ripgrep
        rg = find_ripgrep()
        if rg:
            rows, capped = await asyncio.to_thread(
                _rg_search_collect, rg, cwd, target_str, pattern, include,
                bool(case_insensitive), skip + limit + 1)
        if rows is None:
            rows, capped = await asyncio.to_thread(
                _py_search_collect, cwd, target_str, regex, include, skip + limit + 1)
        return _format_search_rows(rows, skip, limit, capped)
    except Exception as e:
        return f"[Error] Search failed: {str(e)}"


def _normalize_glob_pattern(pattern: str, cwd: str) -> str:
    p = str(pattern or "").strip().replace("\\", "/")
    if not p:
        return "*"
    if p.startswith("./"):
        p = p[2:]
    try:
        pp = Path(p)
        if pp.is_absolute():
            p = pp.resolve().relative_to(Path(cwd).resolve()).as_posix()
    except Exception:
        pass
    parts = []
    for seg in p.split("/"):
        if seg.startswith("**") and seg != "**":
            seg = "**/*" + seg[2:]
        parts.append(seg)
    return "/".join(parts)


async def glob_files_tool_local(pattern: str, exclude: str = "") -> str:
    """[Local] 智能查找：使用 pathlib.glob 支持 ** 递归，兼容 Windows"""
    try:
        cwd = await _get_current_cwd()
        base = Path(cwd).resolve()

        excludes = [e.strip() for e in exclude.split(",") if e.strip()]
        DEFAULT_EXCLUDES = {'.git', 'node_modules', '__pycache__', 'venv', 'dist', 'build'}

        # 使用 pathlib 的 glob，天然支持 ** 递归，并且与系统分隔符无关
        matched_paths = list(base.glob(_normalize_glob_pattern(pattern, cwd)))

        results = []
        for p in matched_paths:
            if not p.is_file():
                continue

            # 计算相对路径，用于后续匹配和输出
            try:
                rel = p.relative_to(base)
            except ValueError:
                # 如果路径不在 base 内（理论上不会发生），跳过
                continue

            rel_str = rel.as_posix()  # 统一使用正斜杠，跨平台一致

            # 排除命中 exclude 参数中的模式
            if any(fnmatch.fnmatch(rel_str, ex) for ex in excludes):
                continue

            # 排除默认隐藏/构建目录（仅检查目录层级，不误伤以点开头的文件名；.agent 为工作区内容目录，放行）
            parts = rel.parts
            if any(part in DEFAULT_EXCLUDES or (part.startswith('.') and part != '.agent') for part in parts[:-1]):
                continue

            results.append(rel_str)

        output = sorted(results)
        limit = 200
        if not output:
            return "No files matched this pattern. This is not an error: try a broader pattern (e.g. '**/*.py'); note that dot-directories are excluded by default."
        if len(output) > limit:
            return "\n".join(output[:limit]) + f"\n... ({len(output)-limit} more files)"
        return "\n".join(output)

    except Exception as e:
        return f"[Error] Glob failed: {str(e)}"

_EDIT_CONTINUE_HINT = (
    " Reminder: this single tool call only modified ONE spot in ONE file; "
    "the overall user task is NOT necessarily finished now. "
    "If any requirement, file edit, or verification step is still pending, continue with your next tool call immediately; "
    "only summarize as completed after everything is verified."
)

async def edit_file_patch_tool_local(path: str, old_string: str = "", new_string: str = "",
                                     edits=None, replace_all: bool = False) -> str:
    """[Local] S201 补丁工具：分级匹配+歧义报错+多点编辑+诊断回显（内核 py/patch_match；WSL 共用本对象）"""
    try:
        from py import patch_match
        edit_list = _patch_edit_list(old_string, new_string, edits, replace_all)
        if not edit_list:
            return "[Error] Provide old_string/new_string or a non-empty edits array of {old_string, new_string, replace_all?}."
        cwd = await _get_current_cwd()
        target = resolve_strict_path(cwd, path, check_symlink=True)
        if not target.exists():
            return f"[Error] File not found: {path}"
        async with aiofiles.open(target, 'r', encoding='utf-8', newline='') as f:
            content = await f.read()
        res = patch_match.apply_edits(content, edit_list)
        if not res.ok:
            return res.report
        if not res.content:  # S309 net-zero No-op：零净改动，跳过写回
            return f"'{path}' — {res.report}"
        async with aiofiles.open(target, 'w', encoding='utf-8', newline='') as f:
            await f.write(res.content)
        return f"Patched '{path}'.\n{res.report}{_EDIT_CONTINUE_HINT}"
    except Exception as e:
        return f"[Error] Patch failed: {str(e)}"

async def ask_user_question_tool(questions=None) -> str:
    """S194: 结构化提问工具。正常路径在 server 工具轮被拦截挂起（见 ask_flow），
    走到这里说明发生在非主流通道（子代理/直调）——不做挂起，提示模型改用文本。"""
    return ("[Info] ask_user_question_tool is only honored in the main chat stream, "
            "where it pauses the task and presents the questions to the user. "
            "In this context, put the questions directly in your visible reply instead.")


async def todo_write_tool_local(action: str, id: str = None, content: str = None, 
                                priority: str = "medium", status: str = None) -> str:
    """本地待办任务管理工具 - 使用3位数字有序ID"""
    try:
        cwd = await _get_current_cwd()
        party_dir = Path(cwd) / ".agent"
        if not party_dir.exists():
            await aiofiles.os.makedirs(party_dir, exist_ok=True)
        
        todo_file = party_dir / "ai_todos.json"
        
        # 读取现有任务
        todos = []
        if todo_file.exists():
            try:
                async with aiofiles.open(todo_file, 'r', encoding='utf-8') as f:
                    file_content = await f.read()
                    if file_content.strip():
                        todos = json.loads(file_content)
            except (json.JSONDecodeError, Exception):
                todos = []
            
        msg = ""

        # 生成下一个有序ID的辅助函数
        def _generate_ordered_id(existing_todos):
            if not existing_todos:
                return "1"
            # 找出最大数字 ID（兼容旧数据）
            numeric_ids = [int(t['id']) for t in existing_todos if t['id'].isdigit()]
            if not numeric_ids:
                return "1"
            return str(max(numeric_ids) + 1)  # 1, 2, 3... 不补零，不限制位数

        if action == "create":
            """创建新任务 - 自动生成3位数字有序ID"""
            if not content: 
                return "[Error] action='create' requires a non-empty 'content'. Add the task description and retry - retrying without content will fail the same way."
            
            new_id = _generate_ordered_id(todos)
            new_todo = {
                "id": new_id,
                "content": content,
                "priority": priority,
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "completed_at": None
            }
            todos.append(new_todo)
            msg = f"[Info] Created todo #{new_id}: {content[:30]}. Note: creating a todo does not advance the underlying work - execute it now if it is the next step."
            
        elif action == "list":
            """列出所有任务 - 按ID数字大小排序"""
            if not todos: 
                return "[Info] No todos yet. If the task has multiple steps, create them with action='create' first, then immediately start executing the first one."
            
            pending_n = sum(1 for _t in todos if _t.get("status") != "done")
            lines = [f"**Todo list**: {pending_n} pending / {len(todos) - pending_n} done (higher id = created later). If pending > 0, work the first pending item NOW - do not end your turn."]
            # 按ID数字排序，确保展示有序性
            sorted_todos = sorted(todos, key=lambda x: int(x['id']) if x['id'].isdigit() else 0)
            
            for t in sorted_todos:
                status_icon = "✅" if t.get('status') == 'done' else "⏳"
                priority_map = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                p_icon = priority_map.get(t.get('priority', 'medium'), "⚪")
                lines.append(f"{status_icon} [{t['id']}] {p_icon} {t['content'][:40]} - {'DONE' if t.get('status') == 'done' else 'STILL PENDING'}")
            return "\n".join(lines)

        elif action == "complete":
            """【高频】标记任务为已完成 - 幂等操作"""
            if not id: 
                return "[Error] action='complete' requires 'id' - use the bare number shown by action='list' (e.g. 3, no zero padding)."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if target.get('status') == 'done':
                msg = f"[Info] Todo #{id} was already done. No change. Run action='list' to see remaining pending items and continue with the first one."
            else:
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Info] Todo #{id} marked done. Before ANY summary: run action='list' - if any item is still pending, start the next pending item with a tool call NOW. Do not end your turn while pending items exist."

        elif action == "toggle":
            """切换完成状态 - pending↔done"""
            if not id: 
                return "[Error] action='toggle' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if target.get('status') != 'done':
                target['status'] = 'done'
                target['completed_at'] = datetime.now().isoformat()
                msg = f"[Info] Todo #{id} marked done. Before ANY summary: run action='list' - if any item is still pending, start the next pending item with a tool call NOW. Do not end your turn while pending items exist."
            else:
                target['status'] = 'pending'
                target['completed_at'] = None
                msg = f"[Info] Todo #{id} reopened as pending. Work on it now before anything else."

        elif action == "update":
            """编辑任务详情"""
            if not id: 
                return "[Error] action='update' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            if content: 
                target['content'] = content
            if priority: 
                target['priority'] = priority
            
            if status:
                if status == "done" and target.get('status') != "done":
                    target['completed_at'] = datetime.now().isoformat()
                elif status != "done" and target.get('status') == "done":
                    target['completed_at'] = None
                target['status'] = status
            
            target['updated_at'] = datetime.now().isoformat()
            msg = f"[Info] Todo #{id} updated. Continue with the current task step."

        elif action == "delete":
            """删除任务"""
            if not id: 
                return "[Error] action='delete' requires 'id' - get it from action='list'."
            
            target = next((t for t in todos if t['id'] == id), None)
            if not target: 
                return f"[Error] Todo #{id} does not exist. Call action='list' to see the valid ids, then retry."
            
            todos.remove(target)
            msg = f"[Info] Todo #{id} deleted. Continue with the current task step."

        else:
            return f"[Error] Unknown action '{action}'. Valid actions: create, list, complete, toggle, update, delete. Pick one and retry."

        # 保存到本地文件
        async with aiofiles.open(todo_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(todos, indent=2, ensure_ascii=False))
            
        return msg + todo_echo(todos)  # S183(T-B): 结果回显全量状态

    except Exception as e:
        return f"[Error] Todo operation failed: {e}. Todo bookkeeping is NOT the task itself - continue the main work even if this fails."
    
# ==================== [新增] Skill 专用读取工具 ====================

async def _skill_cwd_or_none() -> str:
    """S209：技能查找的工作区语义跟随 CLI 开关——CLI 关=无工作区（只读全局）。"""
    settings = await load_settings()
    cli = settings.get("CLISettings", {}) or {}
    if not cli.get("enabled", False):
        return ""
    return cli.get("cc_path") or ""


def _build_skill_tree(base_path: Path, skill_id: str) -> str:
    """S209：技能目录文件树（深度 ≤2）。"""
    tree_lines = [f"{skill_id}/"]
    for p in base_path.rglob("*"):
        if p.name.startswith("."):
            continue
        depth = len(p.relative_to(base_path).parts)
        if depth > 2:
            continue
        indent = "  " * depth
        tree_lines.append(f"{indent}{p.name}{'/' if p.is_dir() else ''}")
    return "\n".join(tree_lines)


async def read_skill_tool_logic(cwd: str, skill_id: str, is_docker: bool = True) -> str:
    """
    内部通用逻辑：读取 Skill 文件夹结构和说明文档。
    若工作区不存在该技能，且全局技能目录可用，则自动复制到工作区（Docker/Local 均支持）。
    S209：本地路径 cwd 为空=CLI 关=无工作区→只读全局；工作区缺失时直接回落全局读取。
    """
    skill_rel_path = f".agent/skills/{skill_id}"
    skill_label = skill_rel_path
    workspace_skill_path = f"/workspace/.agent/skills/{skill_id}" if is_docker else str(Path(cwd) / ".agent" / "skills" / skill_id)

    # ----- 复制逻辑：工作区缺失时，从全局复制 -----
    if is_docker:
        # Docker 环境：利用已映射的全局技能目录
        container_name = await get_or_create_docker_sandbox(cwd)          # 获取/创建容器
        global_skill_path = f"/home/agent/.agents/skills/{skill_id}"      # 容器内全局技能路径
        try:
            # 1. 检查工作区技能是否存在
            test_cmd = ["test", "-d", workspace_skill_path]
            await _exec_docker_cmd_simple(cwd, test_cmd)                  # 不存在会抛出异常
        except Exception:
            # 2. 工作区不存在，尝试从全局复制
            try:
                # 检查全局技能是否存在
                test_global = ["test", "-d", global_skill_path]
                await _exec_docker_cmd_simple(cwd, test_global)

                # 确保目标父目录存在
                mkdir_cmd = ["mkdir", "-p", f"/workspace/.agent/skills"]
                await _exec_docker_cmd_simple(cwd, mkdir_cmd)

                # 执行复制
                cp_cmd = ["cp", "-r", global_skill_path, f"/workspace/.agent/skills/"]
                await _exec_docker_cmd_simple(cwd, cp_cmd)

                logging.getLogger("app").info(f"[Skill AutoCopy][Docker] Copied global skill '{skill_id}' to workspace.")
            except Exception as e:
                # 复制失败或全局技能不存在，继续尝试读取工作区（若不存在则后续报错）
                pass
    else:
        # ----- Local（S209）：工作区（仅 CLI 开）→ 全局回落；CLI 关=无工作区只读全局 -----
        base_path = None
        if cwd:
            ws_path = Path(cwd) / ".agent" / "skills" / skill_id
            if ws_path.is_dir():
                base_path = ws_path
            else:
                global_path = Path(SKILLS_DIR) / skill_id
                if global_path.is_dir():
                    try:
                        ws_path.parent.mkdir(parents=True, exist_ok=True)
                        await asyncio.to_thread(
                            shutil.copytree,
                            global_path,
                            ws_path,
                            dirs_exist_ok=True
                        )
                        logging.getLogger("app").info(f"[Skill AutoCopy][Local] Copied global skill '{skill_id}' to workspace.")
                        base_path = ws_path
                    except Exception as e:
                        logging.getLogger("app").info(f"[Skill AutoCopy][Local] Copy failed: {e}. Will fallback to global read.")
        if base_path is None:
            global_path = Path(SKILLS_DIR) / skill_id
            if global_path.is_dir():
                base_path = global_path
                skill_label = f".agents/skills/{skill_id}"
        if base_path is None:
            return f"[Error] Skill '{skill_id}' not found in workspace or global skills dir."

    # ----- 读取逻辑（Docker 走容器内命令；Local 读上方解析出的目录）-----
    tree_str = ""
    doc_content = ""
    if is_docker:
        try:
            tree_str = await _exec_docker_cmd_simple(cwd, ["find", skill_rel_path, "-maxdepth", "2", "-not", "-path", '*/.*'])
            for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                try:
                    doc_path = f"{skill_rel_path}/{name}"
                    doc_content = await _exec_docker_cmd_simple(cwd, ["cat", doc_path])
                    break
                except Exception:
                    continue
        except Exception as e:
            return f"[Error] Skill '{skill_id}' not found or inaccessible in Docker: {str(e)}"
    else:
        try:
            tree_str = _build_skill_tree(base_path, skill_id)
            for name in ["SKILL.md", "skill.md", "SKILLS.md", "skills.md"]:
                doc_path = base_path / name
                if doc_path.exists():
                    doc_content = doc_path.read_text(encoding="utf-8", errors="replace")
                    break
        except Exception as e:
            return f"[Error] Skill '{skill_id}' read failed: {str(e)}"

    if not doc_content and not tree_str:
        return f"[Error] Could not find skill details for '{skill_id}'."

    res = f"--- Skill Details: {skill_id} ---\n"
    res += f"\n📂 **Folder Structure:**\n```\n{tree_str}\n```\n"
    res += f"\n📖 **Documentation ({skill_label}):**\n\n{doc_content or '(No SKILL.md found)'}"
    return res

async def read_skill_tool(skill_id: str) -> str:
    """[Docker] 读取特定技能的完整文档和文件树"""
    cwd = await _get_current_cwd()
    return await read_skill_tool_logic(cwd, skill_id, is_docker=True)

async def read_skill_tool_local(skill_id: str) -> str:
    """[Local] 读取特定技能的完整文档和文件树（S209：CLI 关=无工作区只读全局）"""
    cwd = await _skill_cwd_or_none()
    return await read_skill_tool_logic(cwd, skill_id, is_docker=False)

COMMON_BASH_DESC = (
    "Execute commands. Guidance: \n"
    "1. For long-running tasks (servers, watchers, large downloads), set 'background': true.\n"
    "2. For medium tasks, adjust 'timeout' (1-3600s, default 600s).\n"
    "3. If 'background' is true, wait a few seconds for initialization before checking logs/status; do not poll rapidly."
)

# ==================== 工具注册表 (完整) ====================

TOOLS_REGISTRY = {
    # --- 只读 ---
    "list_files": {
        "type": "function", "function": {
            "name": "list_files_tool", 
            "description": "List entries of a sandbox workspace directory (NOT recursive - subfolder contents are hidden). For recursive name matching use glob_files; for contents use search_files.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list files in (from workspace root)."
                    }, 
                    "show_all": {"type": "boolean", "default": True, "description": "Include hidden dotfiles in listing"}
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file": {
        "type": "function", "function": {
            "name": "read_file_tool", 
            "description": "Read a text file from the sandbox workspace (large files are truncated - continue with read_file_range; for images/binaries use get_image_content).",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_range": {
        "type": "function", "function": {
            "name": "read_file_range_tool", 
            "description": "Read a specific range of lines from a file. Useful for large files after grepping.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "start_line": {"type": "integer", "description": "1-based first line to read"},
                    "end_line": {"type": "integer", "description": "1-based last line to read (default: end of file)"}
                }, 
                "required": ["path", "start_line"]
            }
        }
    },
    "tail_file": {
        "type": "function", "function": {
            "name": "tail_file_tool", 
            "description": "Read the last N lines of a file. Useful for reading logs.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "lines": {"type": "integer", "default": 100, "description": "Number of lines to read from the end"}
                }, 
                "required": ["path"]
            }
        }
    },
    "search_files": {
        "type": "function", "function": {
            "name": "search_files_tool", 
            "description": "Plain regex (grep BRE) search over file contents in the sandbox workspace. Returns 'path:line_number:line_text' lines; binary files and build dirs are skipped. BRE has no | alternation - use plain substrings or separate searches; if there are no matches, simplify the pattern before concluding absence.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {"type": "string", "description": "Basic regex (grep BRE) or a plain substring to search for in file contents"}, 
                    "path": {
                        "type": "string",
                        "description": "Relative path to directory to search in (from workspace root)."
                    }
                }, 
                "required": ["pattern"]
            }
        }
    },
    "glob_files": {
        "type": "function", "function": {
            "name": "glob_files_tool", 
            "description": "Find files in the sandbox workspace by glob pattern; '**' matches recursively (e.g. '**/*.py'). Returns workspace-relative paths, max 200 results.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (relative to workspace root)."
                    }, 
                    "exclude": {"type": "string", "description": "Optional comma-separated glob patterns of paths to exclude"}
                }, 
                "required": ["pattern"]
            }
        }
    },
    "read_skill": {
        "type": "function", "function": {
            "name": "read_skill_tool", 
            "description": "Read the full documentation and file tree of a skill (operational guide / convention / prompt-writing guide, etc.). Lookup order: workspace .agent/skills/ first, then the global skills dir (auto-copied into the workspace on first use). Knowledge skills can be consulted at any time.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "skill_id": {"type": "string", "description": "Skill directory name (under workspace .agent/skills/ or the global skills dir)"}
                }, 
                "required": ["skill_id"]
            }
        }
    },
    # --- 编辑 ---
    "edit_file": {
        "type": "function", "function": {
            "name": "edit_file_tool", 
            "description": "Overwrite a workspace file with the full new content. Success here only means this one file was saved - continue the remaining task steps and verify results before summarizing.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }, 
                    "content": {"type": "string", "description": "FULL new file content (entire file is overwritten)"}
                }, 
                "required": ["path", "content"]
            }
        }
    },
    "edit_file_patch": {
        "type": "function", "function": {
            "name": "edit_file_patch_tool", 
            "description": "Apply precise string replacement(s) to a file: single old_string/new_string, or edits=[{old_string, new_string, replace_all?}, ...] applied in order (atomic: if any edit fails to match, NOTHING is written). Tiered matching tolerates line-ending and indentation differences. Multiple hits are an ERROR unless replace_all=true (locations are listed). On mismatch the tool echoes the closest actual snippet with line numbers - retry the patch from that echo instead of re-reading and rewriting the whole file; on success it echoes a diff, so no re-read is needed to confirm. A successful patch does NOT mean the overall task is done - continue remaining steps and verify (test) before summarizing.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from workspace root)."
                    }, 
                    "old_string": {"type": "string", "description": "Existing text to be replaced (single-shot form; omit if edits is used)"}, 
                    "new_string": {"type": "string", "description": "Replacement text (use empty string to delete old_string)"}, 
                    "edits": {
                        "type": "array",
                        "description": "Optional multi-edit batch applied in order; each item {old_string, new_string, replace_all?}. Preferred for several changes to one file.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "replace_all": {"type": "boolean"}
                            },
                            "required": ["old_string", "new_string"]
                        }
                    }, 
                    "replace_all": {"type": "boolean", "description": "Replace EVERY occurrence (default false: multiple hits abort with an error listing their lines)"}
                }, 
                "required": ["path"]
            }
        }
    },
    # --- 任务 ---
    "todo_write": {
        "type": "function",
        "function": {
            "name": "todo_write_tool",
            "description": "[Docker sandbox] Todo list manager. The list is a contract with the user: the overall task is NOT complete while any item is still pending. After marking one done, immediately start the next pending item. Never mark done what was not actually executed and verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "complete", "toggle", "update", "delete"],
                        "description": "Operation: create | list (show all ids and states) | complete (mark done, idempotent - prefer this) | toggle (flips state in whichever direction) | update | delete."
                    },
                    "id": {
                        "type": "string",
                        "description": "Todo id as a bare number taken from action='list' (e.g. 3, no zero padding). Optional (auto-generated) for create; required for the other actions."
                    },
                    "content": {
                        "type": "string",
                        "description": "Task description (one concrete step). Required for create; optional for update."
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority: high | medium (default) | low. Optional for create/update."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done"],
                        "description": "[update only] Force the status field: pending | done. Prefer the complete action for normal completion."
                    }
                },
                "required": ["action"]
            }
        }
    },
    # --- 基础设施 ---
    "bash": {
        "type": "function", "function": {
            "name": "docker_sandbox", 
            "description": f"[Docker] {COMMON_BASH_DESC}",
            "parameters": {
                "type": "object", 
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run inside the sandbox container"},
                    "background": {"type": "boolean", "description": "Run non-blocking. Returns PID."},
                    "timeout": {
                        "type": "integer", 
                        "default": 600, 
                        "description": "Max execution time in seconds (1-3600). Default 600."
                    }
                }, 
                "required": ["command"]
            }
        }
    },
    "list_processes": {
        "type": "function",
        "function": {
            "name": "list_processes_tool",
            "description": "List all running background processes (both Docker containers and local processes).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    "get_process_logs": {
        "type": "function",
        "function": {
            "name": "get_process_logs_tool",
            "description": "Retrieve logs for a specific background process using its PID or Container ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "string",
                        "description": "The process ID or container ID to fetch logs for."
                    }
                },
                "required": ["pid"]
            }
        }
    },
    "kill_process": {
        "type": "function",
        "function": {
            "name": "kill_process_tool",
            "description": "Terminate a background process or stop a Docker container using its PID or ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "string",
                        "description": "The process ID or container ID to terminate."
                    }
                },
                "required": ["pid"]
            }
        }
    },
    "manage_ports": {
        "type": "function", "function": {
            "name": "docker_manage_ports_tool", 
            "description": "Forward Docker ports to localhost.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "action": {"type": "string", "enum": ["forward", "stop", "list"], "description": "'forward' adds a host->container port mapping, 'stop' removes it, 'list' shows current mappings"},
                    "container_port": {"type": "integer", "description": "Port inside the container (required for forward/stop)"},
                    "host_port": {"type": "integer", "description": "Port on the host (required for forward/stop)"}
                }, 
                "required": ["action"]
            }
        }
    }
}

LOCAL_TOOLS_REGISTRY = {
    # --- 只读 ---
    "list_files_local": {
        "type": "function", "function": {
            "name": "list_files_tool_local", 
            "description": "List entries of a host workspace directory (NOT recursive, capped at 200 entries). For recursive name matching use glob_files_local; for contents use search_files_local.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to list files in (from current working directory)."
                    }, 
                    "show_all": {"type": "boolean","default": True, "description": "Include hidden dotfiles in listing"}
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_local": {
        "type": "function", "function": {
            "name": "read_file_tool_local", 
            "description": "Read a text file from the host workspace (large files are truncated - continue with read_file_range_local; for images/binaries use get_image_content).",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }
                }, 
                "required": ["path"]
            }
        }
    },
    "read_file_range_local": {
        "type": "function", "function": {
            "name": "read_file_range_tool_local", 
            "description": ("Read lines from a local file. Two modes: (a) symbol=Method_or_function_name — auto-locates and "
                            "returns its COMPLETE definition block (brace-balanced for Java/JS/TS/C…, indent-based for Python; "
                            "no line guessing needed, ideal for code archaeology); falls back to listing reference points if "
                            "no definition found. (b) start_line/end_line — raw line range (after grepping)."),
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "start_line": {"type": "integer", "description": "1-based first line to read (mode b; default 1)"},
                    "end_line": {"type": "integer", "description": "1-based last line to read (default: end of file)"},
                    "symbol": {"type": "string", "description": "Mode (a): method/function name to read COMPLETE definition block for. Takes precedence over start_line."}
                }, 
                "required": ["path"]
            }
        }
    },
    "tail_file_local": {
        "type": "function", "function": {
            "name": "tail_file_tool_local", 
            "description": "Read the last N lines of a local file. Useful for reading logs.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {"type": "string", "description": "Relative path to file"},
                    "lines": {"type": "integer", "default": 100, "description": "Number of lines to read from the end of the file"}
                }, 
                "required": ["path"]
            }
        }
    },
    "search_files_local": {
         "type": "function", "function": {
            "name": "search_files_tool_local",
            "description": ("Cross-platform content search over local workspace files (Python re.search semantics; a plain substring also works). Returns 'path:line_number:line_text' rows, sorted, max 1000 per call with offset pagination. Text files only; binary files and build dirs (.git, node_modules, .venv, __pycache__, dist, build, target, ...) are skipped. Narrow a big search with path= or include=; continue past the cap with offset=. S251: searching several symbols? pass patterns=['a','b',…] (up to 10) to get ALL in one call, grouped per pattern — ideal for call-chain tracing."),
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Python regex (escape ( ) [ ] { } * + ? ^ $ | to match them literally) or a plain substring"},
                    "patterns": {"type": "array", "items": {"type": "string"}, "description": "Multiple patterns to search in ONE call (results grouped per pattern, up to 10). Combine with pattern= to add one more."},
                    "path": {"type": "string", "description": "Optional relative subdirectory of the workspace to restrict the search (default: whole workspace)"},
                    "include": {"type": "string", "description": "Optional comma-separated glob patterns to restrict searched files, e.g. '*.py,src/**/*.ts'"},
                    "max_results": {"type": "integer", "default": 200, "description": "Matches to return per call (1-1000, default 200)"},
                    "offset": {"type": "integer", "default": 0, "description": "Skip this many matches to page through results (continue with the offset suggested in truncated output)"},
                    "case_insensitive": {"type": "boolean", "default": False, "description": "Case-insensitive search"}
                },
                "required": []
            }
        }
    },
    "glob_files_local": {
         "type": "function", "function": {
            "name": "glob_files_tool_local", 
            "description": "Find files in the local workspace by glob pattern; '**' matches recursively (e.g. '**/*.py' or 'src/**/*.ts'). Pattern is relative to the workspace root; returns workspace-relative posix paths, max 200 results.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern (relative to current working directory), e.g. '**/*.md'"
                    },
                    "exclude": {
                        "type": "string",
                        "description": "Optional comma-separated glob patterns of relative paths to exclude, e.g. 'tests/*,*.min.js'"
                    }
                }, 
                "required": ["pattern"]
            }
        }
    },
    "read_skill_local": {
        "type": "function", "function": {
            "name": "read_skill_tool_local", 
            "description": "Read the full documentation and file tree of a skill (operational guide / convention / prompt-writing guide, etc.). Lookup order: workspace .agent/skills/ first, then the global skills dir (auto-copied into the workspace on first use). When CLI/workspace is disabled only global skills are available. Knowledge skills can be consulted at any time.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "skill_id": {"type": "string", "description": "Skill directory name (under workspace .agent/skills/ or the global skills dir)"}
                }, 
                "required": ["skill_id"]
            }
        }
    },
    # --- 编辑 ---
    "edit_file_local": {
        "type": "function", "function": {
            "name": "edit_file_tool_local", 
            "description": "Overwrite a local file with the full new content. Success here only means this one file was saved - continue the remaining task steps and verify results before summarizing.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }, 
                    "content": {"type": "string", "description": "FULL new file content (entire file is overwritten)"}
                }, 
                "required": ["path", "content"]
            }
        }
    },
    "edit_file_patch_local": {
        "type": "function", "function": {
            "name": "edit_file_patch_tool_local", 
            "description": "Apply precise string replacement(s) to a file: single old_string/new_string, or edits=[{old_string, new_string, replace_all?}, ...] applied in order (atomic: if any edit fails to match, NOTHING is written). Tiered matching tolerates line-ending and indentation differences. Multiple hits are an ERROR unless replace_all=true (locations are listed). On mismatch the tool echoes the closest actual snippet with line numbers - retry the patch from that echo instead of re-reading and rewriting the whole file; on success it echoes a diff, so no re-read is needed to confirm. A successful patch does NOT mean the overall task is done - continue remaining steps and verify (test) before summarizing.",
            "parameters": {
                "type": "object", 
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to file (from current working directory)."
                    }, 
                    "old_string": {"type": "string", "description": "Existing text to be replaced (single-shot form; omit if edits is used)"}, 
                    "new_string": {"type": "string", "description": "Replacement text (use empty string to delete old_string)"}, 
                    "edits": {
                        "type": "array",
                        "description": "Optional multi-edit batch applied in order; each item {old_string, new_string, replace_all?}. Preferred for several changes to one file.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_string": {"type": "string"},
                                "new_string": {"type": "string"},
                                "replace_all": {"type": "boolean"}
                            },
                            "required": ["old_string", "new_string"]
                        }
                    }, 
                    "replace_all": {"type": "boolean", "description": "Replace EVERY occurrence (default false: multiple hits abort with an error listing their lines)"}
                }, 
                "required": ["path"]
            }
        }
    },
    "todo_write_local": {
        "type": "function",
        "function": {
            "name": "todo_write_tool_local",
            "description": "[Host workspace] Todo list manager. The list is a contract with the user: the overall task is NOT complete while any item is still pending. After marking one done, immediately start the next pending item. Never mark done what was not actually executed and verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["create", "list", "complete", "toggle", "update", "delete"],
                        "description": "Operation: create | list (show all ids and states) | complete (mark done, idempotent - prefer this) | toggle (flips state in whichever direction) | update | delete."
                    },
                    "id": {
                        "type": "string",
                        "description": "Todo id as a bare number taken from action='list' (e.g. 3, no zero padding). Optional (auto-generated) for create; required for the other actions."
                    },
                    "content": {
                        "type": "string",
                        "description": "Task description (one concrete step). Required for create; optional for update."
                    },
                    "priority": {
                        "type": "string",
                        "enum": ["high", "medium", "low"],
                        "description": "Priority: high | medium (default) | low. Optional for create/update."
                    },
                    "status": {
                        "type": "string",
                        "enum": ["pending", "done"],
                        "description": "[update only] Force the status field: pending | done. Prefer the complete action for normal completion."
                    }
                },
                "required": ["action"]
            }
        }
    },
    # S194：结构化提问（与审批同构的挂起-续流；任何权限模式都可用，含 plan）
    "ask_user_question": {
        "type": "function",
        "function": {
            "name": "ask_user_question_tool",
            "description": (
                "[Interaction] Pause the task and ask the user to decide. Use whenever you need "
                "the user's choice, confirmation, or missing info to proceed - instead of ending "
                "the turn with a plain-text question. Put ALL related questions in ONE call "
                "(1-4). The turn pauses cleanly (todo stays open); the user's reply comes back "
                "as this tool's result, then the task continues."),
            "parameters": {
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 4,
                        "description": "Questions to ask at once (1-4). One call per batch - do not split related questions into multiple calls.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "question": {"type": "string", "description": "The question, self-contained."},
                                "options": {
                                    "type": "array",
                                    "maxItems": 6,
                                    "description": "Numbered suggested answers (0-6; omit for open questions). The user may always answer something else.",
                                    "items": {"type": "string"}
                                }
                            },
                            "required": ["question"]
                        }
                    }
                },
                "required": ["questions"]
            }
        }
    },
    # --- 基础设施 ---
    "bash_local": {
        "type": "function", "function": {
            "name": "shell_tool_local", 
            "description": f"[Local] {COMMON_BASH_DESC}",
            "parameters": {
                "type": "object", 
                "properties": {
                    "command": {"type": "string", "description": "Shell command to run on the host (PowerShell/cmd semantics)"},
                    "background": {"type": "boolean", "description": "Run in background."},
                    "timeout": {
                        "type": "integer", 
                        "default": 600, 
                        "description": "Max execution time in seconds (1-3600). Default 600."
                    }
                }, 
                "required": ["command"]
            }
        }
    },
    "list_processes": {
        "type": "function",
        "function": {
            "name": "list_processes_tool",
            "description": "List all running background processes (both Docker containers and local processes).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    "get_process_logs": {
        "type": "function",
        "function": {
            "name": "get_process_logs_tool",
            "description": "Retrieve logs for a specific background process using its PID or Container ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "string",
                        "description": "The process ID or container ID to fetch logs for."
                    }
                },
                "required": ["pid"]
            }
        }
    },
    "kill_process": {
        "type": "function",
        "function": {
            "name": "kill_process_tool",
            "description": "Terminate a background process or stop a Docker container using its PID or ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pid": {
                        "type": "string",
                        "description": "The process ID or container ID to terminate."
                    }
                },
                "required": ["pid"]
            }
        }
    },
    "local_net_tool": {
        "type": "function", "function": {
            "name": "local_net_tool", 
            "description": "Inspect local TCP ports: 'check' whether one port is listening, 'scan' common ports.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["check", "scan"], "description": "'check' a single port or 'scan' common ports"},
                    "port": {"type": "integer", "description": "Port number to check (required when action='check')"}
                }, 
                "required": ["action"]
            }
        }
    }
}

def get_tools_for_mode(mode: str) -> list:
    """获取 Docker 环境工具集"""
    # 基础只读
    read = [TOOLS_REGISTRY["list_files"], 
            TOOLS_REGISTRY["read_file"], 
            TOOLS_REGISTRY["read_file_range"],
            TOOLS_REGISTRY["tail_file"],     
            TOOLS_REGISTRY["search_files"], 
            TOOLS_REGISTRY["glob_files"],
            TOOLS_REGISTRY["read_skill"]
            ]
    # 编辑
    edit = [TOOLS_REGISTRY["edit_file"], TOOLS_REGISTRY["edit_file_patch"], TOOLS_REGISTRY["todo_write"]]
    # 基础设施 (执行/进程/端口)
    infra = [TOOLS_REGISTRY["bash"], TOOLS_REGISTRY["list_processes"], TOOLS_REGISTRY["get_process_logs"], TOOLS_REGISTRY["kill_process"], TOOLS_REGISTRY["manage_ports"]]
    
    if mode == "default": return read
    if mode == "auto-approve": return read + edit + [TOOLS_REGISTRY["list_processes"], TOOLS_REGISTRY["get_process_logs"], TOOLS_REGISTRY["kill_process"]]
    if mode == "yolo": return read + edit + infra
    return read

def get_local_tools_for_mode(mode: str) -> list:
    """获取 Local 环境工具集"""
    read = [
        LOCAL_TOOLS_REGISTRY["list_files_local"], 
        LOCAL_TOOLS_REGISTRY["read_file_local"], 
        LOCAL_TOOLS_REGISTRY["read_file_range_local"],
        LOCAL_TOOLS_REGISTRY["tail_file_local"],    
        LOCAL_TOOLS_REGISTRY["search_files_local"], 
        LOCAL_TOOLS_REGISTRY["glob_files_local"],
        LOCAL_TOOLS_REGISTRY["read_skill_local"],
        LOCAL_TOOLS_REGISTRY["ask_user_question"]  # S194：提问是只读交互，全模式可用
    ]
    edit = [LOCAL_TOOLS_REGISTRY["edit_file_local"], LOCAL_TOOLS_REGISTRY["edit_file_patch_local"], LOCAL_TOOLS_REGISTRY["todo_write_local"]]
    infra = [
        LOCAL_TOOLS_REGISTRY["bash_local"], 
        LOCAL_TOOLS_REGISTRY["list_processes"], LOCAL_TOOLS_REGISTRY["get_process_logs"], LOCAL_TOOLS_REGISTRY["kill_process"],
        LOCAL_TOOLS_REGISTRY["local_net_tool"]
    ]
    
    if mode == "default": return read
    if mode == "auto-approve": return read + edit + [LOCAL_TOOLS_REGISTRY["list_processes"], LOCAL_TOOLS_REGISTRY["get_process_logs"], LOCAL_TOOLS_REGISTRY["kill_process"], LOCAL_TOOLS_REGISTRY["local_net_tool"]]
    if mode == "yolo": return read + edit + infra
    return read


def normalize_permission_mode(mode) -> str:
    """统一权限模式值域：acceptEdits 等历史变体归一化为 auto-approve"""
    if mode in ("acceptEdits", "accept-edits", "accept_edits"):
        return "auto-approve"
    return mode or "default"


def get_tools_for_permission(permission_mode: str) -> list:
    """Docker 环境：按权限模式给模型的工具集，与 dispatch_tool 强制层保持一致。
    plan=只读 / auto-approve=读+编辑(无命令执行) / default,yolo,cowork=全量(default 由审批弹窗拦截)"""
    permission_mode = normalize_permission_mode(permission_mode)
    read = [TOOLS_REGISTRY["list_files"],
            TOOLS_REGISTRY["read_file"],
            TOOLS_REGISTRY["read_file_range"],
            TOOLS_REGISTRY["tail_file"],
            TOOLS_REGISTRY["search_files"],
            TOOLS_REGISTRY["glob_files"],
            TOOLS_REGISTRY["read_skill"]]
    edit = [TOOLS_REGISTRY["edit_file"], TOOLS_REGISTRY["edit_file_patch"], TOOLS_REGISTRY["todo_write"]]
    infra = [TOOLS_REGISTRY["bash"], TOOLS_REGISTRY["list_processes"], TOOLS_REGISTRY["get_process_logs"],
             TOOLS_REGISTRY["kill_process"], TOOLS_REGISTRY["manage_ports"]]
    if permission_mode == "plan":
        return read + [TOOLS_REGISTRY["todo_write"]]
    if permission_mode == "auto-approve":
        return read + edit
    return read + edit + infra


def get_local_tools_for_permission(permission_mode: str) -> list:
    """Local 环境：按权限模式给模型的工具集，与 dispatch_tool 强制层保持一致。
    plan=只读 / auto-approve=读+编辑(无命令执行) / default,yolo,cowork=全量(default 由审批弹窗拦截)"""
    permission_mode = normalize_permission_mode(permission_mode)
    read = [LOCAL_TOOLS_REGISTRY["list_files_local"],
            LOCAL_TOOLS_REGISTRY["read_file_local"],
            LOCAL_TOOLS_REGISTRY["read_file_range_local"],
            LOCAL_TOOLS_REGISTRY["tail_file_local"],
            LOCAL_TOOLS_REGISTRY["search_files_local"],
            LOCAL_TOOLS_REGISTRY["glob_files_local"],
            LOCAL_TOOLS_REGISTRY["read_skill_local"],
            LOCAL_TOOLS_REGISTRY["ask_user_question"]]  # S194：提问是只读交互，全模式可用
    edit = [LOCAL_TOOLS_REGISTRY["edit_file_local"], LOCAL_TOOLS_REGISTRY["edit_file_patch_local"], LOCAL_TOOLS_REGISTRY["todo_write_local"]]
    infra = [LOCAL_TOOLS_REGISTRY["bash_local"],
             LOCAL_TOOLS_REGISTRY["list_processes"], LOCAL_TOOLS_REGISTRY["get_process_logs"],
             LOCAL_TOOLS_REGISTRY["kill_process"], LOCAL_TOOLS_REGISTRY["local_net_tool"]]
    if permission_mode == "plan":
        return read + [LOCAL_TOOLS_REGISTRY["todo_write_local"]]
    if permission_mode == "auto-approve":
        return read + edit
    return read + edit + infra


# ==================== WSL 引擎工具集（S132/A13，fork=permission 版对齐 local/ds） ====================

WSL_TOOLS_REGISTRY = {
    # --- 只读（复用 Local 文件工具） ---
    "list_files_wsl": LOCAL_TOOLS_REGISTRY["list_files_local"],
    "read_file_wsl": LOCAL_TOOLS_REGISTRY["read_file_local"],
    "read_file_range_wsl": LOCAL_TOOLS_REGISTRY["read_file_range_local"],
    "tail_file_wsl": LOCAL_TOOLS_REGISTRY["tail_file_local"],
    "search_files_wsl": LOCAL_TOOLS_REGISTRY["search_files_local"],
    "glob_files_wsl": LOCAL_TOOLS_REGISTRY["glob_files_local"],
    "read_skill_wsl": LOCAL_TOOLS_REGISTRY["read_skill_local"],
    # --- 编辑（复用 Local 文件工具，fork=patch 版） ---
    "edit_file_wsl": LOCAL_TOOLS_REGISTRY["edit_file_local"],
    "edit_file_patch_wsl": LOCAL_TOOLS_REGISTRY["edit_file_patch_local"],
    "todo_write_wsl": LOCAL_TOOLS_REGISTRY["todo_write_local"],
    # --- 基础设施（WSL 专属 bash + 通用进程管理） ---
    "bash_wsl": {
        "type": "function", "function": {
            "name": "shell_tool_wsl",
            "description": f"[WSL] {COMMON_BASH_DESC}",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "background": {"type": "boolean", "description": "Run in background."},
                    "timeout": {
                        "type": "integer",
                        "default": 60,
                        "description": "Max execution time in seconds (1-3600). Default 60."
                    }
                },
                "required": ["command"]
            }
        }
    },
    "list_processes": LOCAL_TOOLS_REGISTRY["list_processes"],
    "get_process_logs": LOCAL_TOOLS_REGISTRY["get_process_logs"],
    "kill_process": LOCAL_TOOLS_REGISTRY["kill_process"],
    "local_net_tool": LOCAL_TOOLS_REGISTRY["local_net_tool"],
}


def get_wsl_tools_for_permission(permission_mode: str) -> list:
    """WSL 环境：按权限模式给模型的工具集（复用 Local 文件工具 + WSL bash）。
    plan=只读 / auto-approve=读+编辑(无命令执行) / default,yolo,cowork=全量(default 由审批弹窗拦截)"""
    permission_mode = normalize_permission_mode(permission_mode)
    read = [WSL_TOOLS_REGISTRY["list_files_wsl"],
            WSL_TOOLS_REGISTRY["read_file_wsl"],
            WSL_TOOLS_REGISTRY["read_file_range_wsl"],
            WSL_TOOLS_REGISTRY["tail_file_wsl"],
            WSL_TOOLS_REGISTRY["search_files_wsl"],
            WSL_TOOLS_REGISTRY["glob_files_wsl"],
            WSL_TOOLS_REGISTRY["read_skill_wsl"]]
    edit = [WSL_TOOLS_REGISTRY["edit_file_wsl"], WSL_TOOLS_REGISTRY["edit_file_patch_wsl"], WSL_TOOLS_REGISTRY["todo_write_wsl"]]
    infra = [WSL_TOOLS_REGISTRY["bash_wsl"],
             WSL_TOOLS_REGISTRY["list_processes"], WSL_TOOLS_REGISTRY["get_process_logs"],
             WSL_TOOLS_REGISTRY["kill_process"], WSL_TOOLS_REGISTRY["local_net_tool"]]
    if permission_mode == "plan":
        return read + [WSL_TOOLS_REGISTRY["todo_write_wsl"]]
    if permission_mode == "auto-approve":
        return read + edit
    return read + edit + infra