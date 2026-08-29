import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { teamApi } from '@/lib/fetcher';
import { clearSession, currentToken } from './guest/guestSession';

// 庁内（teamApi + JWT）と庁外（公開API + 外部セッション Bearer）で同じ画面ロジックを
// 使えるよう、データ取得を薄いアダプタで抽象化する。既定は庁内（teamApi）。

export type PatchformMode = 'internal' | 'guest';

type Params = Record<string, string | number | boolean | undefined>;

type Options = {
  params?: Params;
  headers?: Record<string, string>;
};

export type PatchformApi = {
  mode: PatchformMode;
  get: <T>(path: string, options?: Options) => Promise<{ data: T; status: number }>;
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
  post: (path, body, options) => teamApi.post(path, body, options),
  put: (path, body, options) => teamApi.put(path, body, options),
  patch: (path, body, options) => teamApi.patch(path, body, options),
  delete: (path, body, options) => teamApi.delete(path, body, options),
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
  const request = async <T,>(
    method: string,
    path: string,
    body?: unknown,
    options?: Options,
  ): Promise<{ data: T; status: number }> => {
    const token = currentToken();
    const headers: Record<string, string> = { ...options?.headers };
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json';
    }
    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }
    const res = await fetch(buildUrl(path, options?.params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const text = await res.text();
    let data: unknown = undefined;
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

  return {
    mode: 'guest',
    get: (path, options) => request('GET', path, undefined, options),
    post: (path, body, options) => request('POST', path, body, options),
    put: (path, body, options) => request('PUT', path, body, options),
    patch: (path, body, options) => request('PATCH', path, body, options),
    delete: (path, body, options) => request('DELETE', path, body, options),
  };
};

const PatchformApiContext = createContext<PatchformApi>(internalApi);

export const PatchformApiProvider = ({
  mode,
  children,
}: {
  mode: PatchformMode;
  children: ReactNode;
}) => {
  const api = useMemo<PatchformApi>(
    () => (mode === 'guest' ? createGuestApi() : internalApi),
    [mode],
  );
  return <PatchformApiContext.Provider value={api}>{children}</PatchformApiContext.Provider>;
};

export const usePatchformApi = (): PatchformApi => useContext(PatchformApiContext);
export { GuestApiError };
