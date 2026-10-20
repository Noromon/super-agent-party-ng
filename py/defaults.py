# -*- coding: utf-8 -*-
"""M-6：py 侧默认端口与默认服务地址的单一事实源（改默认值只改这里）。

- 用户可通过 settings 覆盖的项，覆盖键名保持不变，本模块只提供兜底默认；
- 前端 vue_data.js 侧默认值按计划于 R3 阶段对齐本约定；
- cdp_tool.py 的 3456 是 Chrome 调试端口回退值，与服务端口语义无关，刻意不并入。
"""

# 后端 HTTP 服务默认端口（Electron 主进程/compose 使用同值；argparse 兜底）
DEFAULT_SERVER_PORT = 3456

# 外部组件兜底地址
FUNASR_WS_URL = "ws://localhost:10095"
GSV_TTS_URL = "http://127.0.0.1:9880"

# node 扩展子进程可用端口段
NODE_EXT_PORT_RANGE = (3100, 13999)
