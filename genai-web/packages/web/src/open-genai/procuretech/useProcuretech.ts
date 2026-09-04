import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import { getIdToken } from '@/local/localAuth';
import { parseDownloadFilename } from './format';
import type {
  ProcuretechConfig,
  ProcuretechSection,
  ProcuretechSessionDetail,
  ProcuretechSessionSummary,
  ProcuretechTurnResult,
} from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useProcuretechConfig = () => {
  const { data, isLoading } = useSWR<ProcuretechConfig>(
    'procuretech/config',
    async () => {
      try {
        return await teamApiFetcher<ProcuretechConfig>('procuretech/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const d = e.data as ProcuretechConfig | undefined;
          return {
            enabled: false,
            error: d?.error || errorMessage(e, '情報化企画書ナビに接続できません'),
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

export const useProcuretechSessions = () => {
  const { data, error, isLoading, mutate } = useSWR<{
    sessions: ProcuretechSessionSummary[];
  }>('procuretech/sessions', teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    sessions: data?.sessions ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'セッション一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const useProcuretechSession = (sessionId: string | null) => {
  const key = sessionId ? `procuretech/sessions/${encodeURIComponent(sessionId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<ProcuretechSessionDetail>(key, teamApiFetcher, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });
  return {
    detail: data ?? null,
    isLoading,
    loadError: error ? errorMessage(error, 'セッションの取得に失敗しました。') : null,
    mutate,
  };
};

export const useProcuretechActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const createSession = useCallback(
    async (filename: string, content: string): Promise<ProcuretechSessionDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<ProcuretechSessionDetail>('procuretech/sessions', {
          filename,
          content,
        });
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '情報化企画書の読み込みに失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const deleteSession = useCallback(async (sessionId: string): Promise<boolean> => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`procuretech/sessions/${encodeURIComponent(sessionId)}`);
      return true;
    } catch (e) {
      setError(errorMessage(e, 'セッションの削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const sendChat = useCallback(
    async (
      sessionId: string,
      section: string,
      message: string,
    ): Promise<ProcuretechTurnResult | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<ProcuretechTurnResult>(
          `procuretech/sessions/${encodeURIComponent(sessionId)}/chat`,
          { section, message },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'メッセージの送信に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const finalize = useCallback(
    async (sessionId: string, section: string): Promise<ProcuretechTurnResult | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<ProcuretechTurnResult>(
          `procuretech/sessions/${encodeURIComponent(sessionId)}/finalize`,
          { section },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '書き出しに失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const clearSection = useCallback(
    async (sessionId: string, section: string): Promise<ProcuretechSessionDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<ProcuretechSessionDetail>(
          `procuretech/sessions/${encodeURIComponent(sessionId)}/sections/${encodeURIComponent(
            section,
          )}/clear`,
          {},
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '履歴のクリアに失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  return {
    createSession,
    deleteSession,
    sendChat,
    finalize,
    clearSection,
    submitting,
    error,
    setError,
  };
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

type StreamHandlers = {
  onDelta: (text: string) => void;
};

/**
 * チャット応答を NDJSON ストリームで受信する。
 * バックエンドは `{event:"delta"|"done"|"error", ...}` を1行ずつ返す。
 * delta 断片は onDelta へ、完了時は最終的な section を含む結果を返す。
 */
export const streamProcuretechChat = async (
  sessionId: string,
  section: string,
  message: string,
  handlers: StreamHandlers,
): Promise<ProcuretechTurnResult | null> => {
  const token = await getIdToken();
  const res = await fetch(
    buildTeamUrl(`procuretech/sessions/${encodeURIComponent(sessionId)}/chat`),
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ section, message }),
    },
  );

  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => undefined);
    throw new ApiError(res.status, data);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';
  let result: ProcuretechTurnResult | null = null;

  const handleLine = (raw: string) => {
    const line = raw.trim();
    if (!line) return;
    let obj: {
      event?: string;
      text?: string;
      reply?: string;
      section?: ProcuretechSection;
      error?: string;
    };
    try {
      obj = JSON.parse(line);
    } catch {
      return;
    }
    if (obj.event === 'delta') {
      handlers.onDelta(obj.text ?? '');
    } else if (obj.event === 'done' && obj.section) {
      result = { reply: obj.reply ?? '', finalized: false, section: obj.section };
    } else if (obj.event === 'error') {
      throw new ApiError(502, { error: obj.error });
    } else if (!obj.event && obj.section) {
      // 旧形式（非ストリーミングの単発 JSON）フォールバック
      result = { reply: obj.reply ?? '', finalized: false, section: obj.section };
    }
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx = buffer.indexOf('\n');
    while (idx !== -1) {
      handleLine(buffer.slice(0, idx));
      buffer = buffer.slice(idx + 1);
      idx = buffer.indexOf('\n');
    }
  }
  if (buffer.trim()) handleLine(buffer);

  return result;
};

export const downloadProcuretechWorkbook = async (sessionId: string): Promise<void> => {
  const token = await getIdToken();
  const res = await fetch(
    buildTeamUrl(`procuretech/sessions/${encodeURIComponent(sessionId)}/download`),
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    const data = await res.json().catch(() => undefined);
    throw new ApiError(res.status, data);
  }

  const contentType = res.headers.get('Content-Type') || '';
  // SeaweedFS(S3) 経由: 署名付き URL を受け取り、そのリンクから直接ダウンロードする。
  if (contentType.includes('application/json')) {
    const data = (await res.json()) as { url?: string; filename?: string };
    if (!data.url) {
      throw new Error('ダウンロードURLの取得に失敗しました');
    }
    const a = document.createElement('a');
    a.href = data.url;
    a.download = data.filename || 'systemplan.xlsx';
    a.target = '_blank';
    a.rel = 'noopener';
    a.click();
    return;
  }

  // 直接ダウンロード: レスポンス本文（xlsx バイト列）を Blob 化して保存する。
  const blob = await res.blob();
  const filename = parseDownloadFilename(res.headers.get('Content-Disposition'));
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

export const fileToBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('ファイルの読み込みに失敗しました'));
    reader.readAsDataURL(file);
  });
