import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import type { ModelPolicy, ModelPolicyConfig } from './types';

export const MODEL_POLICY_KEY = 'admin/model-policy';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

/** モデル利用ポリシーの現在値＋利用可能モデル＋対象チームを取得する（管理者限定）。 */
export const useModelPolicy = () => {
  const { data, error, isLoading, mutate } = useSWR<ModelPolicyConfig>(
    MODEL_POLICY_KEY,
    (key: string) => teamApi.get<ModelPolicyConfig>(key).then((res) => res.data),
    { revalidateOnFocus: false },
  );

  const forbidden = error instanceof ApiError && error.status === 403;

  return {
    config: data,
    isLoading,
    forbidden,
    loadError:
      error && !forbidden
        ? 'モデル利用ポリシーの取得に失敗しました。時間をおいて再度お試しください。'
        : null,
    mutate,
  };
};

/** ポリシーを保存する（modelpolicy-app へプロキシ）。 */
export const useModelPolicyActions = (mutate: () => Promise<unknown>) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(
    async (policy: ModelPolicy): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        await teamApi.post(MODEL_POLICY_KEY, { policy });
        await mutate();
        return true;
      } catch (e) {
        setError(errorMessage(e, 'ポリシーの保存に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  return { save, submitting, error, setError };
};
