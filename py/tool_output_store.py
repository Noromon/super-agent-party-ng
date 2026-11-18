# -*- coding: utf-8 -*-
"""S184：opencode 式「可恢复截断」+ ripgrep 定位（工具输出与检索基建）。

超限工具输出全文落盘 <工作区>/.agent/tool_output/，模型拿到真实路径后可用
search_files_local 定位、read_file_range_local 精读——中段信息不再单向丢失。
预览算法对齐 opencode ToolOutputStore（先行头尾各半采样→仍超按字节头尾各半，
marker 恒占 4 行预算）。清理按文件 mtime 判龄——天然跨重启；工作区清单登记于
<SAP_DATA_DIR>/tool_output_workspaces.txt（cc_path 会变，旧区也要能清）。
纯函数 + 轻 IO，无第三方依赖。
"""
import itertools
import os
import re as _re
import shutil
import subprocess
import sys
import time
from pathlib import Path

STORE_SUBDIR = os.path.join(".agent", "tool_output")
WORKSPACE_REGISTRY = "tool_output_workspaces.txt"
RG_VERSION_PIN = "14.1.1"

# 默认限额：保守档（本地小上下文模型混跑），设置页可调
_DEF_LINES, _DEF_BYTES, _DEF_RETENTION = 800, 20000, 7
_MARKER = ("... output truncated; full content saved to {path} ...\n"
           "【完整输出已保存于工作区 .agent/tool_output/。用 read_file_range_tool_local"
           "（path 传上述相对路径）精读行段，或 search_files_tool_local"
           "（path='.agent/tool_output'）在其中定位关键词】")
_MARKER_NOSTORE = "... output truncated (store unavailable) ..."


# ==================== 设置钳位 ====================

def _clamp_int(val, lo, hi, default):
    try:
        v = int(val)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def tool_output_cfg(settings):
    """settings -> (max_lines 100~5000, max_bytes 5000~200000, retention_days 0~90)。"""
    tc = (settings or {}).get("toolOutput")
    if not isinstance(tc, dict):
        tc = {}
    return (_clamp_int(tc.get("maxOutputLines"), 100, 5000, _DEF_LINES),
            _clamp_int(tc.get("maxOutputBytes"), 5000, 200000, _DEF_BYTES),
            _clamp_int(tc.get("retentionDays"), 0, 90, _DEF_RETENTION))


# ==================== 预览算法（opencode 同构） ====================

def line_count(text):
    return text.count("\n") + 1


def _byte_len(text):
    return len(text.encode("utf-8", errors="ignore"))


def _take_prefix_bytes(text, maximum):
    if maximum <= 0:
        return ""
    if _byte_len(text) <= maximum:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _byte_len(text[:mid]) <= maximum:
            lo = mid
        else:
            hi = mid - 1
    # S244: 切点若把代理对劈开，head 尾部的高代理会成孤立字符，下游
    # json/utf-8 序列化整轮炸（15:22 实证）——退到配对边界前。
    while lo > 0 and 0xD800 <= ord(text[lo - 1]) <= 0xDBFF:
        lo -= 1
    return text[:lo]


def _take_suffix_bytes(text, maximum):
    if maximum <= 0:
        return ""
    if _byte_len(text) <= maximum:
        return text
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi) // 2
        if _byte_len(text[mid:]) <= maximum:
            hi = mid
        else:
            lo = mid + 1
    # S244: 对称防护——tail 首字符为低代理（配对被劈开）则前进到配对边界后。
    while lo < len(text) and 0xDC00 <= ord(text[lo]) <= 0xDFFF:
        lo += 1
    return text[lo:]


def _preview(text, max_lines, max_bytes):
    """(head, tail)：先按行头尾各半采样，仍超字节预算再按字节头尾各半。"""
    lines = text.split("\n")
    head_n = (max_lines + 1) // 2
    tail_n = max_lines // 2
    if len(lines) <= max_lines:
        head, tail = text, ""
    else:
        head = "\n".join(lines[:head_n])
        tail = "\n".join(lines[len(lines) - tail_n:]) if tail_n > 0 else ""
    sampled = text if len(lines) <= max_lines else head + "\n" + tail
    if _byte_len(sampled) <= max_bytes:
        return head, tail
    hb, tb = (max_bytes + 1) // 2, max_bytes // 2
    return _take_prefix_bytes(sampled, hb), _take_suffix_bytes(sampled, tb)


