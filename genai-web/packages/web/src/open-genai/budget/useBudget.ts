import useSWR from 'swr';
import { ApiError, teamApiFetcher } from '@/lib/fetcher';
import type { BudgetConfig, BudgetData } from './types';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

export const useBudgetConfig = () => {
  const { data, error, isLoading } = useSWR<BudgetConfig>(
    'budget/config',
    async () => {
      try {
        return await teamApiFetcher<BudgetConfig>('budget/config');
      } catch (e) {
        if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
          const body = e.data as BudgetConfig | undefined;
          return {
            enabled: false,
            error: body?.error || errorMessage(e, '自治体予算サービスに接続できません'),
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
    unavailable: Boolean(error) || data?.enabled === false,
  };
};

export const useBudgetData = (enabled: boolean) => {
  const { data, error, isLoading } = useSWR<BudgetData>(
    enabled ? 'budget/data' : null,
    teamApiFetcher,
    { revalidateOnFocus: false, shouldRetryOnError: false },
  );
  return { data, error, isLoading };
};
