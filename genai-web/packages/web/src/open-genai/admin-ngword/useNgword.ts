import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import type { NgWordConfig, NgWordRules } from './types';

export const NGWORD_KEY = 'admin/ngword';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

/** 入力制限ルールの現在値を取得する（棟別・管理者限定）。 */
export const useNgword = (tenantId?: string) => {
  const params = tenantId ? { tenantId } : undefined;
  const { data, error, isLoading, mutate } = useSWR<NgWordConfig>(
    [NGWORD_KEY, tenantId ?? ''],
    () => teamApi.get<NgWordConfig>(NGWORD_KEY, { params }).then((res) => res.data),
    { revalidateOnFocus: false },
  );

  const forbidden = error instanceof ApiError && error.status === 403;

  return {
    config: data,
    rules: data?.rules,
    isLoading,
    forbidden,
    loadError:
      error && !forbidden
        ? '入力制限ルールの取得に失敗しました。時間をおいて再度お試しください。'
        : null,
    mutate,
  };
};

/** ルールを保存する（ngword-app へプロキシ・棟別）。 */
export const useNgwordActions = (mutate: () => Promise<unknown>) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(
    async (rules: NgWordRules, tenantId: string): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await teamApi.post(NGWORD_KEY, { rules, tenantId });
        await mutate();
        return true;
      } catch (e) {
        setError(errorMessage(e, 'ルールの保存に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  return { save, submitting, error, setError };
};
