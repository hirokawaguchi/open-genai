import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type {
  ChoseiConfig,
  ChoseiDateInput,
  ChoseiEventDetail,
  ChoseiEventSummary,
  InviteDraftResult,
  ParsedDatesResult,
  RecommendResult,
  ResponseStatus,
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

export const useChoseiConfig = () => {
  const { data, error, isLoading } = useSWR<ChoseiConfig>(
    'chosei/config',
    async () => {
      try {
        return await teamApiFetcher<ChoseiConfig>('chosei/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as ChoseiConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, '日程調整サービスに接続できません'),
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
    loadError: error
      ? '日程調整の設定取得に失敗しました。時間をおいて再度お試しください。'
      : null,
    unavailable: data?.enabled === false || (!!data?.error && data.enabled === false),
  };
};

export const useChoseiEvents = () => {
  const { data, error, isLoading, mutate } = useSWR<{ events: ChoseiEventSummary[] }>(
    'chosei/events',
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    events: data?.events ?? [],
    isLoading,
    loadError: error ? errorMessage(error, 'イベント一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const useChoseiEvent = (eventId: string | undefined) => {
  const key = eventId ? `chosei/events/${encodeURIComponent(eventId)}` : null;
  const { data, error, isLoading, mutate } = useSWR<ChoseiEventDetail>(
    key,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    detail: data ?? null,
    isLoading,
    loadError: error ? errorMessage(error, 'イベントの取得に失敗しました。') : null,
    mutate,
  };
};

export const useChoseiActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(
    async (input: {
      title: string;
      description?: string;
      creator_name?: string;
      event_password?: string;
      dates: ChoseiDateInput[];
    }): Promise<ChoseiEventDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.post<ChoseiEventDetail>('chosei/events', input);
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'イベントの作成に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const update = useCallback(
    async (
      eventId: string,
      input: {
        title: string;
        description?: string;
        creator_name?: string;
        event_password?: string;
        dates?: ChoseiDateInput[];
      },
    ): Promise<ChoseiEventDetail | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.put<ChoseiEventDetail>(
          `chosei/events/${encodeURIComponent(eventId)}`,
          input,
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, 'イベントの更新に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const remove = useCallback(async (eventId: string, eventPassword?: string): Promise<boolean> => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`chosei/events/${encodeURIComponent(eventId)}`, {
        event_password: eventPassword,
      });
      return true;
    } catch (e) {
      setError(errorMessage(e, 'イベントの削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const submitResponse = useCallback(
    async (
      eventId: string,
      input: {
        participant_name: string;
        password?: string;
        responses: { event_date_id: number; status: ResponseStatus }[];
      },
    ): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await teamApi.post(`chosei/events/${encodeURIComponent(eventId)}/responses`, input);
        return true;
      } catch (e) {
        setError(errorMessage(e, '回答の送信に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  return { create, update, remove, submitResponse, submitting, error, setError };
};

const parseFilename = (disposition: string | null): string | null => {
  if (!disposition) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1]);
    } catch {
      return utf8[1];
    }
  }
  const ascii = /filename="?([^";]+)"?/i.exec(disposition);
  return ascii?.[1] ?? null;
};

/** 外部共有 URL のリンクファイルをダウンロード（LGWAN carrier）。 */
export const downloadChoseiCarrier = async (
  eventId: string,
  format: 'txt' | 'html' = 'txt',
): Promise<void> => {
  const { blob, disposition } = await teamApi.getBlob(
    `chosei/events/${encodeURIComponent(eventId)}/carrier`,
    { params: { format } },
  );
  const filename = parseFilename(disposition) ?? `chosei_link.${format}`;
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
};

export const useChoseiAssist = () => {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const parseDates = useCallback(async (text: string): Promise<ParsedDatesResult | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await teamApi.post<ParsedDatesResult>('chosei/assist/parse-dates', { text });
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '日程の解釈に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const recommend = useCallback(async (eventId: string): Promise<RecommendResult | null> => {
    setBusy(true);
    setError(null);
    try {
      const res = await teamApi.post<RecommendResult>(
        `chosei/events/${encodeURIComponent(eventId)}/assist/recommend`,
        {},
      );
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '最適日の提案に失敗しました。'));
      return null;
    } finally {
      setBusy(false);
    }
  }, []);

  const draftInvite = useCallback(
    async (eventId: string, tone = '丁寧'): Promise<InviteDraftResult | null> => {
      setBusy(true);
      setError(null);
      try {
        const res = await teamApi.post<InviteDraftResult>(
          `chosei/events/${encodeURIComponent(eventId)}/assist/invite`,
          { tone },
        );
        return res.data ?? null;
      } catch (e) {
        setError(errorMessage(e, '案内文の作成に失敗しました。'));
        return null;
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return { parseDates, recommend, draftInvite, busy, error, setError };
};
