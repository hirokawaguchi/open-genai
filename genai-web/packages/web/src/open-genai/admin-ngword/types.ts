// 入力制限（禁止ワード・機密情報）専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `GET/POST /admin/ngword` の応答に対応する（ngword-app 由来）。

export type NgWordRules = {
  enabled: boolean;
  case_sensitive: boolean;
  check_mynumber: boolean;
  words: string[];
  patterns: string[];
};

export type NgWordConfig = {
  rules: NgWordRules;
};
