![image](static/source/cover.png)

# Super Agent Party **NG**

> A rebuilt fork of [super-agent-party](https://github.com/heshengtao/super-agent-party) (AGPL-3.0).
> This fork is maintained independently and is **not affiliated with the upstream author**.
> Upstream remains the original project; its copyright belongs to its author.
> [简体中文](README_ZH.md) | English | [日本語](README_JA.md)

<a href="https://github.com/Noromon/super-agent-party-ng"><img src="https://img.shields.io/badge/repo-super--agent--party--ng-0052CC?style=for-the-badge&logo=github"/></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge"/></a>
<a href="#"><img src="https://img.shields.io/badge/version-1.0.0-00B4AB?style=for-the-badge"/></a>
<a href="SECURITY.md"><img src="https://img.shields.io/badge/security-SECURITY.md-red?style=for-the-badge"/></a>

---

## Why this fork exists

It didn't start as "let's build our own product". It started like this:

**Act 1 — A skill.**
I wanted to add a workflow skill to Super Agent Party so it could operate procedurally, the way good coding agents do.

**Act 2 — Reality.**
The blocker turned out not to be the skill itself, but the agent core underneath it. The tool loop could be derailed by a single malformed model output, plan mode was decorative, permission modes weren't enforced, and the system prompt was a flat string. Compared to agents like opencode, the gap wasn't the feature list — it was the **foundation**.

**Act 3 — Small problems.**
After patching the core capabilities one by one (tool-loop integrity, plan mode, permission enforcement, layered prompts), small issues started queueing up: message chains corrupted at edge cases, tool arguments lost in history, half-finished replies surviving stop-generation, memory extraction racing with chat calls. Individually minor; together they spelled one thing — no single source of truth on the data path.

**Act 4 — The audit.**
In October 2026 we stopped and ran a full audit: code, backend, frontend, packaging, git history. The verdict went far beyond "a few patches" — reachable auth bypasses on real surfaces, injection in path handling, and dangerous defaults in the build chain.

**Act 5 — The rebuild.**
Thus the M/R refactor batches: the message chain normalized into a single source of truth, a server-side authoritative `turn_log`, a loopback session-token auth kernel, a context-management pipeline, approval/stream correlation snapshots — all pinned by **807 tests** as a ratchet so none of it can quietly regress.

**Act 6 — Convergence.**
The rebuilt skeleton was actually easier to track upstream on: the diary system, OpenAI Responses / Gemini adapters, new search engines, IM quick commands and other upstream features were ported back onto the new architecture. At that point a Super Agent Party that can carry a modern agent workflow actually existed.

From first commit to v1.0.0: 10 days, 313 commits. The whole process is in the history — nothing hidden.

## What's different (vs upstream v0.4.1)

| Area | Upstream | NG |
|---|---|---|
| Tool loop | Derails/history pollution on malformed model output | Integrity validation + capped retries + history sanitizer |
| Plan / permission modes | Present, not enforced | Enforced; out-of-scope calls intercepted |
| System prompt | Flat concatenation | Layered assembly (persona / tools / safety) |
| Message-chain data path | Triplicated cleaning logic | Single source of truth (`py/context_builder`) + server-authoritative `turn_log` |
| Auth | Loopback surfaces largely unprotected | Loopback session-token kernel (cookie / Origin / Host / WS 4401) + tightened exemption whitelist |
| External API (/v1, /mcp) | Fully token-free, wildcard CORS | Token-free by default (compat), one-switch "require token" mode + startup warning; CORS tightened |
| Paths & IDs | Traversal/injection surfaces | realpath containment + strict ID format allowlist |
| Rendering | mermaid `securityLevel: loose` | `strict` + DOMPurify |
| Guardrails | Sparse tests | 807 regression tests + ruff/eslint gates + structural pin tests |
| Windows | Basically works | Primary platform; encoding/signal/path/island fixes |
| Compliance | Incomplete third-party notices | Full vendored LICENSE set + KaTeX fonts restored (see `static/libs/VENDORED.md`) |
| Versioning | v0.4.x | Independent fork semver, currently **1.0.0** (based on the upstream v0.4.1 line) |

## What you get

Everything upstream does — on a foundation the agent part can actually trust:

- **Desktop companion**: custom VRM models, motions, 3D scenes, [live2D extension](https://github.com/heshengtao/sap-live2d)
- **Task center**: advanced background tasks, computer control, MCP and Agent Skills
- **Computer control**: desktop vision plus mouse/keyboard/terminal tooling
- **Multi-character group chat**: tavern character cards + long-term memory
- **IM bots**: QQ, WeChat, Feishu, DingTalk, Telegram, Discord, Slack — one-click deploy
- **Live-stream bots**: Bilibili, YouTube, Twitch, 360° panoramas
- **AI browser**: a dedicated browser the agent can drive
- **Extension system**: install or build extensions; standalone window or sidebar
- **Developer APIs**: OpenAI-compatible API + MCP egress

Screenshots: see the [upstream README](https://github.com/heshengtao/super-agent-party#introduction).

## Install

### Desktop (this fork, from source)

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
npm install
npm start        # Electron desktop
```

Backend only (no Electron):

```bash
uv sync
uv run python server.py
```

> No prebuilt binaries for the fork yet; to package one: `npm run build` (output in `release/`).

### One-click source bootstrap (empty or half-configured machines alike)

Source releases ship **no bundled runtimes**. Whether your machine is a clean empty one or a half-installed "half environment", just run the bootstrap script in the repository root — it asks for confirmation **before every single install action**:

| Platform | Entry point |
| --- | --- |
| Windows | double-click `setup_and_run.bat` (launches `setup_and_run.ps1`; `-Full` forces a complete re-check) |
| Linux / macOS | `bash setup_and_run.sh` (`--full` does the same) |

- **Ready means instant launch**: if the environment is already complete the app starts immediately with zero prompts via `node start.js`; only incomplete environments enter guided setup.
- **Guided flow**: detect runtimes (missing Python 3.12 / Node.js LTS installed via winget or official installer links, after your confirmation) → create `.venv` inside the project and verify it really runs Python 3.12 (recreated only after you confirm) → install Python dependencies **reproducibly from `uv.lock`** via `uv` → install Node dependencies deterministically with `npm ci --ignore-scripts` → explicitly produce the Electron runtime → start the app once you confirm.
- If the locked install (`uv sync --frozen`) fails, the script **explicitly warns that it would fall back to a NON-reproducible `pip install -e .`** and waits for your confirmation before doing so.
- **Three-stage Electron runtime production** (the most common hidden pitfall of source deployments; the script prints on-site evidence and exit codes throughout):
  1. run the official Electron install script directly (local download cache forcibly bypassed);
  2. on failure, retry through the npmmirror Electron binary mirror after your confirmation;
  3. if that still fails, fetch the official runtime archive with the OS built-in downloader and enforce **SHASUMS256 verification** (unpack refused on mismatch), then unpack it into place — npm lifecycle scripting is never relied upon, so even the quirkiest machine has a path that works.
- **Integrity gate**: an Electron binary under 50MB or a missing `path.txt` always counts as "not ready"; the app never launches in a half-installed state, and such states are detected automatically and routed into the repair path.
- **Network & mirrors**: official sources by default; the Tsinghua PyPI mirror and npmmirror are enabled **only after a failure, and only with your confirmation**.
- **Boundaries**: idempotent and re-runnable; apart from confirmed engine installs nothing outside the project folder is touched; no silent elevation, no silent installs, and your system/user environment variables are never modified.
- **Optional degrades gracefully**: esbuild/@serialport native build failures never block launch (the affected features simply degrade).

Troubleshooting: any failure — just re-run (idempotent). The printed file sizes, exit codes and download URLs are your diagnostic leads; in extreme cases repair offline by copying `node_modules/electron/dist` plus `path.txt` from a healthy same-version install, or use the official packaged release with bundled runtimes.

### Upstream installers (do NOT include NG changes)

Upstream ships per-platform installers: <https://github.com/heshengtao/super-agent-party/releases>.
Note those builds do **not** contain this fork's rebuild or security hardening.

### Docker

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
# First create .env with JWT_SECRET (long random string), INIT_USER and INIT_PASS —
# there are no default credentials; the gateway refuses to start without them.
docker-compose up -d
```

Open <http://localhost:3456/> and log in with the `INIT_USER` / `INIT_PASS` you set.
(The compose image is built upstream and lacks NG changes; build the fork yourself with `docker build .` if needed.)

## Security & the external API

- Listens on `127.0.0.1` by default; LAN/public exposure is an explicit choice — read [SECURITY.md](SECURITY.md) first.
- **`/v1` and `/mcp` are token-free by design** for anything that can reach the port (local processes, LAN peers — consuming your model quota). A settings switch turns on `Authorization: Bearer <machine token>`.
- Disclosure: GitHub Issues / Security Advisories on this repo; if a finding also exists upstream, consider notifying upstream maintainers too.

## Relationship with upstream / License

- Upstream: <https://github.com/heshengtao/super-agent-party>, copyright © its author (Copyright © 2025 Heshengtao).
- This fork is distributed under **AGPL-3.0** (same as upstream) and contains substantial modifications — see the commit history and the table above.
- User-data directory and config format are **fully compatible** with upstream: paths and the extension-registry URL were not changed, so both versions can share one dataset.
- Third-party component licenses: [static/libs/VENDORED.md](static/libs/VENDORED.md).

## FAQ

**Q: Why not just send PRs upstream?**
A: The rebuild's scope and direction (core replacement) go well beyond contributing patches. The fork ships first, everything stays public under AGPL, and anyone may take it.

**Q: Can I move over from upstream directly?**
A: Yes. The data directory was not renamed and the formats are compatible — point both at the same data folder; no migration tooling needed.

**Q: What about future upstream updates?**
A: Commit correspondence with upstream is preserved; features are ported in "batch + per-feature adaptation" style (see `feat(port/...)` commits).

**Q: Why is the test count a hard metric?**
A: The biggest risk of a rebuild is silent regression. 807 tests plus structural pins form a ratchet: things may only turn green, never be bypassed.

---

**Maintained by [Noromon](https://github.com/Noromon)** · This fork is unaffiliated with the upstream author. Please file issues in this repository.
