![image](static/source/cover.png)

# Super Agent Party **NG**

> 对 [super-agent-party](https://github.com/heshengtao/super-agent-party)（AGPL-3.0）的**重构分支**。
> 本 fork 独立维护，与上游作者**无关联**；上游是原始项目，其版权归原作者。
> 简体中文 | [English](README.md) | [日本語](README_JA.md)

<a href="https://github.com/Noromon/super-agent-party-ng"><img src="https://img.shields.io/badge/仓库-super--agent--party--ng-0052CC?style=for-the-badge&logo=github"/></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge"/></a>
<a href="#"><img src="https://img.shields.io/badge/版本-1.0.0-00B4AB?style=for-the-badge"/></a>
<a href="SECURITY.md"><img src="https://img.shields.io/badge/安全-SECURITY.md-red?style=for-the-badge"/></a>

---

## 这个 fork 为什么存在

它不是从「想做个自己的产品」开始的。故事是这样的：

**第一幕 · 一个技能。**
我想给 Super Agent Party 追加一个工作流技能，让它像那些优秀的 coding agent 一样按流程办事。

**第二幕 · 现实。**
动手之后发现，真正卡住的不是技能本身——是它的 agent 内核。工具循环可以被模型一句话带停、计划模式形同虚设、权限模式不生效、系统提示词没有分层。和 opencode 这一代 agent 相比，差距不在功能列表，在**地基**。

**第三幕 · 小问题。**
把内核能力一项项补上之后（工具循环完整性、计划模式、权限强制、分层提示词），小问题开始排队出现：消息链在边界处错乱、工具参数丢失、停止生成后残留半截回复、记忆抽取和对话抢锁……每一个都不致命，合起来说明一件事：数据通路没有单一事实源。

**第四幕 · 审计。**
2026 年 10 月，停下来做了一次全面审计：代码、后端、前端、打包、git 历史，逐面过。结论远超「打几个补丁」的尺度——鉴权面有真实可达的绕过、路径处理有注入、构建链带着危险的默认值。

**第五幕 · 重构。**
于是有了 M/R 系列批次重构：消息链归一为单一事实源、服务端权威 turn_log、环回 token 鉴权内核、上下文管理管线、审批与流的关联快照……并为它们配上 **807 个测试**作为棘轮，防止任何一项退化。

**第六幕 · 合拢。**
重构后的骨架反而更好接上游了：日记系统、OpenAI Responses / Gemini 适配器、新搜索引擎、IM 快捷指令等上游新功能被逐个移植回来并适配新架构。至此，一个能装上现代 agent 工作流的 Super Agent Party 成立了。

从第一次提交到 v1.0.0，10 天，313 个提交。完整过程就在提交历史里，没有藏。

## 和上游的差异（vs 上游 v0.4.1）

| 维度 | 上游 | NG |
|---|---|---|
| 工具循环 | 模型输出畸形时循环中断/污染历史 | 完整性校验 + 重试上限 + 历史消毒 |
| 计划模式 / 权限模式 | 存在但不强制生效 | 强制执行，越权调用被拦截 |
| 系统提示词 | 单层拼接 | 分层装配（人格/工具/安全独立成层） |
| 消息链数据通路 | 三处复制的清洗逻辑 | 单一事实源（`py/context_builder`）+ 服务端权威 `turn_log` |
| 鉴权 | 同源面基本不设防 | 环回 session token 内核（cookie/Origin/Host/WS 4401）+ 豁免面白名单收紧 |
| 外联 API（/v1、/mcp） | 完全免鉴权、通配 CORS | 默认仍免 token（兼容），新增一键「需要令牌」开关 + 启动警示；CORS 收紧 |
| 路径与 ID 面 | 存在目录穿越/注入面 | realpath 包含校验 + ID 格式白名单 |
| 渲染面 | mermaid `securityLevel: loose` | `strict` + DOMPurify |
| 质量护栏 | 少量测试 | 807 个回归测试 + ruff/eslint 门控 + 结构 pin 测试 |
| Windows | 基本可用 | 作为主平台修复（编码、信号、路径、灵动岛等） |
| 合规 | 第三方许可不完整 | vendored 库全量 LICENSE + KaTeX 字体补齐（见 `static/libs/VENDORED.md`） |
| 版本线 | v0.4.x | fork 独立 semver，当前 **1.0.0**（基于上游 v0.4.1 谱系） |

## 它能做什么

继承上游的全部能力，并把 agent 部分换成可靠的地基：

- **桌面伴侣**：自定义 VRM 模型、动作、3D 场景，[live2D 扩展](https://github.com/heshengtao/sap-live2d)
- **任务中心**：后台执行高级任务，自动控制电脑干活，支持 MCP 与 Agent Skills
- **电脑控制**：桌面视觉 + 鼠标/键盘/终端工具链
- **多角色群聊**：酒馆角色卡 + 长期记忆
- **IM 机器人**：QQ、微信、飞书、钉钉、Telegram、Discord、Slack 一键部署
- **直播机器人**：B站、YouTube、Twitch，支持 360° 全景直播
- **AI 浏览器**：智能体专属浏览器，支持自动控制
- **扩展系统**：安装与自造扩展，独立窗口/侧边栏双模式
- **开发者接口**：OpenAI 兼容 API + MCP 对外转接

功能截图见[上游 README](https://github.com/heshengtao/super-agent-party#简介)。

## 安装

### 桌面端（本 fork，源码运行）

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
npm install
npm start        # Electron 桌面端
```

后端独立运行（无 Electron 环境时）：

```bash
uv sync
uv run python server.py
```

> fork 暂未发布预编译安装包；如需打包：`npm run build`（产物在 `release/`）。

### 一键部署：源码引导脚本（空机与半残环境均可用）

源码发布包**不自带任何运行时**。无论机器是全新空环境还是装到一半的"半环境"，运行仓库根目录的引导脚本即可；它在**每个安装动作前逐一询问**：

| 平台 | 入口 |
| --- | --- |
| Windows | 双击 `setup_and_run.bat`（转调 `setup_and_run.ps1`；`-Full` 强制完整检查） |
| Linux / macOS | `bash setup_and_run.sh`（`--full` 同上） |

- **就绪即秒启**：环境完全就绪时零确认直接 `node start.js` 启动；未就绪才进入引导安装。
- **引导流程**：探测运行时（缺 Python 3.12 / Node LTS 经确认用 winget 或官方直链补装）→ 项目内建 `.venv` 并校验确为 Python 3.12（不符经确认重建）→ 安装 uv 并按 `uv.lock` 可复现安装 Python 依赖 → `npm ci --ignore-scripts` 确定性安装 Node 依赖 → 显式产出 Electron 运行时 → 经确认启动。
- 锁定安装（`uv sync --frozen`）失败时，脚本会**先明确警告"降级为非可复现 pip 安装"**，得到您的确认才执行 `pip install -e .`。
- **Electron 运行时三级产出**（源码部署最常见的暗坑，全程打印现场证据与退出码）：
  1. 直接执行 Electron 官方安装脚本（强制绕过本地下载缓存）；
  2. 失败后经确认切 npmmirror 二进制镜像重试；
  3. 仍失败则用系统自带下载器直接获取官方运行时压缩包，**SHASUMS256 强校验**（不过即拒绝解包）后自动解包就位——全程不依赖 npm 生命周期脚本，环境再怪也有一条路能走通。
- **完整性闸门**：electron 二进制不足 50MB 或缺 path.txt 一律"未就绪"，永不带病启动；半残安装自动识别并进入修复路径。
- **网络与镜像**：默认全官方源；清华 PyPI 与 npmmirror 仅在失败后经您确认启用。
- **边界**：幂等可重跑；除经确认的运行时安装外只写项目目录；不静默提权、不静默安装、不改系统/用户环境变量。
- **可选降级**：esbuild/@serialport 原生组件编译失败不阻断启动（相应功能降级）。

故障排查：任何失败直接重跑（幂等）；脚本打印的文件大小/退出码/下载 URL 即诊断线索；极端情况可离线修复——拷贝同版本 `node_modules/electron/dist` + `path.txt`，或改用自带运行时的官方打包版。

### 上游安装包（不含 NG 改动）

上游提供各平台安装包下载：<https://github.com/heshengtao/super-agent-party/releases>。
注意上游构建**不包含**本 fork 的重构与安全加固。

### Docker

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
# 先创建 .env：设置 JWT_SECRET（随机长串）、INIT_USER、INIT_PASS —— 没有默认凭据，缺项网关拒绝启动
docker-compose up -d
```

访问 <http://localhost:3456/>，用你设置的 `INIT_USER` / `INIT_PASS` 登录。
（compose 引用的镜像由上游构建，不含 NG 改动；如需 fork 构建，自行 `docker build .`。）

## 安全与外联 API

- 默认仅监听 `127.0.0.1`；局域网/公网暴露是显式选择，请读完 [SECURITY.md](SECURITY.md)。
- **`/v1` 与 `/mcp` 设计上对能触达端口的来源免 token**（本机程序、局域网设备——消耗你的模型配额）。设置中可开启「外联 API 需要令牌」改用 `Authorization: Bearer <机器令牌>`。
- 漏洞披露：本仓库 GitHub Issues / Security Advisories；若问题同样存在于上游，建议同步通知上游维护者。

## 与上游的关系 / License

- 上游：<https://github.com/heshengtao/super-agent-party>，版权归其作者（Copyright © 2025 Heshengtao）。
- 本 fork 依 **AGPL-3.0** 分发（与上游同许可），含大量修改——详见提交历史与上方差异表。
- 用户数据目录与配置格式与上游**完全兼容**：数据路径、插件生态地址均未改动，两个版本可交替使用同一份数据。
- 第三方组件许可见 [static/libs/VENDORED.md](static/libs/VENDORED.md)。

## FAQ

**Q：为什么不直接给上游提 PR？**
A：重构的体量与方向（内核级替换）已超出「贡献补丁」的范畴；fork 先行、成果公开，任何项目都可以按 AGPL 自取。

**Q：我能从上游直接迁移过来吗？**
A：可以。数据目录未改名、格式兼容，直接指向同一份数据即可，无需迁移工具。

**Q：上游继续更新怎么办？**
A：fork 保留了与上游的提交对应关系，移植采用「批次 + 逐功能适配」方式（见提交历史 `feat(port/...)`）。

**Q：为什么测试数量是硬指标？**
A：重构最大的风险是悄悄退化。807 个测试 + 结构 pin 是棘轮：只许变绿，不许绕过。

---

**Maintained by [Noromon](https://github.com/Noromon)** · 本 fork 与上游作者无关，问题请在本仓库提 Issue。
