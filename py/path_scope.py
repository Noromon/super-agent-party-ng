# -*- coding: utf-8 -*-
"""S153: 本地路径权限门（opencode external_directory 语义）。

两类规则（PATH_SCOPED_TOOLS）：
- fs   文件工具类（*_tool_local 七件套，工作区语义由 resolve_strict_path 实施）：
  工作区内免费；区外→单独审批。工具名白名单（allowed_tools）永远绕不过本门。
- read 读取族（图像/文件直读，本无工作区围栏）：任何本地路径都需审批（含工作区内）；
  http(s)/服务器内部 URL 免费。

"不再询问"落点=项目级 allowed_dirs（.party/config.json，与 allowed_tools 相互独立）。
yolo/cowork= Bypass Permissions，连目录门一并豁免并注入通配授权。

放行通道注入 GRANTS contextvar（授权目录集，'*'=全放行）：
- dispatch_tool：门算得放行（yolo/allowed_dirs）时设置；
- execute_approved_tool：批复执行时设置（端点任务上下文，天然不回流生成流）。
contextvar 随 asyncio Task 隔离；即便在长流任务中滞留也无害——门在 hook 之前
执行，未经门的调用永远到不了 grants 的消费点（resolve_strict_path）。
"""
import contextvars
import os
import re
from urllib.parse import unquote, urlparse

# tool_name -> (规则类, 路径参数名列表)
PATH_SCOPED_TOOLS = {
    # fs：工作区内免费，区外审批
    "list_files_tool_local": ("fs", ["path"]),
    "read_file_tool_local": ("fs", ["path"]),
    "read_file_range_tool_local": ("fs", ["path"]),
    "tail_file_tool_local": ("fs", ["path"]),
    "edit_file_tool_local": ("fs", ["path"]),
    "edit_file_patch_tool_local": ("fs", ["path"]),
    "search_files_tool_local": ("fs", ["path"]),
    # read：任何本地路径审批，URL 免费
    "get_image_content": ("read", ["image_url"]),
    "analyze_image": ("read", ["image_url"]),
    "review_image": ("read", ["image_url"]),
    "analyze_images": ("read", ["image_urls"]),
    "get_file_content": ("read", ["file_url"]),
    "custom_llm_tool": ("read", ["image_url"]),
}

# 目录类工具（授权粒度=目标目录本身；文件类=其父目录）
_DIR_TARGET_TOOLS = {"list_files_tool_local", "search_files_tool_local"}

_DRIVE_RE = re.compile(r"^[a-zA-Z]:[\\/]")
_UP_RE = re.compile(r"^(?:\.\.?)(?:[/\\]|$)")
_EXT_RE = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")

_GRANTS = contextvars.ContextVar("sap_path_grants", default=None)


# ==================== 路径工具 ====================

def path_norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def path_within(child, parent) -> bool:
    """child 位于 parent 内（含相等）；分隔符边界安全（C:\\ 不误配 C:\\x 之邻）。"""
    c = path_norm(child)
    p = path_norm(parent)
    if not p:
        return False
    if p.endswith(os.sep):
        return c.startswith(p)
    return c == p or c.startswith(p + os.sep)


def normalize_path(raw, cwd=None) -> dict:
    """把模型给的路径/URL 形态归一：{'kind': url|path|none, 'resolved', 'exists'}。
    file:// 解前缀、~ 展开、工作区相对解析；裸文件名（无分隔符）仅在存在时判 path。"""
    none = {"kind": "none", "resolved": str(raw or ""), "exists": False}
    if raw is None:
        return none
    s = str(raw).strip().strip("<>").strip()
    for q in ('"', "'"):
        if len(s) >= 2 and s.startswith(q) and s.endswith(q):
            s = s[1:-1]
    if not s:
        return none
    low = s.lower()
    if low.startswith(("http://", "https://")):
        return {"kind": "url", "resolved": s, "exists": True}
    if low.startswith("file://"):
        rp = unquote(urlparse(s).path or "")
        if os.name == "nt" and re.match(r"^/[a-zA-Z]:[\\/]", rp):
            rp = rp[1:]
        if rp:
            return _finalize(rp.replace("/", os.sep), cwd)
        return none
    looks = (os.path.isabs(s) or bool(_DRIVE_RE.match(s)) or bool(_UP_RE.match(s))
             or s.startswith("~") or "/" in s or (os.sep != "/" and os.sep in s)
             or bool(_EXT_RE.search(s)))
    s2 = os.path.expanduser(s)
    if ("uploaded_files" in low and not os.path.isabs(s)
            and not _DRIVE_RE.match(s) and not s.startswith("~")):
        # 内部路由相对串：留给 URL 流程（sanitize_url 重写 netloc）
        return none
    if not looks:
        # 无标记串：只有真实存在才按本地路径对待（避免误伤奇异输入）
        try:
            looks = os.path.exists(s2) or bool(cwd and os.path.exists(os.path.join(cwd, s2)))
        except Exception:
            looks = False
    if not looks:
        return none
    return _finalize(s2, cwd)


