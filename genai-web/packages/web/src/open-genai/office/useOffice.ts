import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';

type OfficeConfig = {
  enabled?: boolean;
  error?: string;
  delivery?: 'open' | 'carrier';
};

const loadConfig = async (): Promise<OfficeConfig> => {
  try {
    return await teamApiFetcher<OfficeConfig>('office/config');
  } catch (e) {
    if (e instanceof ApiError && (e.status === 502 || e.status === 503)) {
      const data = e.data as OfficeConfig | undefined;
      return {
        enabled: false,
        error: data?.error || 'オフィスに接続できません',
      };
    }
    throw e;
  }
};

export const useOfficeConfig = () => {
  const { data, error, isLoading } = useSWR<OfficeConfig>('office/config', loadConfig, {
    revalidateOnFocus: false,
    shouldRetryOnError: false,
  });

  return {
    enabled: data?.enabled === true,
    delivery: data?.delivery === 'carrier' ? 'carrier' : 'open',
    isLoading,
    error: data?.enabled === false
      ? data.error || null
      : error
        ? 'オフィスの状態を確認できませんでした。'
        : null,
  };
};
