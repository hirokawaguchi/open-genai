# Web ブラウザ

サーバ上の Chromium を、Open GENAI から開いた別ウィンドウに表示します。
認証済みの利用者が公開 Web を見るための画面です。Compose の **profile `browser`** でオプション起動します。

## 起動

```bash
# 開発
docker compose --profile browser up -d --build

# または .env に
# COMPOSE_PROFILES=browser
```

本番も同様に `COMPOSE_PROFILES=browser` または `--profile browser` を付けます。
`browser-app` のポートはホストに出しません。ブラウザは常に Open GENAI の `/browser` と `/api/browser/*` 経由です。

## 構成

- 起動ページ: `/browser`。ここからアドレスバーのない別ウィンドウを開く
- 別ウィンドウの中は Chromium だけ。Open GENAI のヘッダも、`/browser/window` のアドレスバーも出さない
- フロント: `genai-web/packages/web/src/open-genai/browser/`（`BrowserPage`、`BrowserWindowPage`、noVNC）
- マイクロサービス: `browser-app`（コンテナ `open-genai-browser-app`。内部ポート `8024`）
- コンテナ内で Xvfb、Chromium、x11vnc を利用者ごとに起動し、画面のバイト列を WebSocket で中継する
- backend は `/browser/*` を HMAC 付きでプロキシし、`/browser/ws` で画面を中継する
- nginx は `/api/browser/ws` を rewrite せず backend の `/browser/ws` へ Upgrade する
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示

```
ブラウザ (noVNC)
  → WSS /api/browser/ws（JWT）
  → nginx → backend → browser-app
  → x11vnc → Chromium
  → 出口プロキシ → 公開 IP の 80/443
```

Chromium のアドレスバーとタブがそのまま見えます。Open GENAI 側でページ描画を作り直してはいません。

## 出口

Chromium の通信はコンテナ内の転送プロキシを通ります。プロキシが名前を解決し、接続直前の IP を見ます。

許可するのは公開 IP のポート 80 と 443 だけです。次は拒否します。

- ループバック、リンクローカル、プライベート IP、共有アドレス（100.64.0.0/10）
- クラウドのメタデータアドレス
- `localhost`、`.local`、`.internal`
- 解決結果に内部 IP が一つでも含まれる名前
- 80 と 443 以外のポート

`file://` と `chrome://` は Chromium のポリシーで拒否します。WebRTC のプロキシ外 UDP は無効です。

サイトを管理者が登録した宛先だけに限る機能は、まだありません。許可判定は `browser-app/app/egress.py` の `decide` に閉じているので、あとからそこを差し替えられます。

## セッション

| 項目 | 既定 |
| --- | --- |
| 利用者あたり | 1。開き直すと前の画面は閉じる |
| 全体の同時数 | 2 |
| 無操作の切断 | 30 分 |
| 画面 | 1280×800 |
| 初期ページ | `about:blank` |

Cookie もログイン状態も残しません。切断、アイドル、プロセス終了でプロファイルを消します。

ポインタとキーの操作だけを操作として数えます。画面を見ているだけでは、30 分で切れます。

## ダウンロード

Chromium が受け取ったファイルは、そのセッションの中に一度だけ置きます。画面側が取り、オフィスのダウンロードと同じ配信設定で、見ている PC へ渡します。文書台帳には書きません。

- `open`（`auto` で LGWAN 以外）はファイル本体を保存する
- `carrier`（`auto` で `*.lgwan.jp`）は案内ファイルを保存する。案内ファイルを作れないときは本体を保存し、「案内ファイルを作れなかったため、ファイル本体を保存しました。」と出す

50 MiB を超えるファイルは渡しません。ページの URL は残しません。案内ファイルを作ったときだけ、ファイル名を `file.output`（usecase `browser`）に残します。

## 音声

Chromium の再生は、見ている PC のスピーカーへ出します。画面を一度クリックすると音が出ます。

マイクは「ブラウザを開く」と同時に入り、そのウィンドウを閉じるまで入れたままです。PC が許可を尋ねます。スピーカーもマイクも、セッションごとの仮想デバイスです。別のセッションの音は混ざりません。ウィンドウを閉じるとマイクも切れます。

サイトとの WebRTC の UDP は出口で止まったままです。ページの再生と、ページがマイクを HTTPS で送る通信は、公開の 80 番と 443 番を通ります。

## 監査

接続開始（`browser.session_start`）と切断（`browser.session_end`）を記録します。残すのは利用者、セッション ID、結果、時間です。ページの URL は残しません。

出口プロキシは接続先のホスト名と拒否理由だけをコンテナのログに出します。パスとクエリは残しません。

## 制限

- ファイル選択はコンテナの中を見ます。利用者の PC からはアップロードできません
- 画面サイズは固定です。Open GENAI の枠には縮小して収めます
- 日本語は、見ている PC の入力方式で変換する。確定した文字を Chromium に送る。変換候補は PC 側に出る

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `BROWSER_APP_URL` | `http://browser-app:8024/invoke` | backend からの接続先（末尾 `/invoke` はヘルスチェック導出用） |
| `BROWSER_IDLE_SECONDS` | `1800` | 無操作切断（秒） |
| `BROWSER_MAX_SESSIONS_PER_USER` | `1` | 利用者あたりの同時セッション数 |
| `BROWSER_MAX_SESSIONS` | `2` | 全体の同時セッション数 |
| `BROWSER_SCREEN` | `1280x800` | Chromium の画面サイズ |
| `BROWSER_EGRESS_PORT` | `18080` | コンテナ内の出口プロキシ |
| `COMPOSE_PROFILES` | （空） | `browser` を含めると起動 |

コンテナはメモリ上限 3g、共有メモリ 2g です。Chromium のサンドボックスは外しません。Docker の既定 seccomp がサンドボックスの起動を妨げるため、このサービスだけ `seccomp:unconfined` にしています。
