/**
 * Open GENAI: ローカル SAML 認証のフロント側ヘルパ。
 *
 * クラウド版 源内 は Amazon Cognito (aws-amplify) で認証するが、
 * ローカルでは backend(FastAPI) を SAML SP とし、Keycloak(SAML IdP) で
 * ログインする。backend は検証後にアプリ JWT を発行し、ACS から
 * `#token=<jwt>` 形式でこのフロントへリダイレクトする。
 *
 * - ログインゲート: 未認証なら backend /auth/login へ遷移
 * - API 呼び出し: localStorage の JWT を Authorization: Bearer で送信
 *   （元コードの `getIdToken()` / `getLocalSession()` 互換を維持）
 */

const TOKEN_KEY = 'open-genai-token';
const API_ENDPOINT = import.meta.env.VITE_APP_API_ENDPOINT;

type JwtPayload = {
  sub?: string;
  email?: string;
  name?: string;
  groups?: string[];
  exp?: number;
};

const decodeJwt = (token: string): JwtPayload | null => {
  try {
    const base64Url = token.split('.')[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const json = decodeURIComponent(
      atob(base64)
        .split('')
        .map((c) => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2))
        .join(''),
    );
    return JSON.parse(json) as JwtPayload;
  } catch {
    return null;
  }
};

/** ACS からのリダイレクト直後、URL フラグメントの #token= を取り込む */
export const captureTokenFromUrl = (): void => {
  const hash = window.location.hash;
  const marker = '#token=';
  if (hash.startsWith(marker)) {
    const token = decodeURIComponent(hash.slice(marker.length));
    if (token) {
      localStorage.setItem(TOKEN_KEY, token);
    }
    // トークンを URL から除去
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }
};

export const getToken = (): string | null => localStorage.getItem(TOKEN_KEY);

/** localStorage に JWT を保存する（再発行時に差し替える） */
export const setToken = (token: string): void => {
  localStorage.setItem(TOKEN_KEY, token);
};

/** localStorage の JWT を破棄する（認証エラー時に壊れたセッションを残さない） */
export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY);
};

/** JWT の有効期限（ミリ秒 epoch）。取得できなければ null */
export const getTokenExpMs = (): number | null => {
  const token = getToken();
  if (!token) {
    return null;
  }
  const payload = decodeJwt(token);
  if (!payload?.exp) {
    return null;
  }
  return payload.exp * 1000;
};

export const isAuthenticated = (): boolean => {
  const exp = getTokenExpMs();
  if (exp === null) {
    return false;
  }
  return exp > Date.now();
};

/**
 * アプリ JWT をサイレント再発行する（Keycloak には戻らない）。
 * 成功で新トークンを localStorage に保存して true。失敗（401 等）は false。
 * 期限切れ直後でも backend 側の猶予内なら成功する。
 */
let refreshInFlight: Promise<boolean> | null = null;
export const refreshSession = (): Promise<boolean> => {
  if (refreshInFlight) {
    return refreshInFlight;
  }
  const token = getToken();
  if (!token) {
    return Promise.resolve(false);
  }
  refreshInFlight = (async () => {
    try {
      const res = await fetch(`${API_ENDPOINT}/auth/refresh`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        return false;
      }
      const data = (await res.json()) as { token?: string };
      if (!data?.token) {
        return false;
      }
      setToken(data.token);
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
};

// 残寿命がこの値を切ったら再発行する（既定 1 時間）
const REFRESH_THRESHOLD_MS = 60 * 60 * 1000;
// keep-alive のポーリング間隔（1 分）
const KEEPALIVE_INTERVAL_MS = 60 * 1000;
let keepAliveTimer: ReturnType<typeof setInterval> | null = null;

const maybeRefresh = (): void => {
  const exp = getTokenExpMs();
  if (exp === null) {
    return;
  }
  const remaining = exp - Date.now();
  // 期限切れは keep-alive では扱わない（API の 401 リトライ／ログインゲートに委ねる）
  if (remaining > 0 && remaining < REFRESH_THRESHOLD_MS) {
    void refreshSession();
  }
};

/**
 * 作業中にセッションが切れないよう、期限前に静かに JWT を延長する。
 * - 1 分ごとに残寿命を確認し、残り 1 時間を切ったら再発行
 * - タブが前面へ復帰したときにも確認（スリープ明け対策）
 * - トークンは毎回 localStorage から読むため、他タブでの再発行も自動で共有される
 */
export const startSessionKeepAlive = (): void => {
  if (typeof window === 'undefined' || keepAliveTimer !== null) {
    return;
  }
  maybeRefresh();
  keepAliveTimer = setInterval(maybeRefresh, KEEPALIVE_INTERVAL_MS);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      maybeRefresh();
    }
  });
};

/** backend の SAML ログインへリダイレクト（戻り先は現在のオリジン） */
export const login = (): void => {
  const redirect = window.location.origin;
  window.location.href = `${API_ENDPOINT}/auth/login?redirect=${encodeURIComponent(redirect)}`;
};

export const signOut = (): void => {
  // SLO(Keycloak セッション終了) のため、破棄前のトークンを backend に渡す
  const token = getToken();
  clearToken();
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  window.location.href = `${API_ENDPOINT}/auth/logout${query}`;
};

// ---- 既存コード互換 API ----

export type LocalAuthSession = {
  tokens: {
    idToken: { toString: () => string; payload: Record<string, unknown> };
    accessToken: { toString: () => string; payload: Record<string, unknown> };
  };
  userSub: string;
};

export const getIdToken = async (): Promise<string> => getToken() ?? '';

export const getLocalSession = async (): Promise<LocalAuthSession> => {
  const token = getToken();
  const payload = token ? decodeJwt(token) : null;
  const groups = payload?.groups ?? [];
  return {
    tokens: {
      idToken: {
        toString: () => token ?? '',
        payload: {
          sub: payload?.sub,
          email: payload?.email,
          'cognito:username': payload?.name,
        },
      },
      accessToken: {
        toString: () => token ?? '',
        payload: {
          username: payload?.name,
          'cognito:groups': groups,
        },
      },
    },
    userSub: payload?.sub ?? '',
  };
};
