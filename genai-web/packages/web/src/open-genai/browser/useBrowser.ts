import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';
import type { BrowserConfig } from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useBrowserConfig = () => {
  const { data, error, isLoading } = useSWR<BrowserConfig>(
    'browser/config',
    async () => {
      try {
        return await teamApiFetcher<BrowserConfig>('browser/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const data = e.data as BrowserConfig | undefined;
          return {
            enabled: false,
            error: data?.error || errorMessage(e, 'ブラウザサービスに接続できません'),
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
    loadError: error ? 'ブラウザの設定取得に失敗しました。時間をおいて再度お試しください。' : null,
    unavailable: data?.enabled === false,
  };
};
