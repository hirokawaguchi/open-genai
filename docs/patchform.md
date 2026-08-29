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

LGWAN から外部 URL に届かない場合は、「手続きを公開」の「リンクファイル」を持ち出して別端末で開きます。

## データ保持

- 既定で作成から **365 日**経過したフォームを自動削除（`PATCHFORM_RETENTION_DAYS`）。フォームごとに変更可
- データはボリューム `patchform_app_data`（`/data/patchform.db` と `/data/files`）
- バックアップは当該ボリュームまたは DB と添付ディレクトリのコピーで行う

## フォーム定義

定義は JSON 契約 `opengenai-patchform/1` です。カタログに無い部品、または未実装（`enabled: false`）の部品は保存できません。

現在利用できる部品: text, textarea, email, phone, number, select, radio, checkbox, slider, rating, date, time, datetime-local, daterange, file, address_composite, user_info_composite, company_info_composite, financial_institution_composite, calculated, text_display, image_display, divider, page_break, password, mynumber（庁内専用・暗号化）, matrix_question, signature_pad, location, qr_scanner, image_recognition, document_reader

選択肢は「表示文|値」と書けます。回答と手続きの対応は値を使います。表示だけ変えても切れません。

各部品には任意で IMI 語彙（`imi_type`）を付けられます。複合部品はサブ項目ごと（`imi_subfields`）にも付けられます。カタログ追加と AI 生成では、型から一意に決まる語彙を初期値として入れます。同じ語彙の欄には、今このフォームで入力中の値と、同じ申請束の提出済み様式の値を候補として出します。マイナンバーは候補にしません。マイナンバー部品は `internal` 以外の公開範囲では配置できません。画像認識は Vision モデル、文書読取はテキストファイルを自動抽出し、失敗時は手入力できます。

複合部品では次を補います。郵便番号は zipcloud で都道府県・市区町村・町名を補完します。法人番号は検査数字を確認し、`PATCHFORM_GBIZ_TOKEN` があるときだけ gBizINFO から法人名を補完します（未設定・失敗時は手入力）。氏名の性別と生年月日は編集画面で表示するかを選べます。ゆうちょの記号・番号は店番と口座番号（7桁）に換算して保存します。

届いた回答は「申請受付」で手続きを選び、申請を開いて確認します。手続きを選ぶと、その手続きの申請を CSV / JSONL でまとめて書き出せます。1件の画面では、その申請だけを同じ形式で書き出せます。手続きに職員の通知先を書き、庁内の SMTP を設定しているときだけ、案内の提出を職員へ知らせます。本文に回答は入れません。SMTP が無い開発では `PATCHFORM_MAIL_DUMP_DIR` に同じ文面をテキストで書き出します（開発 compose の既定は `/data/mail`）。庁内の他システムへ渡すときは、`PATCHFORM_SERVICE_KEY` を設定したときだけ、ログインなしで手続きと申請の読み取りができます。`since` を付けると、その日時以降に開いた・様式を出した申請だけ返します。ゲスト公開面からは申請の一括取得はできません。ゲスト送信前には確認画面が出ます。出した回答は消さずに取り下げできます。庁内は申請受付から、外部は控え番号（暗証があればそれも）から操作します。取下げの取消は庁内だけです。

回答の途中は「下書きを保存」で戻せます（庁内はログイン中の職員ごと、外部は同じ端末）。同じ人の再提出を止める設定も編集画面にあります。回答者の扱いはフォームごとに選びます。申請は記名必須、任意記名は空なら匿名、匿名は名前も職員IDも一覧に出しません。作成者は、編集できる職員と回答だけ見られる職員をユーザーIDで指定できます。システム管理者（`SystemAdminGroup`）はすべてのフォームを扱えます。

マイナンバーは一覧では末尾4桁以外を隠します。番号そのものを見る・含めて書き出す操作は監査ログに残ります。

`page_break` を置くと、回答画面は進捗付きのページ送りになります。表示条件（`visibleWhen`）は複数の AND と「いずれかの値」に対応し、隠れた必須項目は回答不要です。計算部品は入力中に再計算します。

フォーム定義を直しても、受付中の窓口にはすぐ見えません。手続きをいったん受付終了してから再公開すると、同じ公開 URL の窓口が開きます。これまでの回答は、答えた当時の版のまま残ります。

