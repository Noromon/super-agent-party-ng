# -*- coding: utf-8 -*-
"""批 1 反耦合棘轮：routers 对 server 的运行时反查（`_srv.`）只降不升。

背景：R1 迁 router 时用 `sys.modules` 拿 server 对象读全局（routers 无法
import server——环依赖），批 1 把共享状态迁 py/app_state.py / py/stream_relay.py
后逐个改直连。本棘轮锁定当前上限，任何新增 `_srv.` 触点都会红灯。
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "py" / "routers"

# 上限基线（批 1b 后实测）；后续子批目标：bots/bot_conversations→1d，
# files/media/memories/system/workflows 余量→批 2。
SRV_REF_CAPS = {
    "agents.py": 0,
    "bot_conversations.py": 10,
    "bots.py": 0,
    "files.py": 0,
    "media.py": 0,
    "memories.py": 25,
    "status.py": 0,
    "system.py": 0,
    "tasks.py": 0,
    "workflows.py": 0,
}


def _srv_refs(path):
    return len(re.findall(r"_srv\.", path.read_text(encoding="utf-8")))


def test_srv_refs_within_caps():
    total = 0
    for f in sorted(ROUTERS.glob("*.py")):
        n = _srv_refs(f)
        total += n
        cap = SRV_REF_CAPS.get(f.name, 0)
        assert n <= cap, f"{f.name}: _srv 触点 {n} 超上限 {cap}（新状态请走 py/app_state.py）"
    assert total <= sum(SRV_REF_CAPS.values())


def test_tasks_and_status_fully_decoupled():
    # 1a/1b/1d 已拔桩的模块禁止回潮
    for name in ("tasks.py", "status.py", "agents.py", "bots.py", "workflows.py"):
        assert "_srv = " not in (ROUTERS / name).read_text(encoding="utf-8"), name


def test_app_state_keys_not_redefined_in_server():
    """迁移后的状态单一事实源在 py/app_state.py，server.py 不得再定义。"""
    state_src = (ROOT / "py" / "app_state.py").read_text(encoding="utf-8")
    tree = ast.parse(state_src)
    keys = set()
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            keys.add(node.targets[0].id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            keys.add(node.target.id)
    assert {"HA_client", "ChromeMCP_client", "sql_client", "mcp_client_list",
            "global_http_client", "mcp_status", "kb_status"} <= keys
    srv = (ROOT / "server.py").read_text(encoding="utf-8")
    for k in keys:
        assert not re.search(r"^" + k + r"\s*=", srv, re.M), \
            f"{k} 在 server.py 重复定义（会遮蔽 app_state 造成双事实源）"
