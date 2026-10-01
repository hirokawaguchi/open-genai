// モデル利用制御 専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `GET/POST /admin/model-policy` の応答に対応する（modelpolicy-app 由来）。

export type ModelPolicy = {
  enabled: boolean;
  default: string[];
  teams: Record<string, string[]>;
  /** 旧グループ別許可（後方互換・表示/保持のみ）。 */
  groups?: Record<string, string[]>;
};

export type PolicyTeam = {
  id: string;
  name: string;
};

/** 棟（テナント）。棟別にモデル利用制御を設定する。 */
export type PolicyTenant = {
  id: string;
  name: string;
};

export type ModelPolicyConfig = {
  /** 現在編集対象の棟。 */
  tenantId: string;
  /** 操作できる棟の一覧（システム管理者は全棟、棟管理者は自分の棟）。 */
  tenants: PolicyTenant[];
  policy: ModelPolicy;
  availableModels: string[];
  teams: PolicyTeam[];
};
