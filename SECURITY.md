# Security Policy

Open GENAI は有志による非公式フォークです。デジタル庁のセキュリティ窓口とは別です。

## サポート対象

原則として **最新のリリースタグ**（例: `v0.6.0`）を対象とします。古いタグへの個別バックポートは保証しません。

## 報告方法（ハイブリッド）

### 1. 優先: GitHub Security Advisories（非公開）

詳細・再現手順・PoC を含む報告は、次から **Private vulnerability report** を送ってください。

https://github.com/hirokawaguchi/open-genai/security/advisories/new

### 2. 次善: 公開 Issue も可

Advisories が使えない場合は [Issue](https://github.com/hirokawaguchi/open-genai/issues/new/choose) でも構いません。
その場合は次を守ってください。

- **書いてよいもの**: 影響の概要、対象コンポーネント名、深刻度の見込み（High/Medium 等）
- **書いてはいけないもの**: 再現手順の詳細、PoC、認証情報、ログ全文、設定値、個人情報

詳細は Advisories へ移すか、メンテナから案内する非公開経路で共有してください。
Issue に詳細が載ってしまった場合、メンテナはロック・編集依頼・Advisories への移行を行うことがあります。

## 対応について

報告を確認でき次第、対応の方針や回避策の有無を連絡します。
修正前に影響の大きい情報を公開チャネルで拡散しないようご協力ください。
