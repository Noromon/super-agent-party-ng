![image](static/source/cover.png)

# Super Agent Party **NG**

> [super-agent-party](https://github.com/heshengtao/super-agent-party)（AGPL-3.0）の**再構築フォーク**。
> 本フォークは独立して維持されており、本家作者とは**無関係**です。本家が元のプロジェクトであり、著作権は原作者に帰属します。
> [简体中文](README_ZH.md) | [English](README.md) | 日本語

<a href="https://github.com/Noromon/super-agent-party-ng"><img src="https://img.shields.io/badge/repo-super--agent--party--ng-0052CC?style=for-the-badge&logo=github"/></a>
<a href="LICENSE"><img src="https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge"/></a>
<a href="#"><img src="https://img.shields.io/badge/version-1.0.0-00B4AB?style=for-the-badge"/></a>
<a href="SECURITY.md"><img src="https://img.shields.io/badge/security-SECURITY.md-red?style=for-the-badge"/></a>

---

## このフォークが存在する理由

「自前の製品を作ろう」から始まったのではありません。

**第一幕・ひとつのスキル。**
Super Agent Party にワークフロースキルを追加しようとしたのが始まりです。優れたコーディングエージェントのように、手順通りに動けるように。

**第二幕・現実。**
詰まりどころはスキル自体ではなく、その下のエージェント基盤でした。ツールループはモデルの不正出力一文で脱線し、プランモードは飾り、権限モードは強制されず、システムプロンプトは平坦な文字列。opencode 世代のエージェントと比べた差は機能リストではなく**土台**にありました。

**第三幕・小さな問題。**
ツールループ完全性・プランモード・権限強制・階層プロンプトを埋めた後、小さな問題が列を作りました：境界で壊れるメッセージ連鎖、失われるツール引数、停止後に残る返信、通話と競合する記憶抽出。個別は軽微、しかし全部合わせて一つのことを示していました——データ経路に単一の真実源がない、と。

**第四幕・監査。**
2026 年 10 月、全面監査を実施：コード、バックエンド、フロントエンド、ビルド、git 履歴。結論は「パッチ数個」の域を超えていました。実到達可能な認証回避、パス処理のインジェクション、危険なビルド既定値。

**第五幕・再構築。**
M/R 系列のリファクタ：メッセージ連鎖の単一真実源化、サーバー側権威 `turn_log`、ループバックセッショントークン認証カーネル、コンテキスト管理パイプライン、承認とストリームの相関スナップショット——そして **807 本のテスト**によるラチェットで退化を許しません。

**第六幕・収束。**
再構築後の土台はむしろ本家追跡が容易くなりました。日記システム、OpenAI Responses / Gemini アダプタ、新規検索エンジン、IM クイックコマンドなど本家の新機能を新アーキテクチャへ移植。ここに「モダンなエージェントワークフローを載せられる Super Agent Party」が成立しました。

初回コミットから v1.0.0 まで：10 日間、313 コミット。全工程は履歴にあります。隠していません。

## 本家との差分（vs 本家 v0.4.1）

| 領域 | 本家 | NG |
|---|---|---|
| ツールループ | 不正出力で中断・履歴汚染 | 完全性検証＋再試行上限＋履歴サニタイザ |
| プラン／権限モード | 存在するが未強制 | 強制実行、範囲外呼び出しを遮断 |
| システムプロンプト | 単層連結 | 階層化（ペルソナ／ツール／安全） |
| メッセージ連鎖のデータ経路 | 3 箇所に重複した清洗処理 | 単一真実源（`py/context_builder`）＋権威 `turn_log` |
| 認証 | ループバック面は無防備に近い | セッショントークンカーネル（cookie/Origin/Host/WS 4401）＋免除面ホワイトリスト |
| 外部 API（/v1, /mcp） | 完全トークンフリー・ワイルドカード CORS | 既定は互換のためフリー、ワンタップでトークン必須化＋起動時警告；CORS 強化 |
| パスと ID 面 | トラバーサル／インジェクション余地 | realpath 包含検証＋書式ホワイトリスト |
| レンダリング | mermaid `securityLevel: loose` | `strict` ＋ DOMPurify |
| 品質ガードレール | テストまばら | 807 本の回帰テスト＋ruff/eslint ゲート＋構造ピン |
| Windows | 概ね動作 | 主戦場として修正（文字コード・シグナル・パス等） |
| 準拠 | 第三者告知不完全 | vendored 全 LICENSE＋KaTeX フォント復元（`static/libs/VENDORED.md`） |
| バージョン | v0.4.x | フォーク独立 semver、現在 **1.0.0**（本家 v0.4.1 系譜） |

## できること

本家の全機能を、信頼できる土台の上で：

- **デスクトップパートナー**：VRM モデル／モーション／3D シーン、[live2D 拡張](https://github.com/heshengtao/sap-live2d)
- **タスクセンター**：バックエンド高度タスク、PC 自動操作、MCP／Agent Skills
- **PC 制御**：デスクトップ視覚＋マウス／キーボード／ターミナル
- **多キャラグループチャット**：キャラカード＋長期記憶
- **IM ボット**：QQ／WeChat／Feishu／DingTalk／Telegram／Discord／Slack ワンクリック展開
- **配信ボット**：Bilibili／YouTube／Twitch、360° パノラマ
- **AI ブラウザ**：エージェント専用ブラウザの自動操作
- **拡張システム**：導入も自作も、独立ウィンドウ／サイドバー両対応
- **開発者向け**：OpenAI 互換 API＋MCP 中継

機能スクリーンショットは[本家 README](https://github.com/heshengtao/super-agent-party)参照。

## インストール

### デスクトップ（本フォーク、ソース実行）

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
npm install
npm start        # Electron デスクトップ
```

バックエンドのみ：

```bash
uv sync
uv run python server.py
```

> フォークのプレビルドは未提供。パッケージングは `npm run build`（出力先 `release/`）。

### 本家インストーラ（NG 変更を**含まない**）

本家が各プラットフォーム版を提供：<https://github.com/heshengtao/super-agent-party/releases>
ただし本家のビルドに本フォークの再構築・セキュリティ強化は**含まれません**。

### Docker

```bash
git clone https://github.com/Noromon/super-agent-party-ng.git
cd super-agent-party-ng
# まず .env に JWT_SECRET（長いランダム文字列）、INIT_USER、INIT_PASS を設定
# — デフォルト認証情報はなく、未設定ならゲートウェイは起動を拒否します
docker-compose up -d
```

<http://localhost:3456/> にアクセスし、設定した `INIT_USER` / `INIT_PASS` でログイン。
（compose のイメージは本家ビルドのため NG 変更なし。フォーク版は `docker build .` で。）

## セキュリティと外部 API

- 既定では `127.0.0.1` のみリッスン。LAN／公開は明示的な選択です。まず [SECURITY.md](SECURITY.md) を。
- **`/v1` と `/mcp` は設計上トークンフリー**（到達できるローカルプロセス／LAN 機器から。クォータを消費されます）。設定で `Authorization: Bearer <マシントークン>` 必須化への切替が可能。
- 脆弱性報告：本リポジトリの GitHub Issues / Security Advisories。本家にも存在する所見は本家メンテナへの通知もご検討ください。

## 本家との関係 / ライセンス

- 本家：<https://github.com/heshengtao/super-agent-party>、著作権は原作者（Copyright © 2025 Heshengtao）。
- 本フォークは **AGPL-3.0**（本家と同ライセンス）で配布される変更版です。変更点はコミット履歴と上表参照。
- ユーザーデータ目錄と設定フォーマットは本家と**完全互換**：データパスも拡張エコシステム URL も未変更のため、両バージョンで同一データを共用できます。
- 第三者コンポーネントのライセンス：[static/libs/VENDORED.md](static/libs/VENDORED.md)。

## FAQ

**Q: 本家に PR を出さないのですか？**
A: 再構築の規模と方向（コア置換）は「寄与パッチ」の範囲を超えるため、フォークで先行し全公開（AGPL）。誰でも持っていけます。

**Q: 本家からそのまま移行できますか？**
A: 可能です。データ目錄改名なし・フォーマット互換。同じフォルダを指すだけです。

**Q: 本家の今後の更新には？**
A: 本家とのコミット対応関係を保持。「バッチ＋機能別適配」で移植（`feat(port/...)` 参照）。

**Q: テスト数が硬性指標なのは何故？**
A: 再構築最大のリスクは静かな退化。807 本と構造ピンはラチェット：緑になる方向にしか進みません。

---

**Maintained by [Noromon](https://github.com/Noromon)** · 本フォークは本家作者と無関係です。問題は本リポジトリの Issue へ。
