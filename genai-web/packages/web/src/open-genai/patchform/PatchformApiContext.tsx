import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { teamApi } from '@/lib/fetcher';
import { clearSession, currentToken } from './guest/guestSession';

// 庁内（teamApi + JWT）と庁外（公開API + 外部セッション Bearer）で同じ画面ロジックを
// 使えるよう、データ取得を薄いアダプタで抽象化する。既定は庁内（teamApi）。

export type PatchformMode = 'internal' | 'guest' | 'anonymous';

type Params = Record<string, string | number | boolean | undefined>;

type Options = {
  params?: Params;
  headers?: Record<string, string>;
};

export type BlobResponse = { blob: Blob; disposition: string | null; status: number };

export type PatchformApi = {
  mode: PatchformMode;
  get: <T>(path: string, options?: Options) => Promise<{ data: T; status: number }>;
  getBlob: (path: string, options?: Options) => Promise<BlobResponse>;
  post: <T>(path: string, body?: unknown, options?: Options) => Promise<{ data: T; status: number }>;
  put: <T>(path: string, body?: unknown, options?: Options) => Promise<{ data: T; status: number }>;
  patch: <T>(
    path: string,
    body?: unknown,
    options?: Options,
  ) => Promise<{ data: T; status: number }>;
  delete: <T>(
    path: string,
    body?: unknown,
    options?: Options,
  ) => Promise<{ data: T; status: number }>;
};

const internalApi: PatchformApi = {
  mode: 'internal',
  get: (path, options) => teamApi.get(path, options),
  getBlob: (path, options) => teamApi.getBlob(path, options),
  post: (path, body, options) => teamApi.post(path, body, options),
  put: (path, body, options) => teamApi.put(path, body, options),
  patch: (path, body, options) => teamApi.patch(path, body, options),
  delete: (path, body, options) => teamApi.delete(path, body, options),
};

// 共有フックは庁内パス（`patchform/...`）で API を叩く。庁外では所有者チェック付き
// Bearer 面（`/public/api/mine/...`）へ読み替える。既に絶対 `/public/api/...` を
// 指すパス（既存の公開フォーム系）はそのまま通す。
const rewriteGuestPath = (path: string): string => {
  const trimmed = path.startsWith('/') ? path.slice(1) : path;
  if (trimmed.startsWith('patchform/')) {
    return `/public/api/mine/${trimmed.slice('patchform/'.length)}`;
  }
  if (trimmed === 'patchform') {
    return '/public/api/mine';
  }
  return path;
};

const buildUrl = (path: string, params?: Params): string => {
  const url = new URL(path, window.location.origin);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined) {
        url.searchParams.set(k, String(v));
      }
    }
  }
  return url.toString();
};

class GuestApiError extends Error {
  readonly status: number;
  readonly data: unknown;
  constructor(status: number, data: unknown, message: string) {
    super(message);
    this.name = 'GuestApiError';
    this.status = status;
    this.data = data;
  }
}

