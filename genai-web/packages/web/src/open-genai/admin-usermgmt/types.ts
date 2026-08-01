// 利用者一括管理 専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `/admin/users`(/plan,/apply) の応答に対応する（usermgmt-app 由来）。

export type ManagedUser = {
  id: string;
  username: string;
  email: string;
  name: string;
  groups: string[];
  enabled: boolean;
};

export type UsersResponse = {
  users: ManagedUser[];
  count: number;
  limitReached: boolean;
};

/** CSV 各行のドライラン結果（Keycloak へは未反映）。 */
export type PlanRow = {
  username: string;
  action: string;
  groups: string[];
  error: string | null;
};

export type PlanResponse = {
  rows: PlanRow[];
  count: number;
};

/** 適用（Keycloak 反映）後の各行の結果。 */
export type ApplyResult = {
  username: string;
  action: string;
  result: string;
  note: string;
};

export type ApplyResponse = {
  results: ApplyResult[];
  count: number;
};