添付（`file`）と署名画像（`signature_pad`）は `/data/files` に実ファイルを保管します。回答一覧からダウンロードできます。CSV にはファイル名と ID が残ります。許可する形式は PDF・画像・テキスト・Office 文書、既定の上限は 10MB です。

## 手続き（申請束）

1つの巨大フォームで様式を出し分けるのではなく、ナビゲーションフォームの答えが必要な様式を足します。ナビゲーションフォームも様式も、定義は同じ「フォーム」です。手続きで答え→様式を付けたときに、その1枚がナビゲーションになります。対応は手続きマスタに置き、ナビゲーションフォームの `properties` には書きません。

フォームにはタグを付けられます。「ナビゲーション」タグで最初に答えるフォームを見分け、同じ案件の様式には同じタグを付けて整理します。

庁内は3つの画面に分けます。「フォーム」は1枚の定義を作る、「手続き」は窓口の組み合わせを決めて公開する、「申請受付」は公開中の手続きと届いた束を見ます。受付の開始は手続きの公開だけです。申請用紙が1枚だけのときは、手続き作成で「ナビゲーションフォームは使わない」を選び、その申請用紙を指定します。ナビゲーションのタグも、状況を聞く設問も不要です。開発起動では `PATCHFORM_SEED=1`（既定）のとき、この形のサンプル「ご意見・お問い合わせ」を入れます。本番は入れません。

フォームの定義（作成中 / 作成完了）と、受付の窓口（公開中 / 受付終了）は別です。定義は部品のひな型で、回答を持ちません。手続きを公開すると、案内と様式のコピーが窓口になります。作成一覧の絞り込みは「すべて / 作成中 / 作成完了」です。

一覧はチェックボックスで複数選び、まとめて処理できます。フォームは「作成完了にする / 作成に戻す / タグを付ける / タグを外す / ゴミ箱へ移す」、手続きは「受付を終了する / ゴミ箱へ移す」です。タグ操作は作成完了のフォームにも効きます（`POST /forms/{id}/tags`）。

削除は事故を避けるため二段階です。まず「ゴミ箱へ移す」で退避すると一覧から隠れ、状態は `archived` になります（`POST .../status` に `archived`）。ゴミ箱タブから「復元」で作成中／下書きに戻せます。「完全に削除」はゴミ箱の中だけで、確認に「削除」と打ち込んだときだけ実行し、元に戻せません。公開中の手続きはゴミ箱へ移せず、先に受付終了が要ります。手続きや受付で使われているフォーム、申請のある手続きは完全削除できません（ゴミ箱への退避は可能）。

答えで申請用紙を足すときは、庁内の「手続き」でナビゲーションフォームを選び、ラジオ・セレクト・チェックボックスの選択肢ごとに足す様式と持ち物を書きます。手続きマスタは定義 ID を持ちます。最初の用紙の窓口を受付終了すると、新しい束は作られません。既存の束と様式の下書きは残ります。

手続きの作成は手作業が原則です。手引きや庁内マニュアルのファイルは、完成品ではなく候補を出すための支援です。目次と見出し（`#` は1〜6個まで拾うので `####` `#####` の節も章になります）で章立てを切り、様式一覧・提出書類など手続きに効く章だけを順に読みます。まず様式名を拾い、一覧にある様式は全部必要とする仮の選択肢を付けます。様式は「様式ファイル（記入済み）を添付」の枠を1つ持つので、記入フォーム化しなくても添付で提出でき、そのまま公開（受付開始）できます。次に、申請区分・許可区分・法人／個人など提出物が変わる分かれ目を手引きから読み取り、案内フォームの設問と、選択肢ごとの準備物・様式の目安（分岐ルール）を作ります（あくまで目安で、確定は職員が行います）。読み取れた様式・手続きの選択肢（ナビゲーションフォーム）・手続きの案内から、反映するものを選んで未公開の下書きにします（本文の貼り付けはしません）。読める形式は txt / md / pdf / docx / xlsx / pptx / xls です（rag-app と同じ抽出）。古い doc / ppt は取れる範囲だけ読みます。スキャン画像だけの PDF は読めません。例規からは作りません。文書に無い分岐は「【確認】」として手続きの説明に残します。自動公開はしません。