def _finalize(p, cwd) -> dict:
    # 相对串以工作区为基准优先（'.'/'sub' 等相对语义=cc_path，而非服务器进程 cwd）
    cands = []
    if cwd and not (os.path.isabs(p) or _DRIVE_RE.match(p)):
        cands.append(os.path.join(cwd, p))
    cands.append(p)
    for c in cands:
        try:
            if os.path.exists(c):
                return {"kind": "path",
                        "resolved": os.path.normpath(os.path.abspath(c)), "exists": True}
        except Exception:
            pass
    prim = cands[0] if cwd and len(cands) > 1 else p
    try:
        resolved = os.path.normpath(os.path.abspath(prim))
    except Exception:
        resolved = str(prim)
    return {"kind": "path", "resolved": resolved, "exists": False}


# ==================== GRANTS（执行期授权注入） ====================

def set_grants(grants):
    _GRANTS.set(grants)


def clear_grants():
    _GRANTS.set(None)


def grants_allow(candidate_path) -> bool:
    g = _GRANTS.get()
    if not g:
        return False
    if g == "*":
        return True
    return any(path_within(candidate_path, d) for d in g)


def grant_dir_for(tool_name: str, resolved_path: str) -> str:
    """审批卡与 allowed_dirs 的授权粒度：目录工具=目标本身，文件=父目录。"""
    if tool_name in _DIR_TARGET_TOOLS:
        return os.path.normpath(resolved_path)
    return resolved_path if os.path.isdir(resolved_path) else os.path.dirname(os.path.normpath(resolved_path))


# ==================== 采集与判定 ====================

def collect_scoped_paths(tool_name: str, tool_params: dict, cwd: str):
    """→ (规则类, [path entries]) 或 None（工具不在表内/无路径参数）。"""
    spec = PATH_SCOPED_TOOLS.get(tool_name)
    if not spec or not isinstance(tool_params, dict):
        return None
    kind, keys = spec
    out = []
    for k in keys:
        v = tool_params.get(k)
        if v is None or v == "":
            continue
        vals = v if isinstance(v, list) else [v]
        for item in vals:
            if not isinstance(item, str) or not item.strip():
                continue
            info = normalize_path(item, cwd)
            if info["kind"] == "path":
                out.append(info)
    return kind, out


class Decision:
    __slots__ = ("payload", "error", "grants")

    def __init__(self, payload=None, error=None, grants=None):
        self.payload = payload
        self.error = error
        self.grants = grants

    @property
    def block(self):
        return self.payload or self.error


def permission_mode_for(settings: dict) -> str:
    """读取当前 CLI 引擎对应的权限模式（值域已归一化）。
    S153: 自 server.py 平移至此（路径门需要，server.cli_permission_mode_for
    改为委托调用，行为零变化）。"""
    from py.cli_tool import normalize_permission_mode
    cli = (settings or {}).get("CLISettings", {})
    engine = cli.get("engine", "")
    if engine == "local":
        env = (settings or {}).get("localEnvSettings", {})
    elif engine == "ds":
        env = (settings or {}).get("dsSettings", {})
    elif engine == "wsl":
        env = (settings or {}).get("wslSettings", {})
    else:
        env = (settings or {}).get("acpSettings", {})
    return normalize_permission_mode(env.get("permissionMode", "default"))


def evaluate(tool_name: str, tool_params: dict, settings: dict):
    """dispatch 前判定。None=与本门无关/免费；Decision.block=哨兵审批或清晰错误；
    Decision.grants=放行且需注入的授权集。"""
    cwd = ((settings or {}).get("CLISettings") or {}).get("cc_path") or os.getcwd()
    got = collect_scoped_paths(tool_name, tool_params or {}, cwd)
    if not got:
        return None
    kind, entries = got
    if not entries:
        return None
    missing = [e["resolved"] for e in entries if not e["exists"]]
    if missing:
        return Decision(error="[参数错误] 本地文件/目录不存在："
                        + "、".join(str(m)[:200] for m in missing)
                        + "。请核实路径（支持工作区相对路径与绝对路径）；"
                        "不要将其当作 URL 重试。")
    need = []
    for e in entries:
        if kind == "fs" and path_within(e["resolved"], cwd):
            continue
        need.append(e)
    if not need:
        return None
    mode = permission_mode_for(settings)
    if mode in ("yolo", "cowork"):
        return Decision(grants="*")
    from py.agent import is_dir_allowed_by_project_config
    dirs = []
    pending = False
    for e in need:
        g = grant_dir_for(tool_name, e["resolved"])
        dirs.append(g)
        if not (cwd and is_dir_allowed_by_project_config(cwd, g)):
            pending = True
    if not pending:
        return Decision(grants=tuple(dict.fromkeys(path_norm(d) for d in dirs)))
    from py.tool_dispatch import _approval_payload
    return Decision(payload=_approval_payload(tool_name, tool_params, mode, cwd,
                                              scope="local-path",
                                              reason="workspace-external-or-raw-disk-read"))


def approved_call_grants(tool_name: str, tool_params: dict, cwd: str) -> tuple:
    """批复执行用：算出本次调用需注入的授权目录集（外部 fs + 读取族本地路径）。"""
    got = collect_scoped_paths(tool_name, tool_params or {}, cwd or os.getcwd())
    if not got:
        return ()
    kind, entries = got
    out = []
    for e in entries:
        if not e["exists"]:
            continue
        if kind == "fs" and path_within(e["resolved"], cwd):
            continue
        out.append(path_norm(grant_dir_for(tool_name, e["resolved"])))
    return tuple(dict.fromkeys(out))
