# ワールドモニター

[World Monitor](https://github.com/koala73/worldmonitor) を、ログイン後の専用ページで開きます。
Compose の **profile `worldmonitor`** でオプション起動します。未起動のときはページに手順だけ出ます。

ソースは同梱しません。ライセンスは上流の AGPL-3.0 です。公開レジストリには版タグが無いので、アプリ本体・Redis の窓口・船舶リレーを上流タグからビルドします。

## 起動

```bash
docker compose --profile worldmonitor up -d

# または .env に
# COMPOSE_PROFILES=worldmonitor
```

本番も同じ profile を足します。ホストへポートは出しません。ブラウザは Open GENAI の
`/worldmonitor` だけを開きます。

初回は upstream のクローンとイメージのビルドがあるため時間がかかります。
タグは `WM_GIT_REF`（既定 `v2.10.0`）です。

## 画面

専用ページは Open GENAI のヘッダの下を、地図とパネルで埋めます。画面上のタイトルは出しません。

## 認証

ページを開くと、ログイン済みの応答が `/worldmonitor-ui/` 向けの HttpOnly クッキーを出します。
nginx はそのクッキーがないリクエストを World Monitor へ通しません。

## データ

鍵がなくても、地震・気象などの公開フィードは API が都度取りに行きます。
市場・紛争・航空・船舶は、環境変数で鍵を足すと増えます。上流の一覧は
[SELF_HOSTING.md](https://github.com/koala73/worldmonitor/blob/v2.10.0/SELF_HOSTING.md) です。

閉域で外へ出られない場合、コンテナは動きますがパネルは空に近くなります。

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `COMPOSE_PROFILES` | （空） | `worldmonitor` を含めると起動 |
| `WORLDMONITOR_UPSTREAM` | `http://worldmonitor:8080` | backend からの到達確認 |
| `WM_GIT_REF` | `v2.10.0` | ビルドする upstream のタグ |
| `WM_SESSION_SECRET` | 開発用の32文字以上 | 上流の匿名セッション署名。本番は変更 |
| `WM_REDIS_PASSWORD` / `WM_REDIS_TOKEN` / `WM_RELAY_SHARED_SECRET` | 開発用 | コンテナ間だけ。本番は変更 |
| `WM_LLM_API_URL` | （空） | 要約を OpenAI 互換の LLM に向けるとき |

要約をこの環境の Ollama に向けると、チャットと同じモデルを使います。既定では呼びません。