手引きの解析は小さなモデルでも動くよう決定的な整形を主にしますが、設問・分岐の読み取りは推論モデルの精度が効きます。gpt-oss / deepseek 系などの推論モデルは推論にトークンを使い、`max_tokens` が小さいと本文が空・JSON が途中で切れることがあります。アシストの JSON 用途では推論を抑制（`think:false`）し、章解析・分岐抽出には広めのトークン枠を渡し、空応答時は枠を広げて一度だけ再試行します。より大きなモデルを使う場合は `PATCHFORM_MODEL` を切り替えます（Ollama cloud の `〇〇:cloud` も可）。

申請者や回答者に渡すのは最初の用紙の `/public/f/...` です。それを提出すると申請束（案内番号）ができ、`/public/p/{token}` で解説・持ち物と提出物の作業台を見ます。庁内の職員は `/patchform/apply/{手続きID}` を開くと、ログインしたまま最初の様式に記入できます。手続き一覧の「申請用リンクとQRコード」から、庁内・庁外それぞれの URL と QR を出せます。ナビゲーションを省略した手続きでも束はできます。同じ用紙を出し直すと新しい束になります。古い束と、各様式の下書きは残ります。

### 申請束は作業台（枠とアイテム）

申請束は完成した用紙の一覧ではなく、その申請者の提出物の集まりです。案内を出したときは推奨する「枠」を1件ずつ置くだけで、束は閉じません。枠には3つの区分があります。

- **記入必須（`data`）**: オンライン記入のみ。データ化して他システムへ項目を揃えて渡せます（例: 案内の設問）。
- **様式（`yoshiki`）**: 同じ枠を、オンライン記入でも、あらかじめ用意した PDF/Word の添付でも満たせます。
- **添付（`attach`）**: 疎明・証明・写真など。ファイルで満たします。「準備するもの」は添付枠の種になります。

手続きマスタの `mapping.rules[].form_ids` は様式枠（記入・添付どちらでも可）に、`prepare` は添付枠に読み替えます。既存の手続き・既存の束はこの読み替えで開けます（束は `form_ids` からアイテムに戻します）。

`/public/p/{token}`（ゲスト）と庁内の申請詳細は作業台です。申請者・職員は、枠ごとに「オンラインで記入する / 記入済みファイルを添付する」を選び、`many` の枠は「同じ枠をもう1件」で人数分に複製し、手続きカタログから別の様式や任意の添付を足せます。ゲスト API はトークンが鍵です。

```
GET    /public/api/applications/{token}            # 束（items を含む）
GET    /public/api/applications/{token}/catalog    # 足せる枠のカタログ
POST   /public/api/applications/{token}/items      # 複製 / カタログ追加 / 任意添付
POST   /public/api/applications/{token}/items/{item_id}/file   # ファイルで充足
DELETE /public/api/applications/{token}/items/{item_id}/file   # 添付を外す
```

庁内は `POST /patchform/applications/{id}/items`、`.../items/{item_id}/file`（職員の補正）で同じアイテムを操作します。フォーム提出時は `application_item_id` を付けると、その枠（複製した各件）に紐づきます。

### 様式ひな型（ダウンロード配布）

オンライン記入しない様式や添付は、自治体側が Word/PDF/Excel のひな型を配ることが多いです。職員は手続き編集の「様式ひな型」で枠（様式・添付）ごとにひな型を1つ登録します（差し替え可）。申請者は作業台の各枠から「様式ひな型をダウンロード」で受け取り、記入して「記入済みファイルを添付する」で満たします。ひな型の実体は案内フォームのバケットに置き、枠は `slot_id`（`yoshiki:{form_id}` / `attach:{名称}`）で対応づけます。`slot_id` は下書き・公開で変わらないので、複製した枠にも同じひな型が付きます。アイテムとカタログの各枠には `template`（`file_id`・`filename`・`mime`・`size`）が入ります。

```
GET    /patchform/procedures/{id}/templates                      # 枠→ひな型の一覧（職員）
POST   /patchform/procedures/{id}/templates                      # 枠にひな型を登録（職員・slot_id指定）
DELETE /patchform/procedures/{id}/templates/{file_id}            # ひな型を削除（職員）
GET    /patchform/procedures/{id}/templates/{file_id}/download   # 庁内ダウンロード
GET    /public/api/applications/{token}/templates/{file_id}      # 申請者ダウンロード（トークンが鍵）
```

