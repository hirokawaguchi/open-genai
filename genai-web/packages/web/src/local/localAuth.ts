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

/** localStorage の JWT を破棄する（認証エラー時に壊れたセッションを残さない） */
export const clearToken = (): void => {
  localStorage.removeItem(TOKEN_KEY);
};

export const isAuthenticated = (): boolean => {
  const token = getToken();
  if (!token) {
    return false;
  }
  const payload = decodeJwt(token);
  if (!payload?.exp) {
    return false;
  }
  return payload.exp * 1000 > Date.now();
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
