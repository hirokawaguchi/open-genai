import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';

type WorldmonitorConfig = {
  enabled?: boolean;
  error?: string;
};

const loadConfig = async (): Promise<WorldmonitorConfig> => {
  try {
    return await teamApiFetcher<WorldmonitorConfig>('worldmonitor/config');
  } catch (e) {
    if (e instanceof ApiError && (e.status === 502 || e.status === 503)) {
      const data = e.data as WorldmonitorConfig | undefined;
      return {
        enabled: false,
        error: data?.error || 'ワールドモニターに接続できません',
      };
    }
    throw e;
  }
};

export const useWorldmonitorConfig = () => {
  const { data, error, isLoading } = useSWR<WorldmonitorConfig>(
    'worldmonitor/config',
    loadConfig,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );

  return {
    enabled: data?.enabled === true,
    isLoading,
    error: data?.enabled === false
      ? data.error || null
      : error
        ? 'ワールドモニターの状態を確認できませんでした。'
        : null,
  };
};
