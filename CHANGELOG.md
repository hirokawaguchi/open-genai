# Changelog

[Semantic Versioning](https://semver.org/) に従います。実験段階のため **0.x** 系とし、
`1.0.0` は本番運用・experimental 解除時を想定しています。

| タグ | コミット | 位置づけ |
| --- | --- | --- |
| [v0.1.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.1.0) | `fc57e53` | 源内のローカル完結化（第一段階） |
| [v0.2.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.2.0) | `6d594d5` 以降 | 自治体・閉域（LGWAN 等）向け拡張 |
| [v0.2.1](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.2.1) | `be88a0d` 以降 | セキュリティ更新・リリース前品質保証 |
| [v0.3.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.0) | `daac82e` 以降 | 画像生成の源内一本化・アプリピン留め・LGWAN 成果物キャリア配信 |
| [v0.3.1](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.1) | `e047dae` 以降 | 起動手順の修正・CI 修正・添付拡張子判定の修正 |
| [v0.3.2](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.2) | `1a9eb42` 以降 | 出典表示・ローカルDify成果物取得・Enter送信など |
| [v0.4.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.4.0) | `96f3484` | 構造化 RAG・ナレッジ MCP・Dify 連携事例・マイナンバー検査 |
| [v0.5.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.5.0) | `9e4015f` | 本番静的ビルド/デプロイ整備・複数LLM/埋め込み/画像モデルの差し替え・SAML/認証堅牢化 |
| [v0.6.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.6.0) | `340e88e` | 添付・ナレッジの個人情報検知、ナレッジ専用ページ、チャット大容量添付、Dify エラー分類、OSS ガバナンス整備 |
| [v0.7.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.7.0) | `d7ae61e` | 提案実装：書類読取とチェック・日程調整（chosei）・様式 Excel 文書生成（自治体の「あったらいいな」を AI で実現） |
| [v0.8.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.8.0) | `b1943d1` 以降 | 提案実装（第2弾）：オンラインフォーム（patchform）／手続き（申請束）・申請受付／マイ手続き（docmaker）／手続き MCP |

## 設計思想の転換（0.1 → 0.2）

| 観点 | v0.1.0（ローカル源内化） | v0.2.0（自治体・閉域向け） |
| --- | --- | --- |
| 目的 | 源内を OSS／ローカルスタックで再現する | 自治体の実務・ガバナンス要件を満たしつつ、源内 UX を活かす |
| 改修の置き場 | `backend/` と最小限の `genai-web/` パッチ | **OpenGENAI レイヤ**（`backend/` + 各 exApp + `shared/`） |
| 利用者モデル | 源内準拠のチーム管理 | **チーム主体・非階層・複数所属** |
| 管理機能 | Keycloak コンソール等 | 管理者向け **exApp**（監査・利用者一括・モデル制御等） |
| ファイル出力 | backend ローカル保存 / Dify 直リンク | **SeaweedFS（S3 互換）** へ再ホスト |
| 公開面 | 各サービスを個別ポート公開 | **nginx 単一入口**（本番 TLS / 閉域 HTTP 検証） |

---

## [Unreleased]

- 情報化企画書エディタ（procuretech-editor）を追加。案件フォルダ（プロジェクト）内の生成文書（Markdown）をブラウザで編集・保存し、出力ファイルごとに章を並べて Word 文書へ合成できる専用ページ（`/procuretech-editor`）。ファイル本体は SeaweedFS（S3 互換）に保存、メタデータは SQLite で管理。ファイル管理（新規/アップロード/リネーム/複製/削除）、分割プレビュー、スクロール連動に対応。Compose profile `procuretech-editor` でオプション起動（詳細は `docs/procuretech-editor.md`）
  - 画像の埋め込みに対応。ツールバーの画像ボタンからローカル画像を案件フォルダ（`images/`）へアップロードし、相対パスで本文へ埋め込む。保存内容は相対パスのまま保持し、プレビュー時のみ presigned URL に差し替えて表示（書き出し zip にも画像が含まれるため Word 変換側でも解決可能）
  - AI 図生成に対応。ツールバーの図ボタンから、既存「ダイアグラムを生成」と同じ genU 推論（`/predict` + 図タイプ別プロンプト）で Mermaid を生成し、` ```mermaid ` ブロックとして本文へ挿入。プレビューは共通 Markdown で図（SVG）として描画
  - ヒアリングシートからの章別 Markdown 生成に対応。編集画面の「ヒアリングシートから生成」ボタンから、まず生成テーマ（例: 調達仕様書）を選び、テーマが要求する Excel（例: `systemplan.xlsx` / `global.xlsx`）をアップロードすると、テーマに紐づく差し替え可能な外部「文書生成」API で章別 Markdown を生成し、結果 zip をプロジェクトへ取り込む。テーマ↔ヒアリングシート↔API の紐づけは管理者が `EDITOR_GENERATE_THEMES`(JSON) で設定（未設定なら既定の単一テーマ）。生成ロジック（テンプレート＋LLM/Dify）は非公開の別サービスに閉じ込め、結果は zip で受け取るため Nextcloud に依存しない。ローカル検証用にモック生成サービス（Compose profile `procuretech-editor-mock`）を同梱
  - 専用ページのアプリ名を「Markdown エディタ」に変更し、UI 用語を「案件（フォルダ）」→「プロジェクト」に統一（route `/procuretech-editor` は維持）
  - 出力ファイルの合成（Word）に対応。「書き出し・統合」タブで、出力ファイルごとに含める章（Markdown）と順番を指定して `.docx` を合成できる合成エディタを追加。テーマの既定定義（調達仕様書／RFI／見積総括表／一次審査表）を初期表示し、プロジェクト単位で並べ替え・ON/OFF・出力ファイル追加を上書き保存できる。章の参照は生成時に付与する安定 ID（`section_key`、`sections.json` 由来）で行い、ファイル名変更に強い（手動ファイルは `file_id` 参照）。ExApp は定義に従い本文を順に集約し、テーマの合成 API（`{api_url}/compose`、pandoc で Word 化）へ送って `.docx` zip を署名付き URL で返す。エンドポイント `GET/PUT /projects/{id}/composition`・`POST /projects/{id}/compose` を追加
  - Excel 形式の出力（見積総括表・一次審査表）に対応。生成サービス（`procuretech-spec-app`）が `/generate` の中で `materials/templates/*.xlsx` を加工して `quotation.xlsx`／`primaryexam.xlsx` を作り、`sections.json` に `section_key`（`quotation`／`primaryexam`）を付けて取り込む。見積総括表は翌年度・有効フェーズのみで加工（Dify 不要）、一次審査表は section2/4/5/6 を追加 Dify ワークフロー（`criteria_section2/4/5/6`）へ送って要件抽出し加工する。合成エディタでは Excel 出力は「生成済み単一ファイル」として扱い、Word 合成を経由せず最終 zip に同梱する（`.docx` と `.xlsx` を 1 つの zip にまとめて返す）。Excel の生成に失敗しても本文（Markdown）生成は成功扱いとする
  - 「調達仕様書」生成・合成サービス `procuretech-spec-app` を追加（非公開参考実装のドメインを移植し、Nextcloud→zip 返却・Dify キー外出し・`/generate`・`/status`・`/result`・`/compose` を実装。Compose profile `procuretech-spec`）
- 情報化企画書ナビ（procuretech）を追加。情報化企画書（Excel）を読み込み、4分野（背景・業務・現行システム・目標）を AI 対話で整理し、各欄（`B10/B14/B19/B23`）へ書き戻して更新版をダウンロードできる専用ページ（`/procuretech`）。Compose profile `procuretech` でオプション起動（詳細は `docs/procuretech.md`）
- プロンプトテンプレートの「チャットで開く」で入力欄が空になる不具合を修正
- HTTP/LAN 環境（非セキュアオリジン）向けに UUID 生成とクリップボードコピーのフォールバックを共通化
- ナレッジ検索・日程調整の回答生成で Qwen 思考モードをオフ（`RAG_EXTRA_BODY` / `CHOSEI_EXTRA_BODY`。空なら `enable_thinking: false`）
- チャット／RAG／日程調整で `content` が空のとき `reasoning` / `reasoning_content` を本文として読む
- 画像プロンプトと日程候補を JSON Schema で固定（思考文や会話文で画面が壊れる問題）
- 未登録・無効なフロント `modelId` は有効な先頭モデルへフォールバック（選択と送信の不一致を防ぐ）
- チャットのストリーム中断・削除済みチャットの復旧処理を堅牢化
- DGX Spark 向けモデル（Qwen3.5 / 3.6、gpt-oss 20B）の表示名を追加
- サービス名称を `VITE_APP_TITLE` / `APP_TITLE` で差し替え可能に（既定は Open GENAI。ゲスト HTML も同じ）
- Dify チャット型 AI アプリの「過去の会話」一覧に削除ボタンを追加（会話単位。本人の履歴のみ）
- 管理・専用アプリのヘッダーを `ManagedAppHeader` に共通化し、登録済み AI アプリの紹介・使い方を反映
- 固定チーム（共通アプリ / 管理者ツール）の名称変更・削除を禁止し、システム管理者は共通アプリに AI アプリを登録可能に
- AI アプリ実行履歴のシード再投入で、管理者が編集した名称・紹介・使い方を保持
- Keycloak 静的リソース `/kc/resources/` をログイン用 rate limit から除外。管理コンソール許可は `proxy/kc-admin-allow.d/`（サイト固有 CIDR は gitignore）
- Whisper に `WHISPER_DEVICE` を追加（既定は CPU）。画像生成・文字起こしの本体は環境側で差し替え（`SD_API_URL` / `WHISPER_APP_URL`）。サイト overlay（`docker-compose.spark.yml`）は `-f` マージで opt-in（`include` は非対応ファイルや同名サービス上書きで失敗するため不使用）。構築メモは `docs/spark.md`

## [0.8.0] - 2026-08-30

このリリースのテーマは前回に続く **「提案実装」**。今回の主役は、自治体の
**オンライン申請**を現実の運用に寄せて形にした **フォーム（patchform）** 一式です。
「全部を1枚の巨大フォームにしない」「様式は必ずしも電子化せず Word/PDF 添付でもよい」
「申請束は申請者ごとに中身が違う」という実務前提から出発し、
**フォーム作成 → 手続き（申請束）の公開 → 申請受付 → 申請者のマイ手続き**までを
1つの流れとして通しました。いずれも既定では無効（opt-in の Compose `profiles`）で、
既存環境への影響はありません。付随して、Dify チャットの表示改善や依存の脆弱性修正も
取り込んでいます。

> フォーム機能は規模が大きいため、以下に独立した節としてまとめます。仕様の詳細は
> [`docs/patchform.md`](docs/patchform.md) を参照してください。

---

### フォーム（patchform）オプション機能 ― 概要

- `patchform-app`（FastAPI + SQLite）を Compose `profiles: ["patchform"]` でオプション起動。画面上の日本語名は「フォーム」。未起動時は専用ページ `/patchform` が有効化手順を表示し、exApp 一覧からも自動的に隠れる
- 3 つの画面に役割を分離：**「フォーム」**（1 枚の定義を作る）／**「手続き」**（窓口の組み合わせを決めて公開する）／**「申請受付」**（公開中の手続きと届いた申請束を見る）
- profile ベースの任意起動。`patchform` を含めない限り一切動かない。庁内は backend が `/patchform/*` を HMAC 付きでプロキシ（`depends_on` なし・疎結合）
- 外部公開はデュアルイングレス。本体 nginx からゲスト API を晒さず、別ホストで `/public` のみを upstream（[`proxy/patchform.public.conf.example`](proxy/patchform.public.conf.example)）
- データは専用ボリューム `patchform_app_data`。作成から既定 365 日で自動削除（`PATCHFORM_RETENTION_DAYS`、フォーム単位で変更可）

### オンラインフォーム（部品・入力支援）

- JSON 契約 `opengenai-patchform/1`。text / textarea / email / phone / number / select / radio / checkbox / slider / rating / date / time / datetime-local / daterange / file / 各種複合部品（住所・氏名・法人・金融機関）／calculated / text_display / image_display / divider / page_break / password / **mynumber（庁内専用・Fernet 暗号化）** / matrix_question / signature_pad / location / qr_scanner / image_recognition / document_reader などに対応
- 選択肢は「表示名｜値」で表示と値を分離。表示を変えても手続きの対応（値）は切れない
- **IMI 語彙（`imi_type`）** を任意付与。同じ語彙の欄には、入力中の値や同じ申請束の提出済み様式の値を候補表示（マイナンバーは候補にしない）
- 複合部品の補完：郵便番号は zipcloud で住所補完、法人番号は検査数字＋（`PATCHFORM_GBIZ_TOKEN` があれば）gBizINFO で法人名補完、ゆうちょ記号番号を店番・口座番号へ換算
- `page_break` によるページ送り（進捗表示）、表示条件 `visibleWhen`（AND・「いずれかの値」）、計算部品の即時再計算、下書き保存、再提出制御、記名/任意記名/匿名の回答者モード
- 画像認識は Vision モデル、文書読取はテキスト自動抽出（失敗時は手入力）。マイナンバーは一覧で末尾 4 桁以外をマスクし、閲覧・書き出しは監査ログに記録

### 手続き（申請束）と申請受付

- 巨大フォームで出し分けるのではなく、**ナビゲーションフォームの答え → 必要な様式を足す**方式。ナビも様式も定義は同じ「フォーム」で、対応は手続きマスタが持つ
- 様式は「様式ファイル（記入済み）を添付」枠を標準装備。記入フォーム化しなくても添付で提出でき、そのまま公開（受付開始）できる
- 申請用紙が 1 枚だけのときは「ナビゲーションフォームは使わない」を選べる（設問・分岐なしの単票運用）
- フォーム／手続きの一覧に **一括処理**（複数選択して作成完了・作成へ戻す・タグ付け/外し・ゴミ箱へ）と **二段階削除**（ゴミ箱 `archived` → 復元／「削除」入力での完全削除）を追加。公開中・使用中・申請ありは完全削除不可
- **申請受付をテーブル化**：受付処理ステータス（未確認／確認中／受理／差戻し）を申請者側の提出状態とは別レーンで管理。並べ替え・絞り込み（受付/提出状態・期間・キーワード）・一括ステータス変更・一括ダウンロード（CSV/JSONL）・一括削除に対応
- **申請束の双方向共有と変更履歴**：申請者と受付が同じ作業台を見つつ、受付側は条件変更などの編集を不可（読み取り専用）。提出後の追加・削除・修正は履歴として記録
- フォーム定義を直しても受付中の窓口には即時反映しない。**受付終了 → 再公開**で同じ URL の窓口が開き、これまでの回答は当時の版のまま保持

### 申請束は作業台（枠とアイテム）・様式ひな型の配布

- 申請束を「完成様式の一覧」ではなく **提出物の作業台** に再設計。枠に 3 区分：**記入必須（`data`）／様式（`yoshiki`）／添付（`attach`）**。様式枠はオンライン記入でも PDF/Word 添付でも満たせる
- `many` 枠は「同じ枠をもう 1 件」で複製（挿入位置は元の直下）、複製・追加した枠は削除可。カタログから別様式や任意添付を足せる。「枠を足す」はタグ一致の様式を候補提示
- **様式ひな型のダウンロード配布**：職員が枠（様式・添付）ごとにひな型を 1 つ登録し、申請者は各枠から受け取り、記入して添付できる。`slot_id` で下書き・公開・複製をまたいで対応
- 明示的な「提出」操作（自動「提出済」を廃止し「準備完了」ステータスを追加）、控えのテキストダウンロード
- **フォーム/手続きの書き出し・読み込み（可搬化）と複製**：ひな型を base64 で内包し、手続きは構成フォームごと自己完結で持ち運び・複製できる

### マイ手続き（庁内・庁外）＝ docmaker

- 「マイ手続き」を独立アプリ **docmaker** として分離（アプリ名 `docmaker`／表示名「マイ手続き」）。庁内ユーザーは案件（プロジェクト）を所有し、作成ウィザードで条件に答えて必要書類を揃える
- 庁内のあらゆる入口から始めても、そのユーザーの所有プロジェクトとしてマイ手続きに一元管理
- **庁外マイ手続き（外部ログイン）**：庁内 Keycloak に依存せず、`/public/mine` のメールリンク（マジックリンク）で外部セッションを確立。自分の申請束の一覧・新規作成・提出・取下げが可能。庁内と同じ実コンポーネントを再利用し、見た目・操作を統一
- **匿名共有リンク束をマイ手続きと同一化**：`/public/p/{token}` の匿名作業台も庁内と同一 UI。単票のその場送信は従来どおり匿名で完結、束の提出状態管理・履歴・取下げはログイン（claim）後にマイ手続きで
- セッションは HMAC 署名 Bearer（既定 30 日 `PATCHFORM_EXT_SESSION_TTL_DAYS`）、マジックトークンは単回・短命（既定 15 分 `PATCHFORM_MAGIC_TTL_MIN`）。列挙防止のため送信要求は常に同じ応答

### 庁内/庁外の公開範囲を手続き単位に一元化

- 公開範囲（`internal` / `both`）を **手続き単位**の単一の真実として管理（フォーム側の可視性セレクタは撤去）。案内フォームが庁内のみで庁外公開できない、という取り違えを画面で解消
- 公開範囲の変更は公開中の受付にも反映

### 手引きからの候補出し（LLM アシスト・庁内のみ）

- 手引き／庁内マニュアル（txt / md / pdf / docx / xlsx / pptx / xls）を **完成品ではなく候補出し** に利用。目次・見出しで章立てし、様式一覧・提出書類など効く章だけを順に読む
- 様式名を決定的に整形（長音符を壊さない）し、申請区分・許可区分・法人/個人などの分岐を読み取って、案内フォームの設問と選択肢ごとの準備物・様式の目安（分岐ルール）を提示。反映するものを選んで未公開の下書きにする（本文の貼り付け・自動公開はしない）
- 推論モデル向けにトークン枠・`think:false`・空応答時の一度だけの再試行など、小さいモデルでも大きいモデルでも安定させる調整。`PATCHFORM_MODEL` で切り替え（Ollama cloud も可）

### 庁内バッチ・書き出し・手続き MCP・安全なファイル受け渡し

- **庁内バッチ（サービス認証）**：`PATCHFORM_SERVICE_KEY` を両者に設定したときだけ、職員ログインなしで手続き・申請を読み取り。`since` で増分取得（`as_of` を次回起点に）
- **書き出しの使い分け**：JSONL（申請単位）／aligned（記入必須だけ様式 ID＋`imi_type` で列固定・連携用）／CSV（ざっと見る用）
- **手続き MCP（`procedure-mcp`）**：公開済み手続きを読み取り専用で配布（`list_procedures` / `inspect_procedure` / `resolve_bundle`）。下書き・提出本文・束トークンは出さない
- **庁外→庁内の安全なファイル受け渡し**：外部アップロード添付は庁内でローカル実体を直接ストリームせず、AI アプリ成果物と同じ経路で backend が SeaweedFS へ再ホストし、署名付き URL（開発）／carrier リンクファイル（LGWAN）で渡す。由来は `uploaded_files.origin` に記録
- 職員通知（SMTP。本文に回答は入れない。未設定時は `PATCHFORM_MAIL_DUMP_DIR` に文面をダンプ）

### 運用フラグ・セキュリティ

- 開発用フラグ `PATCHFORM_DEV_LOGIN`（SMTP 無しでマジックリンクを直接返す）と `PATCHFORM_SEED`（サンプル投入）は既定でコード上は無効。開発 compose のみ有効化し、本番設定では明示的に無効。**有効時は起動時に警告ログ**を出す
- 期限切れ認証レコードの定期クリーンアップを追加

---

### その他の変更・修正

- fix(exapp): Dify チャットのストリーミング中の自動スクロールを滑らかに（トークン到着ごとの smooth 再起動を rAF で間引き、配信中は即時追従・完了時のみ smooth、上へ読み返し中は追尾停止）
- fix(patchform): `cryptography` を 50.0.1 へ更新し既知脆弱性（pip-audit 検出の 7 件）を解消
- refactor(patchform): 未使用コードの掃除・範囲外の型エラー解消・新規 DB 初期化バグ修正、a11y lint 7 件を解消
- chore(genai-web): pnpm のロック/ワークスペース定義を `.gitignore` に追加（npm を正とする）
- CI: Python 依存監査（pip-audit）と回帰テストを `main` で維持

## [0.7.0] - 2026-08-17

このリリースのテーマは **「提案実装」**。自治体の日常業務で挙がる
「こんなことができたらいいな」「こんな機能があると便利だな」という声を、
既存の AI 部品（OCR・Vision LLM・Dify ワークフロー・LLM アシスト）を
組み合わせて形にした。**書類の読取とチェック**、**日程調整**、
**様式 Excel からの文書生成** が主な追加で、いずれも既定では無効
（opt-in の Compose `profiles` / 設定フラグ）のため、既存環境への影響はない。

### 書類読取とチェック（doccheck）オプション機能

- `doccheck-app`（FastAPI + SQLite）を Compose `profiles: ["doccheck"]` でオプション起動。申請書類を領域分割し、OCR 候補と画像を庁内・外部で分散チェックして補正データ（CSV / JSONL）を作る
- 庁内は専用ページ `/doccheck`（DADS）。外部ゲストは `DOCCHECK_PUBLIC_ENDPOINT` の公開チェック画面のみ（デュアルイングレス）
- OCR はテンプレート単位で `ppocr` / `fallback` / `always` を選択。`always` は PP-OCR（RapidOCR）と Vision（OpenAI 互換）の両候補を並記し、チェッカーが選ぶ。手書き・日付・数値・複数行のヒントに対応
- 領域は単一行の N 分割（重なり付き）と複数行（行ごとに領域を作り出力で結合）に対応。単一行分割は安定した `group_id`、複数行は出力項目名で束ねる
- チェック支援: 補正候補（同一項目の過去確定値・手入力を頻度順）、「空欄（記入なし）」の明示確定（合意・裁定・空文字出力）、「判読不能」。Vision の固定信頼度の数値表示は誤解を避けるため非表示
- 合意判定（多数決／全員一致／単独）・裁定・スコア/トラップ・バッチ連続スキャンに対応。領域数上限は 50（`DOCCHECK_MAX_REGIONS`）
- 詳細は [`docs/doccheck.md`](docs/doccheck.md)

### セキュリティ（LGWAN 公開面の硬化）

- 既定秘密情報のまま起動すると backend が `[SECURITY]` 警告と設定手順を stderr に出力（`security_warn.py`）
- `/api/files` に短命 HMAC（`exp`/`sig`）を必須化。`POST /file/url` で upload/download/delete 用 URL を発行
- nginx（prod/verify）: `/kc/admin` 既定全拒否（`proxy/kc-admin-allow.conf` で CIDR 許可）、ログイン系レート制限、`/api/docs` 等の遮断
- 無認証 `/health` は `status` のみ。モデル一覧は認証付き `GET /health/details`
- `knowledge-mcp` のホスト bind 既定を `127.0.0.1` に変更（同一サーバ Dify 向け）

### 依存更新

- `pypdf` を 6.15.0 へ更新（CVE-2026-71852 / CVE-2026-71870。backend / rag-app / tests）
- `doccheck-app`: `Pillow` 12.3.0 / `pypdf` 6.15.0 / `python-multipart` 0.0.31 へ更新（pip-audit 対応。backend と版を統一）

### dify-app: フォーム／様式 Excel からのファイル生成（後方互換）

- `excel_map`（opt-in）: 様式 `.xlsx` のセル値を Dify 開始変数へ注入。未設定時は従来どおり無変更
- 設定: `excel_var`（既定 `form_xlsx`） / `excel_sheet` / `excel_forward`（既定 false＝様式は Dify に送らない）
- `output_mode=xlsx_fill` + `excel_write_map`（opt-in）: Dify が返した値で様式セルを書き戻し、xlsx を artifacts 化（workflow / chat 共通）。値の受け口は `excel_values`（または回答内 JSON）
- サンプル DSL [`FormFileGenerator.yml`](dify-app/dsl/FormFileGenerator.yml): 開始変数 → Dify 側でプロンプト組み立て → md/html/text/json/docx/pptx。任意の参考資料 `ref_files`（様式 Excel とは別キー）に対応
- 源内 Form Spec 例（入力支援の `desc` 付き）と Excel 用 placeholder / config を `dify-app/dsl/samples/` に追加
- backend: 非画像の `content`(base64) 成果物（xlsx 等）を SeaweedFS へ再ホスト。フロントは content フォールバック DL に対応
- 依存: `dify-app` に `openpyxl` を追加（セル読取・書込）。既存 MultiFileGenerator 等の挙動は維持

### 日程調整（chosei）オプション機能

- `chosei-app`（FastAPI + SQLite）を Compose `profiles: ["chosei"]` でオプション起動
- 庁内は専用ページ `/chosei`（DADS）。外部ゲストは `CHOSEI_PUBLIC_ENDPOINT` の `/public` のみ（デュアルイングレス）
- 暗証番号は bcrypt ハッシュ保存。保持日数は `CHOSEI_RETENTION_DAYS`（既定 90 日）
- LLM アシスト（庁内のみ）: 最適日提案・自然文からの日程候補・案内文下書き（Ollama 等の OpenAI 互換 API）
- 詳細は [`docs/chosei.md`](docs/chosei.md)

## [0.6.0] - 2026-08-06

添付・ナレッジの個人情報検知、ナレッジ管理の専用ページ化、チャット大容量添付のマップリデュース、
Dify エラー分類の改善に加え、公式リポジトリとしてのガバナンス文書（貢献・セキュリティ・行動規範）を整備。

### 添付・ナレッジの個人情報検知（警告／ラベル）

- `shared/pii_scan.py`: 氏名・住所・電話番号・マイナンバーを種別付きで検知（匿名化なし）。電話・マイナンバーは正規表現／検査数字、住所はパターン補助、氏名・住所 NER は任意の GiNZA（`PII_INSTALL_NER=1` ビルド）
- チャット等: `PUT /files` 保存と同時に警告（`warned` / `categories`）。フロントは添付行に種別を表示（送信は可）
- ナレッジ: 登録を非同期化（`ingest_status`）。ジョブ内で索引化のあと PII 検知し、`DocsSection` にラベル表示。`NGWORD_DB_PATH` を rag-app が backend_data 経由で参照
- 入力制限画面: 添付警告・ナレッジ検知・NER のトグルを追加
- README: 動作概要と GiNZA（spaCy）セットアップ（`PII_INSTALL_NER`）を追記。`.env.example` / `.env.prod.example` に変数例を追加

### 通常チャット添付の大容量対応（その場マップリデュース）

- backend: チャット添付を 30,000 文字で黙って打ち切る挙動を廃止し、`shared/docextract.py` に切り捨てなしの `extract_doc_text_full` を追加（安全弁 `MAX_CHAT_DOC_CHARS` 既定 500,000、超過は明示注記で先頭保持）
- backend: `doc_mapreduce.py` を新設し、`chat_once`/`chat_stream` の前段でチャンク化 → 読み計画 → 抜粋 or バッチ要約を実施。しきい値 `CHAT_DOC_INLINE_CHARS`（既定 60,000）以下は全文注入、超過は圧縮して参照し「どう参照したか」を応答冒頭に明示（LLM 呼び出しは注入可能にしてテスト可能化）
- ベクトル RAG 簡易登録など従来経路の `MAX_DOC_CHARS`（30,000）切り捨ては据え置き（影響をチャットに限定）。ナレッジ登録の構造化/ベクトル hybrid とは別物（索引を作らず 1 リクエスト内で圧縮）

### Dify exApp のエラー分類と大容量処理の可視化（PR #29 残リスク緩和）

- dify-app: `classify_provider_error` を HTTP status ベースに拡張。429→レート制限、413/本文の context 超過→入力過大、その他 4xx→入力不備、5xx→接続失敗と分類し、**Dify の 4xx を「接続できません」に誤変換しない**（`_run_workflow`/chat の `default_code` はフォールバックのみ）
- dify-app（MultiFileGenerator DSL）: 270,000 文字超のサイレント切り捨てと、大容量時の区間抽出／代表要約を**黙って欠落させず可視化**。文書準備ノードで `truncated`/`kept_chars`/`coverage_note` を算出し、出力整形で表示用テキスト（`result_text`）にのみ注意文を前置（**ファイル本文 `content` は json/html を壊さないよう clean を維持**）
- 運用注意: 更新した [dify-app/dsl/MultiFileGenerator.yml](dify-app/dsl/MultiFileGenerator.yml) を Dify へ再インポート／公開する必要がある

### ナレッジ管理 専用ページ化

汎用 exApp フォームの制約を解消するため、**タグ管理・ドキュメント登録・ドキュメント管理**を
専用ページ `/knowledge` に統合。先頭のスコープセレクタで「共有ナレッジ（共通）」と
「所属チーム」を切り替えて操作できる（ナレッジ検索は従来の `rag` exApp を維持）。

- rag-app: 構造化 REST を追加（タグ CRUD／登録（ファイル base64・URL）／削除・タグ付け替え／URL 再取得／全消去）。既存 `/invoke` の action と書込ロジックを関数抽出して共用
- backend: `/knowledge/*` 認可付きプロキシと `GET /knowledge/scopes` を追加。共有スコープの書込は管理者のみ、チームスコープはメンバー（`refresh`/`clear` は管理者）
- genai-web: 専用ページ（`open-genai/knowledge/`）・ルート追加・旧管理 exApp（`rag-tags`/`rag-register`/`rag-maintain`）から `/knowledge` へのリダイレクト・ナビ導線
- 旧管理系 exApp の廃止: 共通の `rag-tags`/`rag-register`/`rag-maintain` と各チームの「タグ管理／ドキュメント登録／ドキュメント管理」を **メニュー（AI アプリ一覧）から除去**。起動時に既知ロール（`tags`/`register`/`maintain`/旧 `manage`）のレコードのみ削除し、シード・新規チーム自動登録の対象からも外した（**ナレッジ検索 `rag` は維持**。独自 RAG exApp は削除しない）
- 後方互換: 既存 `/schema` `/invoke`（`rag_role` 分岐）は残置のため、万一の旧ピン留め URL もルートで `/knowledge` へ誘導

### セキュリティ / ドキュメント

- ナレッジ検索 MCP（`knowledge-mcp` `:8002/mcp`）が**無認証**で `scope`(teamId) を任意指定でき、到達できれば全チームのナレッジを読める点を明文化。dev `docker-compose.yml` に公開バインドを制御する `KNOWLEDGE_MCP_BIND`（既定 `0.0.0.0` で従来挙動）を追加し、`.env.example`・README・[docs/knowledge-mcp.md](docs/knowledge-mcp.md) に公開範囲の絞り方（loopback/gateway バインド・FW・認証付きリバプロ）を追記。挙動の既定値は不変で、既存環境への影響はない

### OSS ガバナンス

- ルートに `SECURITY.md`（Advisories 優先・公開 Issue 可だが詳細禁止）、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、Issue/PR テンプレートを追加
- `LICENSE` を純粋な MIT 本文に整理し、同梱源内・非公式フォークの注記を `NOTICE` へ分離
- `genai-web/.github` にあった上流向け SECURITY / CODEOWNERS / Issue・PR テンプレを除去し、親リポ方針との混同を防ぐ注記を追加
- 顧客・個別案件の検討ドキュメントはオフィシャル公開物に含めない方針を `.gitignore` / CONTRIBUTING で明文化

---

## [0.5.0] - 2026-07-30

別環境での実運用で見つかった修正・改善をまとめて反映。**本番デプロイの整備**、
**推論/埋め込み/画像の各モデルを環境に応じて差し替えられる自由度**、**SAML・認証の堅牢化**が主軸。
既定値は従来挙動を維持しており、開発・検証・既存本番への影響はない。

### モデル利用制御・入力制限 専用ページ（管理者限定・管理系の第三弾）

- モデル利用制御を専用ページ（`/admin/model-policy`）へ移行。制御の有効/無効、全ユーザー共通の許可モデル、チーム別の追加許可を、利用可能モデルのチェックボックスで直感的に設定できる（一覧にないモデルIDの追加も可能）
- 入力制限（禁止ワード・機密情報）を専用ページ（`/admin/ngword`）へ移行。有効/無効・大文字小文字の区別・マイナンバー検査のトグル、禁止ワード・正規表現パターンの編集をフォームで行える（正規表現はクライアントでも検証、保存時に確認ダイアログ）
- 設定保存型のため、読み取りは backend が読み取り専用で直接参照し、書き込みのみ単一ライターの `modelpolicy-app`（`POST /policy`）／`ngword-app`（`POST /rules`）へプロキシ（`backend` は `GET/POST /admin/model-policy`・`GET/POST /admin/ngword` で管理者権限を検証）
- 旧 exApp 画面（`/apps/:teamId/modelpolicy`・`/apps/:teamId/ngword`）は各専用ページへリダイレクト。`/schema`・`/invoke` は後方互換で維持

### 利用者一括管理 専用ページ（管理者限定・管理系の第二弾）

- 管理者向けの利用者一括管理を汎用 exApp フォームから専用ページ（`/admin/users`）へ移行。「利用者一覧（検索・件数指定）」と「CSV一括処理（ドライラン → 確認ダイアログ → 適用）」をタブで操作でき、ドライラン結果・適用結果を表で確認できる
- 更新系のため `usermgmt-app` に構造化 REST（`GET /users`、`POST /users/plan`、`POST /users/apply`）を追加。`backend` は `/admin/users`(/plan,/apply) として管理者権限を検証（403）のうえ HMAC 署名付きでプロキシ
- CSV はファイル読み込み／貼り付けの両対応。password 列を含むため取り扱い注意を明記
- 旧 exApp 画面（`/apps/:teamId/usermgmt`）は `/admin/users` へリダイレクト。`/invoke`（Markdown 出力）は後方互換で維持

### 監査ログ専用ページ（管理者限定・管理系の第一弾）

- 管理者向けの監査ログ参照を汎用 exApp フォームから専用ページ（`/admin/audit`）へ移行。ユーザーID・アクション種別・キーワード・期間（JST）・表示件数での絞り込み、テーブル表示（日時は JST 表示）、ページング、行ごとの入力/出力全文表示、JSONL エクスポートを 1 画面で操作できる
- backend の既存 API（`GET /admin/audit-logs`(/export)、`_is_system_admin` で 403 ガード）をそのまま利用。マイクロサービスや backend プロキシの追加は不要
- 入力・出力の全文はプレーンテキスト（`<pre>`）で表示し、React 既定エスケープで XSS を防止
- 旧 exApp 画面（`/apps/:teamId/audit`）は `/admin/audit` へリダイレクト。旧 `audit-app` は無改修で維持

### プロンプトテンプレート専用ページ

- 汎用 exApp フォームの縦並び select をやめ、プロンプトテンプレートを専用ページ（`/prompts`）に。一覧の検索・区分バッジ（標準／共有／個人）、変数入力とライブプレビュー、「チャットで開く」までを 1 画面で操作できる
- `prompt-app` に構造化 REST（`/templates` 一覧・作成・削除、`/templates/{id}/render`）を追加。`backend` は `/prompts/*` として HMAC 署名付きでプロキシ
- チャットへは `navigate('/chat', { state })` で流し込むため、長文でも URL 長制限を受けない
- 旧 exApp 画面（`/apps/:teamId/prompt`）は `/prompts` へリダイレクト。`/schema`・`/resolve`・`/invoke` は後方互換で維持

### 本番配信 / デプロイ

- 本番 web を Vite dev server から**静的ビルド配信（`Dockerfile.prod` + nginx）**に変更し、dev/prod の差異を compose で吸収（#18）
- 閉域・HTTP 検証（`docker-compose.verify.yml` / `proxy/nginx.verify.conf`）を静的ビルドに整合
- 本番デプロイ手順（初回 TLS 展開・変更反映・閉域検証・前段ゲートウェイ時の SAML 注意）を README に整備（#19）

### モデル差し替えの自由度（推論 / 埋め込み / 画像）

- 複数の OpenAI 互換 LLM プロバイダを `modelId` ごとに振り分ける `LLM_PROVIDERS`（Azure/OpenAI/Gemini/Ollama 等。`auth_header`/`api-version` 対応）（#7）
- RAG 埋め込みモデルを env で差し替え可能化（`EMBED_BASE_URL`/`EMBED_MODEL`/`EMBED_DIM`/`QDRANT_COLLECTION`/prefix）。ローカル日本語埋め込み（ruri-v3 等）向けに OpenAI 互換 `embed` サイドカーを `profiles: ["embed"]` でオプトイン追加。既定は現行 mxbai 互換を維持（#21）
- 画像生成に `SD_BACKEND=a1111|fastsd` を追加。CPU-only 環境向けに FastSD CPU（LCM）アダプタを実装（既定は現行 A1111）。初期 step/cfg を `VITE_APP_IMAGE_DEFAULT_STEP`/`_CFG` でビルド時に切替（#22）

### SAML / 認証の堅牢化

- SAML ACS のプロキシヘッダ（`X-Forwarded-Proto`/`Host`/`Port`）対応で TLS 終端配下でも ACS/EntityID を正しく構築。Keycloak の重複属性を許容（#16）
- 認証エラー時に localStorage の壊れた JWT を残さず、`/auth-error` からログインへ戻す導線と 401 の自己回復を追加（#17）

### UI / UX

- ナビ配置を `VITE_APP_NAV_LAYOUT=header|sidebar` で選択可能に（サイドバー: おすすめ / ピン留め / 全AIアプリ）（#20）
- ヘッダーのアカウント表示をログイン中ユーザ名（なければ email）に変更（デスクトップ/モバイル両対応）（#23）
- チャットタイトル生成を `TITLE_MODE=heuristic|llm` で切替可能に（既定は非 LLM のヒューリスティック。拒否文がタイトル化される問題を回避）（#15）

### RAG / AI アプリ / 修正

- 管理者向け利用者一覧表示（#10）
- Dify 連携アプリで `hide_inputs` / `default_inputs` による入力の非表示・既定注入（#13）
- RAG タグ名の Unicode NFC 正規化（表記ゆれ防止）（#14）
- .docx 添付の表（テーブル）テキスト抽出に対応（#9）
- Dify MultiFileGenerator の出力形式に単一 HTML（自己完結・デジタル庁デザインシステム風）を追加。`dify-app` の MIME→拡張子補正に `text/html` を追加

---

## [0.4.0] - 2026-07-25

### 構造化 RAG と検索モード自動選択

- 規程・マニュアル向けのツリー索引（`ingest_tree` / PageIndex 系）と共通 `POST /retrieve` を追加
- `mode=auto` で候補に応じて `full` / `hybrid` / `vector` / `tree` を自動選択
- 簡易・URL 登録でも全文を保持。タグ未付与は検索対象外
- ナレッジ UI を検索／タグ／登録／管理に分割し、タグ中心の運用に整理

### ナレッジ検索 MCP と機械向け API

- `knowledge-mcp`（Streamable HTTP `:8002/mcp`）を追加。`knowledge_list_tags` / `knowledge_list_docs` / `knowledge_search` で `rag-app` をラップ
- `rag-app` に機械向け `GET /knowledge/tags` を追加し、`GET /knowledge/docs` も API キーのみで利用可能に
- `knowledge_search` / `/retrieve` で `source`・`doc_id` による資料内検索を全 mode に通す（`auto` 時は構造化なら tree、なければ vector）
- 出典アコーディオン表示名に節タイトル・ページ範囲を付与（例: `[2] 規程.pdf / 第3章 / p.10-12`）

### Dify 連携（事例 DSL・出典抽出）

- HTTP 固定 WF（根拠付き Q&A）: [`OpenGENAI-KnowledgeAgent.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.yml)
- Agent + MCP chatflow: [`OpenGENAI-KnowledgeAgent.chatflow.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.chatflow.yml)
- 応用例（議事録スタンス）: [`OpenGENAI-MinutesStance.yml`](dify-app/dsl/OpenGENAI-MinutesStance.yml)
- `dify-app` が Agent の `agent_log` / ツール応答から `citation_artifacts` を拾い、回答本文の `[n]` に合わせて出典を絞り込み

### ドキュメント

- 公開ガイド: [`docs/knowledge-api.md`](docs/knowledge-api.md) / [`docs/knowledge-mcp.md`](docs/knowledge-mcp.md) / [`docs/dify-knowledge.md`](docs/dify-knowledge.md)
- README の API／Dify 詳細を上記へ移し、リンク中心に短縮

### 個人番号（マイナンバー）検査

- `shared/mynumber.py` と禁止語ルールの `check_mynumber` を追加（検査数字一致のみブロック）
- 旧設定の `\d{12}` 単純一致はマイナンバー検査へ委譲。UUID（teamId 等）は誤検知しないよう除外

### テスト

- 出典抽出・MCP ヘルパ・マイナンバー・retrieve の `source` 正規化などの回帰テストを追加
- `scripts/run-regression-tests.sh` で venv の pytest を明示し、`conftest` の import パスを修正

---

## [0.3.2] - 2026-07-17

### 出典表示（RAG / Dify）

- RAG 検索ヒットと Dify Knowledge Retrieval の引用を `text/x.open-genai.citation` artifact として返し、源内 UI でアコーディオン表示（`ExAppCitations`）
- ダウンロード一覧からは citation を除外し、ファイル成果物と分離

### ローカル／セルフホスト Dify 向け成果物取得

- SSRF ガードで allowlist ホストの private/loopback 解決を許可（リンクローカルは拒否のまま）
- `ARTIFACT_FETCH_ALLOWED_HOSTS` に `host.docker.internal` 等を載せる手順を README / `.env.example` に明記

### UX

- 入力欄の送信を Enter（Shift+Enter で改行、IME 変換中は除外）に統一
- AI アプリ複製で endpoint / apiKey を編集可能にし、入力フォーム JSON（`uiFormat`）を任意化

### ナレッジ管理

- `rag-manage` を共有チーム（COMMON）へ移設し、旧 ADMIN スコープのチャンク／URL を一度きり移行
- シードアプリの teamId 変更時に履歴・ピン留めを追随

### Added

- 検証用 Dify DSL: `DeepResearch` / `DeepResearch.chatflow` / `MultiFileGenerator`

---

## [0.3.1] - 2026-07-14

### Fixed

- README の使い方に `genai-web/packages/web/.env` 作成手順を追加し、`.env.example` の `VITE_APP_MODEL_IDS` 既定値を README 推奨の `qwen2.5:7b` に合わせる（[#2](https://github.com/hirokawaguchi/open-genai/issues/2) / [#3](https://github.com/hirokawaguchi/open-genai/pull/3)）
- 添付ファイルの拡張子判定を大文字・小文字非依存にする
- CI `python-regression` の失敗と GitHub Actions の Node 20 非推奨警告を解消

---

## [0.3.0] - 2026-07-07

### 画像生成の源内一本化

- `sd-app` を廃止し、画像生成を源内 `/image` + `backend/app/image_gen.py`（A1111 互換）に統合
- 汎用 AI アプリ・画像の実行履歴を usecase 別に保存・復元、詳細設定からの永続化
- 画像生成(SD)サーバのヘルスチェック（`/image/health`）に連動し、停止時は「画像を生成」を一覧・トップから非表示

### AI アプリのピン留め

- 利用者ごとに AI アプリをピン留め（カテゴリ横断・本人のみ・上限 8 件）。トップページに「ピン留め」セクションを表示（`open-genai/app-pins/`）

### 成果物配信（SeaweedFS）と LGWAN 対応

- Dify 成果物の SeaweedFS 再ホストを整理し、保持期限超過分と実行履歴連動での自動削除を追加（`S3_ARTIFACT_RETENTION_DAYS` / `S3_ARTIFACT_PURGE_INTERVAL`）
- **LGWAN 向けキャリア配信**を追加（`ARTIFACT_DELIVERY_MODE=carrier`）。署名付き URL を画面に出さず、URL を記載したリンクファイル（`.txt` / `.html`）を所有者チェック付き `GET /exapps/artifact-carrier` から発行し、データ持ち出し後に別端末で開く運用に対応（`ARTIFACT_CARRIER_FORMAT`）
- 検証用 Dify DSL `dify-app/dsl/File Output Test.yml` と、Dify 連携・キャリア配信・リバースプロキシの手順を README に追記

### Fixed

- `.gitignore` を強化（`.env.prod`、テスト生成物、証明書拡張子）。`genai-web/packages/web/.env` の追跡をやめ `.env.example` を追加
- CI `web-regression` の `npm ci` 失敗を修正（`genai-web/package-lock.json` を同期、Node 22.22.2 に合わせる）

### 移行上の注意（0.2 → 0.3）

- `sd-app` を利用していた場合はサービスを削除（compose から除外済み。画像生成は源内 `/image` に統合）
- 閉域（LGWAN 等）では `ARTIFACT_DELIVERY_MODE=carrier` を推奨（本番 compose 既定は `carrier`、開発は `open`）

---

## [0.2.1] - 2026-07-04

### Security

- Python 依存（fastapi / starlette / PyJWT / pypdf / python-multipart / requests）を既知脆弱性修正版へ更新
- リリース前チェック用 `scripts/audit-python-deps.sh` と GitHub Actions ワークフロー `python-deps-audit` を追加

### Testing

- Open GENAI レイヤのリグレッションテスト（pytest 27件 + genai-web Open GENAI 向け Vitest）を追加
- リリース前一括実行用 `scripts/pre-release-check.sh` と CI ワークフロー `regression-tests` を追加

---

## [0.2.0] - 2026-07-04

### 自治体・閉域運用を想定した機能追加

- **監査ログ**（`backend/app/audit.py`, `audit-app/`）— 3 年以上保持、利用者削除と非連動
- **チャット履歴の利用者分離**（`chats.userId`）
- **利用者一括管理**（`usermgmt-app/`）— CSV + Keycloak Admin API
- **モデル利用制御**（`modelpolicy-app/`）
- **入力制限**（`ngword-app/`）— 禁止語・PII 正規表現
- **プロンプトテンプレート**（`prompt-app/`）
- **契約終了時のデータ完全削除**（`scripts/purge-and-report.sh`）

### チーム主体・複数所属への拡張

- 1 人複数チーム所属、保存プロンプトのチーム共有（`sharedTags`）
- RAG を「ナレッジ検索」「ナレッジ管理」に分割、**タグ + URL** モデル

### 源内 UI 制約の opt-in 拡張

- OpenGENAI exApp Form Spec v1（`visibleWhen` / `reactive` / `preview`）
- 各画面の折りたたみヘルプ、ダイアグラム Mermaid 抽出の堅牢化

### 生成ファイルのオブジェクトストレージ

- SeaweedFS + `backend/app/objstore.py`、Dify 成果物の再ホスト

### インフラ・セキュリティ

- nginx リバースプロキシ単一入口（`docker-compose.prod.yml`, `docker-compose.verify.yml`）
- 内部 HMAC 署名（`intauth.py`）、SSRF 対策（`shared/ssrfguard.py`）

### Fixed

- SeaweedFS healthcheck、backend の `depends_on: service_healthy`
- `/exapps/history` の IDOR 修正、履歴削除を本人のみに限定
- 管理者ツールチームのアプリを非システム管理者の一覧から除外

### 移行上の注意（0.1 → 0.2）

- アクセス URL が `http://localhost:5173` / `:8000` から **`http://localhost/`（proxy 経由）** に変更
- **`INTERNAL_SIGNING_SECRET`** を backend と全 exApp で同一値に設定（本番必須）
- RAG のフォルダ階層モデル（中間版）は **タグ + URL モデル** に置き換え

---

## [0.1.0] - 2026-06-27

源内（genai-web）を **クラウド依存から切り離し、ローカル LLM で完結**させる第一段階のリリース。

### Added

- **`backend/`** — FastAPI 代替 API（チャット履歴・推論ストリーム・Team API）、SAML SP + JWT
- **`genai-web/`** — デジタル庁源内 Web のローカル化パッチ（Cognito/Amplify 撤去、ローカル JWT）
- **`rag-app/`** — Qdrant + Ollama 埋め込みによる RAG AI アプリ
- **`whisper-app/`**, **`sd-app/`** — 文字起こし・画像生成 AI アプリ
- **`dify-app/`** — 外部 Dify ワークフロー／チャットフロー連携（`21f9436`）
- **`shared/docextract.py`** — PDF/Word/Excel テキスト抽出
- **Keycloak** — SAML IdP、realm `open-genai` 初期 import
- **`docker-compose.yml`** — web / backend / 各 AI アプリ / qdrant / keycloak を一括起動
- チーム・AI アプリ管理（SQLite）、共通チーム RAG、チーム単位ナレッジ分離

### 構成（v0.1.0 時点）

- 各サービスを **個別ポート公開**（web `:5173`, backend `:8000`, Keycloak `:8088` 等）
- ファイル添付は backend ローカル保存
- Dify ファイル出力は第三者 URL をそのまま提示

---

[Unreleased]: https://github.com/hirokawaguchi/open-genai/compare/v0.7.0...HEAD
[0.7.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hirokawaguchi/open-genai/releases/tag/v0.1.0