export const createGuestApi = (): PatchformApi => {
  const authHeaders = (extra?: Record<string, string>): Record<string, string> => {
    const token = currentToken();
    const headers: Record<string, string> = { ...extra };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  };

  const request = async <T,>(
    method: string,
    path: string,
    body?: unknown,
    options?: Options,
  ): Promise<{ data: T; status: number }> => {
    const headers = authHeaders(options?.headers);
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(buildUrl(rewriteGuestPath(path), options?.params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data: unknown;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      if (res.status === 401) {
        clearSession();
      }
      const msg =
        (data && typeof data === 'object' && 'error' in data
          ? String((data as { error?: unknown }).error)
          : '') || '通信に失敗しました';
      throw new GuestApiError(res.status, data, msg);
    }
    return { data: data as T, status: res.status };
  };

  const getBlob = async (path: string, options?: Options): Promise<BlobResponse> => {
    const res = await fetch(buildUrl(rewriteGuestPath(path), options?.params), {
      method: 'GET',
      headers: authHeaders(options?.headers),
    });
    if (!res.ok) {
      if (res.status === 401) {
        clearSession();
      }
      let data: unknown;
      try {
        data = JSON.parse(await res.text());
      } catch {
        data = undefined;
      }
      const msg =
        (data && typeof data === 'object' && 'error' in data
          ? String((data as { error?: unknown }).error)
          : '') || 'ダウンロードに失敗しました';
      throw new GuestApiError(res.status, data, msg);
    }
    return {
      blob: await res.blob(),
      disposition: res.headers.get('Content-Disposition'),
      status: res.status,
    };
  };

  return {
    mode: 'guest',
    get: (path, options) => request('GET', path, undefined, options),
    getBlob,
    post: (path, body, options) => request('POST', path, body, options),
    put: (path, body, options) => request('PUT', path, body, options),
    patch: (path, body, options) => request('PATCH', path, body, options),
    delete: (path, body, options) => request('DELETE', path, body, options),
  };
};

const stripLead = (p: string): string => (p.startsWith('/') ? p.slice(1) : p);

// 公開（Bearer 任意）系 API の共通ビルダ。rewrite が渡された庁内パスを公開API
// エンドポイントへ読み替える。null を返すパスは匿名では未提供として、GET は空で
// 短絡し書込は 404 とする。ログイン中（guest セッションあり）なら Bearer を best-effort
// で付ける（claim 等の Bearer 必須エンドポイントを同一アダプタから叩けるように）。
const makePublicApi = (
  mode: PatchformMode,
  rewrite: (path: string) => string | null,
): PatchformApi => {
  const authHeaders = (extra?: Record<string, string>): Record<string, string> => {
    const token = currentToken();
    const headers: Record<string, string> = { ...extra };
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    return headers;
  };

  const request = async <T,>(
    method: string,
    path: string,
    body?: unknown,
    options?: Options,
  ): Promise<{ data: T; status: number }> => {
    const target = rewrite(path);
    if (target === null) {
      if (method === 'GET') {
        return { data: {} as T, status: 200 };
      }
      throw new GuestApiError(404, null, 'この操作は共有リンクでは行えません');
    }
    const headers = authHeaders(options?.headers);
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    const res = await fetch(buildUrl(target, options?.params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data: unknown;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      const msg =
        (data && typeof data === 'object' && 'error' in data
          ? String((data as { error?: unknown }).error)
          : '') || '通信に失敗しました';
      throw new GuestApiError(res.status, data, msg);
    }
    return { data: data as T, status: res.status };
  };

  const get = async <T,>(path: string, options?: Options): Promise<{ data: T; status: number }> => {
    // IMI ソースは匿名では扱わないため空で返す（呼び出し側の劣化を防ぐ）。
    if (path.endsWith('/imi-sources')) {
      return { data: { sources: [] } as T, status: 200 };
    }
    return request<T>('GET', path, undefined, options);
  };

  const getBlob = async (path: string, options?: Options): Promise<BlobResponse> => {
    const target = rewrite(path);
    if (target === null) {
      throw new GuestApiError(404, null, 'ダウンロードできません');
    }
    const res = await fetch(buildUrl(target, options?.params), {
      method: 'GET',
      headers: authHeaders(options?.headers),
    });
    if (!res.ok) {
      let data: unknown;
      try {
        data = JSON.parse(await res.text());
      } catch {
        data = undefined;
      }
      const msg =
        (data && typeof data === 'object' && 'error' in data
          ? String((data as { error?: unknown }).error)
          : '') || 'ダウンロードに失敗しました';
      throw new GuestApiError(res.status, data, msg);
    }
    return {
      blob: await res.blob(),
      disposition: res.headers.get('Content-Disposition'),
      status: res.status,
    };
  };

  return {
    mode,
    get,
    getBlob,
    post: (path, body, options) => request('POST', path, body, options),
    put: (path, body, options) => request('PUT', path, body, options),
    patch: (path, body, options) => request('PATCH', path, body, options),
    delete: (path, body, options) => request('DELETE', path, body, options),
  };
};

// 匿名の共有リンク束（/public/p/{token}）向け。庁内パス `patchform/applications/{id}...`
// を常にルートの token に差し替えて token 系公開API（/public/api/applications/{token}/...）
// へ流す。手続き詳細/カタログも公開エンドポイントへ読み替える。
export const createAnonymousApi = (token: string): PatchformApi =>
  makePublicApi('anonymous', (path) => {
    const trimmed = stripLead(path);
    if (trimmed.startsWith('patchform/applications/')) {
      const rest = trimmed.slice('patchform/applications/'.length);
      const slash = rest.indexOf('/');
      const sub = slash >= 0 ? rest.slice(slash) : '';
      return `/public/api/applications/${encodeURIComponent(token)}${sub}`;
    }
    if (trimmed.startsWith('patchform/procedures/')) {
      const rest = trimmed.slice('patchform/procedures/'.length);
      const slash = rest.indexOf('/');
      if (slash < 0) {
        return `/public/api/procedures/${rest}`;
      }
      if (rest.slice(slash) === '/catalog') {
        return `/public/api/applications/${encodeURIComponent(token)}/catalog`;
      }
      return null;
    }
    if (!trimmed.startsWith('patchform')) {
      return path;
    }
    return null;
  });

// 匿名の記入モーダル向け。庁内の記入系フック（usePatchformDetail/Actions/Runtime）が
// 叩く `patchform/forms/{formId}/...`・`patchform/extract`・`patchform/lookup/*` を、
// item の guest_token に固定した公開フォームAPIへ読み替える。これによりモーダル本体は
// 無改変のまま匿名で動く。
export const createGuestFormApi = (guestToken: string): PatchformApi =>
  makePublicApi('anonymous', (path) => {
    const trimmed = stripLead(path);
    if (trimmed.startsWith('patchform/forms/')) {
      const rest = trimmed.slice('patchform/forms/'.length);
      const slash = rest.indexOf('/');
      const sub = slash >= 0 ? rest.slice(slash) : '';
      return `/public/api/forms/${encodeURIComponent(guestToken)}${sub}`;
    }
    if (trimmed === 'patchform/extract') {
      return '/public/api/extract';
    }
    if (trimmed.startsWith('patchform/lookup/')) {
      return `/public/api/${trimmed.slice('patchform/'.length)}`;
    }
    if (!trimmed.startsWith('patchform')) {
      return path;
    }
    return null;
  });

const PatchformApiContext = createContext<PatchformApi>(internalApi);

export const PatchformApiProvider = ({
  mode,
  token,
  children,
}: {
  mode: PatchformMode;
  token?: string;
  children: ReactNode;
}) => {
  const api = useMemo<PatchformApi>(() => {
    if (mode === 'anonymous') {
      return createAnonymousApi(token ?? '');
    }
    return mode === 'guest' ? createGuestApi() : internalApi;
  }, [mode, token]);
  return <PatchformApiContext.Provider value={api}>{children}</PatchformApiContext.Provider>;
};

// 既存プロバイダ配下で、特定サブツリーだけ別アダプタ（記入モーダルの guest_token 固定
// api 等）に差し替えるためのスコープ。
export const PatchformApiScope = ({
  api,
  children,
}: {
  api: PatchformApi;
  children: ReactNode;
}) => <PatchformApiContext.Provider value={api}>{children}</PatchformApiContext.Provider>;

export const usePatchformApi = (): PatchformApi => useContext(PatchformApiContext);
export { GuestApiError };
