# -*- coding: utf-8 -*-
"""S300：运行期取「活的服务端模块实例」的唯一惯用法。

部署形态 `python server.py` 下模块名是 __main__；此时任何 `import server`
都会二次执行 server.py 的模块体（端口二次竞态绑定/change_port 覆盖全局——
S300 e2e 实锤）。routers 域的 `_sys.modules.get('server') or _sys.modules['__main__']`
惯例上提为共享函数：迁移域（vision_tools/group_memory/prompt_builders 及后续
引擎域）读 server 真源必须走 srv()，禁止 `import server`。
"""
import sys


def srv():
    m = sys.modules.get("server") or sys.modules.get("__main__")
    if m is None:  # pragma: no cover - 理论不可达（仅当二者皆无的奇特宿主）
        raise RuntimeError("srv(): live server module not found")
    return m
