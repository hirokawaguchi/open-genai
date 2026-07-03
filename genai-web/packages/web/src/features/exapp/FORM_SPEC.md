# OpenGENAI exApp Form Spec v1

源内(genai-web)の汎用 exApp 入力フォーム規格（`GovAIFormUIJson`）を、**後方互換を保った加算的・opt-in 拡張**として拡張したもの。新キーを使わないスキーマは従来どおり完全に同じ挙動になる（既存 exApp は無改修で不変）。

上流の源内本家とのマージ容易性のため、拡張は `$` 名前空間・版数で分離する。

## 追加要素

### 予約キー（フォームには描画しない）
- `$version: "opengenai-form/1"` … 拡張スキーマである目印。`$` で始まるキーは描画対象外。

### フィールド共通の任意プロパティ
- `visibleWhen` … 条件表示。指定時、条件を満たす場合のみ表示（未指定＝常に表示＝従来動作）。
  - 単一: `{ "field": "operation", "in": ["use", "delete"] }`
  - 複数(AND): `[{ "field": "operation", "in": ["create"] }, { "field": "share", "in": ["group"] }]`
- `reactive: true` … このフィールドの値が変わったら `/resolve` を呼び、フォーム定義を再取得・差し替える。

### 新フィールド型
- `type: "preview"` … 読み取り専用のプレビュー。`template` 中の `{{キー}}` を他フィールドの現在値で置換して表示する。
  - 例: `{ "type": "preview", "title": "プレビュー", "template": "こんにちは {{名前}} さん" }`

## リアクティブ解決（/resolve 契約）
初期スキーマは従来どおり `/schema`（または静的 placeholder）で取得する。`reactive` フィールドが変わると、フロントは現在の入力値を送って**再計算されたスキーマ全体**を受け取り差し替える（入力値は保持）。

- フロント: `POST /exapps/resolve` `{ teamId, exAppId, inputs }` → `{ placeholder: GovAIFormUIJson }`
- backend: `/exapps/schema` と同型のプロキシ。endpoint の `/invoke` を `/resolve` に置換し、署名ヘッダ付きで exApp へ転送。
- exApp: `POST /resolve`（inputs 受領）→ 再計算した `{ placeholder }` を返す。

## 実装箇所
- 型: `src/features/exapp/types.ts`
- 評価/置換ユーティリティ: `src/features/exapp/utils/formSpec.ts`
- 描画: `src/features/exapp/components/ExAppFormComponentBuilder.tsx`, `components/form/ExAppPreview.tsx`
- ランタイム: `src/features/exapp/components/ExAppForm.tsx`（`liveUiJson` 状態化・reactive 監視）
- 解決フック: `src/features/exapp/hooks/useResolveExAppSchema.ts`
- backend プロキシ: `backend/app/main.py` `/exapps/resolve`
- 最初の採用例: `prompt-app`（`/schema`・`/resolve`）

## 後方互換の要点
- `$`始まりキーはスキップ。`visibleWhen` 未指定は常時表示。`preview`/`reactive`/`$version` を含まないスキーマは `/resolve` を一切呼ばない。
- `shouldUnregister: true` により、条件表示で隠れたフィールドは送信・バリデーション対象から外れる（静的フォームでは何も unmount しないため影響なし）。
