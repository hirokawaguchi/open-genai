// 庁外（外部ユーザー）セッション。マジックリンク検証で得た HMAC 署名 Bearer を
// localStorage に保持する。庁内の Keycloak には依存しない軽量な本人管理。

const TOKEN_KEY = 'patchform-ext:token';
const EMAIL_KEY = 'patchform-ext:email';

export type GuestSession = {
  token: string;
  email: string;
};

export const readSession = (): GuestSession | null => {
  try {
    const token = localStorage.getItem(TOKEN_KEY) || '';
    const email = localStorage.getItem(EMAIL_KEY) || '';
    if (!token) {
      return null;
    }
    return { token, email };
  } catch {
    return null;
  }
};

export const writeSession = (session: GuestSession): void => {
  try {
    localStorage.setItem(TOKEN_KEY, session.token);
    localStorage.setItem(EMAIL_KEY, session.email || '');
  } catch {
    // localStorage 不可（プライベートブラウズ等）でも致命ではない
  }
};

export const clearSession = (): void => {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(EMAIL_KEY);
  } catch {
    // noop
  }
};

export const currentToken = (): string => readSession()?.token || '';
