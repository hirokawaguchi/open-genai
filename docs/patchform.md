# フォーム（patchform）

庁内・外部回答者向けのオンラインフォームです。Compose の **profile `patchform`** でオプション起動します。画面上の日本語名は「フォーム」です。

## 起動

```bash
# 開発
docker compose --profile patchform up -d --build

# または .env に
# COMPOSE_PROFILES=patchform
```

本番も同様に `COMPOSE_PROFILES=patchform` または `--profile patchform` を付けます。`PATCHFORM_PUBLIC_ENDPOINT` に外部公開 URL を設定してください。

## 構成

| 経路 | 用途 |
|------|------|
| Open GENAI `/patchform` | 認証済みの作成・回答・集計（DADS 専用画面） |
| `PATCHFORM_PUBLIC_ENDPOINT/public/...` | ゲスト回答（別ホストのリバースプロキシ） |

- マイクロサービス: `patchform-app`（FastAPI + SQLite）
- backend は `/patchform/*` を HMAC 付きでプロキシ（`depends_on` なし）
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示

## 外部公開（デュアルイングレス）

Open GENAI 本体の nginx からゲスト API を晒さないでください。別ホストで [`proxy/patchform.public.conf.example`](../proxy/patchform.public.conf.example) を参考に **`/public` のみ** upstream します。

開発時は `patchform-app` のホストポート（既定 `8012`）でゲスト UI を直接確認できます。

ゲストの入力欄は庁内プレビューと同じ `FillForm` です。部品を変えたあとは、庁内 Web 側でバンドルを再生成します。

```bash
cd genai-web/packages/web
npm run build:patchform-guest
```

出力は `patchform-app/public/guest.js` と `guest.css` です。`patchform-app` のイメージを再ビルドすると公開面に載ります。

LGWAN から外部 URL に届かない場合は、フォーム画面の「リンクファイル」を持ち出して別端末で開きます。

## データ保持

- 既定で作成から **365 日**経過したフォームを自動削除（`PATCHFORM_RETENTION_DAYS`）。フォームごとに変更可
- データはボリューム `patchform_app_data`（`/data/patchform.db` と `/data/files`）
- バックアップは当該ボリュームまたは DB と添付ディレクトリのコピーで行う

## フォーム定義

定義は JSON 契約 `opengenai-patchform/1` です。カタログに無い部品、または未実装（`enabled: false`）の部品は保存できません。

現在利用できる部品: text, textarea, email, phone, number, select, radio, checkbox, slider, rating, date, time, datetime-local, daterange, file, address_composite, user_info_composite, company_info_composite, financial_institution_composite, calculated, text_display, image_display, divider, page_break, password, mynumber（庁内専用・暗号化）, matrix_question, signature_pad, location, qr_scanner, image_recognition, document_reader

各部品には任意で IMI 語彙（`imi_type`）を付けられます。マイナンバーは `internal` 以外の公開範囲では配置できません。画像認識は Vision モデル、文書読取はテキストファイルを自動抽出し、失敗時は手入力できます。

複合部品では次を補います。郵便番号は zipcloud で都道府県・市区町村・町名を補完します。法人番号は検査数字を確認し、`PATCHFORM_GBIZ_TOKEN` があるときだけ gBizINFO から法人名を補完します（未設定・失敗時は手入力）。氏名には性別・生年月日を含めます。ゆうちょの記号・番号は店番と口座番号（7桁）に換算して保存します。

庁内の詳細画面では回答内容を開き、CSV / JSONL で書き出せます。ゲスト送信前には確認画面が出ます。出した回答は消さずに取り下げできます。庁内は一覧から、外部は控え番号（暗証があればそれも）から操作します。取下げの取消は庁内だけです。件数とCSVの「受付」は取下げを除きます。

回答の途中は「下書きを保存」で戻せます（庁内はログイン中の職員ごと、外部は同じ端末）。同じ人の再提出を止める設定も編集画面にあります。回答者の扱いはフォームごとに選びます。申請は記名必須、任意記名は空なら匿名、匿名は名前も職員IDも一覧に出しません。作成者は、編集できる職員と回答だけ見られる職員をユーザーIDで指定できます。システム管理者（`SystemAdminGroup`）はすべてのフォームを扱えます。

マイナンバーは一覧では末尾4桁以外を隠します。番号そのものを見る・含めて書き出す操作は監査ログに残ります。

`page_break` を置くと、回答画面は進捗付きのページ送りになります。表示条件（`visibleWhen`）は複数の AND と「いずれかの値」に対応し、隠れた必須項目は回答不要です。計算部品は入力中に再計算します。

公開後に部品を直しても、回答者にはすぐ見えません。保存は下書きで、詳細画面の「公開版に反映」（受付終了後は「再公開する」）で新しい版になります。これまでの回答は、答えた当時の版のまま残ります。

添付（`file`）と署名画像（`signature_pad`）は `/data/files` に実ファイルを保管します。回答一覧からダウンロードできます。CSV にはファイル名と ID が残ります。許可する形式は PDF・画像・テキスト・Office 文書、既定の上限は 10MB です。

## LLM アシスト（庁内のみ）

OpenAI 互換 API（既定は Ollama）でフォーム定義の作成・修正と案内文下書きを行います。失敗時は自治体向けテンプレートにフォールバックします。ゲスト公開面には出しません。

## 環境変数

| 変数 | 説明 | 例 |
|------|------|-----|
| `COMPOSE_PROFILES` | `patchform` を含めると起動 | `patchform` |
| `PATCHFORM_APP_URL` | backend → サービス | `http://patchform-app:8012/invoke` |
| `PATCHFORM_PUBLIC_ENDPOINT` | 外部共有 URL のホスト | `https://form.example.lg.jp` |
| `PATCHFORM_PUBLIC_PORT` | 開発時ホスト公開ポート | `8012` |
| `PATCHFORM_RETENTION_DAYS` | 既定の保持日数 | `365` |
| `PATCHFORM_MODEL` | アシスト用モデル | `qwen2.5:7b` |
| `PATCHFORM_VISION_MODEL` | 画像認識用 Vision モデル | `gemma3:12b` |
| `PATCHFORM_ENCRYPT_KEY` | マイナンバー暗号化鍵（Fernet）。未設定時は内部署名鍵から導出 | |
| `PATCHFORM_FILES_DIR` | 添付の保存先 | `/data/files` |
| `PATCHFORM_MAX_UPLOAD_BYTES` | 1件あたりの上限 | `10485760`（10MB） |
| `PATCHFORM_LOOKUP_TIMEOUT` | 郵便番号・法人番号照会の秒数 | `8` |
| `PATCHFORM_GBIZ_TOKEN` | gBizINFO の API トークン。未設定時は法人名を自動入力しない | |
