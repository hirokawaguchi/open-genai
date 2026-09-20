// 利用者一括管理 専用ページ（管理者限定・OpenGENAI 拡張）の型。
// backend `/admin/users`(/plan,/apply) の応答に対応する（usermgmt-app 由来）。

export type ManagedUser = {
  id: string;
  username: string;
  email: string;
  name: string;
  groups: string[];
  enabled: boolean;
  /** 所属棟（主鍵の棟名）。Keycloak にだけいる人は空。 */
  tenantName?: string;
};

export type UsersResponse = {
  users: ManagedUser[];
  count: number;
  limitReached: boolean;
};

/** CSV 各行のドライラン結果（Keycloak へは未反映）。 */
export type PlanRow = {
  username: string;
  email?: string;
  action: string;
  groups: string[];
  /** CSV に書かれた棟トークン（ID か棟名）。 */
  tenant?: string;
  /** 解決できた棟名。 */
  tenantName?: string;
  /** 棟の解決エラー（未指定・不明・共有棟など）。 */
  tenantError?: string | null;
  error: string | null;
};

export type PlanResponse = {
  rows: PlanRow[];
  count: number;
};

/** 適用（Keycloak 反映）後の各行の結果。 */
export type ApplyResult = {
  username: string;
  email?: string;
  action: string;
  result: string;
  note: string;
  /** 付与できた棟名。 */
  tenantName?: string;
};

export type ApplyResponse = {
  results: ApplyResult[];
  count: number;
};