各様式の下書き・提出・取下げは今までどおりフォーム単位です。持ち物の文言が添付台紙のチェックボックスと一致するときは、空欄なら自動で付けます。下書きがある欄は触りません。

公開済みの手続きは読み取り専用 MCP（`procedure-mcp`）でも配れます。ツールは `list_procedures` / `inspect_procedure` / `resolve_bundle` です。下書き・提出本文・申請束トークンは出しません。詳細は [procedure-mcp.md](procedure-mcp.md)。デジタル庁の行政手続等調査 MCP とは別物です。

## 庁外「マイ手続き」（外部ログイン）

庁外の申請者も、メールでログインして自分の手続き（申請束）の一覧・新規作成・提出ができます。庁内 Keycloak には依存しません。公開面（`/public/*`）だけで完結します。

- ログイン: `/public/mine`（未ログインならメール入力画面）→ メールのリンク（`/public/auth/verify?token=...`）を開くと外部セッションが確立します。列挙防止のため、送信要求はメールの有無に関わらず同じ応答を返します。
- 一覧: `/public/mine` に、自分が所有する申請束（`owner_kind=external`・`owner_key=正規化メール`）が並びます。
- 新規作成: `/public/new` で公開中の手続きを選ぶと空のプロジェクトができ、作業台の先頭「記入必須」枠（案内フォーム）に答えると必要書類が確定します（プロジェクト先行方式）。
- 作業台: `/public/p/{token}?from=my` で、記入・添付・枠の追加/複製、提出/取下げを行います。条件（案内）の変更は本人だけ、受付（庁内）はできません。

セッションは HMAC 署名の Bearer トークン（既定 TTL 30日、`PATCHFORM_EXT_SESSION_TTL_DAYS`）。マジックトークンは単回・短命（既定 15分、`PATCHFORM_MAGIC_TTL_MIN`）。署名鍵は `PATCHFORM_EXT_SECRET`（本番は必ず固定。未設定時はサービスキー流用、それも無ければ再起動でセッション失効）。dev で SMTP 未設定のときはリンクを標準出力にログし、`PATCHFORM_MAIL_DUMP_DIR` にも文面を書き出します。

```
POST /public/api/auth/request         # {email} → マジックリンク送信（常に成功応答）
POST /public/api/auth/verify          # {token} → {token(Bearer), email, expires_at}
GET  /public/api/auth/session         # 本人確認（Bearer）
POST /public/api/auth/logout          # セッション失効
GET  /public/api/applications/mine    # 自分の申請束一覧（Bearer）
POST /public/api/applications         # {procedure_id} 新規プロジェクト（Bearer）
POST /public/api/applications/{id}/status  # 提出/取下げ等（Bearer・所有者チェック）
PATCH /public/api/applications/{id}   # タイトル等の更新（Bearer・所有者チェック）
GET  /public/api/procedures           # 公開手続き一覧（Bearer）
POST /public/api/procedures/{id}/resolve   # 必要書類の dry-run（Bearer）
```

既存のトークン URL（`/public/f/...` 単体フォーム、`/public/p/{token}` 束）は温存します。トークンのみで開いた束（owner 空）はログインしても一覧には出ません（新規はログイン後に作成した束が対象）。庁内先行で作った `owner_kind=internal` の束は庁外一覧には出ません（別人格）。

## 安全なファイル受け渡し（庁外→庁内）

庁外の申請者がアップロードした添付は、庁内でローカル実体を直接ストリームしません。AI アプリ成果物と同じ経路で、backend がサーバ間で実体を取得し SeaweedFS へ再ホストして、署名付き URL（開発）/ carrier リンクファイル（LGWAN）で庁内へ渡します。

- 由来の記録: `uploaded_files.origin`（`internal` / `external`）。公開（ゲスト/外部）アップロードは `external`。
- 庁内 DL: `GET /patchform/applications/{id}/items/{item_id}/file` は、`external` 由来かつ SeaweedFS 設定時に JSON（`{rehosted, file_url|object_key, mime_type, delivery}`）を返します。`internal` 由来やストレージ未設定時は従来どおりバイナリをストリームします。
- carrier: `ARTIFACT_DELIVERY_MODE=carrier` のとき `file_url` を空にして `object_key` を返し、庁内フロントは `/exapps/artifact-carrier` でリンクファイルを取得します（`ExAppArtifactDownloads` と同じ作法）。
- 再ホストは backend に集約し、`patchform-app` は無改造。庁内由来の添付は従来どおりです。

