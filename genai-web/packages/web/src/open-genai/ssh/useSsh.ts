import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi, teamApiFetcher } from '@/lib/fetcher';
import type { SshConfig, SshHost, SshHostDraft } from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useSshConfig = () => {
  const { data, error, isLoading } = useSWR<SshConfig>(
    'ssh/config',
    async () => {
      try {
        return await teamApiFetcher<SshConfig>('ssh/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as SshConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, 'SSH サービスに接続できません'),
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
    loadError: error ? 'SSH の設定取得に失敗しました。時間をおいて再度お試しください。' : null,
    unavailable: data?.enabled === false,
  };
};

export const useSshHosts = (enabled: boolean) => {
  const { data, error, isLoading, mutate } = useSWR<{ hosts: SshHost[]; is_admin?: boolean }>(
    enabled ? 'ssh/hosts' : null,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    hosts: data?.hosts ?? [],
    isAdmin: data?.is_admin === true,
    isLoading,
    loadError: error ? errorMessage(error, '接続先一覧の取得に失敗しました。') : null,
    mutate,
  };
};

export const useSshHostActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const create = useCallback(async (input: SshHostDraft): Promise<SshHost | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<{ host: SshHost }>('ssh/hosts', input);
      return res.data.host;
    } catch (e) {
      setError(errorMessage(e, '接続先の登録に失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const update = useCallback(
    async (hostId: string, input: SshHostDraft): Promise<SshHost | null> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await teamApi.put<{ host: SshHost }>(
          `ssh/hosts/${encodeURIComponent(hostId)}`,
          input,
        );
        return res.data.host;
      } catch (e) {
        setError(errorMessage(e, '接続先の更新に失敗しました。'));
        return null;
      } finally {
        setSubmitting(false);
      }
    },
    [],
  );

  const remove = useCallback(async (hostId: string): Promise<boolean> => {
    setSubmitting(true);
    setError(null);
    try {
      await teamApi.delete(`ssh/hosts/${encodeURIComponent(hostId)}`);
      return true;
    } catch (e) {
      setError(errorMessage(e, '接続先の削除に失敗しました。'));
      return false;
    } finally {
      setSubmitting(false);
    }
  }, []);

  return { create, update, remove, submitting, error, setError };
};
