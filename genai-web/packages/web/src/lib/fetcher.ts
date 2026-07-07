import { getIdToken } from '@/local/localAuth';

export class ApiError extends Error {
  readonly status: number;
  readonly data: unknown;

  constructor(status: number, data: unknown) {
    super(`Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export const isApiError = (error: unknown): error is ApiError => error instanceof ApiError;

interface ApiResponse<T> {
  data: T;
  status: number;
}

interface RequestOptions {
  params?: Record<string, string | number | boolean | undefined>;
  headers?: Record<string, string>;
}

const buildUrl = (base: string, path: string, params?: RequestOptions['params']): string => {
  const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const combined = `${normalizedBase}${normalizedPath}`;
  // 相対パス（例: /api）は reverse proxy 同一オリジン向け。絶対 URL のみ new URL(単一引数) 可。
  const url = /^https?:\/\//.test(normalizedBase)
    ? new URL(combined)
    : new URL(combined, window.location.origin);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  return url.toString();
};

const parseResponseBody = async <T>(res: Response): Promise<T> => {
  const text = await res.text();
  if (!text) return undefined as T;
  try {
    return JSON.parse(text) as T;
  } catch {
    return text as T;
  }
};

const getAuthHeaders = async (hasBody: boolean): Promise<Record<string, string>> => {
  const token = await getIdToken();
  const headers: Record<string, string> = {};
  if (hasBody) {
    headers['Content-Type'] = 'application/json';
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
};

const createApiClient = (baseURL: string) => {
  const request = async <T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions,
  ): Promise<ApiResponse<T>> => {
    const url = buildUrl(baseURL, path, options?.params);
    const authHeaders = await getAuthHeaders(body !== undefined);

    const res = await fetch(url, {
      method,
      headers: { ...authHeaders, ...options?.headers },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      const errorData = await parseResponseBody<unknown>(res);
      throw new ApiError(res.status, errorData);
    }

    const data = await parseResponseBody<T>(res);
    return { data, status: res.status };
  };

  const getBlob = async (
    path: string,
    options?: RequestOptions,
  ): Promise<{ blob: Blob; disposition: string | null; status: number }> => {
    const url = buildUrl(baseURL, path, options?.params);
    const authHeaders = await getAuthHeaders(false);

    const res = await fetch(url, {
      method: 'GET',
      headers: { ...authHeaders, ...options?.headers },
    });

    if (!res.ok) {
      const errorData = await parseResponseBody<unknown>(res);
      throw new ApiError(res.status, errorData);
    }

    return {
      blob: await res.blob(),
      disposition: res.headers.get('Content-Disposition'),
      status: res.status,
    };
  };

  return {
    get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, undefined, options),
    getBlob,
    post: <T>(path: string, body?: unknown, options?: RequestOptions) =>
      request<T>('POST', path, body, options),
    put: <T>(path: string, body?: unknown, options?: RequestOptions) =>
      request<T>('PUT', path, body, options),
    delete: <T>(path: string, options?: RequestOptions) =>
      request<T>('DELETE', path, undefined, options),
  };
};

export const teamApi = createApiClient(import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT);

export const genUApi = createApiClient(import.meta.env.VITE_APP_API_ENDPOINT);

export const teamApiFetcher = <T>(url: string): Promise<T> =>
  teamApi.get<T>(url).then((res) => res.data);

export const genUApiFetcher = <T>(url: string): Promise<T> =>
  genUApi.get<T>(url).then((res) => res.data);

export const uploadToSignedUrl = async (
  url: string,
  data: File | Blob,
  contentType: string,
): Promise<Response> => {
  const res = await fetch(url, {
    method: 'PUT',
    headers: { 'Content-Type': contentType },
    body: data,
  });
  if (!res.ok) {
    throw new ApiError(res.status, undefined);
  }
  return res;
};
