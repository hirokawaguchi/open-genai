# オフィス

[ibisOffice](https://github.com/ibisjp/ibis-office) のブラウザー版を、ログイン後の専用ページに埋め込みます。
Word（`.docx`）、Excel（`.xlsx`）、PowerPoint（`.pptx`）を、ブラウザの中で開いて編集します。
Compose の **profile `office`** でオプション起動します。未起動のときはページに手順だけ出ます。

配布物は同梱しません。ライセンスは上流の AGPL-3.0-only（商用ライセンスは ibis inc.）です。
ビルドはタグ `v<版>` のソースアーカイブを SHA-256 で照合し、
そのタグが指す GPUI のフォークを取り、
`office-ui/patches/keep-opened-source.patch` を当ててからブラウザー版を作ります。
この差分は、開いたファイルの元データを残し、ファイル > 保存と右上のダウンロードが
今の内容を親ページへ渡せるようにします。上流の 0.8.7 は表示用に読むだけで、
保存時に「新しい文書の保存にはまだ対応していません」となります。
対応するソースは、そのタグとこの差分です。配信ディレクトリの
`OPEN-GENAI-MODIFICATION.txt` にも同じ旨を置きます。
組み込み方は上流の [ブラウザー版の組み込み](https://github.com/ibisjp/ibis-office/blob/v0.8.7/docs/web-embedding-ja.md) に従います。

## 起動

```bash
docker compose --profile office up -d --build

# または .env に
# COMPOSE_PROFILES=office
```

本番も同じ profile を足します。ホストへポートは出しません。ブラウザは Open GENAI の
`/office/word`、`/office/excel`、`/office/powerpoint` を開きます。

初回はソースの取得と、ブラウザー版のビルドがあります。版は `IBIS_OFFICE_VERSION`
（既定 `0.8.7`）です。ソースアーカイブの SHA-256 は `IBIS_OFFICE_SOURCE_SHA256`
に控えてあり、ビルド時に一致しなければ失敗します。

## 画面

アプリは 3 つです。同じエディターを、種類ごとの空のファイルで開きます。

| アプリ | パス | 起動時に開くファイル |
| --- | --- | --- |
| 文書 | `/office/word` | Word（`.docx`） |
| 表計算 | `/office/excel` | Excel（`.xlsx`） |
| スライド | `/office/powerpoint` | PowerPoint（`.pptx`） |

`/office` は文書へ移します。メニューから手元のファイルを開くこともできます。

## ダウンロード

ファイル > 保存と右上のダウンロードは、今のファイル名のまま親ページへ渡します。
名前を付けて保存はファイル名を聞いてから渡します。拡張子は開いているファイルのままです。取り消すと、名前も内容も変わりません。
親ページは成果物の配信設定 `ARTIFACT_DELIVERY_MODE` に従います。

- `open`（既定）: 今の内容を端末へ直接保存します。バイト列はサーバへ送りません。
- `carrier`、または `auto` で Host が `*.lgwan.jp`: 今の内容を SeaweedFS へ書き、案内ファイル（リンクファイル）を端末へ渡します。案内ファイルをインターネット接続端末で開くと本体を取得できます。保存領域へ書けないときは、本体を端末へ保存します。

開く・編集・フォントの保持は、直接ダウンロードのときブラウザの中だけで完結します。

## 認証

ページを開くと、ログイン済みの応答が `/office-ui/` 向けの HttpOnly クッキーを出します。
nginx はそのクッキーがないリクエストをエディターへ通しません。

## ブラウザ

WebGPU が必要です。対応していないブラウザでは、エディター自身が案内を出します。
新しい Chrome、Edge、Safari を使います。

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `COMPOSE_PROFILES` | （空） | `office` を含めると起動 |
| `OFFICE_UPSTREAM` | `http://office:8080` | backend からの到達確認 |
| `IBIS_OFFICE_VERSION` | `0.8.7` | 取得するリリースタグ |
| `IBIS_OFFICE_SOURCE_SHA256` | リポジトリに控えた値 | `v<版>` ソースアーカイブの SHA-256 |

第三者ライセンスの表示は、配信ディレクトリの `license.md`（`/office-ui/license.md`）にあります。
ソースはリリースのタグ `v<版>` と `office-ui/patches/keep-opened-source.patch` です。