def bounded_preview(text, marker, max_lines, max_bytes):
    """头 + marker + 尾（marker 恒占 4 行 / 若干字节预算，保证 marker 完整）。"""
    marker_only = _take_prefix_bytes(marker, max_bytes)
    marker_only = "\n".join(marker_only.split("\n")[:max_lines])
    if max_lines <= 4 or max_bytes <= _byte_len(marker) + 4:
        return marker_only
    head, tail = _preview(text, max_lines - 4, max_bytes - _byte_len(marker) - 4)
    if tail:
        return f"{head}\n\n{marker}\n\n{tail}"
    return f"{head}\n\n{marker}"


# ==================== 落盘与截断入口 ====================

def _store_dir(cwd):
    return Path(cwd) / STORE_SUBDIR


_ID_SEQ = itertools.count(1)


def write_output(cwd, text):
    """全文落盘，返回绝对路径；失败返回 None（调用方降级为无路径预览）。"""
    try:
        d = _store_dir(cwd)
        d.mkdir(parents=True, exist_ok=True)
        name = "tool_%d_%d_%d.txt" % (int(time.time() * 1000),
                                      os.getpid(), next(_ID_SEQ))
        p = d / name
        p.write_text(text, encoding="utf-8", errors="replace")
        register_workspace(cwd)
        return str(p)
    except Exception:
        return None


def bound_output(text, cwd, settings):
    """单一入口：限额内原样返回（幂等）；超限落盘 + 头尾预览 marker。"""
    if not isinstance(text, str):
        text = str(text)
    max_lines, max_bytes, _r = tool_output_cfg(settings)
    if line_count(text) <= max_lines and _byte_len(text) <= max_bytes:
        return text
    path = write_output(cwd, text) if cwd else None
    if path:
        try:
            rel = os.path.relpath(path, cwd)
            show = rel if not rel.startswith("..") else path
        except Exception:
            show = path
        marker = _MARKER.format(path=show.replace("\\", "/"))
    else:
        marker = _MARKER_NOSTORE
    return bounded_preview(text, marker, max_lines, max_bytes)


# ==================== 工作区登记与清理（mtime 判龄，跨重启） ====================

def _registry_path():
    from py.get_setting import USER_DATA_DIR
    return Path(USER_DATA_DIR) / WORKSPACE_REGISTRY


def register_workspace(cwd):
    """登记工作区（幂等）；cc_path 切换后旧工作区仍会被周期清理遍历到。"""
    try:
        rp = _registry_path()
        rp.parent.mkdir(parents=True, exist_ok=True)
        cur = os.path.abspath(str(cwd))
        lines = rp.read_text(encoding="utf-8").splitlines() if rp.exists() else []
        if cur not in lines:
            with rp.open("a", encoding="utf-8") as f:
                f.write(cur + "\n")
    except Exception:
        pass


def list_workspaces():
    try:
        rp = _registry_path()
        if not rp.exists():
            return []
        return [w for w in rp.read_text(encoding="utf-8").splitlines()
                if w.strip() and os.path.isdir(w)]
    except Exception:
        return []


def store_stats(cwd):
    """(文件数, 总字节)。"""
    d = _store_dir(cwd)
    if not d.is_dir():
        return 0, 0
    n = b = 0
    for f in d.iterdir():
        try:
            if f.is_file() and f.name.startswith("tool_"):
                n += 1
                b += f.stat().st_size
        except OSError:
            continue
    return n, b


def cleanup_workspace(cwd, retention_days, force=False):
    """按 mtime 删除超龄文件；retention_days<=0 → 关闭自动清理（no-op）。
    force=True（手动清理端点）无视保留期，删除全部 tool_* 文件。"""
    if retention_days <= 0 and not force:
        return 0, 0
    d = _store_dir(cwd)
    if not d.is_dir():
        return 0, 0
    cutoff = time.time() if force else time.time() - retention_days * 86400
    n = b = 0
    for f in d.iterdir():
        try:
            if not (f.is_file() and f.name.startswith("tool_")):
                continue
            st = f.stat()
            if force or st.st_mtime < cutoff:  # S191：force=无视 mtime 全清（时钟偏斜/时间戳粒度下不漏删）
                b += st.st_size
                f.unlink()
                n += 1
        except OSError:
            continue
    if n:
        try:
            d.rmdir()  # 目录空则顺手回收（非空自动失败）
        except OSError:
            pass
    return n, b


