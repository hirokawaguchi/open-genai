# Contributing to Open GENAI

貢献ありがとうございます。Issue と Pull Request を歓迎します。

## 位置づけ

本リポジトリはデジタル庁「源内（GENAI）」の **非公式フォーク** です。
デジタル庁による承認・支援はありません。`genai-web/` は上流をローカル動作向けに改変して同梱しています。

## 開発の進め方

1. [README.md](README.md) に従い、ローカルで起動・動作確認する
2. 変更はできるだけ小さな PR に分ける
3. 秘密情報（`.env` 等）をコミットしない
4. リリース前相当の確認: `scripts/pre-release-check.sh`

### 源内（`genai-web/`）への改修

機能追加は原則として Open GENAI レイヤ（`backend/`・各 `*-app/`・`shared/`・compose 等）で行います。
`genai-web/` への変更は、回避不能な最小パッチに留めてください（上流追従のため）。

### 公開しないもの（顧客・個別案件）

個別顧客向けの検討資料・適合性マトリクス・非公開の設計メモは **オフィシャルリポジトリに含めません**。
例: `docs/大分市_*` や gitignore 対象の検討ドキュメントをコミットしないでください。

公開ガイドとして追跡しているのは次のみです。

- `docs/knowledge-api.md`
- `docs/knowledge-mcp.md`
- `docs/dify-knowledge.md`

## セキュリティ報告

脆弱性は [SECURITY.md](SECURITY.md) に従ってください。
原則は GitHub Security Advisories。公開 Issue も可ですが、再現手順・PoC・秘密情報は書かないでください。

## 行動規範

[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) に従ってください。
