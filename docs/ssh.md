# SSH 端末

ブラウザ内の対話型ターミナルから、管理者が登録した接続先へ SSH します。
メンテナンスや、SSH 上で動く CLI サービスの操作に使います。
Compose の **profile `ssh`** でオプション起動します。

## 起動

```bash
# 開発
docker compose --profile ssh up -d --build

# または .env に
# COMPOSE_PROFILES=ssh
```

本番も同様に `COMPOSE_PROFILES=ssh` または `--profile ssh` を付けます。
`ssh-app` のポートはホストに出しません。ブラウザは常に Open GENAI の `/ssh` と `/api/ssh/*` 経由です。

## 構成

- 専用ページ: `/ssh`
- フロント: `genai-web/packages/web/src/open-genai/ssh/`（`SshPage`）
- マイクロサービス: `ssh-app`（コンテナ `open-genai-ssh-app`。FastAPI + SQLite、内部ポート `8018`）
- backend は `/ssh/*` を HMAC 付きでプロキシし、`/ssh/ws` で PTY を中継する
- nginx は `/api/ssh/ws` を rewrite せず backend の `/ssh/ws` へ Upgrade する（`/api/` の rewrite だと握手が 404 になる）
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示

```
ブラウザ (xterm.js)
  → WSS /api/ssh/ws（JWT）
  → nginx → backend → ssh-app
  → カタログ上の host:port へ SSH
```

## 権限

| 操作 | 対象 |
| --- | --- |
| 接続先の追加・編集・削除 | SystemAdmin のみ |
| カタログから選んで接続 | 認証済みユーザー |

接続先はカタログ（allowlist）のみです。利用者が任意の `host:port` を入力することはできません。

## SSH 認証

接続時に利用者がユーザー名とパスワードを入力します。パスワードはサーバに保存せず、監査ログにも残しません。

初回接続でホスト鍵を覚え、以後は不一致なら拒否します。管理者は接続先編集でホスト鍵を確認・空にして再取得できます。

## 制限

- エージェント転送・X11・ポートフォワードは使いません
- 画面サイズは 80×25 文字。入力は UTF-8
- アイドル切断（既定 30 分）と、利用者あたりの同時セッション上限（既定 2）
- SFTP、鍵のサーバ保存、踏み台は対象外です

## 監査

接続開始（`ssh.connect`）と切断（`ssh.disconnect`）を記録します。残すのは利用者、接続先 ID、ユーザー名、結果、時間です。パスワードは残しません。

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `SSH_APP_URL` | `http://ssh-app:8018/invoke` | backend からの接続先（末尾 `/invoke` はヘルスチェック導出用） |
| `SSH_IDLE_SECONDS` | `1800` | 無操作切断（秒） |
| `SSH_MAX_SESSIONS_PER_USER` | `2` | 利用者あたりの同時セッション数 |
| `SSH_CONNECT_TIMEOUT` | `20` | SSH ログイン待ち（秒） |
| `COMPOSE_PROFILES` | （空） | `ssh` を含めると起動 |

閉域でも「Web からカタログ上の SSH 先へ届く」点は残ります。カタログは必要なホストだけを登録してください。

## 同じマシンの別コンテナへつなぐ

接続はブラウザではなく **ssh-app コンテナ** から行われます。カタログのホストに `localhost` や `127.0.0.1` を書くと、ssh-app 自身を指して失敗します。

- 相手コンテナがホストにポートを出している場合（例: `2222:2222`）: `host.docker.internal` と、公開しているポートを登録する。`localhost` と書いた場合も内部で `host.docker.internal` に読み替えます
- 同じ Docker ネットワークに載せている場合: 相手のサービス名またはコンテナ名と、コンテナ内の待ち受けポートを登録する
