// 入力制限（禁止ワード・機密情報）専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `GET/POST /admin/ngword` の応答に対応する（ngword-app 由来）。

export type NgWordRules = {
  enabled: boolean;
  case_sensitive: boolean;
  check_mynumber: boolean;
  /** チャット等の添付アップロード時に個人情報を警告する */
  warn_attachments: boolean;
  /** ナレッジ登録ジョブ内で個人情報を検知する */
  scan_knowledge_pii: boolean;
  /** 氏名・住所の NER（GiNZA）を使う */
  check_pii_ner: boolean;
  words: string[];
  patterns: string[];
};

/** 棟（テナント）。棟別に入力制限を設定する。 */
export type NgWordTenant = {
  id: string;
  name: string;
};

export type NgWordConfig = {
  /** 現在編集対象の棟。 */
  tenantId: string;
  /** 操作できる棟の一覧（システム管理者は全棟、棟管理者は自分の棟）。 */
  tenants: NgWordTenant[];
  rules: NgWordRules;
};
