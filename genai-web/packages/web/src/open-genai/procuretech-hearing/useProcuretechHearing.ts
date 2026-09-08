import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';
import { parseDownloadFilename } from '@/open-genai/procuretech/format';
import type {
  HearingConfig,
  HearingSessionDetail,
  HearingSessionSummary,
} from './types';

const BASE = 'procuretech-hearing';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

const buildTeamUrl = (path: string): string => {
  const base = import.meta.env.VITE_APP_TEAM_ACCESS_CONTROL_API_ENDPOINT as string;
  const normalizedBase = base.endsWith('/') ? base.slice(0, -1) : base;
  const normalizedPath = path.startsWith('/') ? path : `/${path}`;
  const combined = `${normalizedBase}${normalizedPath}`;
  const url = /^https?:\/\//.test(normalizedBase)
    ? new URL(combined)
    : new URL(combined, window.location.origin);
  return url.toString();
};

const triggerBlobDownload = async (res: Response, fallback: string): Promise<void> => {
  const blob = await res.blob();
  const filename = parseDownloadFilename(res.headers.get('Content-Disposition'), fallback);
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

export const useHearingConfig = () => {
  const { data, isLoading } = useSWR<HearingConfig>(
    `${BASE}/config`,
    async () => {
      try {
        return await teamApiFetcher<HearingConfig>(`${BASE}/config`);
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const d = e.data as HearingConfig | undefined;
          return {
            enabled: false,
            error: d?.error || errorMessage(e, 'ヒアリングシートに接続できません'),
          };
        }
        throw e;
      }
    },
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    config: data,
    isLoading,
    unavailable: data?.enabled === false,
  };
};

export const useHearingSessions = () => {
  const { data, error, isLoading, mutate } = useSWR<{
    sessions: HearingSessionSummary[];
  }>(`${BASE}/sessions`, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    sessions: data?.sessions ?? [],
    isLoading,
    loadError: error ? errorMessage(error, '作業一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const useHearingSession = (sessionId: string | null) => {
  const key = sessionId ? `${BASE}/sessions/${encodeURIComponent(sessionId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<HearingSessionDetail>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    detail: data ?? null,
    isLoading,
    loadError: error ? errorMessage(error, '作業の取得に失敗しました。') : null,
    mutate,
  };
};

export const useHearingActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [generatingId, setGeneratingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const createSession = useCallback(async (title?: string): Promise<HearingSessionDetail | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<HearingSessionDetail>(`${BASE}/sessions`, { title: title ?? '' });
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '作業の作成に失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const updateSession = useCallback(
    async (
      sessionId: string,
      body: { title?: string; instruction?: string },
    ): Promise<HearingSessionDetail | null> => {
      setError(null);
      try {
        const res = await teamApi.put<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}`,
          body,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '作業の更新に失敗しました。'));
        return null;
      }
    },
    [],
  );

  const deleteSession = useCallback(async (sessionId: string): Promise<boolean> => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`${BASE}/sessions/${encodeURIComponent(sessionId)}`);
      return true;
    } catch (e) {
      setError(errorMessage(e, '作業の削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const addItem = useCallback(async (sessionId: string): Promise<HearingSessionDetail | null> => {
    setError(null);
    try {
      const res = await teamApi.post<HearingSessionDetail>(
        `${BASE}/sessions/${encodeURIComponent(sessionId)}/items`,
        {},
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '項目の追加に失敗しました。'));
      return null;
    }
  }, []);

  const updateItem = useCallback(
    async (
      sessionId: string,
      itemId: string,
      body: { label?: string; value?: string },
    ): Promise<HearingSessionDetail | null> => {
      setError(null);
      try {
        const res = await teamApi.patch<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}`,
          body,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '項目の更新に失敗しました。'));
        return null;
      }
    },
    [],
  );

  const deleteItem = useCallback(
    async (sessionId: string, itemId: string): Promise<HearingSessionDetail | null> => {
      setError(null);
      try {
        const res = await teamApi.delete<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '項目の削除に失敗しました。'));
        return null;
      }
    },
    [],
  );

  const addFile = useCallback(
    async (
      sessionId: string,
      filename: string,
      content: string,
    ): Promise<HearingSessionDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}/files`,
          { filename, content },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '参考ファイルの追加に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const deleteFile = useCallback(
    async (sessionId: string, fileId: string): Promise<HearingSessionDetail | null> => {
      setError(null);
      try {
        const res = await teamApi.delete<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}/files/${encodeURIComponent(fileId)}`,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '参考ファイルの削除に失敗しました。'));
        return null;
      }
    },
    [],
  );

  const generateItem = useCallback(
    async (sessionId: string, itemId: string): Promise<HearingSessionDetail | null> => {
      setGeneratingId(itemId);
      setError(null);
      try {
        const res = await teamApi.post<HearingSessionDetail>(
          `${BASE}/sessions/${encodeURIComponent(sessionId)}/items/${encodeURIComponent(itemId)}/generate`,
          {},
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '生成に失敗しました。'));
        return null;
      } finally {
        setGeneratingId(null);
      }
    },
    [],
  );

  return {
    createSession,
    updateSession,
    deleteSession,
    addItem,
    updateItem,
    deleteItem,
    addFile,
    deleteFile,
    generateItem,
    submitting,
    generatingId,
    error,
    setError,
  };
};

export const downloadHearingTemplate = async (): Promise<void> => {
  const token = await getIdToken();
  const res = await fetch(buildTeamUrl(`${BASE}/template`), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const data = await res.json().catch(() => undefined);
    throw new ApiError(res.status, data);
  }
  await triggerBlobDownload(res, 'hearing-sheet.xlsx');
};

export const downloadHearingWorkbook = async (sessionId: string): Promise<void> => {
  const token = await getIdToken();
  const res = await fetch(
    buildTeamUrl(`${BASE}/sessions/${encodeURIComponent(sessionId)}/download`),
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => undefined);
    throw new ApiError(res.status, data);
  }
  await triggerBlobDownload(res, 'hearing-sheet.xlsx');
};

export const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const raw = String(reader.result || '');
      const comma = raw.indexOf(',');
      resolve(comma >= 0 ? raw.slice(comma + 1) : raw);
    };
    reader.onerror = () => reject(new Error('ファイルの読み込みに失敗しました'));
    reader.readAsDataURL(file);
  });
