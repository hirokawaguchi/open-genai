# TLS 証明書の配置

リバースプロキシ（nginx）はこのディレクトリの証明書で TLS を終端します。

必要なファイル:

- `fullchain.pem` … サーバ証明書（中間CA含むフルチェーン）
- `privkey.pem` … 秘密鍵

## 本番（推奨）

組織/自治体の CA が発行した証明書を上記の名前で配置してください。
`docker-compose.prod.yml` が `./proxy/certs` を `/etc/nginx/certs`（読み取り専用）へマウントします。

## 閉域検証用（自己署名）

TLS 不要で HTTP(80) のみ使う場合は `docker-compose.verify.yml` を併用してください
（証明書の配置は不要）。

自己署名証明書で HTTPS 検証する場合のみ:

```bash
./generate-selfsigned.sh genai.example.lg.jp
```

自己署名のため、利用者端末に当該 CA/証明書を信頼設定する必要があります。

> このディレクトリの `*.pem` は **リポジトリにコミットしない**でください
> （`.gitignore` 済み）。