def _scan_targets(settings):
    """当前 cc_path ∪ 登记工作区（S184 上线前已有 tool_output 的旧区也能被扫到）。"""
    cc = ((settings or {}).get("CLISettings") or {}).get("cc_path") or ""
    ws = list_workspaces()
    if cc and os.path.isdir(cc) and cc not in ws:
        ws = [cc] + ws
    return ws


def cleanup_all(settings, force=False):
    """遍历全部登记工作区清理。返回 (清理文件数, 释放字节, 工作区数)。
    force=True → 手动"立即清理"（无视保留期）。"""
    _l, _b, retention = tool_output_cfg(settings)
    files = size = 0
    ws = _scan_targets(settings)
    for w in ws:
        n, b = cleanup_workspace(w, retention, force=force)
        files += n
        size += b
    return files, size, len(ws)


def stats_all(settings):
    """(当前工作区(文件数,字节), 全部区(文件数,字节))。"""
    cc = ((settings or {}).get("CLISettings") or {}).get("cc_path") or ""
    cur = store_stats(cc) if cc else (0, 0)
    tf = tb = 0
    for w in _scan_targets(settings):
        n, b = store_stats(w)
        tf += n
        tb += b
    return cur, (tf, tb)


# ==================== ripgrep 定位 / 探测 ====================

_RG_RELEASE_URL = ("https://github.com/BurntSushi/ripgrep/releases/download/"
                   "{ver}/ripgrep-{ver}-{arch}.zip")

_RG_TARGETS = {
    ("win32", "amd64"): "x86_64-pc-windows-msvc",
    ("win32", "arm64"): "aarch64-pc-windows-msvc",
    ("linux", "amd64"): "x86_64-unknown-linux-musl",
    ("linux", "arm64"): "aarch64-unknown-linux-musl",
    ("darwin", "amd64"): "x86_64-apple-darwin",
    ("darwin", "arm64"): "aarch64-apple-darwin",
}


def _norm_machine(machine):
    import platform
    m = (machine or platform.machine() or "").lower()
    return {"x86_64": "amd64", "amd64": "amd64", "i686": "amd64",
            "aarch64": "arm64", "arm64": "arm64"}.get(m, m)


def rg_download_url(system=None, machine=None):
    """pin 版本的官方 release zip URL（平台不支持返回 None）。"""
    system = system or sys.platform
    arch = _RG_TARGETS.get((system, _norm_machine(machine)))
    if not arch:
        return None
    return _RG_RELEASE_URL.format(ver=RG_VERSION_PIN, arch=arch)


def rg_bin_dir():
    from py.get_setting import USER_DATA_DIR
    return Path(USER_DATA_DIR) / "bin"


def _rg_name():
    return "rg.exe" if os.name == "nt" else "rg"


def find_ripgrep():
    """探测顺序：SAP_RG_PATH → <SAP_DATA_DIR>/bin/ → PATH。命中返回路径。"""
    env = os.environ.get("SAP_RG_PATH", "").strip()
    if env and os.path.isfile(env):
        return env
    bundled = rg_bin_dir() / _rg_name()
    if bundled.is_file():
        return str(bundled)
    return shutil.which("rg")


def rg_version(rg_path, timeout=5):
    try:
        out = subprocess.run([rg_path, "--version"], capture_output=True,
                             timeout=timeout, text=True)
        first = (out.stdout or "").splitlines()
        m = _re.search(r"(\d+\.\d+\.\d+)", first[0] if first else "")
        return m.group(1) if m else "unknown"
    except Exception:
        return None


def ripgrep_status():
    p = find_ripgrep()
    if not p:
        return {"found": False, "path": "", "version": "", "bundled_dir": str(rg_bin_dir())}
    try:
        source = "env" if os.environ.get("SAP_RG_PATH", "").strip() == p else (
            "installed" if _is_under(p, rg_bin_dir()) else "path")
    except Exception:
        source = "unknown"
    return {"found": True, "path": p, "version": rg_version(p) or "unknown",
            "source": source, "expected_version": RG_VERSION_PIN,
            "bundled_dir": str(rg_bin_dir())}


def _is_under(path, base):
    try:
        return Path(path).resolve().is_relative_to(Path(base).resolve())
    except Exception:
        return False
