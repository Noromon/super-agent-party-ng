# -*- coding: utf-8 -*-
"""S205 提示词组装块注册表：系统提示静态块的单一存放地。

这些块自 server.tools_change_messages 逐字节迁出（golden 永久钉：
tests/data/s205_prompt_literals.json）。条件判断与拼接顺序仍留在调用方，
本模块只管「文本长什么样」，不管「何时注入」。新增常驻静态块请入册 BLOCKS。
"""

DOCKER_ENV_INFO = '【环境信息】操作系统：Linux | Shell：bash\n\n⚠️ 重要提示：\n1. 当前为 Docker 环境，请使用 Linux 命令和工具链\n2. 执行 docker_sandbox 时，命令必须符合 Linux 的语法规范\n3. 路径分隔符：Unix 使用正斜杠(/)\n4. 请尽量使用相对路径，避免使用绝对路径，以免在跨平台时出现问题\n\n### ✅ **已安装的主要开发工具**\n\n#### **编程语言和运行时**\n1. **Python**\n   - Python\n   - pip\n   - uv\n\n2. **Node.js**\n   - Node.js\n   - npm\n   - npx\n\n3. **Go**\n   - Go\n\n4. **Perl**\n   - Perl\n\n#### **版本控制和协作工具**\n1. **Git**\n   - git\n   - GitHub CLI (gh)\n\n#### **包管理和构建工具**\n1. **Python 包管理**\n   - pip / pip3\n   - uv\n\n2. **Node.js 包管理**\n   - npm / npx\n\n3. **系统包管理**\n   - apt-get / dpkg\n\n#### **文本处理和命令行工具**\n1. **文本处理**\n   - jq\n   - awk / sed / grep\n   - cat / less / more / head / tail\n\n2. **文件操作**\n   - tar / unzip\n   - rsync\n   - 所有基本 Unix 命令（ls, cp, mv, rm, mkdir, chmod 等）\n\n3. **系统工具**\n   - bash shell\n   - make\n   - which / whereis\n\n#### **网络工具**\n1. **HTTP 客户端**\n   - curl\n\n2. **安全工具**\n   - openssl\n   - gpg\n\n#### **系统监控**\n1. **进程和资源监控**\n   - top / ps\n   - free / df / du\n   \n'
WSL_ENV_INFO = '【环境信息】操作系统：Linux (WSL2) | Shell：bash\n\n重要提示：\n1. 当前为 WSL2 沙盒环境，请使用 Linux 命令和工具链\n2. 文件系统路径格式为 Linux 标准路径（如 /mnt/d/project）\n3. 命令通过 bash 执行，请使用 Linux 语法规范\n4. 工作目录已自动映射到 WSL 路径\n5. apt、pip、npm 等包管理器可直接使用\n6. 端口监听在 WSL 内，可通过 localhost 从 Windows 访问'
AUTO_BEHAVIOR_HINT = '\n\n当你看到被插入到对话之间的系统消息，这是自主行为系统向你发送的消息，例如用户主动或者要求你设置了一些定时任务或者延时任务，当你看到自主行为系统向你发送的消息时，说明这些任务到了需要被执行的节点，例如：用户要你三点或五分钟后提醒开会的事情，然后当你看到一个被插入的“提醒用户开会”的系统消息，你需要立刻提醒用户开会，以此类推\n\n'
INFERENCE_THINK_HINT = '回答用户前请先思考推理，再回答问题，你的思考推理的过程必须放在<think>与</think>之间。\n\n'
LATEX_DELIM_HINT = "\n\n当你想使用latex公式时，你必须是用 ['$', '$'] 作为行内公式定界符，以及 ['$$', '$$'] 作为行间公式定界符。\n\n"
STICKER_IMAGE_RULE = '\n\n当你需要使用图片时，请将图片的URL放在markdown的图片标签中，例如：\n\n<silence>![图片名](图片URL)</silence>\n\n，图片markdown必须另起并且独占一行！<silence>和</silence>是控制TTS的静音标签，表示这个图片部分不会进入语音合成\n\n你必须在回复中正确使用 <silence> 标签来包裹图片的 Markdown 语法\n\n<silence>和</silence>与图片的 Markdown 语法之间不能有空格和回车，会导致解析失败！\n\n'
TEXT2IMG_IMAGE_RULE = '\n\n当你使用画图工具后，必须将图片的URL放在markdown的图片标签中，例如：\n\n<silence>![图片名](图片URL)</silence>\n\n，图片markdown必须另起并且独占一行！请主动发给用户，工具返回的结果，用户看不到！<silence>和</silence>是控制TTS的静音标签，表示这个图片部分不会进入语音合成\n\n你必须在回复中正确使用 <silence> 标签来包裹图片的 Markdown 语法\n\n注意！！！<silence>和</silence>与图片的 Markdown 语法之间不能有空格和回车，会导致解析失败！\n\n'

BLOCKS = {
    'docker_env_info': DOCKER_ENV_INFO,
    'wsl_env_info': WSL_ENV_INFO,
    'auto_behavior_hint': AUTO_BEHAVIOR_HINT,
    'inference_think_hint': INFERENCE_THINK_HINT,
    'latex_delim_hint': LATEX_DELIM_HINT,
    'sticker_image_rule': STICKER_IMAGE_RULE,
    'text2img_image_rule': TEXT2IMG_IMAGE_RULE,
}
