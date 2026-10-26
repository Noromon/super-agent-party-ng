# Security Policy / 安全策略

## 威胁模型 / Threat Model

Super Agent Party 是一个**本机优先**的桌面应用。默认网络边界：

- 后端仅监听 `127.0.0.1`（`network=local`，默认）。
- 用户可在「系统设置 → 网络」切换为局域网可见（`0.0.0.0`），此为显式选择，风险自负。
- 浏览器侧所有非豁免 API 需 `X-SAP-Token` / `sap_token` cookie / `?sap_token=`（同源自动携带）；
  WebSocket 握手同样校验。Origin 与 Host 校验用于缓解 CSRF 与 DNS rebinding。

## 外联 API（`/v1`、`/mcp`）/ External API

OpenAI 兼容面 `/v1` 与 MCP 面 `/mcp` **默认免 token**，以保持既有脚本/局域网集成兼容。
这意味着：能访问该端口的任何程序都可以调用你的模型配额。

- 收紧方式：系统设置 →「外联 API 需要令牌」（`systemSettings.externalApiRequireToken`），
  或环境变量 `SAP_EXTERNAL_API_REQUIRE_TOKEN=1`。
- 开启后需 `Authorization: Bearer <machine token>`，token 位于数据目录 `.machine_token`。
- 服务启动时若处于免 token 模式，日志会输出一条 warning。

## 已知边界 / Known Boundaries

- 数据目录（会话、记忆、上传文件、`.session_token`、`.machine_token`）为明文存储，
  依赖操作系统级磁盘加密与用户账户隔离。
- 插件/扩展（`/ext/*`）运行于服务端进程内，安装第三方扩展前请自行审查其代码。
- 桌面端渲染层对 Markdown 渲染启用 DOMPurify 与 mermaid `securityLevel: strict`，
  但会话内容仍应视为半可信。

## 漏洞披露 / Reporting a Vulnerability

请通过本仓库的 **GitHub Security Advisories（Private Vulnerability Report）** 或 GitHub Issue 报告安全问题。
避免在公开 Issue 中直接贴出可复现的利用细节；涉及本 fork 特有改动的问题请注明版本号。

请上游与本仓库分别评估影响：若漏洞同样存在于上游
[super-agent-party](https://github.com/heshengtao/super-agent-party)，建议同时通知上游维护者。
