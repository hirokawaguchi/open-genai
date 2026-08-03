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

export type NgWordConfig = {
  rules: NgWordRules;
};
