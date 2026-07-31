// 監査ログ専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `GET /admin/audit-logs` の応答（audit_logs テーブル相当）に対応する。

export type AuditLog = {
  id: string;
  ts: number;
  tsIso: string;
  userId: string;
  userEmail: string;
  userName: string;
  groups: string;
  action: string;
  method: string | null;
  path: string | null;
  usecase: string | null;
  chatId: string | null;
  teamId: string | null;
  exAppId: string | null;
  model: string | null;
  inputChars: number | null;
  outputChars: number | null;
  inputText: string | null;
  outputText: string | null;
  status: number | null;
  latencyMs: number | null;
  ip: string | null;
  userAgent: string | null;
  sessionId: string | null;
};

export type AuditQueryResult = {
  total: number;
  items: AuditLog[];
  limit: number;
  offset: number;
};

/** 絞り込み条件（UI 状態）。日付は YYYY-MM-DD（UTC）。 */
export type AuditFilters = {
  userId: string;
  action: string;
  q: string;
  fromDate: string;
  toDate: string;
  limit: number;
};

export const AUDIT_ACTION_OPTIONS: { title: string; value: string }[] = [
  { title: 'すべて', value: 'all' },
  { title: 'チャットメッセージ', value: 'chat.message' },
  { title: '推論ストリーム', value: 'predict.stream' },
  { title: 'AIアプリ実行', value: 'exapp.invoke' },
  { title: 'ログイン', value: 'auth.login' },
  { title: 'APIアクセス', value: 'api.access' },
];