## 庁内バッチ（サービス認証）

`PATCHFORM_SERVICE_KEY` を backend と `patchform-app` の両方に同じ値で書いたときだけ、職員ログインなしで読み取れます。書き込み・ゲスト公開面では使えません。

庁内 API（推奨）:

```
GET /patchform/procedures
GET /patchform/procedures/{id}
GET /patchform/procedures/{id}/applications?since=2026-08-01T00:00:00+09:00
GET /patchform/procedures/{id}/export?format=jsonl&since=...
GET /patchform/applications/{id}
GET /patchform/applications/{id}/export?format=jsonl
```

ヘッダは `x-service-key` です。`since` はその日時以降に案内を出した、または様式を出した申請です（その時刻を含みます。id で重複を除いてください）。応答の `as_of` を次の取得の起点にできます。マイナンバーは一覧と同じくマスクされます。

### 書き出しの使い分け

束は申請者ごとに異なるため、行をまたいで項目は一致しません。用途で使い分けます。

- **JSONL（`format=jsonl`）**: 申請単位。アイテムごとの記入回答・ファイル ID・充足方法をそのまま残します。列は揃えません。
- **記入必須だけ揃える（`format=aligned`）**: `kind=data` の提出済みだけを、様式 ID + `imi_type`（無ければラベル）で列を固定して揃えます。複製した枠は同じ列の繰り返し（別行）です。様式ファイルや添付の欄は混ざりません。他システムへ渡す連携用です（`GET /patchform/procedures/{id}/export?format=aligned`）。
- **CSV（`format=csv`）**: ざっと見る表です。列は提出された様式の項目から動的に作ります。連携契約には使いません。

## LLM アシスト（庁内のみ）

OpenAI 互換 API（既定は Ollama）でフォーム定義の作成・修正、手引きからの候補出し、案内文下書きを行います。失敗時は自治体向けテンプレートにフォールバックします。ゲスト公開面には出しません。手引きの候補は `POST /assist/procedure`、選んだ反映は `POST /assist/procedure/apply`（庁内は `/patchform/assist/procedure` と `/patchform/assist/procedure/apply`）です。

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
| `PATCHFORM_SEED` | `1` のとき単一フォーム手続きのサンプルを入れる。開発 compose の既定は `1`、本番は入れない | `1` |
| `PATCHFORM_SMTP_HOST` | 職員通知の SMTP。未設定なら送らない | |
| `PATCHFORM_SMTP_PORT` | SMTP ポート | `587` |
| `PATCHFORM_SMTP_USER` | SMTP 認証ユーザー。空なら認証しない | |
| `PATCHFORM_SMTP_PASSWORD` | SMTP 認証パスワード | |
| `PATCHFORM_SMTP_STARTTLS` | `1` で STARTTLS | `1` |
| `PATCHFORM_SMTP_SSL` | `1` で SMTPS（465 向け） | `0` |
| `PATCHFORM_SMTP_FROM` | 差出人。ホストと両方あるときだけ送る | |
| `PATCHFORM_STAFF_BASE_URL` | 通知メール内の申請受付 URL のホスト | `http://localhost` |
| `PATCHFORM_SERVICE_KEY` | 庁内バッチの読み取り鍵。未設定なら使えない | |
| `PATCHFORM_MAIL_DUMP_DIR` | 職員通知の文面を書き出すディレクトリ。SMTP が無くても確認できる。開発は `/data/mail` | `/data/mail` |
| `PATCHFORM_EXT_SECRET` | 庁外セッションの署名鍵（HMAC）。本番は固定必須。未設定はサービスキー流用→無ければ再起動で失効 | |
| `PATCHFORM_MAGIC_TTL_MIN` | マジックリンクの有効分数（単回・短命） | `15` |
| `PATCHFORM_EXT_SESSION_TTL_DAYS` | 庁外セッションの有効日数 | `30` |
| `ARTIFACT_DELIVERY_MODE` | 添付/成果物の配信（`open`=署名付きURL / `carrier`=リンクファイル）。backend 側 | `open` |
| `PROCEDURE_MCP_PORT` | 手続き MCP のホストポート | `8013` |
| `PROCEDURE_MCP_BIND` | 手続き MCP のバインド（既定は loopback） | `127.0.0.1` |
