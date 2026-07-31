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

export type ModelPolicyConfig = {
  policy: ModelPolicy;
  availableModels: string[];
  teams: PolicyTeam[];
};
