import { useCallback, useState } from 'react';
import useSWR from 'swr';
import { ApiError, teamApi } from '@/lib/fetcher';

export const AUDIT_VIEWERS_KEY = 'admin/audit-viewers';
const AUDIT_VIEWER_CANDIDATES_KEY = 'admin/audit-viewer-candidates';

type ViewersResponse = { viewers: string[] };

export type AuditViewerCandidate = {
  username: string;
  email: string;
  firstName?: string;
  lastName?: string;
  name?: string;
};

const errorMessage = (e: unknown, fallback: string): string => {
  if (e instanceof ApiError) {
    const data = e.data as { error?: string } | undefined;
    if (data?.error) {
      return data.error;
    }
  }
  return fallback;
};

/**
 * 監査ログの個別閲覧者の一覧と、追加・取消（システム管理者限定）。
 * 棟では分けない。許可された利用者は全棟のログを閲覧できる。
 */
export const useAuditViewers = (enabled: boolean) => {
  const { data, error, isLoading, mutate } = useSWR<ViewersResponse>(
    enabled ? AUDIT_VIEWERS_KEY : null,
    (key: string) => teamApi.get<ViewersResponse>(key).then((res) => res.data),
    { revalidateOnFocus: false },
  );

  const [submitting, setSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  const addViewer = useCallback(
    async (userId: string): Promise<boolean> => {
      const uid = userId.trim();
      if (!uid) {
        setActionError('利用者ID（メール）を入力してください。');
        return false;
      }
      setSubmitting(true);
      setActionError(null);
      try {
        await teamApi.post(AUDIT_VIEWERS_KEY, { userId: uid });
        await mutate();
        return true;
      } catch (e) {
        setActionError(errorMessage(e, '閲覧者の追加に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  const removeViewer = useCallback(
    async (userId: string): Promise<boolean> => {
      setSubmitting(true);
      setActionError(null);
      try {
        await teamApi.delete(`${AUDIT_VIEWERS_KEY}/${encodeURIComponent(userId)}`);
        await mutate();
        return true;
      } catch (e) {
        setActionError(errorMessage(e, '閲覧者の取消に失敗しました。'));
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [mutate],
  );

  return {
    viewers: data?.viewers ?? [],
    isLoading,
    loadError: error ? '閲覧者の一覧を取得できませんでした。' : null,
    submitting,
    actionError,
    setActionError,
    addViewer,
    removeViewer,
  };
};

/** 閲覧者に指定できる利用者を検索する（棟で絞らない全件検索）。 */
export const searchAuditViewerCandidates = async (
  search: string,
): Promise<AuditViewerCandidate[]> => {
  const { data } = await teamApi.get<{ users?: AuditViewerCandidate[] }>(
    AUDIT_VIEWER_CANDIDATES_KEY,
    { params: { search, limit: 20 } },
  );
  return data.users ?? [];
};
