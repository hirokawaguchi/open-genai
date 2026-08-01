import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';
import type { ApplyResponse, PlanResponse, UsersResponse } from './types';

export const ADMIN_USERS_KEY = 'admin/users';

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

/** Keycloak の利用者一覧を取得する（管理者限定）。search/limit が変わると再取得。 */
export const useUsers = (search: string, limit: number) => {
  const params = { search: search.trim() || undefined, limit };
  const { data, error, isLoading, mutate } = useSWR<UsersResponse>(
    [ADMIN_USERS_KEY, params],
    ([path, p]: [string, typeof params]) =>
      teamApi.get<UsersResponse>(path, { params: p }).then((res) => res.data),
    { revalidateOnFocus: false, keepPreviousData: true },
  );

  const forbidden = error instanceof ApiError && error.status === 403;

  return {
    users: data?.users ?? [],
    count: data?.count ?? 0,
    limitReached: data?.limitReached ?? false,
    isLoading,
    forbidden,
    loadError:
      error && !forbidden
        ? '利用者一覧の取得に失敗しました。時間をおいて再度お試しください。'
        : null,
    mutate,
  };
};

/** CSV のドライラン（変更なし）と適用（Keycloak 反映）。 */
export const useUserMgmtActions = () => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const plan = useCallback(async (csvText: string): Promise<PlanResponse | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<PlanResponse>('admin/users/plan', { csv_text: csvText });
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, 'ドライランに失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  const apply = useCallback(async (csvText: string): Promise<ApplyResponse | null> => {
    setSubmitting(true);
    setError(null);
    try {
      const res = await teamApi.post<ApplyResponse>('admin/users/apply', { csv_text: csvText });
      return res.data ?? null;
    } catch (e) {
      setError(errorMessage(e, '適用に失敗しました。'));
      return null;
    } finally {
      setSubmitting(false);
    }
  }, []);

  return { plan, apply, submitting, error, setError };
};
